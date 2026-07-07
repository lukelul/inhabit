"""P-C timing benchmark phase-gate — measured bounds, provable failure (C7).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **A phase that closes on claims instead of measurements.** "Timing is solid" is not
  evidence. This bench RUNS the merged P-C stack — sim episode (B7) -> seeded disturbance
  (C4 ``sim.chaos``) -> normalization (C2, flagged-never-repaired) -> alignment (C3,
  quality-annotated) -> exported timing metadata (C5) — and emits a :class:`BenchReport`
  of MEASURED numbers: monotonicity violations, published-offset error percentiles,
  dropped-frame counts, contact-event association accuracy, exporter round-trip
  stability, and replay determinism. The committed ``docs/bench`` artifact is the
  phase-close evidence, regenerable byte-for-byte.
* **A gate that cannot fail.** A benchmark whose thresholds every outcome satisfies is
  decoration. :func:`gate` checks explicit per-case :class:`CaseThresholds`; the
  canonical suite CONTAINS injected violations (``burst_stall_200ms`` MUST come out
  ``QUARANTINED``, ``skewed_source_clock`` MUST come out all-out-of-budget), so
  thresholds demanding a clean suite (``--demand-clean``) provably FAIL, and the CLI
  exit code follows the gate. Both directions are pinned by tests.
* **A report that can lie about itself.** Every :class:`BenchReport` embeds the
  :class:`~timing.export_meta.TimingMeta` it was measured from, and construction
  RE-DERIVES the headline counts (violations, flagged/records, non-matched/results,
  per-stream delivered/surviving, max published offset, the verdict) from that metadata
  — a report whose numbers contradict its own provenance cannot exist as a value, and
  :meth:`BenchReport.from_dict` rebuilds through construction so a forged artifact
  cannot load either.
* **Non-reproducible measurements.** No wall clock is read anywhere: episodes, faults
  and clocks are all seeded/deterministic (P-B/P-C invariant), so the same
  ``(case, seed)`` yields a byte-identical report on any machine. :func:`run_bench`
  runs every measurement TWICE and records ``replay_deterministic`` — a bool the gate
  enforces — instead of asserting determinism on faith.

The bench composition (documented once, tested everywhere)
-----------------------------------------------------------
One case = one scenario episode + one optional :class:`~sim.chaos.BenchFixture` + one
:class:`~timing.align.AlignmentBudget`:

* **clean baseline** (``fixture=None``): the real multi-modal scenario episode. The
  proprio stream (chain 0) is the alignment REFERENCE; the frames (chain 2) and tactile
  (chain 1) streams are NEAREST-aligned onto it. The episode's round-robin lattice puts
  frames/tactile at a structural 10/20 ms offset from proprio ticks, so the baseline's
  measured offsets are hand-checkable exactly (max 20 ms, p95 10 ms).
* **fixture cases**: the fixture's clean lattice is the reference and its seeded
  disturbed timeline is the modality under test, normalized as MONOTONIC (backwards
  flagged, never repaired) and NEAREST-aligned within the case budget — the exact
  composition the C4 fixtures were built for.
* **contact events** (every case): the scenario's tactile-event stamps (the labeled
  last-centimeter signal) are WINDOW-associated against the case's primary target
  stream; ``contact_event_accuracy`` is the fraction of events with at least one
  in-window match. The window is ONE nominal target period — the loosest window a
  gap-free stream always satisfies — so a miss is a real coverage hole (the burst
  stall), never lattice phase.
* **case verdict**: ``QUARANTINED`` when the episode-level jitter gate
  (:class:`~logger.jitter.JitterBudget` — the same gate the recorder and both exporters
  refuse episodes with) rejects the disturbed stream (backwards intervals / dropout
  holes), otherwise the :class:`~timing.export_meta.SyncVerdict` the C5 rule derives.
  Both verdicts are recorded; the composition is construction-enforced.
* **offset percentiles** are computed over EXACT/NEAREST published offsets only (the
  alignment-error instrument). WINDOW association offsets are event-to-carrier
  distances bounded by the window BY CONSTRUCTION and live in the embedded
  ``timing_meta`` histograms instead — mixing the two would let the window bound mask
  a real skew regression.

Scope (PONYTAIL): runner + gate + report + CLI only. NO new alignment/normalization
logic — C1..C5 are imported, never edited; frozen contracts (``PVTSample``, adapters,
codec) untouched. Stdlib only, no numpy (the P-C invariant).

CLI: ``cd host && python -m timing.bench --out <dir>`` runs the canonical suite (the
four C4 ``BENCH_FIXTURES`` + the clean baseline), exports+reloads through BOTH
exporters, writes ``P-C-TIMING-BENCH.json`` / ``.md``, and exits 0 iff the gate passed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from export.lerobot import export_lerobot, load_lerobot, load_lerobot_timing_meta
from export.parquet import ParquetExporter, load_parquet_timing_meta
from inhabit_can.pvt import Episode
from logger.jitter import JitterBudget, compute_jitter
from sim.chaos import BENCH_FIXTURES, BenchFixture, apply_faults
from sim.rng import SeededRng
from sim.scenario import EXAMPLE_SCENARIOS
from timing.align import (
    AlignmentBudget,
    AlignmentMethod,
    AlignmentQuality,
    align,
    timeline_from_records,
)
from timing.export_meta import ModalityTiming, SyncVerdict, TimingMeta
from timing.normalize import NormalizationFlag, Normalizer, TimingRecord
from timing.stamp import ClockDomain
from tools.dataset.scenario_episode import build_scenario_episode

__all__ = [
    "BENCH_VERSION",
    "DEFAULT_THRESHOLDS",
    "REPORT_BASENAME",
    "BenchCase",
    "BenchReport",
    "CaseThresholds",
    "canonical_cases",
    "demand_clean_thresholds",
    "gate",
    "main",
    "nearest_rank_percentile",
    "render_markdown",
    "run_bench",
    "run_suite",
]

#: Version of the bench report/artifact shape. Bump with a migration; a reader never
#: guesses at an unknown version (the C5 ``TIMING_META_VERSION`` philosophy).
BENCH_VERSION = 1

#: Basename of the CLI artifact pair (``.json`` + ``.md``) — the committed evidence files.
REPORT_BASENAME = "P-C-TIMING-BENCH"

# Chain layout of tools.dataset.scenario_episode.build_scenario_episode (B7): proprio
# owns joint 0, tactile chain 1, frames chain 2, phase-offset on one 10 ms lattice.
_PROPRIO_CHAIN = 0
_TACTILE_CHAIN = 1
_FRAMES_CHAIN = 2

#: The derived contact-event modality name (the labeled last-centimeter signal).
_EVENTS = "contact_events"

# Baseline budget: the scenario's round-robin lattice places the nearest frame/tactile
# stamp 10 ms from a proprio tick (20 ms for the very first tick, which has no earlier
# neighbor), so 20 ms is the tight structural NEAREST bound; the 30 ms window is one
# full stream period (see the module docstring's window rule).
_BASELINE_BUDGET = AlignmentBudget(max_skew_ns=20_000_000, window_ns=30_000_000)

# Fixture-case NEAREST bound: 2 ms — the same scale as the recorder's default
# JitterBudget p99 (2 ms), i.e. "disturbance a 100 Hz telemetry consumer tolerates".
_FIXTURE_MAX_SKEW_NS = 2_000_000

# Bench-case names are used as report keys AND workdir subdirectory names; a name with
# separators could escape the workdir, and a free-form name cannot be diffed reliably.
_NAME_RE = re.compile(r"[a-z0-9_]+")

_MISSES = (AlignmentQuality.OUT_OF_BUDGET, AlignmentQuality.NO_TARGET)


# ------------------------------------------------------------------------------------
# percentile — the ONE documented method the bench publishes
# ------------------------------------------------------------------------------------


def nearest_rank_percentile(sorted_values: Sequence[int], pct: float) -> int:
    """Nearest-rank percentile: the value at rank ``ceil(pct/100 * n)`` (1-based).

    Failure mode: an interpolating percentile invents a value that was never measured,
    and an undocumented method makes two reports incomparable. Nearest-rank always
    returns an OBSERVED value and is hand-computable: for ``n=20`` ascending values,
    p95 -> rank ``ceil(19.0)=19``, p99 -> rank ``ceil(19.8)=20`` (the tests pin this
    exact arithmetic). Input must be a non-empty ASCENDING sequence of int ns —
    anything else is rejected loud, never sorted or coerced silently.
    """
    if isinstance(pct, bool) or not isinstance(pct, int | float) or not math.isfinite(pct):
        raise ValueError(f"pct must be a finite real number, got {pct!r}")
    if not 0.0 < pct <= 100.0:
        raise ValueError(f"pct must be in (0, 100], got {pct} — other ranks are undefined")
    if not sorted_values:
        raise ValueError(
            "sorted_values is empty — a percentile over nothing is a fabricated number"
        )
    prev: int | None = None
    for i, value in enumerate(sorted_values):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"sorted_values[{i}] must be an int, got {type(value).__name__} {value!r}"
            )
        if prev is not None and value < prev:
            raise ValueError(
                f"sorted_values[{i}]={value} < sorted_values[{i - 1}]={prev} — input must "
                "be ascending; sorting here would hide a caller bug"
            )
        prev = value
    rank = math.ceil(pct / 100.0 * len(sorted_values))
    return sorted_values[rank - 1]


# ------------------------------------------------------------------------------------
# the case — one scenario episode + one optional fixture + one budget
# ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchCase:
    """One benchmark case (a value): scenario episode + optional fault fixture + budget.

    Failure mode: an under-specified case is a bench that measures nothing nameable.
    Every field is validated at construction; ``fixture=None`` is the clean baseline
    (the scenario episode's own modality streams, undisturbed). ``budget.window_ns``
    is REQUIRED — contact events are always WINDOW-associated, and C3 refuses window
    alignment without a window budget.
    """

    name: str
    scenario: str
    episode_seed: int
    fixture: BenchFixture | None
    budget: AlignmentBudget

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise ValueError(
                f"case name must match [a-z0-9_]+, got {self.name!r} — the name is a "
                "report key and a workdir subdirectory; free-form names could collide "
                "or escape the workdir"
            )
        if not isinstance(self.scenario, str) or not self.scenario:
            raise ValueError(f"scenario must be a non-empty str, got {self.scenario!r}")
        if isinstance(self.episode_seed, bool) or not isinstance(self.episode_seed, int):
            raise ValueError(f"episode_seed must be an int, got {self.episode_seed!r}")
        if self.fixture is not None and not isinstance(self.fixture, BenchFixture):
            raise ValueError(
                f"fixture must be a BenchFixture or None, got "
                f"{type(self.fixture).__name__} {self.fixture!r}"
            )
        if not isinstance(self.budget, AlignmentBudget):
            raise ValueError(
                f"budget must be an AlignmentBudget, got {type(self.budget).__name__} "
                f"{self.budget!r}"
            )
        if self.budget.window_ns is None:
            raise ValueError(
                "budget.window_ns is required — contact events are WINDOW-associated in "
                "every case, and C3 refuses window alignment without a window budget"
            )


def canonical_cases(
    scenario: str = "slip_recovery", episode_seed: int = 7
) -> tuple[BenchCase, ...]:
    """The canonical suite: the clean baseline + all four C4 ``BENCH_FIXTURES``.

    ``slip_recovery`` is the default carrier episode because it scripts ALL FOUR frozen
    tactile tokens — the richest last-centimeter event stream to measure association
    against. Fixture cases use one window = the fixture's nominal period (see the
    module docstring's window rule) and the 2 ms NEAREST bound.
    """
    cases = [
        BenchCase(
            name="clean_baseline",
            scenario=scenario,
            episode_seed=episode_seed,
            fixture=None,
            budget=_BASELINE_BUDGET,
        )
    ]
    cases.extend(
        BenchCase(
            name=fixture.name,
            scenario=scenario,
            episode_seed=episode_seed,
            fixture=fixture,
            budget=AlignmentBudget(
                max_skew_ns=_FIXTURE_MAX_SKEW_NS, window_ns=fixture.period_ns
            ),
        )
        for fixture in BENCH_FIXTURES.values()
    )
    return tuple(cases)


# ------------------------------------------------------------------------------------
# the report — a value that cannot contradict its own provenance
# ------------------------------------------------------------------------------------


def _require_count(value: object, name: str) -> int:
    """Non-negative int count; bool/float/negative rejected loud (never coerced)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int count, got {type(value).__name__} {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(
            f"{name} must be a bool, got {type(value).__name__} {value!r} — a truthy "
            "non-bool would silently pass the gate"
        )
    return value


def _backwards_flag_count(meta: TimingMeta) -> int:
    """Monotonicity violations = BACKWARDS_IN_SOURCE flags across all modalities."""
    return sum(
        count
        for _, mod in meta.modalities
        for flag, count in mod.flag_counts
        if flag is NormalizationFlag.BACKWARDS_IN_SOURCE
    )


def _is_window_modality(mod: ModalityTiming) -> bool:
    return any(method is AlignmentMethod.WINDOW for method, _ in mod.method_counts)


def _expected_max_abs_offset(meta: TimingMeta) -> int | None:
    """Max |published offset| over EXACT/NEAREST modalities, re-derived from the meta."""
    best: int | None = None
    for _, mod in meta.modalities:
        if _is_window_modality(mod):
            continue  # window offsets are association distances, not alignment error
        if mod.offset_min_ns is None or mod.offset_max_ns is None:
            continue
        candidate = max(abs(mod.offset_min_ns), abs(mod.offset_max_ns))
        best = candidate if best is None else max(best, candidate)
    return best


_STREAM_KEYS = frozenset({"input", "delivered", "surviving"})
_REPORT_KEYS = frozenset({
    "name",
    "scenario",
    "episode_seed",
    "fixture",
    "monotonicity_violations",
    "flagged_records",
    "total_records",
    "non_matched_results",
    "total_results",
    "max_abs_offset_ns",
    "mean_abs_offset_ns",
    "p95_abs_offset_ns",
    "p99_abs_offset_ns",
    "streams",
    "contact_events_total",
    "contact_events_matched",
    "contact_event_accuracy",
    "episode_gate_passed",
    "episode_gate_reasons",
    "timing_meta",
    "verdict",
    "replay_deterministic",
    "lerobot_roundtrip_ok",
    "parquet_roundtrip_ok",
    "exported_samples",
})


@dataclass(frozen=True, slots=True)
class BenchReport:
    """The measured outcome of one bench case — every headline number re-derivable.

    Failure mode: a hand-edited (or bug-forged) report claiming "0 violations" over a
    quarantined run is worse than no report. Construction re-derives the counts, the
    max published offset, per-stream delivered/surviving counts and the case verdict
    from the embedded :class:`~timing.export_meta.TimingMeta` + episode-gate outcome,
    so a self-contradictory report cannot exist as a value (and cannot load through
    :meth:`from_dict` either).

    Verdict composition (the documented rule): ``QUARANTINED`` when the episode-level
    jitter gate refused the disturbed stream (the recorder/exporter quarantine —
    episodes are atomic, never partially exported), else the C5
    :class:`~timing.export_meta.SyncVerdict` derived from the counts. Both layers stay
    visible: ``episode_gate_passed``/``episode_gate_reasons`` and
    ``timing_meta.verdict`` are recorded alongside the composed ``verdict``.

    ``streams`` records dropped-frame behavior per modality as
    ``(name, input, delivered, surviving)``: ``input`` = stamps before the fault,
    ``delivered`` = stamps after the fault (drop/duplicate change it), ``surviving`` =
    stamps that survived normalization onto the timeline (flagged records are counted,
    never used). Offset stats cover EXACT/NEAREST published offsets only (see module
    docstring); ``None`` means nothing was published — honesty, not zero.
    """

    name: str
    scenario: str
    episode_seed: int
    fixture: str | None
    monotonicity_violations: int
    flagged_records: int
    total_records: int
    non_matched_results: int
    total_results: int
    max_abs_offset_ns: int | None
    mean_abs_offset_ns: float | None
    p95_abs_offset_ns: int | None
    p99_abs_offset_ns: int | None
    streams: tuple[tuple[str, int, int, int], ...]
    contact_events_total: int
    contact_events_matched: int
    contact_event_accuracy: float | None
    episode_gate_passed: bool
    episode_gate_reasons: tuple[str, ...]
    timing_meta: TimingMeta
    verdict: SyncVerdict
    replay_deterministic: bool
    lerobot_roundtrip_ok: bool
    parquet_roundtrip_ok: bool
    exported_samples: int

    def __post_init__(self) -> None:
        # Fail loud at construction: a BenchReport that exists is internally honest.
        # (One long, exhaustive gate on purpose — every check names the fabrication
        # it prevents, and splitting it would scatter the honesty contract.)
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"report name must match [a-z0-9_]+, got {self.name!r}")
        if not isinstance(self.scenario, str) or not self.scenario:
            raise ValueError(f"scenario must be a non-empty str, got {self.scenario!r}")
        if isinstance(self.episode_seed, bool) or not isinstance(self.episode_seed, int):
            raise ValueError(f"episode_seed must be an int, got {self.episode_seed!r}")
        if self.fixture is not None and (
            not isinstance(self.fixture, str) or not self.fixture
        ):
            raise ValueError(f"fixture must be a non-empty str or None, got {self.fixture!r}")
        if not isinstance(self.timing_meta, TimingMeta):
            raise ValueError(
                f"timing_meta must be a TimingMeta, got {type(self.timing_meta).__name__}"
                " — a report without its provenance cannot be audited"
            )
        if not isinstance(self.verdict, SyncVerdict):
            raise ValueError(
                f"verdict must be a SyncVerdict, got {type(self.verdict).__name__} "
                f"{self.verdict!r}"
            )
        _require_bool(self.episode_gate_passed, "episode_gate_passed")
        _require_bool(self.replay_deterministic, "replay_deterministic")
        _require_bool(self.lerobot_roundtrip_ok, "lerobot_roundtrip_ok")
        _require_bool(self.parquet_roundtrip_ok, "parquet_roundtrip_ok")
        _require_count(self.exported_samples, "exported_samples")
        if not isinstance(self.episode_gate_reasons, tuple) or not all(
            isinstance(r, str) and r for r in self.episode_gate_reasons
        ):
            raise ValueError(
                f"episode_gate_reasons must be a tuple of non-empty str, got "
                f"{self.episode_gate_reasons!r}"
            )
        if self.episode_gate_passed != (not self.episode_gate_reasons):
            raise ValueError(
                f"episode_gate_passed={self.episode_gate_passed} with reasons "
                f"{self.episode_gate_reasons!r} — a refusal carries its reasons and a "
                "pass carries none; anything else hides a quarantine"
            )

        meta = self.timing_meta
        # -- counts re-derived from the embedded metadata (a lying report cannot exist) --
        checks: tuple[tuple[str, int, int], ...] = (
            (
                "monotonicity_violations",
                _require_count(self.monotonicity_violations, "monotonicity_violations"),
                _backwards_flag_count(meta),
            ),
            (
                "flagged_records",
                _require_count(self.flagged_records, "flagged_records"),
                meta.flagged_record_count,
            ),
            (
                "total_records",
                _require_count(self.total_records, "total_records"),
                sum(mod.clean_count + mod.flagged_count for _, mod in meta.modalities),
            ),
            (
                "non_matched_results",
                _require_count(self.non_matched_results, "non_matched_results"),
                meta.out_of_budget_count + meta.missing_target_count,
            ),
            (
                "total_results",
                _require_count(self.total_results, "total_results"),
                sum(mod.result_count() for _, mod in meta.modalities),
            ),
        )
        for field_name, claimed, derived in checks:
            if claimed != derived:
                raise ValueError(
                    f"{field_name}={claimed} contradicts the embedded timing_meta "
                    f"(derived {derived}) — headline numbers are computed, never asserted"
                )

        # -- streams: names must be exactly the meta modalities; delivered/surviving
        #    must equal what normalization recorded (input is the pre-fault count).
        if not isinstance(self.streams, tuple):
            raise ValueError(f"streams must be a tuple, got {type(self.streams).__name__}")
        modalities = dict(meta.modalities)
        seen: set[str] = set()
        prev_name: str | None = None
        for i, entry in enumerate(self.streams):
            if not isinstance(entry, tuple) or len(entry) != 4:
                raise ValueError(
                    f"streams[{i}] must be (name, input, delivered, surviving), got {entry!r}"
                )
            s_name, s_input, s_delivered, s_surviving = entry
            if not isinstance(s_name, str) or s_name not in modalities:
                raise ValueError(
                    f"streams[{i}] name {s_name!r} is not a timing_meta modality "
                    f"({sorted(modalities)}) — a stream without provenance is fabricated"
                )
            if prev_name is not None and s_name <= prev_name:
                raise ValueError(
                    f"streams must be strictly sorted by name, got {s_name!r} after "
                    f"{prev_name!r} — order-dependent reports cannot be diffed"
                )
            prev_name = s_name
            seen.add(s_name)
            _require_count(s_input, f"streams[{i}] input")
            mod = modalities[s_name]
            if s_delivered != mod.clean_count + mod.flagged_count:
                raise ValueError(
                    f"streams[{i}] delivered={s_delivered!r} contradicts timing_meta "
                    f"({mod.clean_count + mod.flagged_count} records for {s_name!r})"
                )
            if s_surviving != mod.clean_count:
                raise ValueError(
                    f"streams[{i}] surviving={s_surviving!r} contradicts timing_meta "
                    f"({mod.clean_count} clean records for {s_name!r})"
                )
        if seen != set(modalities):
            raise ValueError(
                f"streams cover {sorted(seen)} but timing_meta summarizes "
                f"{sorted(modalities)} — every measured modality appears exactly once"
            )

        # -- contact events -------------------------------------------------------------
        total = _require_count(self.contact_events_total, "contact_events_total")
        matched = _require_count(self.contact_events_matched, "contact_events_matched")
        if matched > total:
            raise ValueError(
                f"contact_events_matched={matched} > contact_events_total={total} — "
                "more matches than events is arithmetic fiction"
            )
        events_stream = next((s for s in self.streams if s[0] == _EVENTS), None)
        if events_stream is None:
            raise ValueError(
                f"streams must include {_EVENTS!r} — contact association is a required "
                "bench measurement, not an optional extra"
            )
        if events_stream[1] != total:
            raise ValueError(
                f"contact_events_total={total} != {_EVENTS!r} stream input "
                f"{events_stream[1]} — the accuracy denominator is the event count"
            )
        expected_accuracy = (matched / total) if total else None
        if self.contact_event_accuracy != expected_accuracy:
            raise ValueError(
                f"contact_event_accuracy={self.contact_event_accuracy!r} != "
                f"matched/total = {expected_accuracy!r} — accuracy is computed, never "
                "asserted"
            )

        # -- offset stats: present iff an EXACT/NEAREST offset was published ------------
        expected_max = _expected_max_abs_offset(meta)
        if self.max_abs_offset_ns != expected_max:
            raise ValueError(
                f"max_abs_offset_ns={self.max_abs_offset_ns!r} contradicts the embedded "
                f"timing_meta (derived {expected_max!r})"
            )
        stats = (
            self.max_abs_offset_ns,
            self.mean_abs_offset_ns,
            self.p95_abs_offset_ns,
            self.p99_abs_offset_ns,
        )
        if expected_max is None:
            if any(v is not None for v in stats):
                raise ValueError(
                    f"offset stats {stats!r} with no published EXACT/NEAREST offsets — "
                    "statistics over nothing are fabricated"
                )
        else:
            if any(v is None for v in stats):
                raise ValueError(
                    f"offset stats are incomplete {stats!r} — published offsets always "
                    "yield max/mean/p95/p99 together"
                )
            p95 = _require_count(self.p95_abs_offset_ns, "p95_abs_offset_ns")
            p99 = _require_count(self.p99_abs_offset_ns, "p99_abs_offset_ns")
            mean = self.mean_abs_offset_ns
            if isinstance(mean, bool) or not isinstance(mean, float) or not math.isfinite(mean):
                raise ValueError(
                    f"mean_abs_offset_ns must be a finite float, got {mean!r} — the "
                    "runner computes sum/len (always a float)"
                )
            if not (0 <= p95 <= p99 <= expected_max and 0.0 <= mean <= expected_max):
                raise ValueError(
                    f"offset stats out of order: p95={p95}, p99={p99}, mean={mean}, "
                    f"max={expected_max} — nearest-rank percentiles and the mean of "
                    "absolute values cannot exceed the max"
                )

        # -- the composed case verdict (the documented rule) -----------------------------
        expected_verdict = (
            SyncVerdict.QUARANTINED if not self.episode_gate_passed else meta.verdict
        )
        if self.verdict is not expected_verdict:
            raise ValueError(
                f"verdict={self.verdict.value!r} contradicts the composition rule "
                f"(episode_gate_passed={self.episode_gate_passed}, timing_meta verdict "
                f"{meta.verdict.value!r} => {expected_verdict.value!r}) — the case "
                "verdict is computed, never asserted"
            )

    # -- serialization (stdlib only, exact round-trip) ---------------------------------

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form; ``from_dict(to_dict(r)) == r`` exactly, keys deterministic."""
        return {
            "name": self.name,
            "scenario": self.scenario,
            "episode_seed": self.episode_seed,
            "fixture": self.fixture,
            "monotonicity_violations": self.monotonicity_violations,
            "flagged_records": self.flagged_records,
            "total_records": self.total_records,
            "non_matched_results": self.non_matched_results,
            "total_results": self.total_results,
            "max_abs_offset_ns": self.max_abs_offset_ns,
            "mean_abs_offset_ns": self.mean_abs_offset_ns,
            "p95_abs_offset_ns": self.p95_abs_offset_ns,
            "p99_abs_offset_ns": self.p99_abs_offset_ns,
            "streams": {
                name: {"input": i, "delivered": d, "surviving": s}
                for name, i, d, s in self.streams
            },
            "contact_events_total": self.contact_events_total,
            "contact_events_matched": self.contact_events_matched,
            "contact_event_accuracy": self.contact_event_accuracy,
            "episode_gate_passed": self.episode_gate_passed,
            "episode_gate_reasons": list(self.episode_gate_reasons),
            "timing_meta": self.timing_meta.to_dict(),
            "verdict": self.verdict.value,
            "replay_deterministic": self.replay_deterministic,
            "lerobot_roundtrip_ok": self.lerobot_roundtrip_ok,
            "parquet_roundtrip_ok": self.parquet_roundtrip_ok,
            "exported_samples": self.exported_samples,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> BenchReport:
        """Rebuild from :meth:`to_dict` output; every invariant re-runs via construction.

        Missing/unknown keys and unknown tokens are refused loud — a truncated or
        foreign artifact must never load as a plausible measurement.
        """
        missing = _REPORT_KEYS - set(d)
        if missing:
            raise ValueError(f"bench-report dict missing keys {sorted(missing)}")
        unknown = set(d) - _REPORT_KEYS
        if unknown:
            raise ValueError(
                f"bench-report dict has unknown keys {sorted(unknown)} — refusing to "
                "guess at foreign fields (a new field needs a BENCH_VERSION bump)"
            )
        streams_obj = d["streams"]
        if not isinstance(streams_obj, Mapping):
            raise ValueError(
                f"'streams' must be a mapping, got {type(streams_obj).__name__}"
            )
        stream_entries: list[tuple[str, int, int, int]] = []
        for s_name, counts_obj in streams_obj.items():
            if not isinstance(s_name, str) or not s_name:
                raise ValueError(f"stream name must be a non-empty str, got {s_name!r}")
            if not isinstance(counts_obj, Mapping) or set(counts_obj) != _STREAM_KEYS:
                raise ValueError(
                    f"stream {s_name!r} must be a mapping with keys "
                    f"{sorted(_STREAM_KEYS)}, got {counts_obj!r}"
                )
            stream_entries.append((
                s_name,
                _require_count(counts_obj["input"], f"stream {s_name!r} input"),
                _require_count(counts_obj["delivered"], f"stream {s_name!r} delivered"),
                _require_count(counts_obj["surviving"], f"stream {s_name!r} surviving"),
            ))
        stream_entries.sort(key=lambda entry: entry[0])
        reasons_obj = d["episode_gate_reasons"]
        if isinstance(reasons_obj, str) or not isinstance(reasons_obj, list | tuple):
            raise ValueError(
                f"'episode_gate_reasons' must be a list of str, got {reasons_obj!r}"
            )
        for i, reason in enumerate(reasons_obj):
            if not isinstance(reason, str):
                raise ValueError(
                    f"episode_gate_reasons[{i}] must be a str, got {reason!r} — "
                    "coercing it would forge a refusal reason"
                )
        meta_obj = d["timing_meta"]
        if not isinstance(meta_obj, Mapping):
            raise ValueError(
                f"'timing_meta' must be a mapping, got {type(meta_obj).__name__}"
            )
        verdict_obj = d["verdict"]
        if not isinstance(verdict_obj, str):
            raise ValueError(f"'verdict' must be a str token, got {verdict_obj!r}")
        try:
            verdict = SyncVerdict(verdict_obj)
        except ValueError:
            raise ValueError(
                f"unknown verdict token {verdict_obj!r}; known: "
                f"{[m.value for m in SyncVerdict]} — refusing to guess"
            ) from None

        def _opt_int(key: str) -> int | None:
            value = d[key]
            return None if value is None else _require_count(value, key)

        def _opt_float(key: str) -> float | None:
            value = d[key]
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, float):
                raise ValueError(f"{key} must be a float or null, got {value!r}")
            return value

        fixture_obj = d["fixture"]
        if fixture_obj is not None and not isinstance(fixture_obj, str):
            raise ValueError(f"'fixture' must be a str or null, got {fixture_obj!r}")
        name_obj, scenario_obj = d["name"], d["scenario"]
        if not isinstance(name_obj, str) or not isinstance(scenario_obj, str):
            raise ValueError("'name' and 'scenario' must be str")
        seed_obj = d["episode_seed"]
        if isinstance(seed_obj, bool) or not isinstance(seed_obj, int):
            raise ValueError(f"'episode_seed' must be an int, got {seed_obj!r}")
        return cls(
            name=name_obj,
            scenario=scenario_obj,
            episode_seed=seed_obj,
            fixture=fixture_obj,
            monotonicity_violations=_require_count(
                d["monotonicity_violations"], "monotonicity_violations"
            ),
            flagged_records=_require_count(d["flagged_records"], "flagged_records"),
            total_records=_require_count(d["total_records"], "total_records"),
            non_matched_results=_require_count(
                d["non_matched_results"], "non_matched_results"
            ),
            total_results=_require_count(d["total_results"], "total_results"),
            max_abs_offset_ns=_opt_int("max_abs_offset_ns"),
            mean_abs_offset_ns=_opt_float("mean_abs_offset_ns"),
            p95_abs_offset_ns=_opt_int("p95_abs_offset_ns"),
            p99_abs_offset_ns=_opt_int("p99_abs_offset_ns"),
            streams=tuple(stream_entries),
            contact_events_total=_require_count(
                d["contact_events_total"], "contact_events_total"
            ),
            contact_events_matched=_require_count(
                d["contact_events_matched"], "contact_events_matched"
            ),
            contact_event_accuracy=_opt_float("contact_event_accuracy"),
            episode_gate_passed=_require_bool(
                d["episode_gate_passed"], "episode_gate_passed"
            ),
            episode_gate_reasons=tuple(
                r if isinstance(r, str) else str(r) for r in reasons_obj
            ),
            timing_meta=TimingMeta.from_dict(meta_obj),
            verdict=verdict,
            replay_deterministic=_require_bool(
                d["replay_deterministic"], "replay_deterministic"
            ),
            lerobot_roundtrip_ok=_require_bool(
                d["lerobot_roundtrip_ok"], "lerobot_roundtrip_ok"
            ),
            parquet_roundtrip_ok=_require_bool(
                d["parquet_roundtrip_ok"], "parquet_roundtrip_ok"
            ),
            exported_samples=_require_count(d["exported_samples"], "exported_samples"),
        )


# ------------------------------------------------------------------------------------
# the runner — compose sim -> disturb -> normalize -> align -> meta -> export
# ------------------------------------------------------------------------------------


def _episode_streams(episode: Episode) -> tuple[list[int], list[int], list[int], list[int]]:
    """Split the merged B7 episode into (proprio, tactile, frames, event) stamp lists."""
    proprio = [s.timestamp_ns for s in episode.samples if s.chain_index == _PROPRIO_CHAIN]
    tactile = [s.timestamp_ns for s in episode.samples if s.chain_index == _TACTILE_CHAIN]
    frames = [s.timestamp_ns for s in episode.samples if s.chain_index == _FRAMES_CHAIN]
    events = [
        s.timestamp_ns
        for s in episode.samples
        if s.chain_index == _TACTILE_CHAIN and s.tactile_event is not None
    ]
    return proprio, tactile, frames, events


def _roundtrip_lerobot(episode: Episode, meta: TimingMeta, out_dir: Path) -> bool:
    """Export -> reload through lerobot; True iff samples AND TimingMeta survive exactly."""
    root = export_lerobot([episode], out_dir, timing_meta={episode.episode_id: meta})
    loaded = load_lerobot(root)
    metas = load_lerobot_timing_meta(root)
    return (
        len(loaded) == 1
        and len(loaded[0].samples) == len(episode.samples)
        and metas == {episode.episode_id: meta}
    )


def _roundtrip_parquet(episode: Episode, meta: TimingMeta, out_dir: Path) -> bool:
    """Export -> reload through parquet; True iff samples AND TimingMeta survive exactly."""
    exporter = ParquetExporter(timing_meta={episode.episode_id: meta})
    root = exporter.export([episode], out_dir)
    loaded = exporter.load(root)
    metas = load_parquet_timing_meta(root)
    return (
        len(loaded) == 1
        and len(loaded[0].samples) == len(episode.samples)
        and metas == {episode.episode_id: meta}
    )


def _measure(case: BenchCase, scratch: Path) -> dict[str, object]:
    """One full pipeline pass for one case — everything but the determinism flag.

    Returns the :meth:`BenchReport.to_dict` payload (minus ``replay_deterministic``) so
    :func:`run_bench` can byte-compare two passes and then construct the report through
    the strict loader — one construction path, all invariants enforced.
    """
    episode = build_scenario_episode(case.scenario, seed=case.episode_seed)
    proprio, tactile, frames, events = _episode_streams(episode)
    if not events:
        raise ValueError(
            f"scenario {case.scenario!r} produced no tactile events — contact-event "
            "association is a required bench measurement (the last centimeter is the "
            "point); pick a contact-bearing scenario"
        )

    if case.fixture is None:
        ref_name = "proprio"
        reference_raw = proprio
        targets_raw: dict[str, list[int]] = {"frames": frames, "tactile": tactile}
        primary = "frames"
        gate_stamps = [s.timestamp_ns for s in episode.samples]
        input_counts = {
            ref_name: len(proprio),
            "frames": len(frames),
            "tactile": len(tactile),
            _EVENTS: len(events),
        }
    else:
        fixture = case.fixture
        ref_name = "reference"
        reference_raw = fixture.clean()
        disturbed = apply_faults(reference_raw, fixture.spec, SeededRng(fixture.seed))
        targets_raw = {"disturbed": disturbed}
        primary = "disturbed"
        gate_stamps = disturbed
        input_counts = {
            ref_name: fixture.n_stamps,
            "disturbed": fixture.n_stamps,
            _EVENTS: len(events),
        }

    # The episode-level quarantine: the SAME jitter/dropout/backwards gate the recorder
    # and both exporters refuse episodes with, applied to the disturbed stream as
    # delivered. A refusal composes into the case verdict (never hidden by alignment
    # stats that may look locally fine).
    jitter_budget = JitterBudget()
    stats = compute_jitter(gate_stamps, jitter_budget)
    gate_ok, gate_reasons = jitter_budget.check(stats)

    # C2: normalize every stream (MONOTONIC identity; backwards FLAGGED, never repaired).
    records: dict[str, tuple[TimingRecord, ...]] = {
        ref_name: Normalizer(ClockDomain.MONOTONIC).normalize(reference_raw)
    }
    for t_name, raw in targets_raw.items():
        records[t_name] = Normalizer(ClockDomain.MONOTONIC).normalize(raw)
    records[_EVENTS] = Normalizer(ClockDomain.MONOTONIC).normalize(events)
    surviving = {
        name: timeline_from_records(recs)[0] for name, recs in records.items()
    }

    # C3: NEAREST-align each target onto the reference; WINDOW-associate the contact
    # events against the primary target stream (events are never interpolated).
    results = {
        t_name: align(
            surviving[ref_name],
            surviving[t_name],
            case.budget,
            method=AlignmentMethod.NEAREST,
        )
        for t_name in targets_raw
    }
    results[_EVENTS] = align(
        surviving[_EVENTS],
        surviving[primary],
        case.budget,
        method=AlignmentMethod.WINDOW,
    )

    # C5: the auditable summary — counts tallied from real records/results only.
    meta = TimingMeta.from_run(records, results, case.budget, reference=ref_name)

    # Alignment-error percentiles over EXACT/NEAREST published offsets only (see the
    # module docstring for why WINDOW association offsets are excluded).
    abs_offsets = sorted(
        abs(result.offset_ns)
        for t_name in targets_raw
        for result in results[t_name]
        if result.offset_ns is not None
    )
    max_abs: int | None = None
    mean_abs: float | None = None
    p95_abs: int | None = None
    p99_abs: int | None = None
    if abs_offsets:
        max_abs = abs_offsets[-1]
        mean_abs = sum(abs_offsets) / len(abs_offsets)
        p95_abs = nearest_rank_percentile(abs_offsets, 95.0)
        p99_abs = nearest_rank_percentile(abs_offsets, 99.0)

    # Contact accuracy: fraction of event stamps with >= 1 in-window association.
    matched_refs = {
        result.ref_ns
        for result in results[_EVENTS]
        if result.quality is AlignmentQuality.MATCHED
    }
    events_matched = len(matched_refs)

    # Exporter round-trip stability: the clean carrier episode + THIS case's TimingMeta
    # through both exporters' sidecar channels, reloaded and compared exactly.
    lerobot_ok = _roundtrip_lerobot(episode, meta, scratch / "lerobot")
    parquet_ok = _roundtrip_parquet(episode, meta, scratch / "parquet")

    verdict = SyncVerdict.QUARANTINED if not gate_ok else meta.verdict
    return {
        "name": case.name,
        "scenario": case.scenario,
        "episode_seed": case.episode_seed,
        "fixture": None if case.fixture is None else case.fixture.name,
        "monotonicity_violations": _backwards_flag_count(meta),
        "flagged_records": meta.flagged_record_count,
        "total_records": sum(
            mod.clean_count + mod.flagged_count for _, mod in meta.modalities
        ),
        "non_matched_results": meta.out_of_budget_count + meta.missing_target_count,
        "total_results": sum(mod.result_count() for _, mod in meta.modalities),
        "max_abs_offset_ns": max_abs,
        "mean_abs_offset_ns": mean_abs,
        "p95_abs_offset_ns": p95_abs,
        "p99_abs_offset_ns": p99_abs,
        "streams": {
            name: {
                "input": input_counts[name],
                "delivered": len(records[name]),
                "surviving": len(surviving[name]),
            }
            for name in sorted(records)
        },
        "contact_events_total": len(events),
        "contact_events_matched": events_matched,
        "contact_event_accuracy": events_matched / len(events),
        "episode_gate_passed": gate_ok,
        "episode_gate_reasons": list(gate_reasons),
        "timing_meta": meta.to_dict(),
        "verdict": verdict.value,
        "lerobot_roundtrip_ok": lerobot_ok,
        "parquet_roundtrip_ok": parquet_ok,
        "exported_samples": len(episode.samples),
    }


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def run_bench(case: BenchCase, *, workdir: str | Path) -> BenchReport:
    """Run one bench case through the FULL pipeline, twice, and report measured numbers.

    Deterministic and wall-clock-free: episodes, faults and clocks are all seeded. The
    pipeline is executed TWICE (independent export scratch dirs under ``workdir``) and
    ``replay_deterministic`` records whether the two measurement payloads are
    byte-identical — measured, never assumed. The report is constructed through
    :meth:`BenchReport.from_dict`, so every cross-field invariant is enforced on the
    freshly measured values too.
    """
    if not isinstance(case, BenchCase):
        raise ValueError(
            f"case must be a BenchCase, got {type(case).__name__} {case!r} — an "
            "unvalidated case cannot be reproduced or attributed"
        )
    root = Path(workdir)
    first = _measure(case, root / "run1")
    second = _measure(case, root / "run2")
    deterministic = _canonical_json(first) == _canonical_json(second)
    return BenchReport.from_dict({**first, "replay_deterministic": deterministic})


def run_suite(
    cases: Sequence[BenchCase], *, workdir: str | Path
) -> tuple[BenchReport, ...]:
    """Run every case (unique names required) and return the reports in case order."""
    if not cases:
        raise ValueError("cases is empty — a suite that measures nothing gates nothing")
    names = [case.name for case in cases if isinstance(case, BenchCase)]
    if len(names) != len(cases):
        bad = next(c for c in cases if not isinstance(c, BenchCase))
        raise ValueError(f"cases must all be BenchCase, got {type(bad).__name__} {bad!r}")
    if len(set(names)) != len(names):
        raise ValueError(
            f"duplicate case names in {names} — reports are keyed by name; a duplicate "
            "would silently shadow a measurement"
        )
    root = Path(workdir)
    return tuple(run_bench(case, workdir=root / case.name) for case in cases)


# ------------------------------------------------------------------------------------
# the gate — explicit thresholds, provable failure
# ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseThresholds:
    """Explicit pass criteria for ONE bench case — a gate entry that can actually fail.

    ``allowed_verdicts`` is exact set membership: for ``burst_stall_200ms`` the default
    table allows ONLY ``QUARANTINED``, so a burst case that comes out looking aligned
    FAILS the gate — the detection path is gated, not just the happy path. Offset
    ceilings apply to published EXACT/NEAREST offsets (``None`` published offsets pass
    a ceiling trivially — the verdict check catches a nothing-matched case).
    ``replay_deterministic`` and both exporter round-trips are enforced UNCONDITIONALLY
    by :func:`gate` — they are not configurable, because a threshold that can waive
    determinism is a gate that cannot be trusted.
    """

    allowed_verdicts: frozenset[SyncVerdict]
    max_monotonicity_violations: int
    max_flagged_records: int | None = None
    max_abs_offset_ns: int | None = None
    max_p99_abs_offset_ns: int | None = None
    min_contact_accuracy: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_verdicts, frozenset) or not self.allowed_verdicts:
            raise ValueError(
                f"allowed_verdicts must be a non-empty frozenset, got "
                f"{self.allowed_verdicts!r} — an empty allowance can never pass and a "
                "mutable one can be edited after review"
            )
        for member in self.allowed_verdicts:
            if not isinstance(member, SyncVerdict):
                raise ValueError(
                    f"allowed_verdicts contains {member!r} — only SyncVerdict members "
                    "can be compared to a report verdict"
                )
        _require_count(self.max_monotonicity_violations, "max_monotonicity_violations")
        for opt_name in ("max_flagged_records", "max_abs_offset_ns", "max_p99_abs_offset_ns"):
            value = getattr(self, opt_name)
            if value is not None:
                _require_count(value, opt_name)
        if self.min_contact_accuracy is not None:
            acc = self.min_contact_accuracy
            if isinstance(acc, bool) or not isinstance(acc, int | float):
                raise ValueError(f"min_contact_accuracy must be a real number, got {acc!r}")
            if not 0.0 <= acc <= 1.0:
                raise ValueError(
                    f"min_contact_accuracy must be within [0, 1], got {acc} — it is a "
                    "fraction of events"
                )

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form for the committed artifact (thresholds are evidence too)."""
        return {
            "allowed_verdicts": sorted(m.value for m in self.allowed_verdicts),
            "max_monotonicity_violations": self.max_monotonicity_violations,
            "max_flagged_records": self.max_flagged_records,
            "max_abs_offset_ns": self.max_abs_offset_ns,
            "max_p99_abs_offset_ns": self.max_p99_abs_offset_ns,
            "min_contact_accuracy": self.min_contact_accuracy,
        }


#: The canonical gate table — the documented pass criteria the phase closes against.
#:
#: * ``clean_baseline`` must be fully ALIGNED with zero violations/flags; its offset
#:   ceilings are the episode's structural interleave bounds (max 20 ms — measured,
#:   hand-checkable), so a lattice regression fails loud.
#: * mild fixtures (``can_jitter_mild``, ``camera_variable_33ms``) may be DEGRADED at
#:   worst, never quarantined, with zero monotonicity violations/flags; the jitter
#:   ceiling is the fault's own +/-0.2 ms magnitude — a jitter published past its own
#:   bound means the measurement (not the fault) broke.
#: * ``burst_stall_200ms`` MUST be QUARANTINED (backwards + dropout => the episode
#:   gate refuses it) with its exactly-20 flagged stamps; every published offset is an
#:   exact lattice coincidence, so the ceiling is 0.
#: * ``skewed_source_clock`` MUST be QUARANTINED per the documented C5 rule: alignment
#:   is attempted and NOTHING matches (every candidate is 4-6 ms out against a 2 ms
#:   budget) while interval stats stay perfectly clean (0 violations) — the case that
#:   proves a reference-offset instrument is required, not just interval jitter.
DEFAULT_THRESHOLDS: dict[str, CaseThresholds] = {
    "clean_baseline": CaseThresholds(
        allowed_verdicts=frozenset({SyncVerdict.ALIGNED_WITHIN_BUDGET}),
        max_monotonicity_violations=0,
        max_flagged_records=0,
        max_abs_offset_ns=20_000_000,
        max_p99_abs_offset_ns=20_000_000,
        min_contact_accuracy=1.0,
    ),
    "can_jitter_mild": CaseThresholds(
        allowed_verdicts=frozenset(
            {SyncVerdict.ALIGNED_WITHIN_BUDGET, SyncVerdict.DEGRADED}
        ),
        max_monotonicity_violations=0,
        max_flagged_records=0,
        max_abs_offset_ns=200_000,
        max_p99_abs_offset_ns=200_000,
        min_contact_accuracy=1.0,
    ),
    "camera_variable_33ms": CaseThresholds(
        allowed_verdicts=frozenset(
            {SyncVerdict.ALIGNED_WITHIN_BUDGET, SyncVerdict.DEGRADED}
        ),
        max_monotonicity_violations=0,
        max_flagged_records=0,
        max_abs_offset_ns=_FIXTURE_MAX_SKEW_NS,
        max_p99_abs_offset_ns=_FIXTURE_MAX_SKEW_NS,
        min_contact_accuracy=1.0,
    ),
    "burst_stall_200ms": CaseThresholds(
        allowed_verdicts=frozenset({SyncVerdict.QUARANTINED}),
        max_monotonicity_violations=20,
        max_flagged_records=20,
        max_abs_offset_ns=0,
        max_p99_abs_offset_ns=0,
        min_contact_accuracy=0.5,
    ),
    "skewed_source_clock": CaseThresholds(
        allowed_verdicts=frozenset({SyncVerdict.QUARANTINED}),
        max_monotonicity_violations=0,
        max_flagged_records=0,
        min_contact_accuracy=1.0,
    ),
}


def demand_clean_thresholds(case_names: Sequence[str]) -> dict[str, CaseThresholds]:
    """Thresholds demanding a violation-free suite — the gate's provable failure path.

    Applied to the canonical suite (which CONTAINS injected violations by design) these
    thresholds MUST fail: burst/skew cases are quarantined, not aligned. Used by the
    CLI's ``--demand-clean`` and by the tests that prove the gate can say no.
    """
    if not case_names:
        raise ValueError("case_names is empty — thresholds over nothing gate nothing")
    strict = CaseThresholds(
        allowed_verdicts=frozenset({SyncVerdict.ALIGNED_WITHIN_BUDGET}),
        max_monotonicity_violations=0,
        max_flagged_records=0,
        min_contact_accuracy=1.0,
    )
    out: dict[str, CaseThresholds] = {}
    for name in case_names:
        if not isinstance(name, str) or not name:
            raise ValueError(f"case name must be a non-empty str, got {name!r}")
        if name in out:
            raise ValueError(f"duplicate case name {name!r}")
        out[name] = strict
    return out


def gate(
    reports: Sequence[BenchReport], thresholds: Mapping[str, CaseThresholds]
) -> tuple[bool, list[str]]:
    """The phase gate: ``(passed, failures)`` over measured reports + explicit thresholds.

    Failure mode: a gate with implicit coverage silently passes what nobody gated. The
    threshold keys must be EXACTLY the report names — a report without a threshold is
    an ungated measurement (always-pass by omission) and raises; a threshold without a
    report gates nothing and raises. Determinism and exporter round-trips are enforced
    unconditionally. Malformed inputs raise ``ValueError``; a gate FAILURE (measured
    number out of bounds) is returned, never raised — the caller decides the exit code.
    """
    if not reports:
        raise ValueError("reports is empty — a gate over nothing proves nothing")
    for i, report in enumerate(reports):
        if not isinstance(report, BenchReport):
            raise ValueError(
                f"reports[{i}] must be a BenchReport, got {type(report).__name__} "
                f"{report!r} — an unvalidated blob cannot be gated"
            )
    names = [report.name for report in reports]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate report names {names} — one measurement per case")
    for name, threshold in thresholds.items():
        if not isinstance(threshold, CaseThresholds):
            raise ValueError(
                f"thresholds[{name!r}] must be a CaseThresholds, got "
                f"{type(threshold).__name__} {threshold!r}"
            )
    missing = set(names) - set(thresholds)
    if missing:
        raise ValueError(
            f"no thresholds for case(s) {sorted(missing)} — an ungated report is an "
            "always-pass by omission (banned)"
        )
    extra = set(thresholds) - set(names)
    if extra:
        raise ValueError(
            f"thresholds for absent case(s) {sorted(extra)} — a threshold that gates "
            "nothing hides a dropped measurement"
        )

    failures: list[str] = []
    for report in reports:
        t = thresholds[report.name]
        prefix = f"[{report.name}]"
        if report.verdict not in t.allowed_verdicts:
            allowed = sorted(m.value for m in t.allowed_verdicts)
            failures.append(
                f"{prefix} verdict {report.verdict.value!r} not in allowed {allowed}"
            )
        if report.monotonicity_violations > t.max_monotonicity_violations:
            failures.append(
                f"{prefix} monotonicity violations {report.monotonicity_violations} > "
                f"max {t.max_monotonicity_violations}"
            )
        if (
            t.max_flagged_records is not None
            and report.flagged_records > t.max_flagged_records
        ):
            failures.append(
                f"{prefix} flagged records {report.flagged_records} > max "
                f"{t.max_flagged_records}"
            )
        if (
            t.max_abs_offset_ns is not None
            and report.max_abs_offset_ns is not None
            and report.max_abs_offset_ns > t.max_abs_offset_ns
        ):
            failures.append(
                f"{prefix} max |offset| {report.max_abs_offset_ns} ns > max "
                f"{t.max_abs_offset_ns} ns"
            )
        if (
            t.max_p99_abs_offset_ns is not None
            and report.p99_abs_offset_ns is not None
            and report.p99_abs_offset_ns > t.max_p99_abs_offset_ns
        ):
            failures.append(
                f"{prefix} p99 |offset| {report.p99_abs_offset_ns} ns > max "
                f"{t.max_p99_abs_offset_ns} ns"
            )
        if t.min_contact_accuracy is not None:
            if report.contact_event_accuracy is None:
                failures.append(
                    f"{prefix} contact accuracy required (>= {t.min_contact_accuracy}) "
                    "but no events were measured"
                )
            elif report.contact_event_accuracy < t.min_contact_accuracy:
                failures.append(
                    f"{prefix} contact accuracy {report.contact_event_accuracy:.4f} < "
                    f"min {t.min_contact_accuracy}"
                )
        if not report.replay_deterministic:
            failures.append(f"{prefix} replay is NOT deterministic (two runs differed)")
        if not report.lerobot_roundtrip_ok:
            failures.append(f"{prefix} lerobot export round-trip failed")
        if not report.parquet_roundtrip_ok:
            failures.append(f"{prefix} parquet export round-trip failed")
    return (not failures, failures)


# ------------------------------------------------------------------------------------
# artifacts — the committed evidence (JSON + human-readable markdown)
# ------------------------------------------------------------------------------------


def _fmt_ns(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def render_markdown(
    reports: Sequence[BenchReport],
    thresholds: Mapping[str, CaseThresholds],
    *,
    passed: bool,
    failures: Sequence[str],
    gate_mode: str,
    regenerate: str,
) -> str:
    """The human-readable report table — same measured numbers as the JSON artifact."""
    lines = [
        "# P-C timing benchmark — measured phase-gate report (C7)",
        "",
        f"- bench version: {BENCH_VERSION}",
        f"- regenerate: `{regenerate}`",
        f"- gate mode: `{gate_mode}` — **{'PASS' if passed else 'FAIL'}**",
        "- offsets are published EXACT/NEAREST alignment offsets (ns); WINDOW event-"
        "association offsets live in each report's `timing_meta`. Percentiles are "
        "nearest-rank (`ceil(p/100*n)`).",
        "",
        "| case | verdict | mono. viol. | flagged/records | non-matched/results "
        "| max abs offset (ns) | p95 (ns) | p99 (ns) | contact events | deterministic "
        "| lerobot rt | parquet rt |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        acc = "-" if r.contact_event_accuracy is None else f"{r.contact_event_accuracy:.3f}"
        lines.append(
            f"| {r.name} | {r.verdict.value} | {r.monotonicity_violations} "
            f"| {r.flagged_records}/{r.total_records} "
            f"| {r.non_matched_results}/{r.total_results} "
            f"| {_fmt_ns(r.max_abs_offset_ns)} | {_fmt_ns(r.p95_abs_offset_ns)} "
            f"| {_fmt_ns(r.p99_abs_offset_ns)} "
            f"| {r.contact_events_matched}/{r.contact_events_total} ({acc}) "
            f"| {'yes' if r.replay_deterministic else 'NO'} "
            f"| {'ok' if r.lerobot_roundtrip_ok else 'FAIL'} "
            f"| {'ok' if r.parquet_roundtrip_ok else 'FAIL'} |"
        )
    lines += ["", "## Dropped-frame behavior (input -> delivered -> surviving)", ""]
    for r in reports:
        per_stream = ", ".join(
            f"{name} {i}->{d}->{s}" for name, i, d, s in r.streams
        )
        gate_note = (
            "episode gate PASSED"
            if r.episode_gate_passed
            else "episode gate REFUSED: " + "; ".join(r.episode_gate_reasons)
        )
        lines.append(f"- **{r.name}**: {per_stream} — {gate_note}")
    lines += ["", "## Gate thresholds", ""]
    for name in sorted(thresholds):
        t = thresholds[name]
        lines.append(f"- `{name}`: {json.dumps(t.to_dict(), sort_keys=True)}")
    lines += ["", "## Gate result", ""]
    if failures:
        lines.extend(f"- FAIL: {failure}" for failure in failures)
    else:
        lines.append("- all thresholds satisfied")
    lines.append("")
    return "\n".join(lines)


def _artifact_payload(
    reports: Sequence[BenchReport],
    thresholds: Mapping[str, CaseThresholds],
    *,
    passed: bool,
    failures: Sequence[str],
    gate_mode: str,
    scenario: str,
    episode_seed: int,
    regenerate: str,
) -> dict[str, object]:
    return {
        "bench_version": BENCH_VERSION,
        "scenario": scenario,
        "episode_seed": episode_seed,
        "gate_mode": gate_mode,
        "gate_passed": passed,
        "gate_failures": list(failures),
        "regenerate": regenerate,
        "thresholds": {name: t.to_dict() for name, t in sorted(thresholds.items())},
        "reports": [report.to_dict() for report in reports],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: run the canonical suite, write JSON+markdown artifacts, exit 0 iff gate passed.

    Deterministic: the same arguments produce byte-identical artifacts (no wall clock,
    no paths in the output). Export round-trips run in a throwaway temp dir; only their
    boolean outcomes enter the report.
    """
    parser = argparse.ArgumentParser(
        prog="python -m timing.bench",
        description=(
            "P-C timing benchmark phase-gate: sim -> chaos -> normalize -> align -> "
            "export, with measured numbers and explicit pass thresholds."
        ),
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="directory for the JSON+md artifacts"
    )
    parser.add_argument(
        "--scenario",
        default="slip_recovery",
        choices=sorted(EXAMPLE_SCENARIOS),
        help="carrier contact scenario for the episode/events (default: slip_recovery)",
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="episode seed (timestamps are seed-invariant)"
    )
    parser.add_argument(
        "--demand-clean",
        action="store_true",
        help=(
            "gate with thresholds demanding a violation-free suite; the canonical "
            "suite contains injected violations, so this MUST fail (proves the gate "
            "can say no)"
        ),
    )
    args = parser.parse_args(argv)

    cases = canonical_cases(scenario=args.scenario, episode_seed=args.seed)
    with tempfile.TemporaryDirectory(prefix="timing_bench_") as scratch:
        reports = run_suite(cases, workdir=Path(scratch))
    if args.demand_clean:
        gate_mode = "demand-clean"
        thresholds = demand_clean_thresholds([case.name for case in cases])
    else:
        gate_mode = "default"
        thresholds = DEFAULT_THRESHOLDS
    passed, failures = gate(reports, thresholds)

    regenerate = (
        f"cd host && python -m timing.bench --scenario {args.scenario} "
        f"--seed {args.seed}{' --demand-clean' if args.demand_clean else ''} "
        "--out <output-dir>"
    )
    payload = _artifact_payload(
        reports,
        thresholds,
        passed=passed,
        failures=failures,
        gate_mode=gate_mode,
        scenario=args.scenario,
        episode_seed=args.seed,
        regenerate=regenerate,
    )
    markdown = render_markdown(
        reports,
        thresholds,
        passed=passed,
        failures=failures,
        gate_mode=gate_mode,
        regenerate=regenerate,
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{REPORT_BASENAME}.json"
    md_path = out_dir / f"{REPORT_BASENAME}.md"
    json_path.write_text(
        _canonical_json(payload) + "\n", encoding="utf-8", newline="\n"
    )
    md_path.write_text(markdown, encoding="utf-8", newline="\n")

    print(markdown)
    print(f"artifacts: {json_path} / {md_path}")
    print(f"GATE {'PASSED' if passed else 'FAILED'} ({gate_mode})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
