"""C4 — chaos bench: every fault shape is deterministic AND provably detected.

Two directions per fault (MASTER_TASK_QUEUE §P-C C4 — no always-pass thresholds):

* a MILD parameterization that stays WITHIN the default ``JitterBudget`` (disturbed but
  exportable), and
* a VIOLATING parameterization (or the fault's documented instrument) where the check
  FAILS with reasons — proving the measurement stack catches the disturbance rather
  than blessing it.

Reference-only faults (FIXED_DELAY, SKEWED_CLOCK) are *documented* as invisible to
single-stream interval stats; the tests prove BOTH that invisibility and that the
offset-vs-reference instrument catches them — a budget "pass" here is not a free pass.
"""
from __future__ import annotations

import pytest

from logger.jitter import JitterBudget, JitterStats, compute_jitter
from sim.chaos import (
    BENCH_FIXTURES,
    BURST_STALL_200MS,
    CAMERA_VARIABLE_33MS,
    CAN_JITTER_MILD,
    SKEWED_SOURCE_CLOCK,
    BenchFixture,
    FaultKind,
    FaultSpec,
    apply_faults,
    lattice_stamps,
)
from sim.rng import SeededRng

_BUDGET = JitterBudget()


def _stats(stamps: list[int]) -> tuple[bool, list[str], JitterStats]:
    st = compute_jitter(stamps)
    ok, reasons = _BUDGET.check(st)
    return ok, reasons, st


# -- identity & determinism ----------------------------------------------------------------------


def test_no_spec_is_identity() -> None:
    base = lattice_stamps(50)
    assert apply_faults(base, None, SeededRng(1)) == base
    assert apply_faults(base, [], SeededRng(1)) == base


def test_fixtures_are_byte_deterministic() -> None:
    for name, fx in BENCH_FIXTURES.items():
        assert fx.disturbed() == fx.disturbed(), name
        assert fx.clean() == fx.clean(), name


def test_different_seed_differs_for_stochastic_faults() -> None:
    base = lattice_stamps(100)
    spec = FaultSpec(kind=FaultKind.JITTER, magnitude_ns=200_000)
    a = apply_faults(base, spec, SeededRng(1))
    b = apply_faults(base, spec, SeededRng(2))
    assert a != b
    assert a == apply_faults(base, spec, SeededRng(1))  # and same seed converges


def test_extending_a_chain_does_not_shift_earlier_faults() -> None:
    """Per-fault spawned sub-streams: fault[0]'s draws are identical whether or not a
    second fault follows it — the chain is bisectable."""
    base = lattice_stamps(60)
    jit = FaultSpec(kind=FaultKind.JITTER, magnitude_ns=100_000)
    dup = FaultSpec(kind=FaultKind.DUPLICATE, at_index=5)
    only_jitter = apply_faults(base, [jit], SeededRng(7))
    chained = apply_faults(base, [jit, dup], SeededRng(7))
    del chained[5]  # remove the inserted duplicate
    assert chained == only_jitter


# -- JITTER: mild passes, violating fails, never reorders ----------------------------------------


def test_jitter_mild_within_budget_but_measurable() -> None:
    disturbed = CAN_JITTER_MILD.disturbed()
    ok, reasons, st = _stats(disturbed)
    assert ok, reasons
    assert st.jitter_max_ns > 0  # measurably disturbed, not secretly identity
    assert disturbed == sorted(disturbed)  # jitter NEVER reorders (clamped bands)


def test_jitter_violating_fails_budget_with_reasons() -> None:
    base = lattice_stamps(200)  # 10 ms lattice
    spec = FaultSpec(kind=FaultKind.JITTER, magnitude_ns=4_900_000)  # ±4.9 ms >> 2 ms p99
    ok, reasons, st = _stats(apply_faults(base, spec, SeededRng(3)))
    assert not ok
    assert any("jitter" in r for r in reasons)
    assert st.jitter_p99_ns > _BUDGET.max_jitter_p99_ns


# -- FIXED_DELAY: invisible to interval stats, caught by the reference instrument -----------------


def test_fixed_delay_invisible_to_interval_stats_but_caught_vs_reference() -> None:
    base = lattice_stamps(100)
    delayed = apply_faults(
        base, FaultSpec(kind=FaultKind.FIXED_DELAY, delay_ns=50_000_000), SeededRng(1)
    )
    assert compute_jitter(delayed) == compute_jitter(base)  # documented invisibility
    offsets = [d - c for d, c in zip(delayed, base, strict=True)]
    assert set(offsets) == {50_000_000}  # the reference instrument sees ALL of it


# -- BURST: the must-quarantine case ---------------------------------------------------------------


def test_burst_stall_fails_budget_with_dropout_and_backwards() -> None:
    ok, reasons, st = _stats(BURST_STALL_200MS.disturbed())
    assert not ok
    assert st.dropouts > 0 and st.backwards > 0  # gap in, collisions out
    assert len(reasons) >= 2


def test_burst_window_past_end_rejected() -> None:
    with pytest.raises(ValueError, match="past the end"):
        apply_faults(
            lattice_stamps(10),
            FaultSpec(kind=FaultKind.BURST_DELAY, window_start=10, window_len=2,
                      delay_ns=1_000),
            SeededRng(1),
        )


# -- DROP: count + period instruments --------------------------------------------------------------


def test_drop_every_k_shrinks_count_and_shifts_measured_period() -> None:
    base = lattice_stamps(100, period_ns=10_000_000)
    dropped = apply_faults(
        base, FaultSpec(kind=FaultKind.DROP, every_k=2), SeededRng(1)
    )
    assert len(dropped) == 50
    # Uniform every-2nd drop doubles every interval: the measured period is 2x nominal —
    # the period-drift instrument (dropouts stay 0 because the gaps are uniform; that is
    # exactly why count+period checks exist alongside the gap check).
    assert compute_jitter(dropped).period_ns == 20_000_000


def test_drop_probability_is_seeded_and_deterministic() -> None:
    base = lattice_stamps(200)
    spec = FaultSpec(kind=FaultKind.DROP, probability=0.3)
    a = apply_faults(base, spec, SeededRng(11))
    assert a == apply_faults(base, spec, SeededRng(11))
    assert 0 < len(a) < len(base)  # something dropped, not everything


# -- DUPLICATE / REORDER: backwards counter + permutation signatures -------------------------------


def test_duplicate_fails_budget_and_preserves_set() -> None:
    base = lattice_stamps(50)
    doubled = apply_faults(
        base, FaultSpec(kind=FaultKind.DUPLICATE, at_index=10), SeededRng(1)
    )
    assert len(doubled) == 51 and set(doubled) == set(base)
    ok, _, st = _stats(doubled)
    assert not ok and st.backwards >= 1  # dt == 0 counts as backwards (dt <= 0)


def test_duplicate_past_end_rejected() -> None:
    with pytest.raises(ValueError, match="past the end"):
        apply_faults(lattice_stamps(5),
                     FaultSpec(kind=FaultKind.DUPLICATE, at_index=5), SeededRng(1))


def test_reorder_fails_budget_and_is_a_pure_permutation() -> None:
    base = lattice_stamps(50)
    swapped = apply_faults(
        base,
        FaultSpec(kind=FaultKind.REORDER, window_start=10, window_len=10),
        SeededRng(9),
    )
    assert sorted(swapped) == base and swapped != base  # permutation, actually disturbed
    ok, _, st = _stats(swapped)
    assert not ok and st.backwards >= 1


def test_reorder_window_exceeding_sequence_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        apply_faults(lattice_stamps(5),
                     FaultSpec(kind=FaultKind.REORDER, window_start=4, window_len=2),
                     SeededRng(1))


# -- SKEWED_CLOCK: interval-clean, reference-caught ------------------------------------------------


def test_skewed_clock_passes_interval_budget_but_reference_sees_growing_offset() -> None:
    clean = SKEWED_SOURCE_CLOCK.clean()
    skewed = SKEWED_SOURCE_CLOCK.disturbed()
    ok, reasons, _ = _stats(skewed)
    assert ok, reasons  # near-invisible to single-stream stats — documented
    offsets = [s - c for s, c in zip(skewed, clean, strict=True)]
    assert offsets[0] == 5_000_000  # exactly offset_ns at the anchor
    assert offsets[-1] > offsets[0]  # drift accumulates — the reference instrument


def test_skewed_clock_identity_params_rejected() -> None:
    with pytest.raises(ValueError, match="identity"):
        FaultSpec(kind=FaultKind.SKEWED_CLOCK, offset_ns=0, drift_ppm=0.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_drift_rejected(bad: float) -> None:
    """NaN/inf drift is unbounded (no range check to catch it) — must fail loud at the
    spec boundary, never reach round() inside the applier."""
    with pytest.raises(ValueError, match="finite"):
        FaultSpec(kind=FaultKind.SKEWED_CLOCK, offset_ns=0, drift_ppm=bad)


# -- VARIABLE_FRAME_TIME: mild passes, violating fails, stays monotonic ----------------------------


def test_variable_frame_time_mild_monotonic_and_within_budget() -> None:
    disturbed = CAMERA_VARIABLE_33MS.disturbed()
    assert disturbed == sorted(disturbed) and len(set(disturbed)) == len(disturbed)
    ok, reasons, st = _stats(disturbed)
    assert ok, reasons
    assert st.jitter_max_ns > 0  # a real wobble, not a lattice


def test_variable_frame_time_violating_fails_budget() -> None:
    base = lattice_stamps(90, period_ns=33_333_333)
    spec = FaultSpec(kind=FaultKind.VARIABLE_FRAME_TIME, wobble=0.45)
    ok, reasons, _ = _stats(apply_faults(base, spec, SeededRng(5)))
    assert not ok
    assert any("jitter" in r for r in reasons)


# -- value gating: raise, never clamp --------------------------------------------------------------


def test_overflow_raises_never_clamps() -> None:
    near_max = [2**63 - 10, 2**63 - 5]
    with pytest.raises(ValueError, match="refusing to clamp"):
        apply_faults(near_max,
                     FaultSpec(kind=FaultKind.FIXED_DELAY, delay_ns=100), SeededRng(1))


def test_underflow_raises_never_clamps() -> None:
    with pytest.raises(ValueError, match="refusing to clamp"):
        apply_faults([100, 200],
                     FaultSpec(kind=FaultKind.SKEWED_CLOCK, offset_ns=-150,
                               drift_ppm=0.1),
                     SeededRng(1))


def test_invalid_input_stamps_rejected() -> None:
    with pytest.raises(ValueError):
        apply_faults([0, 100], None, SeededRng(1))


# -- spec validation: wrong/identity/ambiguous parameters ------------------------------------------


def test_wrong_parameter_for_kind_rejected() -> None:
    with pytest.raises(ValueError, match="silently ignored"):
        FaultSpec(kind=FaultKind.JITTER, magnitude_ns=100, delay_ns=5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": FaultKind.JITTER, "magnitude_ns": 0},
        {"kind": FaultKind.DROP},  # neither selector
        {"kind": FaultKind.DROP, "every_k": 2, "probability": 0.5},  # both
        {"kind": FaultKind.DROP, "probability": 1.0},
        {"kind": FaultKind.DROP, "every_k": 1},  # drops everything
        {"kind": FaultKind.VARIABLE_FRAME_TIME, "wobble": 0.0},
        {"kind": FaultKind.REORDER, "window_start": 0, "window_len": 1},
    ],
)
def test_degenerate_specs_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        FaultSpec(**kwargs)  # type: ignore[arg-type]


def test_chain_order_enforced_for_monotonic_base_faults() -> None:
    """Jitter after an order-breaking fault raises — attribution stays unambiguous."""
    base = lattice_stamps(20)
    with pytest.raises(ValueError, match="strictly increasing base"):
        apply_faults(
            base,
            [FaultSpec(kind=FaultKind.DUPLICATE, at_index=3),
             FaultSpec(kind=FaultKind.JITTER, magnitude_ns=100)],
            SeededRng(1),
        )


def test_non_faultspec_in_chain_rejected() -> None:
    with pytest.raises(ValueError, match="FaultSpec"):
        apply_faults(lattice_stamps(5), ["jitter"], SeededRng(1))  # type: ignore[list-item]


# -- fixture and helper validation -----------------------------------------------------------------


def test_lattice_stamps_validation() -> None:
    with pytest.raises(ValueError, match="n_stamps"):
        lattice_stamps(-1)
    with pytest.raises(ValueError, match="n_stamps"):
        lattice_stamps(True)  # type: ignore[arg-type]


def test_bench_fixture_validation() -> None:
    spec = FaultSpec(kind=FaultKind.FIXED_DELAY, delay_ns=1)
    with pytest.raises(ValueError, match="n_stamps"):
        BenchFixture(name="x", start_ns=1, period_ns=1, n_stamps=1, spec=spec, seed=0)
    with pytest.raises(ValueError, match="name"):
        BenchFixture(name="", start_ns=1, period_ns=1, n_stamps=2, spec=spec, seed=0)


def test_registry_names_match_fixture_names() -> None:
    assert set(BENCH_FIXTURES) == {
        "can_jitter_mild", "camera_variable_33ms", "burst_stall_200ms",
        "skewed_source_clock",
    }
    assert all(name == fx.name for name, fx in BENCH_FIXTURES.items())
