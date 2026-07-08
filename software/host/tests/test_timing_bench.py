"""C7 — the timing benchmark phase-gate, tested in BOTH directions.

The point of a gate is that it can say no. These tests pin the measured numbers of the
canonical suite AND prove the gate FAILS on the injected violations (burst/skew), that the
CLI exits non-zero on that failure, and that every headline number is re-derived (so a
hand-forged report cannot pass). Un-fakeable: reorder/guess/clamp a value and the
construction or a threshold catches it. Deterministic: no wall clock, seeded throughout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from timing.align import AlignmentBudget
from timing.bench import (
    BENCH_VERSION,
    DEFAULT_THRESHOLDS,
    REPORT_BASENAME,
    BenchCase,
    BenchReport,
    CaseThresholds,
    canonical_cases,
    demand_clean_thresholds,
    gate,
    main,
    nearest_rank_percentile,
    render_markdown,
    run_bench,
    run_suite,
)
from timing.export_meta import SyncVerdict

# ---------------------------------------------------------------------------
# percentile — the ONE published method, pinned on a hand-computed case
# ---------------------------------------------------------------------------


class TestNearestRankPercentile:
    def test_hand_computed_ranks(self) -> None:
        values = list(range(1, 21))  # 1..20 ascending, n=20
        # nearest-rank: rank = ceil(pct/100 * n), 1-based -> value at index rank-1
        assert nearest_rank_percentile(values, 50.0) == 10  # ceil(10.0)=10
        assert nearest_rank_percentile(values, 95.0) == 19  # ceil(19.0)=19
        assert nearest_rank_percentile(values, 99.0) == 20  # ceil(19.8)=20
        assert nearest_rank_percentile(values, 100.0) == 20  # ceil(20.0)=20
        assert nearest_rank_percentile([42], 99.0) == 42  # single value, any rank

    def test_returns_an_observed_value_never_interpolates(self) -> None:
        # An interpolating percentile between 10 and 20 could invent 19.5; nearest-rank
        # must return an element that is actually present.
        values = [10, 20]
        assert nearest_rank_percentile(values, 75.0) in values

    def test_rejects_empty_and_out_of_range_and_unsorted(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50.0)
        with pytest.raises(ValueError, match="must be in"):
            nearest_rank_percentile([1], 0.0)
        with pytest.raises(ValueError, match="must be in"):
            nearest_rank_percentile([1], 100.1)
        with pytest.raises(ValueError, match="ascending"):
            nearest_rank_percentile([2, 1], 50.0)  # sorting here would hide a caller bug
        with pytest.raises(ValueError, match="finite"):
            nearest_rank_percentile([1], float("nan"))
        with pytest.raises(ValueError, match="must be an int"):
            nearest_rank_percentile([True], 50.0)  # bool is not a measurement


# ---------------------------------------------------------------------------
# the canonical suite — measured once, reused (run_suite is the slow part)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def suite(tmp_path_factory: pytest.TempPathFactory) -> tuple[BenchReport, ...]:
    workdir = tmp_path_factory.mktemp("bench_suite")
    return run_suite(canonical_cases(), workdir=workdir)


def _by_name(reports: tuple[BenchReport, ...]) -> dict[str, BenchReport]:
    return {r.name: r for r in reports}


class TestCanonicalSuiteMeasurements:
    def test_the_five_canonical_cases_are_present(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        assert [r.name for r in suite] == [
            "clean_baseline",
            "can_jitter_mild",
            "camera_variable_33ms",
            "burst_stall_200ms",
            "skewed_source_clock",
        ]

    def test_clean_baseline_is_aligned_zero_violations(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        r = _by_name(suite)["clean_baseline"]
        assert r.verdict is SyncVerdict.ALIGNED_WITHIN_BUDGET
        assert r.monotonicity_violations == 0
        assert r.flagged_records == 0
        assert r.contact_event_accuracy == 1.0
        # structural interleave bound of the round-robin lattice
        assert r.max_abs_offset_ns is not None and r.max_abs_offset_ns <= 20_000_000

    def test_burst_stall_is_quarantined_with_flagged_stamps(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        r = _by_name(suite)["burst_stall_200ms"]
        # burst_stall injects backwards + dropout -> the episode gate refuses it.
        assert r.verdict is SyncVerdict.QUARANTINED
        assert r.monotonicity_violations == 20
        assert r.flagged_records == 20
        assert r.episode_gate_passed is False
        assert r.episode_gate_reasons  # the refusal reason is recorded, never silent

    def test_skewed_clock_is_quarantined_with_clean_intervals(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        # The case that proves interval jitter is NOT enough: intervals are perfectly
        # clean (0 violations) yet NOTHING aligns (every candidate is out of budget).
        r = _by_name(suite)["skewed_source_clock"]
        assert r.verdict is SyncVerdict.QUARANTINED
        assert r.monotonicity_violations == 0
        assert r.flagged_records == 0
        assert r.non_matched_results > 0

    def test_every_case_is_deterministic_and_roundtrips_both_formats(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        for r in suite:
            assert r.replay_deterministic is True
            assert r.lerobot_roundtrip_ok is True
            assert r.parquet_roundtrip_ok is True

    def test_offsets_are_re_derivable_from_the_embedded_meta(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        # to_dict -> from_dict reconstructs through the strict loader; a report whose
        # headline offsets contradicted its own TimingMeta could not survive this.
        for r in suite:
            assert BenchReport.from_dict(r.to_dict()) == r


# ---------------------------------------------------------------------------
# the gate — it must be able to say NO
# ---------------------------------------------------------------------------


class TestGate:
    def test_default_thresholds_pass_the_canonical_suite(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        passed, failures = gate(suite, DEFAULT_THRESHOLDS)
        assert passed is True, failures
        assert failures == []

    def test_demand_clean_thresholds_FAIL_on_injected_violations(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        # The canonical suite CONTAINS quarantined cases by design; demanding a clean
        # suite MUST fail. This is the whole point of the gate.
        thresholds = demand_clean_thresholds([r.name for r in suite])
        passed, failures = gate(suite, thresholds)
        assert passed is False
        # the burst + skew cases are the ones that break the "all aligned" demand
        joined = " ".join(failures)
        assert "burst_stall_200ms" in joined
        assert "skewed_source_clock" in joined

    def test_ungated_report_is_rejected_not_silently_passed(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        partial = {"clean_baseline": DEFAULT_THRESHOLDS["clean_baseline"]}
        with pytest.raises(ValueError, match="no thresholds for case"):
            gate(suite, partial)

    def test_threshold_for_absent_case_is_rejected(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        extra = dict(DEFAULT_THRESHOLDS)
        extra["ghost_case"] = DEFAULT_THRESHOLDS["clean_baseline"]
        with pytest.raises(ValueError, match="absent case"):
            gate(suite, extra)

    def test_determinism_is_enforced_unconditionally(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        # Even if a case were allow-listed for its verdict, a non-deterministic replay
        # must still fail the gate — determinism is not a configurable threshold.
        r = _by_name(suite)["clean_baseline"]
        forged = BenchReport.from_dict({**r.to_dict(), "replay_deterministic": False})
        passed, failures = gate([forged], {"clean_baseline": DEFAULT_THRESHOLDS["clean_baseline"]})
        assert passed is False
        assert any("NOT deterministic" in f for f in failures)

    def test_empty_reports_or_bad_types_raise(self) -> None:
        with pytest.raises(ValueError, match="reports is empty"):
            gate([], DEFAULT_THRESHOLDS)
        # An unvalidated blob is not a gateable measurement.
        with pytest.raises(ValueError, match="must be a BenchReport"):
            gate([object()], DEFAULT_THRESHOLDS)  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# report + case construction — fabrication cannot exist as a value
# ---------------------------------------------------------------------------


class TestConstructionInvariants:
    def test_case_requires_window_budget(self) -> None:
        with pytest.raises(ValueError, match="window_ns is required"):
            BenchCase(
                name="x",
                scenario="slip_recovery",
                episode_seed=1,
                fixture=None,
                budget=AlignmentBudget(max_skew_ns=1_000_000),  # no window
            )

    def test_case_name_must_be_slug(self) -> None:
        with pytest.raises(ValueError, match=r"\[a-z0-9_\]"):
            BenchCase(
                name="../escape",
                scenario="slip_recovery",
                episode_seed=1,
                fixture=None,
                budget=AlignmentBudget(max_skew_ns=1, window_ns=1),
            )

    def test_thresholds_reject_empty_allowance(self) -> None:
        with pytest.raises(ValueError, match="non-empty frozenset"):
            CaseThresholds(
                allowed_verdicts=frozenset(),
                max_monotonicity_violations=0,
            )

    def test_thresholds_reject_bool_count(self) -> None:
        with pytest.raises(ValueError, match="int count"):
            CaseThresholds(
                allowed_verdicts=frozenset({SyncVerdict.ALIGNED_WITHIN_BUDGET}),
                max_monotonicity_violations=True,  # bool would pass a truthy compare
            )

    def test_run_bench_rejects_non_case(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must be a BenchCase"):
            run_bench(object(), workdir=tmp_path)  # type: ignore[arg-type]

    def test_run_suite_rejects_duplicate_names(self, tmp_path: Path) -> None:
        case = canonical_cases()[0]
        with pytest.raises(ValueError, match="duplicate case names"):
            run_suite([case, case], workdir=tmp_path)


# ---------------------------------------------------------------------------
# the CLI — one command, deterministic artifacts, exit code reflects the gate
# ---------------------------------------------------------------------------


class TestCli:
    def test_default_run_writes_artifacts_and_exits_zero(self, tmp_path: Path) -> None:
        rc = main(["--out", str(tmp_path), "--seed", "7"])
        assert rc == 0
        json_path = tmp_path / f"{REPORT_BASENAME}.json"
        md_path = tmp_path / f"{REPORT_BASENAME}.md"
        assert json_path.exists() and md_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["bench_version"] == BENCH_VERSION
        assert payload["gate_passed"] is True
        assert len(payload["reports"]) == 5

    def test_demand_clean_exits_nonzero(self, tmp_path: Path) -> None:
        # The REQUIRED failure path: the gate provably rejects the injected-violation
        # suite, and the CLI surfaces that as a non-zero exit for CI.
        rc = main(["--out", str(tmp_path), "--seed", "7", "--demand-clean"])
        assert rc == 1
        payload = json.loads((tmp_path / f"{REPORT_BASENAME}.json").read_text("utf-8"))
        assert payload["gate_passed"] is False
        assert payload["gate_failures"]

    def test_artifacts_are_byte_identical_for_same_args(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        # Same args must also mean the same gate outcome (exit code), not just bytes.
        assert main(["--out", str(a), "--seed", "7"]) == 0
        assert main(["--out", str(b), "--seed", "7"]) == 0
        for base in (f"{REPORT_BASENAME}.json", f"{REPORT_BASENAME}.md"):
            assert (a / base).read_bytes() == (b / base).read_bytes()

    def test_module_entrypoint_exits_nonzero_on_demand_clean(
        self, tmp_path: Path
    ) -> None:
        # Prove `python -m timing.bench` actually returns the gate's exit code to the OS.
        proc = subprocess.run(
            [sys.executable, "-m", "timing.bench", "--out", str(tmp_path), "--demand-clean"],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1, proc.stderr


class TestMarkdownArtifact:
    def test_markdown_shows_pass_and_lists_every_case(
        self, suite: tuple[BenchReport, ...]
    ) -> None:
        passed, failures = gate(suite, DEFAULT_THRESHOLDS)
        md = render_markdown(
            suite,
            DEFAULT_THRESHOLDS,
            passed=passed,
            failures=failures,
            gate_mode="default",
            regenerate="cd host && python -m timing.bench --out <dir>",
        )
        assert "**PASS**" in md
        for r in suite:
            assert r.name in md
