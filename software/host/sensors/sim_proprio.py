"""``sim-proprio`` — seeded, deterministic proprioceptive sensor source.

Emits :class:`~inhabit_can.pvt.PVTSample` rows carrying the *proprioceptive* portion of
the PVT triplet (joint angle / velocity / motor current / estimated torque) for one
simulated joint pod. No hardware, no ROS, stdlib-only.

Determinism (a hard requirement — see ``MASTER_PLAN.md`` quality bar)
--------------------------------------------------------------------
Given the same ``seed`` and the same injected clock, the source produces a **byte-identical
sequence** of samples. Randomness comes exclusively from a private ``random.Random(seed)``
(reproducible across machines/Python builds); the trajectory is a deterministic closed-form
sweep plus seeded noise. No global RNG, no wall-clock, no ``time`` calls on the hot path —
the clock is injected.

This source IMPORTS the frozen :class:`PVTSample`/``PVT_SCHEMA_VERSION`` to shape its
output but never edits them; new proprio fields would be a schema decision upstream, not a
change here.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterator

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample

from .interface import ClockNs, SensorKind, SensorMetadata, SensorSource

# Nominal synthetic sample period: 5 ms => 200 Hz. The injected clock advances by this much
# per sample so stamps are monotonic and reproducible without reading the host clock.
_DEFAULT_PERIOD_NS = 5_000_000
_NOMINAL_RATE_HZ = 1e9 / _DEFAULT_PERIOD_NS  # 200.0


class _SteppingClock:
    """Deterministic monotonic clock: starts at ``start_ns``, advances ``period_ns`` per call.

    Used as the default clock so a ``sim-proprio`` built with only a seed is fully
    reproducible (same seed => same stamps) without depending on the host wall/monotonic
    clock. Real ingestion injects ``time.monotonic_ns`` instead.
    """

    __slots__ = ("_next", "_period")

    def __init__(self, start_ns: int, period_ns: int) -> None:
        self._next = start_ns
        self._period = period_ns

    def __call__(self) -> int:
        now = self._next
        self._next += self._period
        return now


class SimProprioSource(SensorSource):
    """Synthesize seeded proprioceptive :class:`PVTSample` rows for one joint pod.

    The joint follows a deterministic sinusoidal sweep with seeded per-sample noise;
    velocity is the analytic derivative plus noise; motor current and estimated torque are
    derived from velocity so the modalities are internally consistent (a faster joint draws
    more current) — useful, not random soup, for downstream P-C/P-D work.

    Parameters
    ----------
    seed:
        Seeds the private RNG. Same seed (+ same clock) => byte-identical sequence.
    count:
        Number of samples the source emits before reporting exhaustion.
    episode_id:
        Episode id stamped onto every sample.
    chain_index:
        Logical position of this pod in the kinematic chain.
    device_id:
        Logical device identity advertised in :meth:`metadata`.
    task_label:
        Optional task label stamped onto every sample.
    amplitude_rad / frequency_hz:
        Shape of the deterministic angle sweep.
    noise_rad:
        Std-dev of the seeded angle noise (radians); ``0.0`` => noise-free golden path.
    clock_ns:
        Monotonic-ns clock. Defaults to a deterministic stepping clock so a seed-only
        source is fully reproducible; inject ``time.monotonic_ns`` for live ingestion.
    start_ns / period_ns:
        Start value and per-sample step of the *default* stepping clock (ignored when a
        custom ``clock_ns`` is injected).
    """

    kind = SensorKind.PROPRIO

    def __init__(
        self,
        *,
        seed: int = 0,
        count: int = 100,
        episode_id: str = "sim_episode",
        chain_index: int = 0,
        device_id: str = "sim_joint_pod",
        task_label: str | None = None,
        amplitude_rad: float = 1.0,
        frequency_hz: float = 0.5,
        noise_rad: float = 0.01,
        clock_ns: ClockNs | None = None,
        start_ns: int = 0,
        period_ns: int = _DEFAULT_PERIOD_NS,
    ) -> None:
        if count < 0:
            raise ValueError(f"count must be >= 0, got {count}")
        if period_ns <= 0:
            raise ValueError(f"period_ns must be > 0, got {period_ns}")
        self._seed = seed
        self._count = count
        self._episode_id = episode_id
        self._chain_index = chain_index
        self._device_id = device_id
        self._task_label = task_label
        self._amplitude = amplitude_rad
        self._frequency = frequency_hz
        self._noise = noise_rad
        self._period_ns = period_ns
        # First timestamp seen this open(); the signal phase is measured from it so the
        # emitted angle/velocity/current/torque share ONE timeline with timestamp_ns under
        # ANY injected clock (set in open()).
        self._t0_ns: int | None = None
        # Default to a deterministic stepping clock so a seed-only source is reproducible.
        self._clock_ns: ClockNs = (
            clock_ns if clock_ns is not None else _SteppingClock(start_ns, period_ns)
        )
        self._open = False
        # RNG + cursor are (re)initialised in open() so a source can be re-opened and
        # replay the exact same sequence — determinism survives reuse.
        self._rng = random.Random(seed)
        self._emitted = 0

    # -- metadata -----------------------------------------------------------------------

    def metadata(self) -> SensorMetadata:
        return SensorMetadata(
            kind=self.kind,
            name="sim-proprio",
            device_id=self._device_id,
            sample_schema_version=PVT_SCHEMA_VERSION,
            nominal_rate_hz=_NOMINAL_RATE_HZ,
        )

    # -- lifecycle ----------------------------------------------------------------------

    def open(self) -> None:
        # Re-seed the RNG + reset the cursor so each open() replays the identical seeded
        # DATA. The clock is deliberately NOT rewound: monotonic time only moves forward
        # (the time-sync invariant), so timestamps advance across re-opens.
        self._rng = random.Random(self._seed)
        self._emitted = 0
        # Re-anchor the signal timeline to the first stamp of THIS open() so the phase is
        # measured from t=0 at the first emitted sample, regardless of the clock's start.
        self._t0_ns = None
        self._open = True

    def close(self) -> None:
        self._open = False

    # -- sample production --------------------------------------------------------------

    def read(self) -> PVTSample | None:
        """Return the next :class:`PVTSample`, or ``None`` once ``count`` are emitted."""
        if not self._open:
            raise RuntimeError("SimProprioSource.read() called before open()")
        if self._emitted >= self._count:
            return None
        sample = self._make_sample()
        self._emitted += 1
        return sample

    def stream(self) -> Iterator[PVTSample]:
        """Yield samples until the source is exhausted OR closed.

        Honors the :class:`SensorSource` "until exhausted or closed" contract: a mid-stream
        ``close()`` (e.g. exiting a ``with`` block while a consumer holds the generator) ends
        the generator cleanly instead of calling :meth:`read` after close and raising. The
        loop re-checks ``self._open`` each iteration, so close transitions terminate it.
        """
        if not self._open:
            raise RuntimeError("SimProprioSource.stream() called before open()")
        while self._open:
            sample = self.read()
            if sample is None:
                return
            yield sample

    def _make_sample(self) -> PVTSample:
        """Build the next sample deterministically from the seeded RNG + closed-form sweep.

        The signal phase is derived from the SAME clock that stamps the sample: ``t_s`` is the
        elapsed time since this open()'s first stamp. So the emitted angle/velocity/current/
        torque always describe the same timeline as ``timestamp_ns`` — even under a clock that
        jumps or steps by something other than ``period_ns``. For the default stepping clock
        (start_ns + i*period_ns) this is exactly ``i*period_ns/1e9``, so seed+clock stay
        byte-identical to before.
        """
        timestamp_ns = int(self._clock_ns())
        if self._t0_ns is None:
            self._t0_ns = timestamp_ns
        t_s = (timestamp_ns - self._t0_ns) / 1e9
        phase = 2.0 * math.pi * self._frequency * t_s
        # Deterministic sweep + seeded noise. Draw noise in a FIXED order every sample so
        # the RNG state advances identically regardless of branch — byte-stable.
        angle_noise = self._rng.gauss(0.0, self._noise)
        vel_noise = self._rng.gauss(0.0, self._noise)
        angle = self._amplitude * math.sin(phase) + angle_noise
        # Analytic derivative of the sweep (rad/s) + noise => internally consistent velocity.
        velocity = (
            self._amplitude * 2.0 * math.pi * self._frequency * math.cos(phase) + vel_noise
        )
        # Current/torque derived from velocity so modalities correlate (faster => more draw).
        motor_current = 0.1 + 0.5 * abs(velocity)
        estimated_torque = 0.2 * velocity
        return PVTSample(
            timestamp_ns=timestamp_ns,
            episode_id=self._episode_id,
            chain_index=self._chain_index,
            joint_angle=angle,
            joint_velocity=velocity,
            motor_current=motor_current,
            estimated_torque=estimated_torque,
            task_label=self._task_label,
        )


__all__ = ["SimProprioSource"]
