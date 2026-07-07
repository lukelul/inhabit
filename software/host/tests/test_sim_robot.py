"""Property + contract tests for the configurable ``SimRobot`` (P-B/B2).

The failure modes under test are the P-B invariants (``MASTER_TASK_QUEUE.md`` §P-B):

* **Non-monotonic / zero timestamps => cross-modal misalignment** — every emitted stamp is
  strictly increasing and never ``0``, and passes ``compute_jitter`` with ``backwards==0``.
* **By-reference reads => caller corruption** — a returned sample/state is an INDEPENDENT copy;
  mutating it leaves the generator's next read untouched.
* **Non-portable randomness => non-byte-stable fixtures** — same config => byte-identical output
  (``as_row()`` equality) across two independent runs.

Plus the B2 scope proper: configurable DOF (``N joints == dof``), ≥2 pluggable trajectory
models each behaving per its spec, and joint angles bounded by the trajectory amplitude.
"""
from __future__ import annotations

import math
from itertools import pairwise

import pytest

from adapters import list_adapters, make_adapter
from inhabit_can.adapter import RobotCommand, RobotState
from logger.jitter import JitterBudget, compute_jitter
from sim.rng import SeededRng
from sim.robot import (
    TRAJECTORIES,
    SimRobot,
    SimRobotAdapter,
    TrajectoryParams,
    _phase_offset,
    hold,
    ramp,
    sine,
    trajectory,
)

# ---------------------------------------------------------------------------
# DOF configuration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dof", [1, 2, 3, 6, 12])
def test_dof_controls_joint_count(dof: int) -> None:
    """A tick emits exactly ``dof`` samples, one per joint, indexed 0..dof-1."""
    robot = SimRobot(dof=dof)
    samples = robot.read()
    assert len(samples) == dof
    assert [s.chain_index for s in samples] == list(range(dof))


def test_dof_below_one_rejected() -> None:
    """DOF < 1 fails loud at construction (a zero-DOF robot's capabilities would lie)."""
    with pytest.raises(ValueError, match="dof must be >= 1"):
        SimRobot(dof=0)


def test_read_state_length_matches_dof() -> None:
    """``read_state`` returns exactly ``dof`` joint angles (the buffer-sizing contract)."""
    robot = SimRobot(dof=5)
    assert len(robot.read_state().joint_angles) == 5


# ---------------------------------------------------------------------------
# Monotonic, non-zero, seeded timestamps
# ---------------------------------------------------------------------------


def test_timestamps_strictly_increasing_and_nonzero() -> None:
    """Same-joint stamps are strictly increasing and never zero (the time-sync contract)."""
    robot = SimRobot(dof=2, start_ns=1_000_000_000, period_ns=10_000_000)
    stamps = [robot.read()[0].timestamp_ns for _ in range(20)]
    assert all(ts > 0 for ts in stamps)
    assert all(b > a for a, b in pairwise(stamps))
    # Exact clock: start + i*period.
    assert stamps == [1_000_000_000 + i * 10_000_000 for i in range(20)]


def test_timestamps_pass_jitter_budget() -> None:
    """The stamp stream passes ``compute_jitter``: backwards==0, dropouts==0, within budget.

    A fixed-period clock has 0 jitter by construction; this pins that the sim's timeline is
    clean input to the recorder's quarantine gate (no cross-modal-misalignment holes).
    """
    robot = SimRobot(dof=1, period_ns=10_000_000)
    stamps = [robot.read()[0].timestamp_ns for _ in range(50)]
    stats = compute_jitter(stamps)
    ok, reasons = JitterBudget().check(stats)
    assert ok, reasons
    assert stats.backwards == 0
    assert stats.dropouts == 0


def test_start_and_period_must_be_positive() -> None:
    """Zero/negative start or period is rejected (never a zero/backwards timestamp)."""
    with pytest.raises(ValueError, match="start_ns must be > 0"):
        SimRobot(start_ns=0)
    with pytest.raises(ValueError, match="period_ns must be > 0"):
        SimRobot(period_ns=0)


def test_frequency_must_be_positive() -> None:
    """A non-positive frequency is rejected (it would silently flatten every trajectory)."""
    with pytest.raises(ValueError, match="frequency_hz must be > 0"):
        SimRobot(frequency_hz=0.0)


def test_rng_seam_is_seeded_and_reproducible() -> None:
    """``rng()`` exposes the ONE seeded stream B3 will draw noise from (seed-reproducible)."""
    assert SimRobot(seed=13).rng() == SeededRng(13)
    # Same seed => same stream identity; different seed => different.
    assert SimRobot(seed=13).rng() == SimRobot(seed=13).rng()
    assert SimRobot(seed=1).rng() != SimRobot(seed=2).rng()


def test_generate_orders_rows_by_tick_then_joint() -> None:
    """``generate`` yields (tick, joint) order; per-joint stamps strictly increase."""
    robot = SimRobot(dof=2, start_ns=1_000, period_ns=1_000)
    rows = robot.generate(3)
    assert len(rows) == 6  # 3 ticks x 2 joints
    # Reconstruct per-joint stamp series and assert strict monotonicity per joint.
    for j in (0, 1):
        series = [r.timestamp_ns for r in rows if r.chain_index == j]
        assert series == [1_000, 2_000, 3_000]


def test_generate_rejects_negative_ticks() -> None:
    with pytest.raises(ValueError, match="n_ticks must be >= 0"):
        SimRobot().generate(-1)


# ---------------------------------------------------------------------------
# Independent-copy reads (no by-reference corruption)
# ---------------------------------------------------------------------------


def test_read_returns_independent_samples() -> None:
    """Mutating a returned sample must not change what the next read produces."""
    robot = SimRobot(dof=2)
    first = robot.read()
    baseline = first[0].joint_angle
    first[0].joint_angle = 999.0  # caller corrupts its copy
    robot.reset()
    again = robot.read()
    assert again[0].joint_angle == baseline  # internal state untouched


def test_read_state_returns_independent_list() -> None:
    """Mutating a returned RobotState's list must not corrupt the next read_state()."""
    robot = SimRobot(dof=3)
    state = robot.read_state()
    state.joint_angles[0] = 123.0
    robot.reset()
    assert robot.read_state().joint_angles[0] != 123.0


def test_sample_at_is_pure_no_cursor_mutation() -> None:
    """``sample_at`` does not advance the cursor (pure) — repeated calls are identical."""
    robot = SimRobot(dof=1)
    a = robot.sample_at(4, 0)
    b = robot.sample_at(4, 0)
    assert a.as_row() == b.as_row()
    # And the streaming cursor is unaffected: first read() is still tick 0.
    assert robot.read()[0].timestamp_ns == robot.start_ns


# ---------------------------------------------------------------------------
# Determinism (byte-stable across independent runs)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["sine", "ramp", "hold"])
def test_same_config_is_byte_identical(model: str) -> None:
    """Same config => identical output (as_row() equality) across two fresh robots."""
    a = SimRobot(dof=3, trajectory=model, seed=7).generate(40)
    b = SimRobot(dof=3, trajectory=model, seed=7).generate(40)
    assert [s.as_row() for s in a] == [s.as_row() for s in b]


def test_reset_replays_identical_sequence() -> None:
    """After reset(), the robot replays the identical seeded sequence (reuse-safe)."""
    robot = SimRobot(dof=2, trajectory="ramp")
    first = [s.as_row() for s in robot.read() + robot.read()]
    robot.reset()
    second = [s.as_row() for s in robot.read() + robot.read()]
    assert first == second


def test_seed_does_not_change_zero_noise_output() -> None:
    """Back-compat: with the default (zero-noise) config, the seed does NOT perturb output.

    B2 shipped this as the ``test_seed_does_not_change_output_yet`` canary (the seed was
    threaded but unused). B3 makes the seed matter *only when noise is enabled*; with the
    default :data:`NO_NOISE` config the trajectories are still fully deterministic, so different
    seeds remain byte-identical. The inverse ("seed DOES change output with noise ON") is pinned
    by ``test_noise_on_different_seed_diverges`` in test_sim_noise.py — coverage is not lost,
    just correctly split between the noise-off and noise-on regimes.
    """
    a = SimRobot(dof=2, seed=0).generate(20)
    b = SimRobot(dof=2, seed=999).generate(20)
    assert [s.as_row() for s in a] == [s.as_row() for s in b]


# ---------------------------------------------------------------------------
# Trajectory models: registry + per-model spec
# ---------------------------------------------------------------------------


def test_at_least_two_trajectory_models_registered() -> None:
    """The B2 exit bar: >= 2 pluggable trajectory models, sine among them."""
    assert {"sine", "ramp"} <= set(TRAJECTORIES)
    assert len(TRAJECTORIES) >= 2


def test_unknown_trajectory_rejected() -> None:
    """An unknown trajectory name fails loud at construction, listing the options."""
    with pytest.raises(ValueError, match="unknown trajectory"):
        SimRobot(trajectory="does_not_exist")


def test_custom_callable_trajectory_accepted() -> None:
    """A bespoke Callable is a first-class trajectory (the Callable seam, not a class tree)."""

    def flat(t_sec: float, joint_index: int, params: TrajectoryParams) -> float:
        return 0.42

    robot = SimRobot(dof=1, trajectory=flat)
    assert robot.read()[0].joint_angle == 0.42


@pytest.mark.parametrize("model", ["sine", "ramp", "hold"])
@pytest.mark.parametrize("amplitude", [0.5, 1.0, 2.5])
def test_angles_bounded_by_amplitude(model: str, amplitude: float) -> None:
    """Every model keeps joint angles within [-amplitude, +amplitude] (the range property)."""
    robot = SimRobot(dof=4, trajectory=model, amplitude_rad=amplitude, frequency_hz=1.0)
    rows = robot.generate(200)
    assert rows  # non-empty
    assert all(abs(s.joint_angle) <= amplitude + 1e-9 for s in rows)


def test_sine_matches_closed_form() -> None:
    """``sine`` is exactly ``amplitude*sin(2*pi*f*t + phase)`` at joint 0 (phase 0)."""
    params = TrajectoryParams(amplitude_rad=1.5, frequency_hz=2.0)
    got = sine(0.1, 0, params)
    assert got == pytest.approx(1.5 * math.sin(2 * math.pi * 2.0 * 0.1))


def test_ramp_hits_amplitude_extremes() -> None:
    """``ramp`` reaches +amplitude at the cycle midpoint and -amplitude at the cycle start."""
    params = TrajectoryParams(amplitude_rad=1.0, frequency_hz=1.0)
    assert ramp(0.0, 0, params) == pytest.approx(-1.0)  # cycle start
    assert ramp(0.5, 0, params) == pytest.approx(1.0)  # cycle midpoint


def test_ramp_velocity_is_piecewise_constant() -> None:
    """``ramp`` has a constant-magnitude slope on each half-cycle (unlike sine's smooth deriv).

    Sampled velocities on the rising half all share one sign/magnitude — the contrast to sine
    the model exists to provide for downstream P-C/P-D work.
    """
    robot = SimRobot(dof=1, trajectory="ramp", frequency_hz=1.0, period_ns=1_000_000)
    rows = robot.generate(50)
    # Velocities at index 2..10 are on the first rising ramp; magnitudes ~equal.
    vels = [r.joint_velocity for r in rows[2:10]]
    assert all(v > 0 for v in vels)
    assert max(vels) - min(vels) < 1e-6


def test_hold_is_static() -> None:
    """``hold`` parks each joint at a constant angle => ~zero velocity after the first tick."""
    robot = SimRobot(dof=3, trajectory="hold")
    rows = robot.generate(10)
    for r in rows:
        assert r.joint_velocity == pytest.approx(0.0)
    # Joint 0 sits at sin(0) == 0 exactly.
    assert all(r.joint_angle == 0.0 for r in rows if r.chain_index == 0)


def test_duplicate_trajectory_name_rejected() -> None:
    """Re-registering a name is a loud error (no silent golden-shadowing footgun)."""
    with pytest.raises(ValueError, match="already registered"):

        @trajectory("sine")
        def _dupe(t_sec: float, joint_index: int, params: TrajectoryParams) -> float:
            return 0.0


def test_hold_and_sine_and_ramp_are_distinct() -> None:
    """The three models produce different signals (they are not accidentally the same fn).

    Sampled at joint 1 (non-zero hold offset) at t=0.1 so all three differ.
    """
    p = TrajectoryParams(amplitude_rad=1.0, frequency_hz=1.0)
    vals = {sine(0.1, 1, p), ramp(0.1, 1, p), hold(0.1, 1, p)}
    assert len(vals) == 3


# ---------------------------------------------------------------------------
# SimRobotAdapter — behind the FROZEN RobotAdapter
# ---------------------------------------------------------------------------


def test_adapter_read_state_monotonic_nonzero() -> None:
    """Adapter read_state stamps are strictly increasing and never zero (fixes SimAdapter=0)."""
    a = SimRobotAdapter(dof=3)
    a.connect()
    stamps = [a.read_state().timestamp_ns for _ in range(10)]
    assert all(ts > 0 for ts in stamps)
    assert all(y > x for x, y in pairwise(stamps))


def test_adapter_read_state_independent_copy() -> None:
    """Mutating a returned adapter state must not corrupt internal state (fixes by-reference)."""
    a = SimRobotAdapter(dof=2)
    a.connect()
    s = a.read_state()
    s.joint_angles[0] = 999.0
    a.connect()  # rewind
    assert a.read_state().joint_angles[0] != 999.0


def test_adapter_reflects_command() -> None:
    """After send_command, read_state reflects the targets — on a fresh, freshly-stamped state."""
    a = SimRobotAdapter(dof=3)
    a.connect()
    targets = [0.1, 0.2, 0.3]
    a.send_command(RobotCommand(joint_targets=targets))
    s1 = a.read_state()
    assert s1.joint_angles == targets
    assert s1.timestamp_ns > 0
    s2 = a.read_state()
    assert s2.joint_angles == targets
    assert s2.timestamp_ns > s1.timestamp_ns  # still advancing the monotonic clock


def test_adapter_command_is_copied() -> None:
    """A caller mutating the command after send_command cannot reach the reflected state."""
    a = SimRobotAdapter(dof=2)
    a.connect()
    cmd = RobotCommand(joint_targets=[1.0, 2.0])
    a.send_command(cmd)
    cmd.joint_targets[0] = 99.0  # mutate after handing it over
    assert a.read_state().joint_angles == [1.0, 2.0]


def test_adapter_connect_is_idempotent_and_resets() -> None:
    """connect() is idempotent and rewinds the trajectory + clears any pending command."""
    a = SimRobotAdapter(dof=2)
    a.connect()
    a.send_command(RobotCommand(joint_targets=[5.0, 6.0]))
    a.connect()  # should clear the command and rewind
    s = a.read_state()
    assert s.joint_angles != [5.0, 6.0]
    assert s.timestamp_ns == a.robot.start_ns


def test_adapter_capabilities_truthful() -> None:
    """capabilities().dof matches state length; force feedback stays False."""
    a = SimRobotAdapter(dof=7)
    a.connect()
    caps = a.capabilities()
    assert caps.dof == 7
    assert caps.has_force_feedback is False
    assert len(a.read_state().joint_angles) == caps.dof


def test_adapter_via_registry() -> None:
    """The adapter is reachable through the registry as ``sim_robot`` (lazy factory)."""
    assert "sim_robot" in list_adapters()
    a = make_adapter("sim_robot", dof=4)
    assert isinstance(a, SimRobotAdapter)
    a.connect()
    assert len(a.read_state().joint_angles) == 4


def test_adapter_state_is_robot_state() -> None:
    """read_state returns a RobotState (type contract)."""
    a = SimRobotAdapter(dof=1)
    a.connect()
    assert isinstance(a.read_state(), RobotState)


def test_phase_offsets_unique_across_all_dof() -> None:
    """No two joints share a phase at ANY DOF — regression for the fixed ``i*pi/3`` spread
    that repeated every 6 joints (joint 6 in lockstep with joint 0 at ``dof >= 7``)."""
    for dof in (3, 6, 7, 8, 12):
        phases = {round(_phase_offset(i, dof) % (2 * math.pi), 9) for i in range(dof)}
        assert len(phases) == dof, f"phase collision at dof={dof}"


def test_adapter_send_command_rejects_wrong_dof() -> None:
    """A command whose target count != dof is rejected loud, so ``read_state`` can never return
    ``joint_angles`` that disagree with ``capabilities().dof`` (the DOF-length invariant)."""
    a = SimRobotAdapter(dof=3)
    a.connect()
    with pytest.raises(ValueError, match="expected 3"):
        a.send_command(RobotCommand(joint_targets=[0.1, 0.2]))  # 2 != 3
    # A correctly-sized command is reflected on a fresh, freshly-stamped state.
    a.send_command(RobotCommand(joint_targets=[0.1, 0.2, 0.3]))
    st = a.read_state()
    assert st.joint_angles == [0.1, 0.2, 0.3]
    assert len(st.joint_angles) == a.capabilities().dof
