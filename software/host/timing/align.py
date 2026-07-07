"""Multi-modal alignment engine — bounded, quality-annotated, never guessing (C3).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **Guessed / stale / out-of-budget matches => silently misaligned training data.** An
  aligner that returns "the nearest frame" no matter how far away pairs a proprio tick
  with a frame captured long before or after it; a model trained on that learns
  cross-modal timing that never happened, and nothing in the dataset says so. Here a
  match is published ONLY within an explicit :class:`AlignmentBudget`; anything farther
  is an honest :data:`AlignmentQuality.OUT_OF_BUDGET` result with ``matched_ns=None`` —
  the too-far candidate is never surfaced as a value, so it *cannot* be reused
  (:class:`AlignmentResult` construction enforces this, not just the engine).
* **Hidden missing modality => silently proprio-only "PVT" data.** A missing frame or
  tactile stream must show up as explicit :data:`AlignmentQuality.NO_TARGET` results,
  never as a shorter output list, a stale neighbor, or an invented value. Every
  reference stamp yields at least one result — a miss is a result, not an absence.
* **Values without provenance are banned.** Every result records WHICH
  :class:`AlignmentMethod` produced it, the signed ``offset_ns``, the budget verdict and
  the quality token — so an exported association can be audited and re-derived, and a
  bare "aligned value" with no story cannot exist.
* **Interpolated events => fabricated contacts.** Linear interpolation is physically
  meaningful for continuous proprio channels ONLY. :func:`interpolate_proprio` takes
  numeric ``(stamp, value)`` pairs and loudly rejects event-typed data (a tactile token
  like ``"slip"`` is categorical — a blend of two events is a contact that never
  happened) and refuses extrapolation outside the segment.
* **Nondeterministic ties / silently repaired input => non-reproducible datasets.** An
  equidistant NEAREST tie is resolved by a DOCUMENTED rule (earlier target wins) and
  recorded (``tie=True``) — never left to iteration order. Out-of-order or duplicated
  target stamps are REJECTED loud at the boundary — never sorted or deduped silently;
  normalizing a dirty timeline is C2's job (:class:`~timing.normalize.Normalizer`),
  and flagged C2 records are excluded AND surfaced by :func:`timeline_from_records`,
  never quietly used.

Scope (PONYTAIL): the alignment core + quality metadata only — no fault injection (C4),
no export changes (C5), no CLI (C7). Stdlib only, no numpy (the P-C invariant). The
FROZEN ``PVTSample`` is untouched: alignment works over monotonic int-ns timestamps
(plus opaque payload references the caller keeps), never by editing samples.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from timing.normalize import TimingRecord
from timing.stamp import MAX_STAMP_NS, validate_stamp_ns

__all__ = [
    "AlignmentBudget",
    "AlignmentMethod",
    "AlignmentQuality",
    "AlignmentResult",
    "align",
    "align_modalities",
    "interpolate_proprio",
    "timeline_from_records",
]


class AlignmentMethod(StrEnum):
    """How an alignment result was produced — recorded per result, never guessed.

    Failure mode: an association whose method is unknown cannot be audited (was that
    frame exactly coincident, or the nearest within 20 ms?) and cannot be reproduced.
    A :class:`~enum.StrEnum` (mirroring ``ClockDomain``/``NormalizationFlag``): **the
    token values are serialization-stable contract** — they land in exported metadata
    (C5), so renaming one is a versioned decision, never a refactor.

    Members
    -------
    EXACT:
        The matched target stamp equals the reference stamp (``offset_ns == 0``).
        Requestable directly (only exact coincidence counts) and also recorded when a
        NEAREST search lands at offset 0 — "exact" is a measured fact, strictly
        stronger than "nearest", so recording it is honesty, not a guess.
    NEAREST:
        The single nearest target within ``budget.max_skew_ns``. An equidistant tie is
        resolved by the documented rule (earlier target wins) and marked ``tie=True``.
    WINDOW:
        Bounded-window association: ALL targets inside the closed interval
        ``[ref - window_ns, ref + window_ns]`` — for event streams (tactile) that may
        fire between reference samples. WINDOW results always record ``WINDOW`` (even
        at offset 0): window membership is the semantics, not best-match ranking.
    """

    EXACT = "exact"
    NEAREST = "nearest"
    WINDOW = "window"


class AlignmentQuality(StrEnum):
    """The honest per-result verdict — the minimal set, deliberately NO catch-all.

    Failure mode: a bare matched-or-not bit cannot distinguish "the modality is absent"
    from "the modality is present but too skewed", so quarantine (C4) and export audit
    (C5) could not act intelligently. Serialization-stable tokens, like
    :class:`AlignmentMethod`. An unclassifiable outcome means this enum (and the engine
    emitting it) must grow a precise token first — never a vague "other".

    Members
    -------
    MATCHED:
        A target was associated within budget. ``matched_ns``/``offset_ns`` are set.
    OUT_OF_BUDGET:
        A nearest candidate EXISTS but lies farther than ``max_skew_ns``. The candidate
        is deliberately NOT published (``matched_ns=None``) — surfacing it would invite
        exactly the stale-reuse this module bans. (NEAREST/EXACT only: WINDOW's bound
        is the window itself, so a WINDOW miss is NO_TARGET, not OUT_OF_BUDGET.)
    NO_TARGET:
        No candidate at all: the target timeline is empty (any method) or nothing falls
        inside the WINDOW interval. The modality is missing HERE — flagged, never
        hidden, never filled with a stale neighbor.
    """

    MATCHED = "matched"
    OUT_OF_BUDGET = "out_of_budget"
    NO_TARGET = "no_target"


def _validate_budget_ns(value: object, *, name: str) -> int:
    """Validate a non-negative int-ns budget field; return it or raise ``ValueError``.

    Failure mode: a bool/float/negative budget would silently widen or collapse the
    acceptance band (``True`` -> 1 ns, ``0.02e9`` -> float compare against exact int
    ns). Same rejection classes as C1's stamp validator, budget-shaped range: ``0`` is
    legal (only exact coincidence is acceptable), negatives are not.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be an int nanosecond budget, got bool {value!r} — a bool "
            "would silently coerce to 0/1 and forge a budget out of a flag"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int nanosecond budget, got {type(value).__name__} "
            f"{value!r} — non-int budgets lose nanosecond exactness"
        )
    if value < 0:
        raise ValueError(
            f"{name} must be >= 0, got {value} — a negative acceptance band matches "
            "nothing and is always a caller bug"
        )
    if value > MAX_STAMP_NS:
        raise ValueError(
            f"{name} must be <= 2**63-1 ({MAX_STAMP_NS}), got {value} — a budget past "
            "int64 cannot round-trip through on-disk metadata without truncation"
        )
    return value


@dataclass(frozen=True, slots=True)
class AlignmentBudget:
    """The documented acceptance band for cross-modal association (all ns).

    Failure mode: an implicit or unbounded budget is how stale matches happen — every
    association needs an explicit, recorded bound (rhymes with
    ``logger.jitter.JitterBudget``, but alignment error is reference-to-target skew,
    NOT inter-sample jitter — hence a separate type with its own fields).

    Attributes
    ----------
    max_skew_ns:
        Maximum |target - reference| a NEAREST/EXACT match may publish, INCLUSIVE
        (``|offset| == max_skew_ns`` is within budget — tested at exactly the
        boundary). ``0`` means only exact coincidence is acceptable.
    window_ns:
        Half-width of the WINDOW method's closed interval ``[ref - w, ref + w]``.
        ``None`` (default) means WINDOW was not budgeted for — calling
        :func:`align` with ``AlignmentMethod.WINDOW`` then fails loud rather than
        guessing a window from ``max_skew_ns``.
    """

    max_skew_ns: int
    window_ns: int | None = None

    def __post_init__(self) -> None:
        # Fail loud at construction (never mid-alignment): a budget that exists is valid.
        _validate_budget_ns(self.max_skew_ns, name="max_skew_ns")
        if self.window_ns is not None:
            _validate_budget_ns(self.window_ns, name="window_ns")


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """One quality-annotated alignment outcome — a value that cannot lie about itself.

    Failure mode: a bare aligned value with no provenance cannot be audited, and a
    "matched anyway" stamp on an out-of-budget result is exactly the stale reuse that
    poisons training data. Construction enforces the invariants below, so a result that
    EXISTS is internally honest — the engine cannot emit, and a deserializer cannot
    load, a contradictory one.

    Invariants (enforced in ``__post_init__``):

    * ``quality == MATCHED``  <=>  ``matched_ns is not None``  <=>
      ``offset_ns is not None``  <=>  ``within_budget is True``. A miss NEVER carries a
      stamp or offset (no stale value to reuse); a match always carries both.
    * ``offset_ns == matched_ns - ref_ns`` exactly (signed, target minus reference) —
      re-derivable, so a forged offset cannot exist.
    * ``tie=True`` only on a MATCHED NEAREST result: it records that an equidistant
      before/after pair was resolved by the documented earlier-wins rule.
    * a MATCHED EXACT result has ``offset_ns == 0`` (that is what "exact" means).

    ``within_budget`` is deliberately locked to ``quality`` — it is the budget verdict
    consumers filter on, and letting it diverge from the quality token would let one
    reader see a match where another sees a miss.
    """

    ref_ns: int
    matched_ns: int | None
    offset_ns: int | None
    method: AlignmentMethod
    within_budget: bool
    quality: AlignmentQuality
    tie: bool = False

    def __post_init__(self) -> None:
        validate_stamp_ns(self.ref_ns, name="ref_ns")
        if not isinstance(self.method, AlignmentMethod):
            raise ValueError(
                f"method must be an AlignmentMethod, got {type(self.method).__name__} "
                f"{self.method!r} — a result without a recorded method cannot be audited"
            )
        if not isinstance(self.quality, AlignmentQuality):
            raise ValueError(
                f"quality must be an AlignmentQuality, got "
                f"{type(self.quality).__name__} {self.quality!r} — a foreign verdict "
                "token cannot be acted on by quarantine or export audit"
            )
        if not isinstance(self.within_budget, bool):
            raise ValueError(
                f"within_budget must be a bool, got {type(self.within_budget).__name__} "
                f"{self.within_budget!r} — a truthy non-bool would silently pass filters"
            )
        if not isinstance(self.tie, bool):
            raise ValueError(
                f"tie must be a bool, got {type(self.tie).__name__} {self.tie!r}"
            )
        matched = self.quality is AlignmentQuality.MATCHED
        if matched:
            if self.matched_ns is None:
                raise ValueError(
                    "quality=matched with matched_ns=None — a match without a stamp is "
                    "a value with no provenance"
                )
            validate_stamp_ns(self.matched_ns, name="matched_ns")
            if isinstance(self.offset_ns, bool) or self.offset_ns != (
                self.matched_ns - self.ref_ns
            ):
                raise ValueError(
                    f"offset_ns={self.offset_ns!r} != matched_ns - ref_ns = "
                    f"{self.matched_ns - self.ref_ns} — the offset must be exactly "
                    "re-derivable; anything else is a forged association"
                )
            if not self.within_budget:
                raise ValueError(
                    "quality=matched with within_budget=False — a published match IS "
                    "the budget verdict; an out-of-budget candidate must not be "
                    "published as matched (stale-reuse ban)"
                )
            if self.method is AlignmentMethod.EXACT and self.offset_ns != 0:
                raise ValueError(
                    f"method=exact with offset_ns={self.offset_ns} — exact means the "
                    "stamps are equal; a nonzero offset labeled 'exact' is a lie"
                )
            if self.method is AlignmentMethod.NEAREST and self.offset_ns == 0:
                raise ValueError(
                    "method=nearest with offset_ns=0 — an exact coincidence is recorded "
                    "as EXACT (a measured fact, documented on AlignmentMethod); labeling "
                    "it 'nearest' would let two readers disagree about what matched"
                )
        else:
            if self.matched_ns is not None:
                raise ValueError(
                    f"quality={self.quality.value!r} with matched_ns="
                    f"{self.matched_ns} — a non-match must never publish a stamp; a "
                    "surfaced too-far candidate is exactly the stale reuse this bans"
                )
            if self.offset_ns is not None:
                raise ValueError(
                    f"quality={self.quality.value!r} with offset_ns={self.offset_ns} — "
                    "an offset to nothing is a value without provenance"
                )
            if self.within_budget:
                raise ValueError(
                    f"quality={self.quality.value!r} with within_budget=True — a miss "
                    "cannot be within budget; diverging verdicts let one reader see a "
                    "match where another sees a miss"
                )
        if self.tie:
            if not matched or self.method is not AlignmentMethod.NEAREST:
                raise ValueError(
                    f"tie=True on quality={self.quality.value!r} method="
                    f"{self.method.value!r} — the tie flag records an equidistant "
                    "NEAREST resolution (earlier wins); it is meaningless anywhere else"
                )
        if (
            self.method is AlignmentMethod.WINDOW
            and self.quality is AlignmentQuality.OUT_OF_BUDGET
        ):
            raise ValueError(
                "method=window with quality=out_of_budget — WINDOW's bound IS the window "
                "(documented on AlignmentQuality): a window miss is NO_TARGET; an "
                "'out-of-budget window' result is a contradictory state"
            )


def _validate_timeline(stamps: Sequence[int], *, name: str) -> list[int]:
    """Validate a strictly-increasing monotonic-ns timeline; return it as a list.

    Failure mode: sorting or deduping here would silently repair the caller's dirty
    timeline — the exact fake synchronization C2 exists to prevent. Duplicates and
    out-of-order stamps are REJECTED loud with the offending index; the caller must
    normalize first (``timing.normalize.Normalizer`` -> :func:`timeline_from_records`).
    Each element is validated with C1's :func:`~timing.stamp.validate_stamp_ns`.
    """
    out: list[int] = []
    for i, raw in enumerate(stamps):
        value = validate_stamp_ns(raw, name=f"{name}[{i}]")
        if out:
            prev = out[-1]
            if value == prev:
                raise ValueError(
                    f"{name}[{i}]={value} duplicates {name}[{i - 1}] — duplicate "
                    "stamps are upstream's problem (normalize via C2 first); deduping "
                    "here would silently merge two distinct observations"
                )
            if value < prev:
                raise ValueError(
                    f"{name}[{i}]={value} < {name}[{i - 1}]={prev} — out-of-order "
                    "input is rejected, never sorted silently; reordering here would "
                    "forge a timeline that never happened (normalize via C2 first)"
                )
        out.append(value)
    return out


def _miss(
    ref: int, method: AlignmentMethod, quality: AlignmentQuality
) -> AlignmentResult:
    """An explicit miss result — the flagged, never-hidden form of a missing match."""
    return AlignmentResult(
        ref_ns=ref,
        matched_ns=None,
        offset_ns=None,
        method=method,
        within_budget=False,
        quality=quality,
    )


def _match(
    ref: int, target: int, method: AlignmentMethod, *, tie: bool = False
) -> AlignmentResult:
    """A within-budget match result (offset re-derived here, verified at construction)."""
    return AlignmentResult(
        ref_ns=ref,
        matched_ns=target,
        offset_ns=target - ref,
        method=method,
        within_budget=True,
        quality=AlignmentQuality.MATCHED,
        tie=tie,
    )


def _align_one_nearest(
    ref: int, target: list[int], max_skew_ns: int, method: AlignmentMethod
) -> AlignmentResult:
    """NEAREST/EXACT association for one reference stamp (target is validated, sorted).

    The tie rule (DOCUMENTED, deterministic): when the nearest-before and nearest-after
    candidates are exactly equidistant, the EARLIER target wins and the result records
    ``tie=True`` — never iteration/dict order. For ``method=EXACT`` the effective skew
    budget is 0: only ``target == ref`` matches; a non-exact nearest is OUT_OF_BUDGET.
    """
    idx = bisect_left(target, ref)
    if idx < len(target) and target[idx] == ref:
        # Exact coincidence: recorded as EXACT even under a NEAREST search — a measured
        # fact (offset == 0), strictly stronger than "nearest", never a guess.
        return _match(ref, ref, AlignmentMethod.EXACT)
    if method is AlignmentMethod.EXACT:
        # A candidate exists but is not coincident: out of the zero-skew budget.
        return _miss(ref, method, AlignmentQuality.OUT_OF_BUDGET)
    before = target[idx - 1] if idx > 0 else None
    after = target[idx] if idx < len(target) else None
    tie = False
    if before is None:
        # mypy: at least one side exists (empty target is handled by the caller).
        assert after is not None
        candidate = after
    elif after is None:
        candidate = before
    elif ref - before < after - ref:
        candidate = before
    elif after - ref < ref - before:
        candidate = after
    else:
        # Equidistant: the documented deterministic rule — the EARLIER target wins.
        candidate = before
        tie = True
    if abs(candidate - ref) <= max_skew_ns:
        return _match(ref, candidate, AlignmentMethod.NEAREST, tie=tie)
    # Stale-reuse ban: the too-far candidate is NOT published (matched_ns stays None).
    return _miss(ref, method, AlignmentQuality.OUT_OF_BUDGET)


def align(
    reference: Sequence[int],
    target: Sequence[int],
    budget: AlignmentBudget,
    *,
    method: AlignmentMethod = AlignmentMethod.NEAREST,
) -> list[AlignmentResult]:
    """Align one target modality timeline onto a reference timeline — the C3 primitive.

    Failure mode: guessed/stale/out-of-budget matches => silently misaligned training
    data. Every reference stamp yields at least one :class:`AlignmentResult`; a miss is
    an explicit result (``NO_TARGET``/``OUT_OF_BUDGET`` with ``matched_ns=None``),
    never a hole and never a stale neighbor. Both timelines must already be
    strictly-increasing monotonic ns — dirty input is REJECTED loud (see
    :func:`_validate_timeline`), never sorted/deduped silently; normalize via C2 first.

    Parameters
    ----------
    reference:
        The QUERY timeline (e.g. the proprio tick lattice) — one result group per stamp.
    target:
        The modality timeline to associate (frame stamps, tactile event stamps).
    budget:
        The explicit acceptance band. NEAREST/EXACT use ``max_skew_ns``; WINDOW
        requires ``window_ns`` (loud error if absent — no guessed windows).
    method:
        The association strategy (recorded on every result). Under NEAREST, an
        offset-0 hit is recorded as EXACT (a measured fact, see
        :class:`AlignmentMethod`).

    Returns
    -------
    list[AlignmentResult]:
        In reference order. NEAREST/EXACT: exactly one result per reference stamp.
        WINDOW: one result per (reference, in-window target) pair — plus one explicit
        ``NO_TARGET`` result for a reference whose window is empty — so the list length
        is data-dependent but every reference appears at least once.

    Many-to-one is legitimate, not stale reuse.
        Several reference stamps MAY share the same nearest target (a 100 Hz proprio
        lattice against 25 Hz frames: up to four ticks share each frame). That is
        correct nearest-neighbor association — each tick's offset to that frame is
        real and within budget. The stale-reuse BAN is about distance, not sharing: a
        target farther than ``max_skew_ns`` is never published, so a consumer can
        never be handed a frame that is not actually near its tick.
    """
    if not isinstance(budget, AlignmentBudget):
        raise ValueError(
            f"budget must be an AlignmentBudget, got {type(budget).__name__} "
            f"{budget!r} — an implicit/unbounded budget is how stale matches happen"
        )
    if not isinstance(method, AlignmentMethod):
        raise ValueError(
            f"method must be an AlignmentMethod, got {type(method).__name__} "
            f"{method!r} — the method is recorded on every result, never guessed"
        )
    if method is AlignmentMethod.WINDOW and budget.window_ns is None:
        raise ValueError(
            "method=window requires budget.window_ns — refusing to guess a window "
            "from max_skew_ns (alignment error and window association are different "
            "questions with different bounds)"
        )
    ref_list = _validate_timeline(reference, name="reference")
    tgt_list = _validate_timeline(target, name="target")

    results: list[AlignmentResult] = []
    for ref in ref_list:
        if not tgt_list:
            # Missing modality: flagged per reference stamp, never hidden.
            results.append(_miss(ref, method, AlignmentQuality.NO_TARGET))
        elif method is AlignmentMethod.WINDOW:
            window_ns = budget.window_ns
            assert window_ns is not None
            lo = bisect_left(tgt_list, ref - window_ns)
            hi = bisect_right(tgt_list, ref + window_ns)
            if lo == hi:
                # Nothing inside the closed interval: the modality is absent HERE.
                results.append(_miss(ref, method, AlignmentQuality.NO_TARGET))
            else:
                # All in-window targets, in target order. The interval is CLOSED on
                # both ends (documented boundary rule): an event exactly at
                # ref +/- window_ns is in budget, and an event equidistant between two
                # references belongs to BOTH windows — deterministic set membership,
                # no arbitration to get wrong.
                results.extend(
                    _match(ref, t, AlignmentMethod.WINDOW) for t in tgt_list[lo:hi]
                )
        else:
            results.append(
                _align_one_nearest(ref, tgt_list, budget.max_skew_ns, method)
            )
    return results


def align_modalities(
    reference: Sequence[int],
    targets: Mapping[str, Sequence[int]],
    budget: AlignmentBudget,
    *,
    method: AlignmentMethod = AlignmentMethod.NEAREST,
) -> dict[str, list[AlignmentResult]]:
    """Align several named modality timelines against ONE reference — thin convenience.

    Failure mode: hand-rolled per-modality loops drift (different budgets/methods per
    call site with nothing recorded). This applies the SAME budget and method to every
    named target and returns per-modality result lists keyed by the caller's names.
    Modalities needing different methods (frames NEAREST, tactile WINDOW) call
    :func:`align` directly per modality — mixing methods implicitly here would make
    the recorded metadata depend on invisible defaults.
    """
    out: dict[str, list[AlignmentResult]] = {}
    for name, stamps in targets.items():
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"modality name must be a non-empty str, got {name!r} — an unnamed "
                "modality cannot be surfaced in quality metadata"
            )
        out[name] = align(reference, stamps, budget, method=method)
    return out


def timeline_from_records(
    records: Iterable[TimingRecord],
) -> tuple[tuple[int, ...], tuple[TimingRecord, ...]]:
    """Extract an alignable timeline from C2 records: clean stamps + surfaced rejects.

    Failure mode: feeding a FLAGGED record's original stamp into alignment would use a
    value C2 explicitly refused to place on the timeline (backwards clock, unknown
    skew) — silently un-flagging quarantined data. Clean records contribute their
    ``normalized_ns`` (in input order); flagged records are EXCLUDED from the timeline
    and returned alongside it, so the caller must see exactly what was left out (and
    can quarantine the episode) — they are never silently dropped OR silently used.

    Returns ``(clean_stamps, flagged_records)``. The clean stamps of one normalizer
    sequence are strictly increasing by C2's high-water rule, so they feed
    :func:`align` directly; :func:`align` re-validates at its own boundary regardless.
    """
    clean: list[int] = []
    flagged: list[TimingRecord] = []
    for i, record in enumerate(records):
        if not isinstance(record, TimingRecord):
            raise ValueError(
                f"records[{i}] must be a TimingRecord, got "
                f"{type(record).__name__} {record!r} — a bare value has no flags to "
                "honor (wrap raw stamps via timing.normalize.Normalizer)"
            )
        if record.normalized_ns is None:
            flagged.append(record)  # clean-xor-flagged: None iff flags non-empty (C2)
        else:
            clean.append(record.normalized_ns)
    return tuple(clean), tuple(flagged)


def _require_continuous_value(value: object, *, name: str) -> float:
    """Admit only continuous numeric channel values; loudly reject event-typed data.

    Failure mode: interpolating categorical data fabricates observations — the blend
    of two tactile tokens is a contact that never happened, and the "midpoint" of two
    frame ids is not a frame. Only real numbers (int/float, NOT bool) pass; strings
    (event tokens, frame ids) get the event-specific rejection so the API-level ban is
    explicit at the call site.
    """
    if isinstance(value, str):
        raise ValueError(
            f"{name} is a str ({value!r}) — event-typed data (tactile tokens, frame "
            "ids) is categorical and is NEVER interpolated: a blended event is a "
            "contact that never happened. Associate events with align(method=WINDOW) "
            "instead"
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a continuous numeric value (int/float), got "
            f"{type(value).__name__} {value!r} — only physically continuous channels "
            "(angle, velocity, current, torque) may be interpolated"
        )
    if not math.isfinite(value):
        raise ValueError(
            f"{name} must be finite, got {value!r} — a NaN/inf sensor value would "
            "propagate silently through interpolation and poison the synthesized sample"
        )
    return float(value)


def interpolate_proprio(
    t_ns: int,
    p0: tuple[int, float],
    p1: tuple[int, float],
) -> float:
    """Linear interpolation between two continuous proprio observations — numeric ONLY.

    Failure mode: extrapolation invents data outside anything observed, and
    interpolating events fabricates contacts (see :func:`_require_continuous_value`).
    This is a SEPARATE numeric utility, deliberately not a fourth alignment method:
    alignment associates observed stamps; this synthesizes an in-between VALUE, which
    is physically safe only for continuous channels between two real observations.

    ``p0``/``p1`` are ``(stamp_ns, value)`` with ``t0 < t1``; ``t_ns`` must satisfy
    ``t0 <= t_ns <= t1`` — anything outside REFUSES loudly (no extrapolation, ever).
    Endpoint queries return the endpoint value exactly (no float round-trip); the
    midpoint of ``(v0, v1)`` is exactly ``(v0 + v1) / 2``.
    """
    t0_ns, v0_raw = p0
    t1_ns, v1_raw = p1
    validate_stamp_ns(t0_ns, name="p0 stamp")
    validate_stamp_ns(t1_ns, name="p1 stamp")
    validate_stamp_ns(t_ns, name="t_ns")
    v0 = _require_continuous_value(v0_raw, name="p0 value")
    v1 = _require_continuous_value(v1_raw, name="p1 value")
    if t1_ns <= t0_ns:
        raise ValueError(
            f"p1 stamp ({t1_ns}) must be > p0 stamp ({t0_ns}) — a zero-length or "
            "backwards segment has no interior to interpolate over"
        )
    if not t0_ns <= t_ns <= t1_ns:
        raise ValueError(
            f"t_ns={t_ns} is outside [{t0_ns}, {t1_ns}] — refusing to extrapolate: a "
            "value outside the observed segment is invented data, not interpolation"
        )
    if t_ns == t0_ns:
        return v0
    if t_ns == t1_ns:
        return v1
    return v0 + (v1 - v0) * ((t_ns - t0_ns) / (t1_ns - t0_ns))
