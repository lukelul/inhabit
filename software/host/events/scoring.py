"""Precision/recall scoring for contact-event detection — the P-D gate's spine (P-D/D1).

A detector is only as trustworthy as the scorer that grades it, and a scorer is only useful
if it is **impossible to fool in either direction**: it must penalize a detector that MISSES
scripted events (low recall) AND a detector that HALLUCINATES events (low precision). This
module scores a detector's :class:`~events.interface.Event` list against the ground-truth
list minted by :mod:`events.labels`, with a matching rule that grants no double credit.

The matching rule (documented once, tested exhaustively)
--------------------------------------------------------
A detected event *matches* a truth event iff:

1. they share the same :class:`~events.interface.EventKind` (a right-time, wrong-kind
   detection is NOT a match — it is a false positive AND a false negative), and
2. their monotonic timestamps are within tolerance:
   ``abs(detected.t_monotonic_ns - truth.t_monotonic_ns) <= tolerance_ns``. The boundary is
   INCLUSIVE — a detection at exactly ``+tolerance_ns`` matches; at ``+tolerance_ns + 1`` it
   does not (a miss + a false positive).

Matching is **one-to-one, greedy-nearest**: among all in-tolerance same-kind
(truth, detection) candidate pairs we assign the closest pair first, then the next-closest
whose endpoints are both still free, and so on. Each truth is matched at most once and each
detection is consumed at most once — so two detections crowding one truth score 1 true
positive + 1 false positive, never 2 true positives. Ties break deterministically by
(distance, truth ts, truth index, detection ts, detection index) so the score is
reproducible. Because a match requires equal kinds, scoring partitions cleanly by kind: the
per-kind breakdowns are independent and sum exactly to the aggregate.

Division-by-zero conventions (chosen and documented — honesty over a silent ``nan``)
-----------------------------------------------------------------------------------
* **precision** ``= tp / (tp + fp)``; with **no detections** (``tp + fp == 0``) precision is
  ``1.0`` — a detector that claims nothing makes no false claim (vacuously precise). This is
  why precision alone cannot pass a silent detector: its recall is ``0``.
* **recall** ``= tp / (tp + fn)``; with **no truth** (``tp + fn == 0``) recall is ``1.0`` —
  there was nothing to find, so nothing was missed. This is why recall alone cannot pass a
  spammer on a free-space episode: its precision is ``0``.
* **f1** ``= 2·p·r / (p + r)``; when ``p + r == 0`` f1 is ``0.0``. An all-silent detector on
  a contact-bearing episode scores precision ``1.0``, recall ``0.0``, f1 ``0.0`` — caught.

Every :class:`DetectionScore` / :class:`KindScore` RE-DERIVES its ratios from its counts at
construction and refuses to exist if a caller-supplied ratio disagrees, so a score cannot
lie about itself (the C7 "a report cannot contradict its own provenance" philosophy). The
aggregate counts are likewise checked to equal the sum of the per-kind breakdown.

Stdlib-only, deterministic, no wall clock; reads FROZEN contracts (``Event``/``EventKind``)
and never mutates them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .interface import Event, EventKind

__all__ = [
    "DetectionScore",
    "KindScore",
    "score_events",
]


# ------------------------------------------------------------------------------------
# ratio conventions — one implementation, reused by construction and re-derivation
# ------------------------------------------------------------------------------------


def _precision(true_positives: int, false_positives: int) -> float:
    """``tp / (tp + fp)``; ``1.0`` when nothing was detected (no false claims made)."""
    denom = true_positives + false_positives
    return 1.0 if denom == 0 else true_positives / denom


def _recall(true_positives: int, false_negatives: int) -> float:
    """``tp / (tp + fn)``; ``1.0`` when there was no truth to find (nothing missed)."""
    denom = true_positives + false_negatives
    return 1.0 if denom == 0 else true_positives / denom


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean ``2pr/(p+r)``; ``0.0`` when ``p + r == 0`` (no signal either way)."""
    denom = precision + recall
    return 0.0 if denom == 0.0 else 2.0 * precision * recall / denom


def _require_count(value: object, name: str) -> int:
    """A non-negative int count; bool/float/negative rejected loud (never coerced)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int count, got {type(value).__name__} {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def _check_ratios(
    tp: int, fp: int, fn: int, precision: float, recall: float, f1: float, where: str
) -> None:
    """Fail loud unless the ratios are EXACTLY the ones derived from the counts.

    The counts are the ground truth of a score; the ratios are a computed convenience. Using
    the one ``_precision``/``_recall``/``_f1`` implementation for both the stored value and
    this re-derivation makes the comparison exact (same inputs, same formula), so a score
    that claims a ratio inconsistent with its counts cannot be constructed.
    """
    want_p = _precision(tp, fp)
    want_r = _recall(tp, fn)
    want_f1 = _f1(want_p, want_r)
    if precision != want_p:
        raise ValueError(f"{where}: precision {precision!r} != tp/(tp+fp) {want_p!r}")
    if recall != want_r:
        raise ValueError(f"{where}: recall {recall!r} != tp/(tp+fn) {want_r!r}")
    if f1 != want_f1:
        raise ValueError(f"{where}: f1 {f1!r} != 2pr/(p+r) {want_f1!r}")


# ------------------------------------------------------------------------------------
# the scores — values that cannot contradict their own counts
# ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KindScore:
    """Precision/recall for ONE :class:`EventKind` — a slice of the aggregate breakdown."""

    kind: EventKind
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            raise TypeError(f"kind must be an EventKind, got {type(self.kind).__name__}")
        tp = _require_count(self.true_positives, "true_positives")
        fp = _require_count(self.false_positives, "false_positives")
        fn = _require_count(self.false_negatives, "false_negatives")
        _check_ratios(
            tp, fp, fn, self.precision, self.recall, self.f1, f"KindScore[{self.kind.value}]"
        )

    @classmethod
    def from_counts(
        cls, kind: EventKind, true_positives: int, false_positives: int, false_negatives: int
    ) -> KindScore:
        """Build from raw counts, deriving the ratios by the documented conventions."""
        precision = _precision(true_positives, false_positives)
        recall = _recall(true_positives, false_negatives)
        return cls(
            kind=kind,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
        )

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form (kind as its stable token); ``from_dict`` round-trips it."""
        return {
            "kind": self.kind.value,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> KindScore:
        """Rebuild from :meth:`to_dict`, re-deriving ratios so a forged ratio cannot load."""
        kind_obj = d.get("kind")
        if not isinstance(kind_obj, str):
            raise ValueError(f"kind must be a token str, got {kind_obj!r}")
        try:
            kind = EventKind(kind_obj)
        except ValueError:
            raise ValueError(
                f"unknown EventKind token {kind_obj!r}; known: {[k.value for k in EventKind]}"
            ) from None
        score = cls.from_counts(
            kind,
            _require_count(d.get("true_positives"), "true_positives"),
            _require_count(d.get("false_positives"), "false_positives"),
            _require_count(d.get("false_negatives"), "false_negatives"),
        )
        # A stored ratio that disagrees with the counts is a forged artifact — reject it.
        for key, derived in (
            ("precision", score.precision),
            ("recall", score.recall),
            ("f1", score.f1),
        ):
            if key in d and d[key] != derived:
                raise ValueError(
                    f"KindScore[{kind.value}] stored {key}={d[key]!r} contradicts the "
                    f"counts (derived {derived!r})"
                )
        return score


@dataclass(frozen=True, slots=True)
class DetectionScore:
    """Aggregate precision/recall for a detection run, with a per-:class:`EventKind` breakdown.

    ``per_kind`` covers exactly the kinds present in truth OR detection, sorted by token, and
    its counts sum to the aggregate — construction refuses any other arrangement. Like
    :class:`KindScore` the aggregate ratios are re-derived from the aggregate counts, so the
    value cannot misreport itself.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    per_kind: tuple[KindScore, ...]

    def __post_init__(self) -> None:
        tp = _require_count(self.true_positives, "true_positives")
        fp = _require_count(self.false_positives, "false_positives")
        fn = _require_count(self.false_negatives, "false_negatives")
        if not isinstance(self.per_kind, tuple):
            raise TypeError(f"per_kind must be a tuple, got {type(self.per_kind).__name__}")
        prev: str | None = None
        for ks in self.per_kind:
            if not isinstance(ks, KindScore):
                raise TypeError(f"per_kind entries must be KindScore, got {ks!r}")
            token = ks.kind.value
            if prev is not None and token <= prev:
                raise ValueError(
                    f"per_kind must be strictly sorted by kind token; {token!r} follows "
                    f"{prev!r} (a duplicate or unordered breakdown cannot be diffed)"
                )
            prev = token
        # The aggregate is the sum of the breakdown — no orphaned or invented counts.
        for field, agg in (
            ("true_positives", tp),
            ("false_positives", fp),
            ("false_negatives", fn),
        ):
            summed = sum(getattr(ks, field) for ks in self.per_kind)
            if agg != summed:
                raise ValueError(
                    f"aggregate {field}={agg} != sum of per_kind {field}={summed} — the "
                    "breakdown must account for every event"
                )
        _check_ratios(tp, fp, fn, self.precision, self.recall, self.f1, "DetectionScore")

    @classmethod
    def from_counts(
        cls,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
        per_kind: tuple[KindScore, ...],
    ) -> DetectionScore:
        """Build from aggregate counts + breakdown, deriving the aggregate ratios."""
        precision = _precision(true_positives, false_positives)
        recall = _recall(true_positives, false_negatives)
        return cls(
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            precision=precision,
            recall=recall,
            f1=_f1(precision, recall),
            per_kind=per_kind,
        )

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form; ``from_dict(to_dict(s)) == s`` (a score is recordable too)."""
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "per_kind": [ks.to_dict() for ks in self.per_kind],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> DetectionScore:
        """Rebuild from :meth:`to_dict`; every invariant re-runs through construction."""
        per_kind_obj = d.get("per_kind")
        if not isinstance(per_kind_obj, list | tuple):
            raise ValueError(f"per_kind must be a list, got {type(per_kind_obj).__name__}")
        per_kind = tuple(
            KindScore.from_dict(entry)
            if isinstance(entry, Mapping)
            else _reject_entry(entry)
            for entry in per_kind_obj
        )
        score = cls.from_counts(
            _require_count(d.get("true_positives"), "true_positives"),
            _require_count(d.get("false_positives"), "false_positives"),
            _require_count(d.get("false_negatives"), "false_negatives"),
            per_kind,
        )
        for key, derived in (
            ("precision", score.precision),
            ("recall", score.recall),
            ("f1", score.f1),
        ):
            if key in d and d[key] != derived:
                raise ValueError(
                    f"DetectionScore stored {key}={d[key]!r} contradicts the counts "
                    f"(derived {derived!r})"
                )
        return score


def _reject_entry(entry: object) -> KindScore:
    """A per_kind entry must be a mapping; anything else is a malformed artifact."""
    raise ValueError(f"per_kind entry must be a mapping, got {type(entry).__name__} {entry!r}")


# ------------------------------------------------------------------------------------
# the matcher — greedy-nearest, one-to-one, within a single kind
# ------------------------------------------------------------------------------------


def _match_one_kind(
    truth: Sequence[Event], detected: Sequence[Event], tolerance_ns: int
) -> tuple[int, int, int]:
    """``(true_positives, false_positives, false_negatives)`` for ONE kind's events.

    Greedy-nearest one-to-one: enumerate every in-tolerance (truth, detection) pair, assign
    the closest first (deterministic tie-break), and never reuse an already-matched endpoint.
    ``fp`` = detections left unmatched, ``fn`` = truths left unmatched. Inputs are already
    filtered to a single kind, so distance alone decides a match.
    """
    pairs: list[tuple[int, int, int, int, int]] = []
    for ti, t in enumerate(truth):
        for di, d in enumerate(detected):
            distance = abs(d.t_monotonic_ns - t.t_monotonic_ns)
            if distance <= tolerance_ns:
                pairs.append((distance, t.t_monotonic_ns, ti, d.t_monotonic_ns, di))
    pairs.sort()

    matched_truth: set[int] = set()
    matched_det: set[int] = set()
    for _distance, _t_ts, ti, _d_ts, di in pairs:
        if ti in matched_truth or di in matched_det:
            continue
        matched_truth.add(ti)
        matched_det.add(di)

    true_positives = len(matched_truth)
    return true_positives, len(detected) - true_positives, len(truth) - true_positives


def _validate_events(events: Sequence[Event], name: str) -> None:
    """Reject a non-Event in the input rather than mis-scoring a poisoned list silently."""
    if isinstance(events, str) or not isinstance(events, Sequence):
        raise TypeError(f"{name} must be a sequence of Event, got {type(events).__name__}")
    for i, event in enumerate(events):
        if not isinstance(event, Event):
            raise TypeError(
                f"{name}[{i}] must be an Event, got {type(event).__name__} {event!r}"
            )


def score_events(
    truth: Sequence[Event], detected: Sequence[Event], *, tolerance_ns: int
) -> DetectionScore:
    """Score ``detected`` against ground-truth ``truth`` within ``tolerance_ns``.

    Returns a :class:`DetectionScore` whose precision penalizes false positives and whose
    recall penalizes misses, per the module's documented one-to-one greedy-nearest matching
    rule and division-by-zero conventions. ``tolerance_ns`` is a non-negative int of
    monotonic nanoseconds (``0`` demands an exact-timestamp match); a negative or non-int
    tolerance fails loud. Scoring partitions by :class:`EventKind`, so the per-kind breakdown
    is exact and sums to the aggregate.
    """
    _validate_events(truth, "truth")
    _validate_events(detected, "detected")
    if isinstance(tolerance_ns, bool) or not isinstance(tolerance_ns, int):
        raise TypeError(f"tolerance_ns must be an int, got {type(tolerance_ns).__name__}")
    if tolerance_ns < 0:
        raise ValueError(f"tolerance_ns must be >= 0, got {tolerance_ns}")

    kinds = sorted(
        {e.kind for e in truth} | {e.kind for e in detected}, key=lambda k: k.value
    )
    per_kind: list[KindScore] = []
    for kind in kinds:
        truth_k = [e for e in truth if e.kind == kind]
        detected_k = [e for e in detected if e.kind == kind]
        tp, fp, fn = _match_one_kind(truth_k, detected_k, tolerance_ns)
        per_kind.append(KindScore.from_counts(kind, tp, fp, fn))

    return DetectionScore.from_counts(
        sum(ks.true_positives for ks in per_kind),
        sum(ks.false_positives for ks in per_kind),
        sum(ks.false_negatives for ks in per_kind),
        tuple(per_kind),
    )
