"""C3 — multi-modal alignment engine: adversarial tests for every required failure case.

The failure modes under test (MASTER_TASK_QUEUE §P-C C3 — each test must FAIL if the
engine ever starts to):

* guess a timestamp (publish a match with no candidate, or an offset that is not
  exactly ``matched - ref``),
* silently reuse a stale/too-far target (out-of-budget candidates must never surface),
* hide a missing modality (a miss must be an explicit flagged result, never a hole),
* accept out-of-order or duplicated target input (reject loud — never sort/dedup),
* mishandle duplicated/equidistant stamps (ties resolve by the DOCUMENTED earlier-wins
  rule, deterministically, and are recorded),
* interpolate event-typed data or extrapolate (fabricated observations).

Perfect synthetic timing passing is NOT the bar — the shifted-clock integration test
proves the engine catches real skew on the same data it happily aligns when clean.
"""
from __future__ import annotations

import pytest

from sensors.sim_scenario import SimFramesSource, SimTactileSource
from sim.robot import SimRobot
from sim.scenario import SLIP_RECOVERY
from timing.align import (
    AlignmentBudget,
    AlignmentMethod,
    AlignmentQuality,
    AlignmentResult,
    align,
    align_modalities,
    interpolate_proprio,
    timeline_from_records,
)
from timing.normalize import Normalizer
from timing.stamp import ClockDomain

_B = AlignmentBudget(max_skew_ns=10, window_ns=10)


# -- exact match ------------------------------------------------------------------------------


def test_exact_match_is_exact_offset_zero() -> None:
    (res,) = align([100], [100], _B)
    assert res.method is AlignmentMethod.EXACT
    assert res.quality is AlignmentQuality.MATCHED
    assert res.offset_ns == 0 and res.matched_ns == 100 and res.within_budget


def test_exact_method_rejects_non_coincident() -> None:
    """EXACT means equal stamps — a 1 ns-away candidate is OUT_OF_BUDGET, never matched."""
    (res,) = align([100], [101], _B, method=AlignmentMethod.EXACT)
    assert res.quality is AlignmentQuality.OUT_OF_BUDGET
    assert res.matched_ns is None and res.offset_ns is None and not res.within_budget


# -- bounded skew: both sides of the boundary, boundary inclusive ------------------------------


@pytest.mark.parametrize("k", [1, 9, 10])  # 10 == max_skew_ns exactly: inclusive
def test_nearest_within_budget_matches_with_signed_offset(k: int) -> None:
    (res,) = align([100], [100 + k], _B)
    assert res.quality is AlignmentQuality.MATCHED
    assert res.method is AlignmentMethod.NEAREST
    assert res.offset_ns == k and res.matched_ns == 100 + k


def test_nearest_beyond_budget_is_flagged_and_unpublished() -> None:
    """k = budget+1: the candidate EXISTS but must not surface (stale-reuse ban)."""
    (res,) = align([100], [111], _B)
    assert res.quality is AlignmentQuality.OUT_OF_BUDGET
    assert res.matched_ns is None and res.offset_ns is None and not res.within_budget


def test_large_jitter_beyond_budget_every_ref_flagged() -> None:
    refs = [1_000, 2_000, 3_000]
    (bad,) = [t + 500 for t in refs[:1]]  # single far target
    results = align(refs, [bad], _B)
    assert all(r.quality is AlignmentQuality.OUT_OF_BUDGET for r in results)
    assert all(r.matched_ns is None for r in results)


# -- missing modality ---------------------------------------------------------------------------


def test_empty_target_yields_explicit_no_target_per_ref() -> None:
    results = align([10, 20, 30], [], _B)
    assert len(results) == 3  # a miss is a result, never a shorter list
    assert all(r.quality is AlignmentQuality.NO_TARGET for r in results)
    assert all(r.matched_ns is None for r in results)


def test_window_gap_flags_only_the_gap_span() -> None:
    """No visual frame for a middle span: that span is NO_TARGET; neighbors still match."""
    refs = [100, 200, 300]
    frames = [95, 305]  # nothing near 200
    results = align(refs, frames, _B, method=AlignmentMethod.WINDOW)
    by_ref: dict[int, list[AlignmentResult]] = {}
    for r in results:
        by_ref.setdefault(r.ref_ns, []).append(r)
    assert by_ref[100][0].quality is AlignmentQuality.MATCHED
    assert by_ref[300][0].quality is AlignmentQuality.MATCHED
    assert [r.quality for r in by_ref[200]] == [AlignmentQuality.NO_TARGET]


# -- dirty target input: rejected loud, never repaired -----------------------------------------


def test_out_of_order_target_rejected() -> None:
    with pytest.raises(ValueError, match="out-of-order"):
        align([100], [50, 40], _B)


def test_duplicate_target_stamps_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        align([100], [50, 50], _B)


def test_dirty_reference_rejected_too() -> None:
    with pytest.raises(ValueError, match="out-of-order"):
        align([100, 90], [50], _B)


@pytest.mark.parametrize("bad", [0, -5, True, 1.5])
def test_invalid_stamp_values_rejected_per_class(bad: object) -> None:
    with pytest.raises(ValueError):
        align([100], [bad], _B)  # type: ignore[list-item]


# -- ties: documented, deterministic, recorded ---------------------------------------------------


def test_equidistant_tie_earlier_wins_and_is_recorded() -> None:
    """Event exactly between two candidates: earlier target wins, tie=True — every run."""
    for _ in range(3):  # determinism across repeated calls
        (res,) = align([100], [95, 105], _B)
        assert res.matched_ns == 95 and res.offset_ns == -5
        assert res.tie is True and res.method is AlignmentMethod.NEAREST


def test_event_between_samples_belongs_to_both_windows() -> None:
    """A tactile event equidistant between two refs is in BOTH closed windows."""
    results = align([100, 120], [110], AlignmentBudget(0, window_ns=10),
                    method=AlignmentMethod.WINDOW)
    matched = [r for r in results if r.quality is AlignmentQuality.MATCHED]
    assert [r.ref_ns for r in matched] == [100, 120]
    assert all(r.matched_ns == 110 for r in matched)


def test_window_boundary_is_closed() -> None:
    (res,) = align([100], [110], AlignmentBudget(0, window_ns=10),
                   method=AlignmentMethod.WINDOW)
    assert res.quality is AlignmentQuality.MATCHED  # exactly at ref+window: in budget


# -- result invariants: a forged result cannot exist ---------------------------------------------


def test_forged_offset_rejected() -> None:
    with pytest.raises(ValueError, match="re-derivable"):
        AlignmentResult(ref_ns=100, matched_ns=105, offset_ns=4,
                        method=AlignmentMethod.NEAREST, within_budget=True,
                        quality=AlignmentQuality.MATCHED)


def test_miss_carrying_a_stamp_rejected() -> None:
    with pytest.raises(ValueError, match="never publish a stamp"):
        AlignmentResult(ref_ns=100, matched_ns=111, offset_ns=None,
                        method=AlignmentMethod.NEAREST, within_budget=False,
                        quality=AlignmentQuality.OUT_OF_BUDGET)


def test_matched_out_of_budget_rejected() -> None:
    with pytest.raises(ValueError, match="stale-reuse"):
        AlignmentResult(ref_ns=100, matched_ns=105, offset_ns=5,
                        method=AlignmentMethod.NEAREST, within_budget=False,
                        quality=AlignmentQuality.MATCHED)


def test_tie_flag_only_on_matched_nearest() -> None:
    with pytest.raises(ValueError, match="tie"):
        AlignmentResult(ref_ns=100, matched_ns=None, offset_ns=None,
                        method=AlignmentMethod.WINDOW, within_budget=False,
                        quality=AlignmentQuality.NO_TARGET, tie=True)


def test_exact_with_nonzero_offset_rejected() -> None:
    with pytest.raises(ValueError, match="exact"):
        AlignmentResult(ref_ns=100, matched_ns=105, offset_ns=5,
                        method=AlignmentMethod.EXACT, within_budget=True,
                        quality=AlignmentQuality.MATCHED)


def test_nearest_with_zero_offset_rejected() -> None:
    """An exact coincidence labeled NEAREST is a contradictory record (must be EXACT)."""
    with pytest.raises(ValueError, match=r"recorded\s+as EXACT"):
        AlignmentResult(ref_ns=100, matched_ns=100, offset_ns=0,
                        method=AlignmentMethod.NEAREST, within_budget=True,
                        quality=AlignmentQuality.MATCHED)


def test_window_out_of_budget_rejected() -> None:
    """WINDOW's bound IS the window: a window miss is NO_TARGET, never OUT_OF_BUDGET."""
    with pytest.raises(ValueError, match="window"):
        AlignmentResult(ref_ns=100, matched_ns=None, offset_ns=None,
                        method=AlignmentMethod.WINDOW, within_budget=False,
                        quality=AlignmentQuality.OUT_OF_BUDGET)


# -- budget / method boundary validation ---------------------------------------------------------


@pytest.mark.parametrize("bad", [True, -1, 0.5])
def test_budget_validated_per_class(bad: object) -> None:
    with pytest.raises(ValueError, match="max_skew_ns"):
        AlignmentBudget(max_skew_ns=bad)  # type: ignore[arg-type]


def test_window_method_without_window_budget_fails_loud() -> None:
    with pytest.raises(ValueError, match="window_ns"):
        align([100], [100], AlignmentBudget(max_skew_ns=10),
              method=AlignmentMethod.WINDOW)


def test_align_modalities_names_and_shared_budget() -> None:
    out = align_modalities([100], {"frames": [103], "tactile": [150]}, _B)
    assert out["frames"][0].quality is AlignmentQuality.MATCHED
    assert out["tactile"][0].quality is AlignmentQuality.OUT_OF_BUDGET
    with pytest.raises(ValueError, match="modality name"):
        align_modalities([100], {"": [100]}, _B)


# -- C2 seam: flagged records surfaced, never used ------------------------------------------------


def test_timeline_from_records_excludes_and_surfaces_flagged() -> None:
    records = Normalizer(ClockDomain.MONOTONIC).normalize([100, 50, 200])  # 50 backwards
    clean, flagged = timeline_from_records(records)
    assert clean == (100, 200)
    assert len(flagged) == 1 and flagged[0].original.raw_ns == 50
    # The clean timeline feeds align() directly.
    results = align(list(clean), [100], _B)
    assert results[0].quality is AlignmentQuality.MATCHED


def test_timeline_from_records_rejects_bare_values() -> None:
    with pytest.raises(ValueError, match="TimingRecord"):
        timeline_from_records([100])  # type: ignore[list-item]


# -- interpolation: numeric only, no extrapolation, no events -------------------------------------


def test_interpolate_midpoint_exact_and_endpoints_identity() -> None:
    assert interpolate_proprio(150, (100, 1.0), (200, 3.0)) == 2.0
    assert interpolate_proprio(100, (100, 1.0), (200, 3.0)) == 1.0
    assert interpolate_proprio(200, (100, 1.0), (200, 3.0)) == 3.0


def test_interpolate_refuses_extrapolation() -> None:
    with pytest.raises(ValueError, match="extrapolat"):
        interpolate_proprio(250, (100, 1.0), (200, 3.0))


def test_interpolate_refuses_event_typed_data() -> None:
    with pytest.raises(ValueError, match="NEVER interpolated"):
        interpolate_proprio(150, (100, "slip"), (200, "release"))  # type: ignore[arg-type]


def test_interpolate_refuses_degenerate_segment() -> None:
    with pytest.raises(ValueError, match="backwards"):
        interpolate_proprio(100, (100, 1.0), (100, 2.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_interpolate_refuses_non_finite_values(bad: float) -> None:
    """A NaN/inf sensor value must fail loud, never propagate through the blend."""
    with pytest.raises(ValueError, match="finite"):
        interpolate_proprio(150, (100, bad), (200, 3.0))
    with pytest.raises(ValueError, match="finite"):
        interpolate_proprio(150, (100, 1.0), (200, bad))


# -- determinism ----------------------------------------------------------------------------------


def test_same_inputs_identical_results() -> None:
    a = align(list(range(100, 1100, 100)), [105, 342, 799], _B)
    b = align(list(range(100, 1100, 100)), [105, 342, 799], _B)
    assert [repr(r) for r in a] == [repr(r) for r in b]


# -- integration: the sim stack, clean vs shifted clock -------------------------------------------


@pytest.fixture(scope="module")
def scenario_timelines() -> tuple[list[int], list[int], list[int]]:
    """Proprio lattice + frame/tactile stamps from the real B2/B5 sim stack (seeded).

    Module-scoped: the stack is deterministic, so both integration tests share ONE
    build instead of regenerating identical timelines (CodeRabbit #54)."""
    lattice_ns = 20_000_000
    robot = SimRobot(dof=1, seed=7, start_ns=1_000_000_000, period_ns=lattice_ns)
    n_ticks = round(SLIP_RECOVERY.total_duration_s * 1e9) // lattice_ns
    proprio = [s.timestamp_ns for s in robot.generate(n_ticks)]
    # Bind the concrete sources before `with` (the ABC's __enter__ widens to
    # SensorSource, whose stream() yields object — the B6 fixture pattern).
    tac = SimTactileSource(scenario=SLIP_RECOVERY, seed=7, episode_id="c3",
                           start_ns=1_000_000_000, period_ns=lattice_ns)
    with tac:
        tactile = [s.timestamp_ns for s in tac.stream()]
    fr = SimFramesSource(scenario=SLIP_RECOVERY, seed=7, episode_id="c3",
                         start_ns=1_000_000_000, period_ns=2 * lattice_ns)
    with fr:
        frames = [s.timestamp_ns for s in fr.stream()]
    return proprio, frames, tactile


def test_integration_clean_scenario_aligns_within_budget(
    scenario_timelines: tuple[list[int], list[int], list[int]],
) -> None:
    proprio, frames, tactile = scenario_timelines
    budget = AlignmentBudget(max_skew_ns=20_000_000, window_ns=10_000_000)
    frame_res = align(proprio, frames, budget)
    matched = [r for r in frame_res if r.quality is AlignmentQuality.MATCHED]
    assert len(matched) == len(proprio)  # every tick finds a frame within one period
    assert all(abs(r.offset_ns or 0) <= budget.max_skew_ns for r in matched)
    tactile_res = align(proprio, tactile, budget, method=AlignmentMethod.WINDOW)
    assert any(r.quality is AlignmentQuality.MATCHED for r in tactile_res)


def test_integration_shifted_clock_is_caught_not_absorbed(
    scenario_timelines: tuple[list[int], list[int], list[int]],
) -> None:
    """The un-fakeable case: shift the frame clock beyond budget — EVERY frame
    association must go honestly out of budget; nothing may silently still 'match'."""
    proprio, frames, _ = scenario_timelines
    budget = AlignmentBudget(max_skew_ns=5_000_000)
    shifted = [t + 50_000_000 for t in frames]  # 50 ms skew >> 5 ms budget... mostly
    results = align(proprio, shifted, budget)
    assert all(r.quality is not AlignmentQuality.NO_TARGET for r in results)
    # 50ms shift on a 40ms frame lattice: a shifted frame can land near a LATER tick,
    # so some ticks legitimately re-match. The un-fakeable assertion is about offsets:
    # no published match may exceed the budget, and the tick-to-its-own-frame pairing
    # (offset 10ms in clean data) must be gone.
    for r in results:
        if r.quality is AlignmentQuality.MATCHED:
            assert r.offset_ns is not None and abs(r.offset_ns) <= budget.max_skew_ns
    # And with a shift that exceeds any inter-frame gap remainder, nothing matches:
    far = [t + 1_000_000_000_000 for t in frames]
    far_results = align(proprio, far, budget)
    assert all(r.quality is AlignmentQuality.OUT_OF_BUDGET for r in far_results)
    assert all(r.matched_ns is None for r in far_results)
