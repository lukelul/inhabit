"""C5 — exported timing metadata: auditable sync, no fabrication, legacy-safe.

Un-fakeable by construction:

* the round-trip fixture is a REAL sim-stack run (SimRobot proprio episode + scenario
  frames/tactile sources), normalized by C2 and aligned by C3 — and the reloaded
  ``TimingMeta`` must equal a HAND-COUNTED expected dict, so a builder that guesses,
  drops or invents a single count/offset/flag fails these tests;
* contradictory summaries (offsets without matches, verdicts flattering the counts,
  offsets outside the recorded budget, ...) must be unconstructible;
* unknown keys/tokens/versions must be refused loud on load, never guessed;
* datasets written WITHOUT the sidecar (pre-C5) must load exactly as before (None).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from export import (
    LeRobotExporter,
    ParquetExporter,
    load_lerobot_timing_meta,
    load_parquet_timing_meta,
    make_exporter,
)
from inhabit_can.pvt import Episode, PVTSample
from sensors import SimFramesSource, SimTactileSource
from sim.robot import SimRobot
from sim.scenario import ContactPhase, ContactScenario
from timing import (
    TIMING_META_VERSION,
    AlignmentBudget,
    AlignmentMethod,
    AlignmentQuality,
    AlignmentResult,
    ClockDomain,
    ModalityTiming,
    NormalizationFlag,
    Normalizer,
    SyncVerdict,
    TimingMeta,
    TimingRecord,
    align,
    read_timing_sidecar,
    select_episode_timing,
    timeline_from_records,
    write_timing_sidecar,
)

# ---------------------------------------------------------------------------
# The real-run fixture: sim episode + scenario sources -> C2 -> C3 -> TimingMeta.
# Every expected number below is hand-derivable from these constants.
# ---------------------------------------------------------------------------

_EP_ID = "timing_ep_000"
_BUDGET = AlignmentBudget(max_skew_ns=20_000_000, window_ns=25_000_000)
_CAMERA_SKEW_NS = 500_000  # known camera->host offset, recorded by the C2 normalizer

_SCEN = ContactScenario(
    name="timing_meta_fixture",
    phases=(
        ContactPhase(kind="approach", start_s=0.0, duration_s=0.1),
        ContactPhase(kind="contact_start", start_s=0.1, duration_s=0.1),
        ContactPhase(kind="slip", start_s=0.2, duration_s=0.1),
        ContactPhase(kind="impact", start_s=0.3, duration_s=0.1),
        ContactPhase(kind="release", start_s=0.4, duration_s=0.1),
        ContactPhase(kind="settle", start_s=0.5, duration_s=0.1),
    ),
)


def _sim_episode() -> Episode:
    """A real SimRobot episode: 2 joints, 20 instants at 10 ms from t=1 ms (40 samples)."""
    ep = Episode(episode_id=_EP_ID, task_label="sync_audit")
    robot = SimRobot(dof=2, start_ns=1_000_000, period_ns=10_000_000, seed=7)
    for sample in robot.generate(20):
        ep.add(sample)
    return ep


def _build_run() -> tuple[Episode, TimingMeta]:
    """Episode + TimingMeta from a full sim -> normalize (C2) -> align (C3) pipeline."""
    ep = _sim_episode()

    # Proprio reference timeline: the episode's unique instants (host-monotonic).
    proprio_raw = sorted({s.timestamp_ns for s in ep.samples})
    proprio_records = Normalizer(ClockDomain.MONOTONIC).normalize(proprio_raw)
    proprio_timeline, proprio_flagged = timeline_from_records(proprio_records)
    assert not proprio_flagged  # sim stamps are clean by construction

    # Visual: sim-frames on a camera-local SOURCE clock (raw = host - 500 us), plus ONE
    # injected backwards camera stamp -> honestly flagged by C2, excluded from alignment.
    # Bind the concrete source before `with` (the ABC's __enter__ widens to SensorSource,
    # whose stream() yields object — the B6 fixture pattern).
    frames_src = SimFramesSource(
        scenario=_SCEN, start_ns=_CAMERA_SKEW_NS, period_ns=40_000_000
    )
    with frames_src:
        frame_raw = [s.timestamp_ns for s in frames_src.stream()]
    assert len(frame_raw) == 15  # 0.6 s scenario at 40 ms
    frame_raw.append(frame_raw[0])  # camera clock jumps back
    visual_records = Normalizer(
        ClockDomain.SOURCE, offset_ns=_CAMERA_SKEW_NS
    ).normalize(frame_raw)
    visual_timeline, visual_flagged = timeline_from_records(visual_records)
    assert len(visual_flagged) == 1

    # Tactile: sim-tactile at 50 ms from t=2 ms; only stamps carrying a contact token.
    tactile_src = SimTactileSource(
        scenario=_SCEN, start_ns=2_000_000, period_ns=50_000_000
    )
    with tactile_src:
        tactile_samples = list(tactile_src.stream())
    tactile_raw = [s.timestamp_ns for s in tactile_samples if s.tactile_event is not None]
    assert len(tactile_raw) == 8  # contact phases span [0.1 s, 0.5 s) at 50 ms
    tactile_records = Normalizer(ClockDomain.MONOTONIC).normalize(tactile_raw)
    tactile_timeline, tactile_flagged = timeline_from_records(tactile_records)
    assert not tactile_flagged

    results = {
        "visual": align(
            proprio_timeline, visual_timeline, _BUDGET, method=AlignmentMethod.NEAREST
        ),
        "tactile": align(
            proprio_timeline, tactile_timeline, _BUDGET, method=AlignmentMethod.WINDOW
        ),
    }
    records = {
        "proprio": list(proprio_records),
        "visual": list(visual_records),
        "tactile": list(tactile_records),
    }
    meta = TimingMeta.from_run(records, results, _BUDGET, reference="proprio")
    return ep, meta


def _expected_meta_dict() -> dict[str, Any]:
    """The HAND-COUNTED expected serialization of the fixture run (fresh copy per call).

    Derivation (all on paper, no code): proprio ticks t_i = 1 ms + i*10 ms (i=0..19);
    frames at 1 ms + j*40 ms (15 clean + 1 flagged backwards); NEAREST vs the frame grid
    gives per-4-tick offsets (0, -10, -20 tie, +10) ms -> 5 EXACT / 15 NEAREST, all
    matched, min -20 ms, max +10 ms, mean -5 ms. Tactile events at 102+50k ms (k=0..7);
    WINDOW(+-25 ms) leaves ticks 0..7 empty (8 no_target) and matches exactly one event
    for ticks 8..19 (12 matched) with offsets [21, 11, 1, -9, -19]*2 + [21, 11] ms ->
    min -19 ms, max +21 ms, mean +3.5 ms.
    """
    return {
        "timing_meta_version": TIMING_META_VERSION,
        "budget": {"max_skew_ns": 20_000_000, "window_ns": 25_000_000},
        # One flagged camera stamp + 8 tactile no_target results = defects, but every
        # modality stays usable (clean timelines, matches present) -> DEGRADED, not
        # quarantined (the three-state rule on SyncVerdict).
        "verdict": "degraded",
        "modalities": {
            "proprio": {
                "clock_domain": "monotonic",
                "clean_count": 20,
                "flagged_count": 0,
                "flag_counts": {},
                "method_counts": {},
                "quality_counts": {},
                "offset_min_ns": None,
                "offset_max_ns": None,
                "offset_mean_ns": None,
            },
            "tactile": {
                "clock_domain": "monotonic",
                "clean_count": 8,
                "flagged_count": 0,
                "flag_counts": {},
                "method_counts": {"window": 20},
                "quality_counts": {"matched": 12, "no_target": 8},
                "offset_min_ns": -19_000_000,
                "offset_max_ns": 21_000_000,
                "offset_mean_ns": 3_500_000.0,
            },
            "visual": {
                "clock_domain": "source",
                "clean_count": 15,
                "flagged_count": 1,
                "flag_counts": {"backwards_in_source": 1},
                "method_counts": {"exact": 5, "nearest": 15},
                "quality_counts": {"matched": 20},
                "offset_min_ns": -20_000_000,
                "offset_max_ns": 10_000_000,
                "offset_mean_ns": -5_000_000.0,
            },
        },
    }


@pytest.fixture(scope="module")
def run() -> tuple[Episode, TimingMeta]:
    return _build_run()


def _backwards_episode() -> Episode:
    """An episode whose timeline goes backwards — refused by BOTH exporters' gates."""
    ep = Episode(episode_id="bad_ep", task_label="sync_audit")
    for ts in (30_000_000, 20_000_000, 10_000_000):
        ep.add(PVTSample(timestamp_ns=ts, episode_id="bad_ep", chain_index=0, joint_angle=0.1))
    return ep


# ---------------------------------------------------------------------------
# from_run: computed from real records/results — counts match hand counts exactly.
# ---------------------------------------------------------------------------


class TestFromRun:
    def test_matches_hand_counted_fixture(self, run: tuple[Episode, TimingMeta]) -> None:
        _, meta = run
        assert meta.to_dict() == _expected_meta_dict()

    def test_hand_counted_dict_rebuilds_the_same_meta(
        self, run: tuple[Episode, TimingMeta]
    ) -> None:
        _, meta = run
        assert TimingMeta.from_dict(_expected_meta_dict()) == meta

    def test_derived_indicators(self, run: tuple[Episode, TimingMeta]) -> None:
        _, meta = run
        assert meta.flagged_record_count == 1  # the injected backwards camera stamp
        assert meta.missing_target_count == 8  # proprio ticks before the first contact
        assert meta.out_of_budget_count == 0
        assert meta.matched_count == 32  # 20 visual + 12 tactile
        assert meta.verdict is SyncVerdict.DEGRADED  # defective but no modality unusable

    def test_three_flagged_records_in_means_flagged_three_out(self) -> None:
        # High-water rule: 5, 6, 7 all sit below the 20 mark -> exactly 3 flagged.
        records = Normalizer(ClockDomain.MONOTONIC).normalize([10, 20, 5, 6, 7])
        meta = TimingMeta.from_run(
            {"proprio": records}, {}, _BUDGET, reference="proprio"
        )
        (name, mod), = meta.modalities
        assert name == "proprio"
        assert mod.clean_count == 2
        assert mod.flagged_count == 3
        assert dict(mod.flag_counts) == {NormalizationFlag.BACKWARDS_IN_SOURCE: 3}
        # Flagged records with a surviving clean timeline: defective, not unusable.
        assert meta.verdict is SyncVerdict.DEGRADED

    def test_out_of_budget_result_in_means_quarantine_out(self) -> None:
        records = {
            "proprio": list(Normalizer(ClockDomain.MONOTONIC).normalize([1_000_000])),
            "visual": list(Normalizer(ClockDomain.MONOTONIC).normalize([5_000_000])),
        }
        tight = AlignmentBudget(max_skew_ns=1_000_000)
        results = {"visual": align([1_000_000], [5_000_000], tight)}
        meta = TimingMeta.from_run(records, results, tight, reference="proprio")
        assert meta.out_of_budget_count == 1
        assert meta.matched_count == 0
        # Alignment was attempted and NOTHING matched: the modality is unusable.
        assert meta.verdict is SyncVerdict.QUARANTINED

    def test_fully_matched_clean_run_is_aligned_within_budget(self) -> None:
        stamps = [1_000_000, 2_000_000]
        records = {
            "proprio": list(Normalizer(ClockDomain.MONOTONIC).normalize(stamps)),
            "visual": list(Normalizer(ClockDomain.MONOTONIC).normalize(stamps)),
        }
        results = {"visual": align(stamps, stamps, AlignmentBudget(max_skew_ns=0))}
        meta = TimingMeta.from_run(
            records, results, AlignmentBudget(max_skew_ns=0), reference="proprio"
        )
        assert meta.verdict is SyncVerdict.ALIGNED_WITHIN_BUDGET
        assert meta.matched_count == 2

    def test_results_without_records_rejected(self) -> None:
        results = {"visual": align([1_000_000], [1_000_000], _BUDGET)}
        with pytest.raises(ValueError, match="records_by_modality is empty"):
            TimingMeta.from_run({}, results, _BUDGET)
        records = {"proprio": list(Normalizer(ClockDomain.MONOTONIC).normalize([1_000_000]))}
        with pytest.raises(ValueError, match="modalities with no records"):
            TimingMeta.from_run(records, results, _BUDGET)

    def test_records_without_results_rejected_unless_reference(self) -> None:
        """A target modality whose C3 output is absent must not summarize as silently
        clean — only the EXPLICIT reference may go unaligned (CodeRabbit #57)."""
        stamps = [1_000_000, 2_000_000]
        records = {
            "proprio": list(Normalizer(ClockDomain.MONOTONIC).normalize(stamps)),
            "visual": list(Normalizer(ClockDomain.MONOTONIC).normalize(stamps)),
        }
        results = {"visual": align(stamps, stamps, _BUDGET)}
        # No reference: proprio has records but no results -> rejected.
        with pytest.raises(ValueError, match="no alignment results"):
            TimingMeta.from_run(records, results, _BUDGET)
        # Wrong reference name -> rejected before anything is summarized.
        with pytest.raises(ValueError, match="not a records_by_modality key"):
            TimingMeta.from_run(records, results, _BUDGET, reference="nope")
        # Correct reference -> the same run summarizes fine.
        meta = TimingMeta.from_run(records, results, _BUDGET, reference="proprio")
        assert meta.verdict is SyncVerdict.ALIGNED_WITHIN_BUDGET

    def test_totally_flagged_modality_is_quarantined(self) -> None:
        """clean_count == 0 means no usable timeline at all — QUARANTINED, never
        degraded (the three-state rule's unusable branch)."""
        records = Normalizer(ClockDomain.SOURCE).normalize([10, 20])  # unknown skew
        meta = TimingMeta.from_run(
            {"visual": list(records)}, {}, _BUDGET, reference="visual"
        )
        assert meta.verdict is SyncVerdict.QUARANTINED

    def test_empty_modality_rejected(self) -> None:
        with pytest.raises(ValueError, match="has no records"):
            TimingMeta.from_run({"proprio": []}, {}, _BUDGET)

    def test_empty_modality_name_rejected(self) -> None:
        records = list(Normalizer(ClockDomain.MONOTONIC).normalize([1_000_000]))
        with pytest.raises(ValueError, match="non-empty str"):
            TimingMeta.from_run({"": records}, {}, _BUDGET)

    def test_mixed_clock_domains_rejected(self) -> None:
        mono = list(Normalizer(ClockDomain.MONOTONIC).normalize([10, 20]))
        src = list(Normalizer(ClockDomain.SOURCE, offset_ns=5).normalize([30]))
        with pytest.raises(ValueError, match="mixes clock domains"):
            TimingMeta.from_run({"m": mono + src}, {}, _BUDGET)

    def test_bare_values_rejected(self) -> None:
        records = list(Normalizer(ClockDomain.MONOTONIC).normalize([1_000_000]))
        junk_records = cast(Mapping[str, Sequence[TimingRecord]], {"m": [10]})
        with pytest.raises(ValueError, match="must be a TimingRecord"):
            TimingMeta.from_run(junk_records, {}, _BUDGET)
        junk_results = cast(Mapping[str, Sequence[AlignmentResult]], {"m": [10]})
        with pytest.raises(ValueError, match="must be an AlignmentResult"):
            TimingMeta.from_run({"m": records}, junk_results, _BUDGET)

    def test_foreign_budget_rejected(self) -> None:
        records = {"m": list(Normalizer(ClockDomain.MONOTONIC).normalize([1_000_000]))}
        with pytest.raises(ValueError, match="must be an AlignmentBudget"):
            TimingMeta.from_run(records, {}, cast(AlignmentBudget, 5))

    def test_determinism_same_run_identical_dict(self) -> None:
        _, first = _build_run()
        _, second = _build_run()
        assert first == second
        assert first.to_dict() == second.to_dict()
        assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
            second.to_dict(), sort_keys=True
        )


# ---------------------------------------------------------------------------
# Construction: a contradictory summary cannot exist as a value.
# ---------------------------------------------------------------------------


def _matched_mod(
    *,
    method: AlignmentMethod = AlignmentMethod.NEAREST,
    offset_min_ns: int | None = 1_000,
    offset_max_ns: int | None = 1_000,
    offset_mean_ns: float | None = 1_000.0,
) -> ModalityTiming:
    return ModalityTiming(
        clock_domain=ClockDomain.MONOTONIC,
        clean_count=1,
        flagged_count=0,
        method_counts=((method, 1),),
        quality_counts=((AlignmentQuality.MATCHED, 1),),
        offset_min_ns=offset_min_ns,
        offset_max_ns=offset_max_ns,
        offset_mean_ns=offset_mean_ns,
    )


class TestNoFabrication:
    def test_offsets_without_matches_rejected(self) -> None:
        with pytest.raises(ValueError, match="zero matched results"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=2,
                flagged_count=0,
                offset_min_ns=0,
                offset_max_ns=0,
                offset_mean_ns=0.0,
            )

    def test_matches_without_offsets_rejected(self) -> None:
        with pytest.raises(ValueError, match="offset stats are incomplete"):
            _matched_mod(offset_min_ns=None, offset_max_ns=None, offset_mean_ns=None)
        with pytest.raises(ValueError, match="offset stats are incomplete"):
            _matched_mod(offset_mean_ns=None)

    def test_flagged_without_reason_tokens_rejected(self) -> None:
        with pytest.raises(ValueError, match="flagged_count=2"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC, clean_count=0, flagged_count=2
            )

    def test_flag_tokens_without_flagged_rejected(self) -> None:
        with pytest.raises(ValueError, match="flagged_count=0"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                flag_counts=((NormalizationFlag.UNKNOWN_SKEW, 1),),
            )

    def test_flag_histogram_counting_ghost_records_rejected(self) -> None:
        # One token appearing on more records than were flagged is impossible (C2 bans
        # duplicate flags per record) — so a bigger per-token count is fabrication.
        with pytest.raises(ValueError, match="counts records that never existed"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=0,
                flagged_count=1,
                flag_counts=((NormalizationFlag.BACKWARDS_IN_SOURCE, 2),),
            )

    def test_flag_histogram_hiding_flags_rejected(self) -> None:
        with pytest.raises(ValueError, match="hides flags"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=0,
                flagged_count=2,
                flag_counts=((NormalizationFlag.BACKWARDS_IN_SOURCE, 1),),
            )

    def test_method_quality_total_mismatch_rejected(self) -> None:
        # The spirit of "matched_count > total": more verdicts than methods (or vice
        # versa) summarizes results that never existed.
        with pytest.raises(ValueError, match="method_counts total"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                method_counts=((AlignmentMethod.NEAREST, 1),),
                quality_counts=((AlignmentQuality.MATCHED, 2),),
            )

    def test_window_mixed_with_other_methods_rejected(self) -> None:
        with pytest.raises(ValueError, match="mixes WINDOW"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                method_counts=((AlignmentMethod.NEAREST, 1), (AlignmentMethod.WINDOW, 1)),
                quality_counts=((AlignmentQuality.MATCHED, 2),),
                offset_min_ns=0,
                offset_max_ns=1,
                offset_mean_ns=0.5,
            )

    def test_window_out_of_budget_rejected(self) -> None:
        with pytest.raises(ValueError, match="no_target by C3's contract"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                method_counts=((AlignmentMethod.WINDOW, 2),),
                quality_counts=(
                    (AlignmentQuality.MATCHED, 1),
                    (AlignmentQuality.OUT_OF_BUDGET, 1),
                ),
                offset_min_ns=0,
                offset_max_ns=0,
                offset_mean_ns=0.0,
            )

    def test_all_exact_with_nonzero_offsets_rejected(self) -> None:
        with pytest.raises(ValueError, match="all-EXACT"):
            _matched_mod(method=AlignmentMethod.EXACT)

    def test_inverted_offset_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="inverted range"):
            _matched_mod(offset_min_ns=10, offset_max_ns=5, offset_mean_ns=7.0)

    def test_mean_outside_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="arithmetic fiction"):
            _matched_mod(offset_min_ns=0, offset_max_ns=10, offset_mean_ns=20.0)

    def test_non_float_mean_rejected(self) -> None:
        with pytest.raises(ValueError, match="offset_mean_ns must be a float"):
            _matched_mod(offset_mean_ns=cast(float, 1_000))

    def test_zero_count_histogram_entry_rejected(self) -> None:
        with pytest.raises(ValueError, match="count 0"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=1,
                flag_counts=((NormalizationFlag.UNKNOWN_SKEW, 0),),
            )

    def test_unsorted_histogram_rejected(self) -> None:
        with pytest.raises(ValueError, match="strictly sorted"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                method_counts=((AlignmentMethod.NEAREST, 1), (AlignmentMethod.EXACT, 1)),
                quality_counts=((AlignmentQuality.MATCHED, 2),),
                offset_min_ns=0,
                offset_max_ns=1,
                offset_mean_ns=0.5,
            )

    def test_histogram_shape_junk_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a tuple"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                flag_counts=cast(tuple[tuple[NormalizationFlag, int], ...], []),
            )
        with pytest.raises(ValueError, match=r"\(token, count\) pair"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                flag_counts=cast(tuple[tuple[NormalizationFlag, int], ...], (1,)),
            )
        with pytest.raises(ValueError, match="foreign token"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=1,
                flagged_count=0,
                flag_counts=cast(tuple[tuple[NormalizationFlag, int], ...], (("junk", 1),)
                ),
            )

    def test_count_junk_rejected(self) -> None:
        with pytest.raises(ValueError, match="got bool"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=cast(int, True),
                flagged_count=0,
            )
        with pytest.raises(ValueError, match="must be an int count"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC,
                clean_count=cast(int, 1.5),
                flagged_count=0,
            )
        with pytest.raises(ValueError, match=">= 0"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC, clean_count=-1, flagged_count=1
            )

    def test_offset_junk_rejected(self) -> None:
        with pytest.raises(ValueError, match="got bool"):
            _matched_mod(offset_min_ns=cast(int, True))
        with pytest.raises(ValueError, match="int nanosecond offset"):
            _matched_mod(offset_min_ns=cast(int, 1.5))
        with pytest.raises(ValueError, match="within"):
            _matched_mod(offset_max_ns=2**64)

    def test_empty_modality_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="no records cannot be summarized"):
            ModalityTiming(
                clock_domain=ClockDomain.MONOTONIC, clean_count=0, flagged_count=0
            )

    def test_foreign_domain_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a ClockDomain"):
            ModalityTiming(
                clock_domain=cast(ClockDomain, "monotonic"),
                clean_count=1,
                flagged_count=0,
            )

    def test_verdict_contradicting_counts_rejected(self) -> None:
        clean = _matched_mod(offset_min_ns=0, offset_max_ns=1, offset_mean_ns=0.5)
        with pytest.raises(ValueError, match="contradicts the counts"):
            TimingMeta(
                modalities=(("m", clean),),
                budget=_BUDGET,
                verdict=SyncVerdict.QUARANTINED,
            )
        flagged = ModalityTiming(
            clock_domain=ClockDomain.MONOTONIC,
            clean_count=0,
            flagged_count=1,
            flag_counts=((NormalizationFlag.UNKNOWN_SKEW, 1),),
        )
        with pytest.raises(ValueError, match="contradicts the counts"):
            TimingMeta(
                modalities=(("m", flagged),),
                budget=_BUDGET,
                verdict=SyncVerdict.ALIGNED_WITHIN_BUDGET,
            )

    def test_offsets_beyond_recorded_budget_rejected(self) -> None:
        # C3 never publishes an offset past the budget, so a wider range is forged.
        wide = _matched_mod(
            offset_min_ns=30_000_000, offset_max_ns=30_000_000, offset_mean_ns=30_000_000.0
        )
        with pytest.raises(ValueError, match="exceeds the recorded budget"):
            TimingMeta(
                modalities=(("m", wide),),
                budget=AlignmentBudget(max_skew_ns=20_000_000),
                verdict=SyncVerdict.ALIGNED_WITHIN_BUDGET,
            )

    def test_window_results_without_window_budget_rejected(self) -> None:
        windowed = _matched_mod(method=AlignmentMethod.WINDOW)
        with pytest.raises(ValueError, match=r"window_ns is"):
            TimingMeta(
                modalities=(("m", windowed),),
                budget=AlignmentBudget(max_skew_ns=20_000_000),
                verdict=SyncVerdict.ALIGNED_WITHIN_BUDGET,
            )

    def test_modalities_shape_junk_rejected(self) -> None:
        good = _matched_mod(offset_min_ns=0, offset_max_ns=1, offset_mean_ns=0.5)
        pairs = cast(tuple[tuple[str, ModalityTiming], ...], None)
        with pytest.raises(ValueError, match="must be a tuple"):
            TimingMeta(pairs, _BUDGET, SyncVerdict.ALIGNED_WITHIN_BUDGET)
        with pytest.raises(ValueError, match="audits"):
            TimingMeta((), _BUDGET, SyncVerdict.ALIGNED_WITHIN_BUDGET)
        bad_pair = cast(tuple[tuple[str, ModalityTiming], ...], (("m",),))
        with pytest.raises(ValueError, match=r"\(name, ModalityTiming\) pair"):
            TimingMeta(bad_pair, _BUDGET, SyncVerdict.ALIGNED_WITHIN_BUDGET)
        with pytest.raises(ValueError, match="non-empty str"):
            TimingMeta((("", good),), _BUDGET, SyncVerdict.ALIGNED_WITHIN_BUDGET)
        bad_value = cast(tuple[tuple[str, ModalityTiming], ...], (("m", 5),))
        with pytest.raises(ValueError, match="must be a ModalityTiming"):
            TimingMeta(bad_value, _BUDGET, SyncVerdict.ALIGNED_WITHIN_BUDGET)
        with pytest.raises(ValueError, match="strictly sorted"):
            TimingMeta(
                (("b", good), ("a", good)),
                _BUDGET,
                SyncVerdict.ALIGNED_WITHIN_BUDGET,
            )
        with pytest.raises(ValueError, match="must be an AlignmentBudget"):
            TimingMeta(
                (("m", good),),
                cast(AlignmentBudget, None),
                SyncVerdict.ALIGNED_WITHIN_BUDGET,
            )
        with pytest.raises(ValueError, match="must be a SyncVerdict"):
            TimingMeta((("m", good),), _BUDGET, cast(SyncVerdict, "quarantined"))


# ---------------------------------------------------------------------------
# from_dict: unknown keys / tokens / versions refused loud, tampering cannot load.
# ---------------------------------------------------------------------------


def _tamper(mutate: str) -> dict[str, Any]:
    """A fresh expected dict with one named mutation applied."""
    d = _expected_meta_dict()
    if mutate == "missing_top_key":
        del d["verdict"]
    elif mutate == "unknown_top_key":
        d["extra"] = 1
    elif mutate == "future_version":
        d["timing_meta_version"] = TIMING_META_VERSION + 1
    elif mutate == "bool_version":
        d["timing_meta_version"] = True
    elif mutate == "unknown_verdict_token":
        d["verdict"] = "totally_fine"
    elif mutate == "unknown_budget_key":
        d["budget"]["extra"] = 1
    elif mutate == "float_skew":
        d["budget"]["max_skew_ns"] = 1.5
    elif mutate == "junk_window":
        d["budget"]["window_ns"] = "wide"
    elif mutate == "budget_not_mapping":
        d["budget"] = [1, 2]
    elif mutate == "modalities_not_mapping":
        d["modalities"] = []
    elif mutate == "empty_modality_name":
        d["modalities"][""] = d["modalities"].pop("visual")
    elif mutate == "modality_not_mapping":
        d["modalities"]["visual"] = 5
    elif mutate == "missing_modality_key":
        del d["modalities"]["visual"]["clean_count"]
    elif mutate == "unknown_modality_key":
        d["modalities"]["visual"]["extra"] = 1
    elif mutate == "unknown_domain_token":
        d["modalities"]["visual"]["clock_domain"] = "gps"
    elif mutate == "unknown_flag_token":
        d["modalities"]["visual"]["flag_counts"] = {"clamped": 1}
    elif mutate == "unknown_method_token":
        d["modalities"]["visual"]["method_counts"] = {"vibes": 20}
    elif mutate == "unknown_quality_token":
        d["modalities"]["visual"]["quality_counts"] = {"fine": 20}
    elif mutate == "non_str_token":
        d["modalities"]["visual"]["flag_counts"] = {1: 1}
    elif mutate == "histogram_not_mapping":
        d["modalities"]["visual"]["method_counts"] = ["exact"]
    elif mutate == "negative_count":
        d["modalities"]["visual"]["clean_count"] = -1
    elif mutate == "int_mean":
        d["modalities"]["visual"]["offset_mean_ns"] = -5_000_000
    elif mutate == "float_offset":
        d["modalities"]["visual"]["offset_min_ns"] = -5.5
    elif mutate == "flattering_verdict":
        d["verdict"] = "aligned_within_budget"  # counts say quarantined
    elif mutate == "offset_beyond_budget":
        d["modalities"]["visual"]["offset_max_ns"] = 21_000_000  # budget is 20 ms
    else:  # pragma: no cover - fixture bug guard
        raise AssertionError(mutate)
    return d


_TAMPER_CASES = [
    "missing_top_key",
    "unknown_top_key",
    "future_version",
    "bool_version",
    "unknown_verdict_token",
    "unknown_budget_key",
    "float_skew",
    "junk_window",
    "budget_not_mapping",
    "modalities_not_mapping",
    "empty_modality_name",
    "modality_not_mapping",
    "missing_modality_key",
    "unknown_modality_key",
    "unknown_domain_token",
    "unknown_flag_token",
    "unknown_method_token",
    "unknown_quality_token",
    "non_str_token",
    "histogram_not_mapping",
    "negative_count",
    "int_mean",
    "float_offset",
    "flattering_verdict",
    "offset_beyond_budget",
]


class TestFromDict:
    @pytest.mark.parametrize("case", _TAMPER_CASES)
    def test_tampered_dict_refused(self, case: str) -> None:
        with pytest.raises(ValueError):
            TimingMeta.from_dict(_tamper(case))

    def test_round_trips_exactly(self, run: tuple[Episode, TimingMeta]) -> None:
        _, meta = run
        assert TimingMeta.from_dict(meta.to_dict()) == meta


# ---------------------------------------------------------------------------
# Exporter wiring: both formats carry the sidecar; legacy datasets stay loadable.
# ---------------------------------------------------------------------------


class TestExporterRoundTrip:
    def test_lerobot_round_trip(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        ep, meta = run
        exporter = LeRobotExporter(timing_meta={_EP_ID: meta})
        root = exporter.export([ep], tmp_path / "ds")
        assert (Path(root) / "meta" / "timing.json").is_file()
        loaded = load_lerobot_timing_meta(root)
        assert loaded is not None
        assert set(loaded) == {_EP_ID}
        assert loaded[_EP_ID] == meta
        assert loaded[_EP_ID].to_dict() == _expected_meta_dict()  # no silent loss
        # The dataset itself still round-trips untouched.
        episodes = exporter.load(root)
        assert len(episodes) == 1
        assert len(episodes[0].samples) == len(ep.samples)
        assert {s.timestamp_ns for s in episodes[0].samples} == {
            s.timestamp_ns for s in ep.samples
        }

    def test_parquet_round_trip(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        ep, meta = run
        exporter = make_exporter("parquet", timing_meta={_EP_ID: meta})
        root = exporter.export([ep], tmp_path / "ds")
        assert (Path(root) / "timing.json").is_file()
        loaded = load_parquet_timing_meta(root)
        assert loaded is not None
        assert set(loaded) == {_EP_ID}
        assert loaded[_EP_ID] == meta
        assert loaded[_EP_ID].to_dict() == _expected_meta_dict()  # no silent loss
        episodes = exporter.load(root)
        assert len(episodes) == 1
        assert len(episodes[0].samples) == len(ep.samples)

    def test_legacy_datasets_load_unchanged(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        ep, _ = run
        for name, loader in (
            ("lerobot", load_lerobot_timing_meta),
            ("parquet", load_parquet_timing_meta),
        ):
            exporter = make_exporter(name)  # no timing meta: the pre-C5 layout
            root = exporter.export([ep], tmp_path / f"legacy_{name}")
            assert loader(root) is None
            episodes = exporter.load(root)
            assert len(episodes) == 1
            assert len(episodes[0].samples) == len(ep.samples)

    def test_deleted_sidecar_reads_as_legacy(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        ep, meta = run
        exporter = ParquetExporter(timing_meta={_EP_ID: meta})
        root = exporter.export([ep], tmp_path / "ds")
        (Path(root) / "timing.json").unlink()
        assert load_parquet_timing_meta(root) is None
        assert len(exporter.load(root)) == 1

    def test_unknown_episode_id_raises(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        ep, meta = run
        with pytest.raises(ValueError, match="unknown episode id"):
            LeRobotExporter(timing_meta={"nope": meta}).export([ep], tmp_path / "lr")
        with pytest.raises(ValueError, match="unknown episode id"):
            ParquetExporter(timing_meta={"nope": meta}).export([ep], tmp_path / "pq")

    def test_unknown_episode_id_fails_before_any_write(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        """The fail-fast contract: a bad timing_meta id must leave NOTHING on disk —
        not a partial dataset, not an empty directory (CodeRabbit #57)."""
        ep, meta = run
        for cls_, sub in ((LeRobotExporter, "lr"), (ParquetExporter, "pq")):
            out = tmp_path / sub
            with pytest.raises(ValueError, match="unknown episode id"):
                cls_(timing_meta={"nope": meta}).export([ep], out)
            assert not out.exists(), f"{cls_.__name__} left files behind on a bad id"

    def test_refused_episode_meta_omitted_with_warning(
        self,
        run: tuple[Episode, TimingMeta],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ep, meta = run
        bad = _backwards_episode()
        metas = {_EP_ID: meta, "bad_ep": meta}
        for name, loader, out in (
            ("lerobot", load_lerobot_timing_meta, tmp_path / "lr"),
            ("parquet", load_parquet_timing_meta, tmp_path / "pq"),
        ):
            with caplog.at_level(logging.WARNING, logger="inhabit.export"):
                root = make_exporter(name, timing_meta=metas).export([ep, bad], out)
            loaded = loader(root)
            assert loaded is not None
            assert set(loaded) == {_EP_ID}  # only the episode actually in the dataset
            assert "timing meta for episode=bad_ep NOT written" in caplog.text

    def test_empty_timing_meta_writes_empty_sidecar(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        # {} is not None: "timing was considered, nothing recorded" is an honest,
        # distinguishable state (loader returns {}, not legacy None).
        ep, _ = run
        root = ParquetExporter(timing_meta={}).export([ep], tmp_path / "ds")
        assert load_parquet_timing_meta(root) == {}


# ---------------------------------------------------------------------------
# Sidecar helpers: deterministic writes; corrupt files are corruption, not legacy.
# ---------------------------------------------------------------------------


class TestSidecar:
    def test_missing_file_is_none(self, tmp_path: Path) -> None:
        assert read_timing_sidecar(tmp_path / "absent.json") is None

    def test_write_is_deterministic_and_creates_parents(
        self, run: tuple[Episode, TimingMeta], tmp_path: Path
    ) -> None:
        _, meta = run
        a = write_timing_sidecar(tmp_path / "a" / "deep" / "timing.json", {_EP_ID: meta})
        b = write_timing_sidecar(tmp_path / "b" / "timing.json", {_EP_ID: meta})
        assert a.read_bytes() == b.read_bytes()
        loaded = read_timing_sidecar(a)
        assert loaded is not None and loaded[_EP_ID] == meta

    def test_write_rejects_junk(self, run: tuple[Episode, TimingMeta], tmp_path: Path) -> None:
        _, meta = run
        with pytest.raises(ValueError, match="must be a mapping"):
            write_timing_sidecar(
                tmp_path / "t.json", cast(Mapping[str, TimingMeta], [meta])
            )
        with pytest.raises(ValueError, match="non-empty str"):
            write_timing_sidecar(tmp_path / "t.json", {"": meta})
        with pytest.raises(ValueError, match="must be a TimingMeta"):
            write_timing_sidecar(
                tmp_path / "t.json", cast(Mapping[str, TimingMeta], {"e": 5})
            )

    @pytest.mark.parametrize(
        ("payload", "match"),
        [
            ("{not json", "not valid JSON"),
            ("[]", "JSON object"),
            ('{"episodes": {}}', "missing"),
            (
                '{"timing_meta_version": 1, "episodes": {}, "extra": 1}',
                "unknown",
            ),
            ('{"timing_meta_version": 2, "episodes": {}}', "unsupported"),
            ('{"timing_meta_version": true, "episodes": {}}', "unsupported"),
            # 1.0 == 1 in Python: a float version must still be refused (CodeRabbit #57).
            ('{"timing_meta_version": 1.0, "episodes": {}}', "unsupported"),
            ('{"timing_meta_version": 1, "episodes": []}', "must be an object"),
            ('{"timing_meta_version": 1, "episodes": {"": {}}}', "empty episode id"),
            ('{"timing_meta_version": 1, "episodes": {"e": 5}}', "must be an object"),
        ],
    )
    def test_corrupt_sidecar_raises_never_legacy(
        self, tmp_path: Path, payload: str, match: str
    ) -> None:
        sidecar = tmp_path / "timing.json"
        sidecar.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            read_timing_sidecar(sidecar)

    def test_select_episode_timing(self, run: tuple[Episode, TimingMeta]) -> None:
        _, meta = run
        kept, omitted = select_episode_timing(
            {"a": meta, "b": meta},
            written_ids={"a"},
            known_ids={"a", "b"},
        )
        assert kept == {"a": meta}
        assert omitted == ["b"]
        with pytest.raises(ValueError, match="unknown episode id"):
            select_episode_timing(
                {"ghost": meta}, written_ids=set(), known_ids={"a"}
            )
