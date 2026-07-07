"""``SimRobot`` — the configurable, seeded synthetic joint robot (P-B/B2).

This is the *real* data-engine simulator that supersedes the ``SimAdapter`` reference stub
(``inhabit_can.adapter.SimAdapter``, which returns ``timestamp_ns=0`` and its internal state
**by reference** — the two gaps documented in ``docs/sdk/ROBOT_SDK_MAPPING.md`` §4.7). B2
builds the thing that closes both gaps, driven by pluggable trajectory models over a
configurable DOF, so the whole PVT pipeline runs on synthetic proprio data with zero hardware.

Failure modes this module exists to prevent (the P-B invariants, lead-with-the-failure-mode):

* **Non-monotonic / zero timestamps => cross-modal misalignment.** Every emitted sample is
  stamped from ONE clock as ``start_ns + i*period_ns`` — strictly increasing, never ``0`` — so
  CAN, video, and tactile streams can be aligned to a single monotonic timeline (the core PVT
  failure mode). The stamps pass ``host/logger/jitter.py`` with ``backwards==0``/``dropouts==0``.
* **By-reference reads => caller corruption.** Every ``read``/state accessor returns an
  INDEPENDENT copy (mirroring ``ReplayAdapter``/``ROS2Adapter``), so a consumer that mutates a
  returned sample/state in place cannot corrupt the generator's internal cursor or the next read.
* **Non-portable randomness => non-byte-stable fixtures.** Randomness flows through exactly ONE
  :class:`sim.rng.SeededRng` (stdlib ``random.Random``; **NO numpy**). The trajectories are pure
  closed-form functions today, but the RNG seam is threaded through so B3's per-channel noise
  plugs in without touching this file's structure or the golden fixtures.

PONYTAIL. A trajectory is a plain ``Callable`` (:data:`Trajectory`), not a class hierarchy: a
``(t_sec, joint_index, params) -> angle`` function. Two are shipped (:func:`sine`, :func:`ramp`)
plus :func:`hold`; adding a model is a one-line function + one registry entry, never a subclass.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState
from inhabit_can.pvt import PVTSample
from sim.rng import SeededRng

__all__ = [
    "NOISE_CHANNELS",
    "NO_NOISE",
    "TRAJECTORIES",
    "NoiseSpec",
    "SimRobot",
    "SimRobotAdapter",
    "Trajectory",
    "TrajectoryParams",
    "hold",
    "ramp",
    "sine",
    "trajectory",
]

# The proprio channels B3 perturbs, in the fixed order noise is applied. Each name is BOTH
# a ``NoiseSpec`` sigma field and the ``spawn`` sub-stream label, so a channel's draws come
# from ``rng.spawn(<name>)`` and are independent of every other channel (adding/reordering
# one channel's noise never shifts another's stream — see ``NoiseSpec`` docstring).
NOISE_CHANNELS: tuple[str, ...] = (
    "joint_angle",
    "joint_velocity",
    "motor_current",
    "estimated_torque",
)


@dataclass(frozen=True, slots=True)
class TrajectoryParams:
    """Shape parameters shared by every trajectory model (frozen — a value, not state).

    Kept deliberately small (PONYTAIL): the two knobs every model needs. A model that wants
    a bespoke knob reads it here or is parameterised by a closure — we do NOT grow a union of
    per-model config until a model actually needs it (YAGNI).

    Attributes
    ----------
    amplitude_rad:
        Peak joint excursion in radians. A model MUST keep its output within
        ``[-amplitude_rad, +amplitude_rad]`` (the range property the tests assert); this is
        also the ``motor_current``/``estimated_torque`` reference downstream code can trust.
    frequency_hz:
        Trajectory frequency in Hz (cycles/sweeps per second). ``> 0`` is enforced by
        :meth:`SimRobot.__init__` because a non-positive frequency would silently flatten
        every trajectory to a constant.
    """

    amplitude_rad: float = 1.0
    frequency_hz: float = 0.5
    dof: int = 1
    """Joint count the model is spread across — threaded in by :class:`SimRobot` so the
    per-joint phase offset stays unique for ANY DOF (see :func:`_phase_offset`)."""


@dataclass(frozen=True, slots=True)
class NoiseSpec:
    """Bounded, seeded, per-channel additive proprio noise (frozen — a value, not state).

    Failure mode this exists to prevent: **unbounded / non-reproducible sensor noise** — noise
    drawn from a shared or process-global RNG, or from an unclamped Gaussian, produces
    non-diffable golden fixtures (draws shift when any channel is added/reordered) and
    unrealistic multi-sigma outliers that poison downstream P-C alignment / P-D contact
    detection. This spec makes the noise (a) *bounded* — a clamped Gaussian, never an outlier
    past ``±clamp_sigmas·sigma`` — and (b) *per-channel independent* — each channel draws from
    its OWN ``SeededRng.spawn(<channel>)`` sub-stream, so raising one channel's sigma leaves
    every other channel byte-identical.

    Noise model (documented, bounded)
    ---------------------------------
    For each proprio channel, the emitted value is ``clean + clamp(gauss(0, sigma), k)`` where
    ``gauss(0, sigma)`` is drawn from that channel's independent sub-stream and ``clamp`` limits
    the draw to ``[-clamp_sigmas·sigma, +clamp_sigmas·sigma]``. Therefore:

    * ``|noise| <= clamp_sigmas * sigma`` for that channel — a **hard, per-channel bound** (the
      B3 property test's exit criterion), so no sample ever wanders past the clean value by more
      than ``clamp_sigmas`` standard deviations.
    * ``sigma == 0`` (the default for every channel) ⇒ ``gauss`` returns ``0.0`` exactly and the
      clamp is a no-op ⇒ the emitted value is the clean B2 value, byte-for-byte. The all-zero
      :data:`NO_NOISE` default therefore reproduces B2 output exactly (back-compat is a HARD
      requirement — the zero-noise config must be indistinguishable from the noise-free path).

    Attributes
    ----------
    joint_angle_sigma / joint_velocity_sigma / motor_current_sigma / estimated_torque_sigma:
        Per-channel Gaussian standard deviation (same physical unit as the channel; ``>= 0``).
        ``0.0`` (default) disables noise on that channel. Names mirror :data:`NOISE_CHANNELS`.
    clamp_sigmas:
        The symmetric bound as a multiple of each channel's sigma (``> 0``). Default ``3.0`` —
        a 3-sigma clamp keeps ~99.7% of the natural mass while hard-rejecting the fat-tail
        outliers that would otherwise create unrealistic spikes in the dataset.
    """

    joint_angle_sigma: float = 0.0
    joint_velocity_sigma: float = 0.0
    motor_current_sigma: float = 0.0
    estimated_torque_sigma: float = 0.0
    clamp_sigmas: float = 3.0

    def __post_init__(self) -> None:
        # Fail loud on a nonsensical spec (never mid-stream): a negative sigma is a caller bug
        # (sigma is a standard deviation), and clamp_sigmas <= 0 would collapse every draw to 0
        # — a silent "noise config that does nothing", which is a footgun, not a feature.
        for name in NOISE_CHANNELS:
            s = self.sigma(name)
            if s < 0.0:
                raise ValueError(f"{name}_sigma must be >= 0, got {s}")
        if self.clamp_sigmas <= 0.0:
            raise ValueError(f"clamp_sigmas must be > 0, got {self.clamp_sigmas}")

    def sigma(self, channel: str) -> float:
        """The configured standard deviation for ``channel`` (a :data:`NOISE_CHANNELS` name).

        An explicit ``match`` (not ``getattr``) so mypy statically verifies the
        ``NOISE_CHANNELS`` <-> sigma-field relationship: a channel with no matching field is a
        static/type error here, not a runtime ``AttributeError`` discovered mid-stream.
        """
        match channel:
            case "joint_angle":
                return self.joint_angle_sigma
            case "joint_velocity":
                return self.joint_velocity_sigma
            case "motor_current":
                return self.motor_current_sigma
            case "estimated_torque":
                return self.estimated_torque_sigma
            case _:
                raise ValueError(f"unknown noise channel {channel!r}")

    @property
    def enabled(self) -> bool:
        """``True`` iff any channel has non-zero sigma (i.e. this spec perturbs output).

        The all-zero default is disabled, so ``SimRobot`` can short-circuit the draw entirely
        and stay byte-identical to B2 without even spawning sub-streams.
        """
        return any(self.sigma(name) > 0.0 for name in NOISE_CHANNELS)


# The zero-noise default: every channel sigma is 0, so output is byte-identical to B2. This is
# the ``SimRobot.noise`` default and the back-compat guarantee (a shared frozen value is safe).
NO_NOISE = NoiseSpec()


# A trajectory model: (elapsed_seconds, joint_index, params) -> joint_angle_rad. A plain
# Callable so a model is a small pure function (or any callable/closure), swappable by name,
# with NO class tree. Pure and side-effect-free: same inputs => same angle, which is what
# makes ``SimRobot`` deterministic and its fixtures byte-stable.
Trajectory = Callable[[float, int, TrajectoryParams], float]

# Registry of built-in trajectory models, keyed by short name. Populated by the ``@trajectory``
# decorator below so a model self-registers next to its definition; ``SimRobot`` resolves a
# string name through this map, and callers can pass a bespoke Callable directly.
TRAJECTORIES: dict[str, Trajectory] = {}


def trajectory(name: str) -> Callable[[Trajectory], Trajectory]:
    """Register a :data:`Trajectory` under ``name`` (fail loud on a duplicate name).

    Failure mode this prevents: a silently shadowed model. If two models registered the same
    name, ``SimRobot("sine")`` would resolve to whichever imported last — a non-reproducible
    footgun for goldens. Registering is explicit and rejects collisions up front.
    """

    def _register(fn: Trajectory) -> Trajectory:
        if name in TRAJECTORIES:
            raise ValueError(f"trajectory {name!r} already registered")
        TRAJECTORIES[name] = fn
        return fn

    return _register


def _phase_offset(joint_index: int, dof: int) -> float:
    """Per-joint phase spread, unique across all ``dof`` joints (no lockstep at ANY DOF).

    Spreads the ``dof`` joints evenly across one full cycle — joint ``i`` gets ``2*pi*i/dof`` —
    so no two joints ever share a phase. A fixed spread like ``i*pi/3`` repeats every 6 joints,
    which would silently put joint 6 in lockstep with joint 0 for ``dof >= 7`` (Inhabit's
    multi-pod chains / humanoids). Deterministic in ``(joint_index, dof)`` => reproducible.
    """
    return 2.0 * math.pi * joint_index / dof


@trajectory("sine")
def sine(t_sec: float, joint_index: int, params: TrajectoryParams) -> float:
    """Sinusoidal sweep — the model matching today's ``sim_adapter`` sweep.

    ``amplitude * sin(2*pi*freq*t + phase(joint))``. Bounded in ``[-amplitude, +amplitude]``
    by construction (``|sin| <= 1``), which is the range invariant the property tests assert.
    A per-joint phase offset fans the joints across the cycle so an N-DOF arm does not move in
    lockstep.
    """
    phase = 2.0 * math.pi * params.frequency_hz * t_sec + _phase_offset(joint_index, params.dof)
    return params.amplitude_rad * math.sin(phase)


@trajectory("ramp")
def ramp(t_sec: float, joint_index: int, params: TrajectoryParams) -> float:
    """Triangle ramp — a monotone-per-segment reach/retract, the non-sine second model.

    A symmetric triangle wave of period ``1/frequency_hz`` sweeping the full
    ``[-amplitude, +amplitude]`` band: linearly out to ``+amplitude`` over the first half of
    each cycle, linearly back over the second. Exercises the pipeline with a signal whose
    *velocity* is piecewise-constant (unlike sine's smooth derivative) — useful contrast for
    downstream P-C alignment / P-D contact detection. Stays within ``[-amplitude, +amplitude]``.
    The per-joint phase offset (normalised into the cycle) fans joints apart, matching ``sine``.
    """
    # Fraction through the current cycle in [0, 1), offset per joint so joints differ.
    cycle = params.frequency_hz * t_sec + _phase_offset(joint_index, params.dof) / (2.0 * math.pi)
    frac = cycle - math.floor(cycle)
    # Triangle in [-1, 1]: rises 0->1 (frac 0->0.5), falls 1->-1... normalise to full band.
    tri = 1.0 - 4.0 * abs(frac - 0.5)  # frac=0 -> -1, frac=0.5 -> +1, frac->1 -> -1
    return params.amplitude_rad * tri


@trajectory("hold")
def hold(t_sec: float, joint_index: int, params: TrajectoryParams) -> float:
    """Static hold — every joint parks at a fixed per-joint offset, no motion.

    A deliberately trivial third model: the joint sits at a constant angle
    (``amplitude * sin(phase(joint))``, i.e. sine frozen at ``t=0``) so ``joint_velocity`` is
    ~0. Useful as the "settled / no-contact baseline" segment a scenario (B4) can splice in,
    and as the degenerate case for the range/velocity property tests. Bounded in
    ``[-amplitude, +amplitude]``.
    """
    return params.amplitude_rad * math.sin(_phase_offset(joint_index, params.dof))


def _resolve(model: str | Trajectory) -> Trajectory:
    """Resolve a trajectory name or callable to a :data:`Trajectory` (fail loud on unknown)."""
    if callable(model):
        return model
    if model not in TRAJECTORIES:
        raise ValueError(
            f"unknown trajectory {model!r}; available: {sorted(TRAJECTORIES)}"
        )
    return TRAJECTORIES[model]


@dataclass
class SimRobot:
    """A configurable, seeded synthetic joint robot — the hardware-free proprio source.

    Emits :class:`~inhabit_can.pvt.PVTSample` rows (one per joint per tick) following a
    pluggable :data:`Trajectory` over ``dof`` joints, each stamped with a strictly-increasing
    monotonic ``timestamp_ns``. It is the generation engine B3 (noise), B4 (scenarios), and
    the golden fixtures build on; :class:`SimRobotAdapter` wraps it behind the FROZEN
    ``RobotAdapter``.

    Parameters
    ----------
    dof:
        Joint count (degrees of freedom). Must be ``>= 1`` — a zero-DOF robot emits no signal
        and makes ``capabilities().dof`` a lie the conformance suite rejects.
    trajectory:
        The angle model: a built-in name (``"sine"``/``"ramp"``/``"hold"``) or any
        :data:`Trajectory` callable. Resolved once at construction and stored, so a bad name
        fails loud immediately, not mid-stream.
    seed:
        Seeds the ONE randomness source (:class:`sim.rng.SeededRng`). With the default
        zero-noise :class:`NoiseSpec` the trajectories are deterministic, so the seed does NOT
        perturb output (B2 byte-for-byte). With ``noise`` enabled the seed DOES change output —
        each channel draws from an independent, seed-derived :meth:`SeededRng.spawn` sub-stream.
    noise:
        Per-channel additive proprio noise (:class:`NoiseSpec`). Default :data:`NO_NOISE`
        (all-zero) ⇒ output is byte-identical to B2. Non-zero sigmas add a clamped Gaussian to
        the affected channels; see :class:`NoiseSpec` for the documented bound.
    amplitude_rad / frequency_hz:
        Trajectory shape (see :class:`TrajectoryParams`). ``frequency_hz > 0`` is required.
    start_ns / period_ns:
        The monotonic clock: sample ``i`` is stamped ``start_ns + i*period_ns``. ``start_ns``
        must be ``> 0`` (never emit a zero timestamp) and ``period_ns`` must be ``> 0`` (strict
        monotonicity — the time-sync contract).
    episode_id / task_label:
        Stamped onto every emitted sample.
    """

    dof: int = 3
    trajectory: str | Trajectory = "sine"
    seed: int = 0
    noise: NoiseSpec = NO_NOISE
    amplitude_rad: float = 1.0
    frequency_hz: float = 0.5
    start_ns: int = 1_000_000_000
    period_ns: int = 10_000_000  # 10 ms => 100 Hz, matching the recorder's nominal budget
    episode_id: str = "sim_robot"
    task_label: str | None = None

    _traj: Trajectory = field(init=False, repr=False, compare=False)
    _params: TrajectoryParams = field(init=False, repr=False, compare=False)
    _rng: SeededRng = field(init=False, repr=False, compare=False)
    _index: int = field(init=False, default=0, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Fail loud at construction (never mid-stream) on every value that would silently
        # break an invariant: DOF/timestamp/period must be positive so state length is
        # truthful and the clock is strictly increasing and never zero.
        if self.dof < 1:
            raise ValueError(f"dof must be >= 1, got {self.dof}")
        if self.frequency_hz <= 0:
            raise ValueError(f"frequency_hz must be > 0, got {self.frequency_hz}")
        if self.start_ns <= 0:
            raise ValueError(f"start_ns must be > 0 (never a zero timestamp), got {self.start_ns}")
        if self.period_ns <= 0:
            raise ValueError(f"period_ns must be > 0 (strict monotonicity), got {self.period_ns}")
        self._traj = _resolve(self.trajectory)
        self._params = TrajectoryParams(
            amplitude_rad=self.amplitude_rad, frequency_hz=self.frequency_hz, dof=self.dof
        )
        # The ONE randomness source for this robot; built from ``seed`` so a fresh SimRobot
        # replays the identical stream. Deliberately not drawn from yet (noise is B3).
        self._rng = SeededRng(self.seed)

    def rng(self) -> SeededRng:
        """The seeded RNG seam B3's per-channel noise draws from (independent per instance)."""
        return self._rng

    def reset(self) -> None:
        """Rewind the sample cursor to 0 so the next tick re-emits from ``start_ns``.

        Determinism survives reuse: after ``reset()`` a robot replays the identical seeded
        sequence (mirrors ``SimProprioSource.open`` / ``ReplayAdapter.connect``).
        """
        self._index = 0

    def _timestamp(self, index: int) -> int:
        """Monotonic stamp for the ``index``-th tick: ``start_ns + index*period_ns`` (> 0)."""
        return self.start_ns + index * self.period_ns

    def _noise(self, channel: str, index: int, joint_index: int) -> float:
        """Bounded per-channel additive noise for ``channel`` at ``(index, joint_index)``.

        Failure mode this prevents: **non-reproducible / cross-coupled / unbounded noise.** The
        draw is fully determined by ``(seed, channel, index, joint_index)`` and NOTHING else —
        never by call order or the streaming cursor — so ``sample_at`` stays PURE (repeated calls
        return the identical value) and independent of how many samples were read before it.

        How independence is guaranteed: each channel gets its own sub-stream via
        ``rng.spawn(channel)`` (labelled by the :data:`NOISE_CHANNELS` name), then a per-cell
        sub-stream via ``.spawn(f"{index}:{joint_index}")``. Because :meth:`SeededRng.spawn`
        derives the child seed from ``(parent_seed, label)`` with salt-free FNV-1a arithmetic,
        distinct channels and distinct cells yield distinct, deterministic streams — so raising
        one channel's sigma cannot shift another channel's draws, and reordering channels is
        immaterial. The first ``gauss(0, sigma)`` of that per-cell stream is the raw noise, then
        **clamped to ``±clamp_sigmas·sigma``** — the documented, hard per-channel bound.

        Returns ``0.0`` (no draw at all) when the channel's sigma is ``0`` — which keeps the
        zero-noise config byte-identical to B2 and also means a disabled channel never perturbs
        another channel's stream (there is nothing to spawn).
        """
        sigma = self.noise.sigma(channel)
        if sigma <= 0.0:
            return 0.0
        cell = self._rng.spawn(channel).spawn(f"{index}:{joint_index}")
        raw = cell.gauss(0.0, sigma)
        bound = self.noise.clamp_sigmas * sigma
        # Symmetric clamp: the emitted noise never exceeds ``clamp_sigmas`` standard deviations,
        # so no sample is ever a fat-tail outlier past the documented bound (max(-b, min(b, x))).
        return max(-bound, min(bound, raw))

    def sample_at(self, index: int, joint_index: int) -> PVTSample:
        """Build ONE joint's :class:`PVTSample` for tick ``index`` — pure, no cursor mutation.

        Failure mode: returning shared/mutable internal state. This constructs a brand-new
        ``PVTSample`` every call, so the returned object is inherently an independent copy —
        a caller mutating it cannot corrupt any internal state. ``joint_velocity`` is a
        one-tick finite difference against the previous tick (0 at ``index==0``), matching the
        existing ``sim_adapter`` convention; ``motor_current``/``estimated_torque`` are derived
        from velocity so the modalities stay internally consistent (faster joint => more draw).

        Noise (B3). Bounded, seeded, per-channel noise from :attr:`noise` is added to the four
        proprio channels via :meth:`_noise` (each channel drawn from its own independent
        sub-stream). The default :data:`NO_NOISE` adds exactly ``0.0`` everywhere, so the emitted
        sample is byte-for-byte the B2 value. The monotonic ``timestamp_ns`` is NEVER perturbed —
        noise is proprioceptive only, so the one-clock time-sync contract is untouched.
        """
        t_ns = self._timestamp(index)
        t_sec = index * self.period_ns / 1e9
        angle = self._traj(t_sec, joint_index, self._params)
        if index > 0:
            prev_t_sec = (index - 1) * self.period_ns / 1e9
            prev_angle = self._traj(prev_t_sec, joint_index, self._params)
            velocity = (angle - prev_angle) / (self.period_ns / 1e9)
        else:
            velocity = 0.0
        motor_current = 0.1 + 0.5 * abs(velocity)
        estimated_torque = 0.2 * velocity
        return PVTSample(
            timestamp_ns=t_ns,
            episode_id=self.episode_id,
            chain_index=joint_index,
            joint_angle=angle + self._noise("joint_angle", index, joint_index),
            joint_velocity=velocity + self._noise("joint_velocity", index, joint_index),
            motor_current=motor_current + self._noise("motor_current", index, joint_index),
            estimated_torque=estimated_torque
            + self._noise("estimated_torque", index, joint_index),
            task_label=self.task_label,
        )

    def read(self) -> list[PVTSample]:
        """Advance one tick and return a fresh ``PVTSample`` per joint (independent copies).

        Each call advances the monotonic cursor by one period and returns ``dof`` brand-new
        samples — so the stamps across successive reads are strictly increasing, and a caller
        mutating any returned sample cannot corrupt the next read. This is the fix for the
        ``SimAdapter`` by-reference/zero-timestamp gap, at the sample granularity.
        """
        index = self._index
        self._index += 1
        return [self.sample_at(index, j) for j in range(self.dof)]

    def read_state(self) -> RobotState:
        """Advance one tick and return the joint vector as an independent ``RobotState``.

        A fresh ``RobotState`` (new list) carrying every joint's angle for this tick and the
        tick's monotonic ``timestamp_ns`` (> 0). Independent-copy by construction; this is what
        :class:`SimRobotAdapter` returns so the adapter honours the FROZEN contract.
        """
        samples = self.read()
        return RobotState(
            joint_angles=[s.joint_angle for s in samples],
            timestamp_ns=samples[0].timestamp_ns,
        )

    def generate(self, n_ticks: int) -> list[PVTSample]:
        """Generate ``n_ticks`` ticks as a flat, time-ordered list of ``PVTSample`` rows.

        Rewinds first (``reset()``) so the output depends only on the config, not on prior
        reads — reproducible for goldens. Rows are ordered ``(tick, joint)``: all joints of
        tick 0, then tick 1, ... (the ``sim_adapter`` row order), so successive same-joint
        stamps are strictly increasing and ``compute_jitter`` sees a clean monotonic stream.
        """
        if n_ticks < 0:
            raise ValueError(f"n_ticks must be >= 0, got {n_ticks}")
        self.reset()
        rows: list[PVTSample] = []
        for _ in range(n_ticks):
            rows.extend(self.read())
        return rows


class SimRobotAdapter(RobotAdapter):
    """``SimRobot`` behind the FROZEN ``RobotAdapter`` — a proper (non-stub) simulation adapter.

    Fixes the two ``SimAdapter`` gaps the conformance contract cares about:

    * **Monotonic, non-zero timestamps.** ``read_state`` stamps every state from the
      ``SimRobot`` clock (``start_ns + i*period_ns`` > 0) — never the ``RobotState`` default of
      ``0`` (``ROBOT_SDK_MAPPING.md`` §4.7 gap).
    * **Independent-copy reads.** ``read_state`` returns a brand-new ``RobotState`` (new list),
      so a caller mutating ``joint_angles`` cannot corrupt internal state (the ``SimAdapter``
      by-reference gap; ``ReplayAdapter``/``ROS2Adapter`` copy for the same reason).

    Command handling. ``send_command`` records the targets and ``read_state`` then reflects
    them (still on a fresh, freshly-stamped state) until the next command — so the adapter
    satisfies the conformance suite's "state reflects command" invariant AND stays a driver of
    monotonic time. With no command outstanding, ``read_state`` advances the trajectory. A
    caller wanting the raw trajectory stream reads the underlying :attr:`robot` directly.
    """

    def __init__(
        self,
        *,
        dof: int = 6,
        trajectory: str | Trajectory = "sine",
        seed: int = 0,
        **robot_kwargs: object,
    ) -> None:
        # Build the engine; SimRobot validates dof/frequency/timestamps and rejects a bad
        # trajectory name loudly at construction (never mid-read).
        self.robot = SimRobot(
            dof=dof,
            trajectory=trajectory,
            seed=seed,
            **robot_kwargs,  # type: ignore[arg-type]  # forwarded SimRobot fields
        )
        self._dof = dof
        # Last commanded targets, or None => free-run the trajectory. Reflecting the last
        # command lets the adapter pass the conformance "state reflects command" invariant
        # without special-casing it in core.
        self._command: list[float] | None = None

    def connect(self) -> None:
        # Idempotent (the frozen contract): rewind the trajectory cursor and drop any pending
        # command so a reconnect starts from a clean, reproducible state.
        self.robot.reset()
        self._command = None

    def read_state(self) -> RobotState:
        # Always advance the monotonic clock by one tick so successive reads are strictly
        # increasing and never zero, whether free-running or command-reflecting.
        state = self.robot.read_state()
        if self._command is not None:
            # Reflect the last command on a fresh state (new list) carrying THIS tick's stamp:
            # independent-copy + monotonic time preserved, command honoured.
            return replace(state, joint_angles=list(self._command))
        return state

    def send_command(self, cmd: RobotCommand) -> None:
        # Fail loud on a DOF mismatch: reflecting a wrong-length command would make read_state
        # return joint_angles whose length disagrees with capabilities().dof — a contract lie.
        if len(cmd.joint_targets) != self._dof:
            raise ValueError(
                f"command has {len(cmd.joint_targets)} targets, expected {self._dof} (dof)"
            )
        # Copy the incoming targets so a later caller mutation of ``cmd`` can't reach into our
        # reflected state (independent-copy on the write path too).
        self._command = list(cmd.joint_targets)

    def capabilities(self) -> Capabilities:
        # Truthful DOF (matches the state length the conformance suite checks); no force
        # feedback until real force data is wired (never over-advertise).
        return Capabilities(dof=self._dof, has_force_feedback=False)
