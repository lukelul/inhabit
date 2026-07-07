"""``sim-tactile`` / ``sim-frames`` — scenario-driven tactile + visual sensor sources (B5).

Both sources are driven by a validated :class:`~sim.scenario.ContactScenario` (B4): a
scripted last-centimeter timeline that answers *which tactile token (if any) is active at
time t*. They emit the already-FROZEN :class:`~inhabit_can.pvt.PVTSample` rows — no schema
bump — populating the fields the proprio source leaves at defaults:

* ``sim-tactile`` (TACTILE) stamps ``tactile_event`` with the scenario's active contact
  token (``contact_start | slip | impact | release``) exactly when the sample's
  clock-derived elapsed time falls inside a contact phase window, and ``None`` inside the
  non-contact ``approach``/``settle`` gaps. The token is copied verbatim from
  :meth:`ContactScenario.tactile_event_at` — this module invents no vocabulary.
* ``sim-frames`` (VISUAL) stamps ``camera_frame_id`` with a monotonic, unique, zero-padded
  frame counter (``frame_000000``, ``frame_000001``, ...) and leaves ``tactile_event``
  ``None`` — it references frames, it does not render pixels.

Determinism (hard P-B invariant — same as ``sim-proprio``)
----------------------------------------------------------
Stdlib-only, NO numpy. Given the same scenario and the same injected clock, each source
produces an identical sequence: synthesis is fully scripted (the scenario is the script),
so there is no RNG on the hot path. The ``seed`` parameter is stored for constructor
symmetry with ``sim-proprio`` and reserved for seeded tactile noise (a later task); today
it does not influence output. The elapsed time each sample is labeled with is derived from
the SAME clock that stamps ``timestamp_ns`` (anchored at the first stamp of each
``open()``), so labels and timestamps share ONE timeline under ANY injected clock.

Streams are finite: a source is exhausted once the clock-derived elapsed time reaches the
scenario's ``total_duration_s`` — the episode ends when the script ends.
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample
from sim.scenario import PICK_PLACE, SLIP_RECOVERY, ContactScenario

from .interface import ClockNs, SensorKind, SensorMetadata, SensorSource
from .sim_proprio import _SteppingClock

# Nominal synthetic periods. Tactile pads sample fast (5 ms => 200 Hz, matching the proprio
# pod so the modalities interleave 1:1); cameras are slower (40 ms => 25 Hz — a round period
# so default frame stamps land exactly on scenario phase boundaries in tests).
_TACTILE_PERIOD_NS = 5_000_000
_FRAME_PERIOD_NS = 40_000_000

# Zero-pad width of the sim frame counter: 6 digits covers ~11 hours at 25 Hz per episode,
# far beyond any scripted scenario, while keeping ids lexicographically == numerically
# ordered (the property downstream sorts/joins rely on).
_FRAME_ID_DIGITS = 6


class _ScenarioSource(SensorSource):
    """Shared engine for scenario-driven sources: one clock, one timeline, finite stream.

    Owns the lifecycle + timing that ``sim-tactile`` and ``sim-frames`` have in common so
    the two plugins differ ONLY in how they fill a :class:`PVTSample` (the
    :meth:`_make_sample` hook). Mirrors ``SimProprioSource``'s contract exactly: fail-loud
    ``read``/``stream`` before ``open()``; ``open()`` replays identical data while the
    default stepping clock is never rewound (monotonic time only moves forward); a
    mid-stream ``close()`` ends the generator cleanly.
    """

    def __init__(
        self,
        *,
        scenario: ContactScenario,
        seed: int,
        episode_id: str,
        chain_index: int,
        device_id: str,
        task_label: str | None,
        clock_ns: ClockNs | None,
        start_ns: int,
        period_ns: int,
    ) -> None:
        if period_ns <= 0:
            raise ValueError(f"period_ns must be > 0, got {period_ns}")
        # Fail loud at construction: a nonsensical script must never reach sample stamping
        # (B4's validate() is the gate; see ContactScenario.validate for the guards).
        scenario.validate()
        self._scenario = scenario
        self._seed = seed  # reserved for seeded tactile noise (later task); unused today
        self._episode_id = episode_id
        self._chain_index = chain_index
        self._device_id = device_id
        self._task_label = task_label
        self._period_ns = period_ns
        # First timestamp seen this open(); scenario time is measured from it so the emitted
        # labels share ONE timeline with timestamp_ns under ANY injected clock (see open()).
        self._t0_ns: int | None = None
        # Default to a deterministic stepping clock so a no-kwargs source is reproducible.
        self._clock_ns: ClockNs = (
            clock_ns if clock_ns is not None else _SteppingClock(start_ns, period_ns)
        )
        self._open = False
        self._exhausted = False
        self._emitted = 0

    # -- metadata (concrete sources declare kind/name) ------------------------------------

    def _metadata(self, name: str) -> SensorMetadata:
        return SensorMetadata(
            kind=self.kind,
            name=name,
            device_id=self._device_id,
            sample_schema_version=PVT_SCHEMA_VERSION,
            nominal_rate_hz=1e9 / self._period_ns,
        )

    # -- lifecycle ------------------------------------------------------------------------

    def open(self) -> None:
        # Reset the cursor + re-anchor the scenario timeline so each open() replays the
        # identical scripted DATA. The clock is deliberately NOT rewound: monotonic time
        # only moves forward (the time-sync invariant), so timestamps advance across
        # re-opens while labels/frame ids replay exactly.
        self._t0_ns = None
        self._exhausted = False
        self._emitted = 0
        self._open = True

    def close(self) -> None:
        self._open = False

    # -- sample production ------------------------------------------------------------------

    def read(self) -> PVTSample | None:
        """Return the next :class:`PVTSample`, or ``None`` once the scenario timeline ends.

        Exhaustion is scenario-driven: the first stamp whose elapsed time reaches
        ``total_duration_s`` ends the stream (that stamp is discarded — the script is a
        half-open ``[0, total)`` timeline). Once exhausted, ``read()`` keeps returning
        ``None`` without touching the clock.
        """
        if not self._open:
            raise RuntimeError(f"{type(self).__name__}.read() called before open()")
        if self._exhausted:
            return None
        timestamp_ns = int(self._clock_ns())
        if self._t0_ns is None:
            self._t0_ns = timestamp_ns
        t_s = (timestamp_ns - self._t0_ns) / 1e9
        if t_s >= self._scenario.total_duration_s:
            self._exhausted = True
            return None
        sample = self._make_sample(timestamp_ns, t_s)
        self._emitted += 1
        return sample

    def stream(self) -> Iterator[PVTSample]:
        """Yield samples until the scenario ends OR the source is closed.

        Honors the :class:`SensorSource` "until exhausted or closed" contract exactly like
        ``sim-proprio``: the loop re-checks ``self._open`` each iteration so a mid-stream
        ``close()`` (e.g. exiting a ``with`` block while a consumer holds the generator)
        ends the generator cleanly instead of raising on the next ``read()``.
        """
        if not self._open:
            raise RuntimeError(f"{type(self).__name__}.stream() called before open()")
        while self._open:
            sample = self.read()
            if sample is None:
                return
            yield sample

    @abstractmethod
    def _make_sample(self, timestamp_ns: int, t_s: float) -> PVTSample:
        """Fill one :class:`PVTSample` at scenario time ``t_s`` (the per-modality hook)."""


class SimTactileSource(_ScenarioSource):
    """Scenario-driven TACTILE source: stamps ``tactile_event`` from the contact script.

    Each sample copies :meth:`ContactScenario.tactile_event_at` verbatim: a FROZEN contact
    token (``contact_start | slip | impact | release``) when the sample's scenario time
    falls inside that contact phase's half-open window, ``None`` inside ``approach`` /
    ``settle`` gaps. Proprio fields stay at neutral defaults (this is a tactile source);
    ``camera_frame_id`` stays ``None``.

    Parameters mirror ``sim-proprio`` where they overlap. ``scenario`` defaults to the
    built-in ``SLIP_RECOVERY`` script because it exercises ALL FOUR frozen tokens — so a
    no-kwargs source (the registry/conformance path) observably emits every event kind.
    """

    kind = SensorKind.TACTILE

    def __init__(
        self,
        *,
        scenario: ContactScenario = SLIP_RECOVERY,
        seed: int = 0,
        episode_id: str = "sim_episode",
        chain_index: int = 0,
        device_id: str = "sim_tactile_pad",
        task_label: str | None = None,
        clock_ns: ClockNs | None = None,
        start_ns: int = 0,
        period_ns: int = _TACTILE_PERIOD_NS,
    ) -> None:
        super().__init__(
            scenario=scenario,
            seed=seed,
            episode_id=episode_id,
            chain_index=chain_index,
            device_id=device_id,
            task_label=task_label,
            clock_ns=clock_ns,
            start_ns=start_ns,
            period_ns=period_ns,
        )

    def metadata(self) -> SensorMetadata:
        return self._metadata("sim-tactile")

    def _make_sample(self, timestamp_ns: int, t_s: float) -> PVTSample:
        return PVTSample(
            timestamp_ns=timestamp_ns,
            episode_id=self._episode_id,
            chain_index=self._chain_index,
            joint_angle=0.0,
            tactile_event=self._scenario.tactile_event_at(t_s),
            task_label=self._task_label,
        )


class SimFramesSource(_ScenarioSource):
    """Scenario-driven VISUAL source: stamps a monotonic, unique ``camera_frame_id``.

    Frame ids are ``{frame_prefix}{counter:06d}`` (``frame_000000``, ``frame_000001``, ...):
    strictly monotonic and unique within a stream, zero-padded so lexicographic order equals
    numeric order. The counter resets on ``open()`` (identical replay — determinism), while
    timestamps keep advancing. ``tactile_event`` is always ``None`` (this is a visual
    source); the scenario bounds the episode length so the frame stream is finite and
    time-aligned with the tactile/proprio streams of the same script.

    ``scenario`` defaults to the built-in ``PICK_PLACE`` script (the canonical happy path);
    the 25 Hz default period reflects a camera being slower than the 200 Hz pods.
    """

    kind = SensorKind.VISUAL

    def __init__(
        self,
        *,
        scenario: ContactScenario = PICK_PLACE,
        seed: int = 0,
        episode_id: str = "sim_episode",
        chain_index: int = 0,
        device_id: str = "sim_camera",
        task_label: str | None = None,
        frame_prefix: str = "frame_",
        clock_ns: ClockNs | None = None,
        start_ns: int = 0,
        period_ns: int = _FRAME_PERIOD_NS,
    ) -> None:
        super().__init__(
            scenario=scenario,
            seed=seed,
            episode_id=episode_id,
            chain_index=chain_index,
            device_id=device_id,
            task_label=task_label,
            clock_ns=clock_ns,
            start_ns=start_ns,
            period_ns=period_ns,
        )
        self._frame_prefix = frame_prefix

    def metadata(self) -> SensorMetadata:
        return self._metadata("sim-frames")

    def _make_sample(self, timestamp_ns: int, t_s: float) -> PVTSample:
        return PVTSample(
            timestamp_ns=timestamp_ns,
            episode_id=self._episode_id,
            chain_index=self._chain_index,
            joint_angle=0.0,
            camera_frame_id=f"{self._frame_prefix}{self._emitted:0{_FRAME_ID_DIGITS}d}",
            task_label=self._task_label,
        )


__all__ = ["SimFramesSource", "SimTactileSource"]
