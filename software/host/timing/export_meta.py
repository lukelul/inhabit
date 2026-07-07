"""Exported timing metadata — the auditable sync summary that travels with a dataset (C5).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **Un-auditable exports => sync rot nobody can detect.** A dataset whose alignment was
  in budget at export time is worthless as evidence if the artifact carries no timing
  metadata: nobody can later verify which clock each modality used, how many stamps were
  flagged, or whether alignment stayed in budget. :class:`TimingMeta` is the canonical,
  versioned summary — per-modality clock domains, normalization counts + flag-token
  histogram, alignment method/quality histograms, published-offset stats, the
  :class:`~timing.align.AlignmentBudget` used, and a :class:`SyncVerdict` — written into
  the exporters' existing metadata channels so synchronization can be AUDITED from the
  exported dataset alone.
* **Fabricated quality => a dataset that lies about itself.** Every field is either
  computed from real C2 records / C3 results (:meth:`TimingMeta.from_run`) or absent —
  no default ever invents quality. Construction enforces cross-field consistency
  (offset stats require matches, published offsets must fit the recorded budget, the
  verdict must equal what the counts say), so a contradictory summary cannot exist as a
  value — and :meth:`TimingMeta.from_dict` rebuilds through construction, so a forged
  file cannot load either.
* **Guessed tokens / silent drift => unverifiable provenance.** Unknown dict keys,
  unknown enum tokens and unknown versions are REFUSED loud — never skipped, never
  defaulted. A token this reader does not know is a schema change that needs a
  ``TIMING_META_VERSION`` bump and a migration, not a guess (the C2/C3 ``from_dict``
  philosophy, applied to the whole summary).
* **Legacy datasets breaking => back-compat regression.** :func:`read_timing_sidecar`
  returns ``None`` when the sidecar file does not exist — a dataset written before C5
  is legitimate legacy, not an error. A PRESENT but garbled/foreign sidecar raises:
  unreadable provenance is corruption, never silently treated as legacy.

Scope (PONYTAIL): ONE canonical dict shape + write/read sidecar helpers; the exporter
wiring lives in ``export.lerobot`` / ``export.parquet`` (their existing metadata
channels), and C1/C2/C3 are imported, never edited. Stdlib only, no numpy (the P-C
invariant). FROZEN contracts untouched: NO new ``PVTSample`` columns — timing metadata
is dataset-level sidecar ONLY.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from timing.align import (
    AlignmentBudget,
    AlignmentMethod,
    AlignmentQuality,
    AlignmentResult,
)
from timing.normalize import NormalizationFlag, TimingRecord
from timing.stamp import MAX_STAMP_NS, ClockDomain

__all__ = [
    "TIMING_META_VERSION",
    "ModalityTiming",
    "SyncVerdict",
    "TimingMeta",
    "read_timing_sidecar",
    "select_episode_timing",
    "write_selected_timing_sidecar",
    "write_timing_sidecar",
]

# Version of THIS metadata shape (the TimingMeta dict + the sidecar document), distinct
# from the frozen PVT_SCHEMA_VERSION, the exporter layout versions, and EXPORTER_ABC_VERSION.
# Bump with a load-time migration; a reader NEVER guesses at an unknown version.
TIMING_META_VERSION = 1

_TokenEnumT = TypeVar("_TokenEnumT", bound=StrEnum)


class SyncVerdict(StrEnum):
    """The one-token sync-quality verdict for an exported episode — derived, never asserted.

    Failure mode: a hand-assigned "quality: good" label is exactly the fabrication this
    module bans. The verdict is DERIVED from the counts (see :meth:`TimingMeta.from_run`)
    and construction re-derives it, so a :class:`TimingMeta` whose verdict contradicts its
    own counts cannot exist. A :class:`~enum.StrEnum` like ``ClockDomain`` /
    ``NormalizationFlag`` / ``AlignmentQuality``: the token values are
    serialization-stable contract.

    Members (the derivation rule — documented once, enforced everywhere)
    -------
    ALIGNED_WITHIN_BUDGET:
        Every normalization record is clean AND every alignment result is
        :data:`~timing.align.AlignmentQuality.MATCHED` — the whole episode's cross-modal
        timing is in budget and re-derivable.
    DEGRADED:
        Usable with recorded defects: at least one flagged record (C2) or one
        non-MATCHED alignment result (C3 ``out_of_budget`` / ``no_target``), but NO
        modality is unusable (see QUARANTINED). Consumers can train on the matched
        associations while the defects stay visible in the histograms.
    QUARANTINED:
        At least one modality is UNUSABLE: its entire timeline was flagged
        (``clean_count == 0`` — no stamps survived normalization) or alignment was
        attempted and NOTHING matched (``result_count > 0 and matched_count == 0``).
        The episode needs human or pipeline triage before training on cross-modal
        associations — the same quarantine-not-repair stance the recorder takes.
    """

    ALIGNED_WITHIN_BUDGET = "aligned_within_budget"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


def _validate_count(value: object, *, name: str) -> int:
    """Validate a non-negative int count; return it or raise ``ValueError``.

    Failure mode: a bool/float/negative count would forge a summary (``True`` -> 1) or
    claim negative observations. Same rejection classes as C1's stamp validator,
    count-shaped range (``0`` is legal: honestly counted absence).
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be an int count, got bool {value!r} — a bool would silently "
            "coerce to 0/1 and forge a count out of a flag"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int count, got {type(value).__name__} {value!r} — "
            "non-int counts cannot be exact"
        )
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value} — negative observations do not exist")
    return value


def _validate_offset_ns(value: object, *, name: str) -> int:
    """Validate a signed int-ns alignment offset; return it or raise ``ValueError``.

    Failure mode: offsets are signed (target minus reference), so the stamp validator is
    the wrong gate — but a bool/float/past-int64 offset would still forge or truncate
    nanoseconds. Mirrors C2's skew validation without reaching into its private helpers.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be an int nanosecond offset, got bool {value!r} — a bool "
            "would silently coerce to 0/1 and forge an offset out of a flag"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int nanosecond offset, got {type(value).__name__} "
            f"{value!r} — non-int offsets lose nanosecond exactness"
        )
    if not -MAX_STAMP_NS <= value <= MAX_STAMP_NS:
        raise ValueError(
            f"{name} must be within ±(2**63-1), got {value} — an offset past int64 "
            "cannot round-trip through on-disk metadata without truncation"
        )
    return value


def _member_from_token(
    token: object, enum_cls: type[_TokenEnumT], *, name: str
) -> _TokenEnumT:
    """Parse one serialization-stable enum token; unknown tokens are REFUSED, never guessed."""
    if not isinstance(token, str):
        raise ValueError(
            f"{name} must be a str token, got {type(token).__name__} {token!r}"
        )
    try:
        return enum_cls(token)
    except ValueError:
        raise ValueError(
            f"unknown {name} token {token!r}; known tokens: "
            f"{[m.value for m in enum_cls]} — refusing to guess (an unknown token is a "
            "schema change that needs a TIMING_META_VERSION bump, not a default)"
        ) from None


def _validate_histogram(
    pairs: object, enum_cls: type[_TokenEnumT], *, name: str
) -> tuple[tuple[_TokenEnumT, int], ...]:
    """Validate a canonical ``((member, count>0), ...)`` histogram, sorted by token.

    Failure mode: an unsorted or duplicated histogram makes ``to_dict`` output depend on
    construction order — two exports of the same run would diff. Zero-count entries are
    banned (they are noise claiming an observation class that was never observed).
    """
    if not isinstance(pairs, tuple):
        raise ValueError(
            f"{name} must be a tuple of (token, count) pairs, got "
            f"{type(pairs).__name__} — a mutable histogram could be edited after the "
            "summary is built"
        )
    prev_token: str | None = None
    for i, pair in enumerate(pairs):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError(f"{name}[{i}] must be a (token, count) pair, got {pair!r}")
        member, count = pair
        if not isinstance(member, enum_cls):
            raise ValueError(
                f"{name}[{i}] token must be a {enum_cls.__name__}, got "
                f"{type(member).__name__} {member!r} — a foreign token cannot be "
                "serialized stably or audited"
            )
        _validate_count(count, name=f"{name}[{i}] count")
        if count == 0:
            raise ValueError(
                f"{name}[{i}] has count 0 for {member.value!r} — a zero-count entry "
                "claims an observation class that was never observed; omit it"
            )
        if prev_token is not None and member.value <= prev_token:
            raise ValueError(
                f"{name} must be strictly sorted by token with no duplicates, got "
                f"{member.value!r} after {prev_token!r} — an order-dependent histogram "
                "cannot be reproduced or diffed"
            )
        prev_token = member.value
    return pairs  # type: ignore[return-value]  # runtime-validated element types above


def _histogram_total(pairs: tuple[tuple[_TokenEnumT, int], ...]) -> int:
    return sum(count for _, count in pairs)


def _histogram_count(
    pairs: tuple[tuple[_TokenEnumT, int], ...], member: _TokenEnumT
) -> int:
    for m, count in pairs:
        if m is member:
            return count
    return 0


def _histogram_from_counter(
    counter: Counter[_TokenEnumT],
) -> tuple[tuple[_TokenEnumT, int], ...]:
    """Canonical (sorted-by-token) histogram from a Counter — the from_run builder."""
    return tuple(sorted(counter.items(), key=lambda pair: pair[0].value))


def _histogram_from_dict(
    obj: object, enum_cls: type[_TokenEnumT], *, name: str
) -> tuple[tuple[_TokenEnumT, int], ...]:
    """Parse a ``{token: count}`` dict back into the canonical histogram (loud on junk)."""
    if not isinstance(obj, Mapping):
        raise ValueError(
            f"{name} must be a mapping of token -> count, got {type(obj).__name__} {obj!r}"
        )
    counter: Counter[_TokenEnumT] = Counter()
    for token, count in obj.items():
        member = _member_from_token(token, enum_cls, name=name)
        if member in counter:
            raise ValueError(f"{name} repeats token {member.value!r} — duplicated provenance")
        counter[member] = _validate_count(count, name=f"{name}[{member.value!r}]")
    return _histogram_from_counter(counter)


_MODALITY_KEYS = frozenset({
    "clock_domain",
    "clean_count",
    "flagged_count",
    "flag_counts",
    "method_counts",
    "quality_counts",
    "offset_min_ns",
    "offset_max_ns",
    "offset_mean_ns",
})


@dataclass(frozen=True, slots=True)
class ModalityTiming:
    """The per-modality timing summary — every number re-derivable from C2/C3 output.

    Failure mode: a per-modality "quality" blob assembled by hand can claim clean
    normalization for a stream full of flagged stamps, or in-budget offsets that were
    never published. Construction enforces the cross-field invariants below, so a
    summary that EXISTS is internally honest; :meth:`TimingMeta.from_run` is the only
    sanctioned producer (it counts real records/results).

    Invariants (enforced in ``__post_init__``):

    * at least one record was summarized (``clean_count + flagged_count >= 1``) — an
      empty modality has no domain and no story; omit it instead.
    * ``flagged_count == 0`` iff ``flag_counts`` is empty; when flagged, the histogram
      total is ``>= flagged_count`` (every flagged record carries >= 1 reason token) and
      each per-token count is ``<= flagged_count`` (C2 bans duplicate flags per record).
    * ``method_counts`` and ``quality_counts`` have EQUAL totals — every C3 result
      records exactly one method and one quality verdict.
    * WINDOW is exclusive: C3 emits WINDOW for every result of a window alignment
      (matches AND misses), so a histogram mixing WINDOW with another method — or a
      WINDOW ``out_of_budget`` count (a contradictory state per C3) — is forged.
    * offset stats exist iff at least one result MATCHED (published offsets are matched
      offsets, nothing else); ``min <= mean <= max``; an all-EXACT modality has all-zero
      offset stats (that is what "exact" means).
    """

    clock_domain: ClockDomain
    clean_count: int
    flagged_count: int
    flag_counts: tuple[tuple[NormalizationFlag, int], ...] = ()
    method_counts: tuple[tuple[AlignmentMethod, int], ...] = ()
    quality_counts: tuple[tuple[AlignmentQuality, int], ...] = ()
    offset_min_ns: int | None = None
    offset_max_ns: int | None = None
    offset_mean_ns: float | None = None

    def __post_init__(self) -> None:
        # Fail loud at construction (never at export/audit time): a summary that exists
        # is internally consistent. Each check names the fabrication it prevents.
        if not isinstance(self.clock_domain, ClockDomain):
            raise ValueError(
                f"clock_domain must be a ClockDomain, got "
                f"{type(self.clock_domain).__name__} {self.clock_domain!r} — an "
                "unlabeled domain cannot be audited against the one-monotonic-timeline rule"
            )
        _validate_count(self.clean_count, name="clean_count")
        _validate_count(self.flagged_count, name="flagged_count")
        if self.clean_count + self.flagged_count == 0:
            raise ValueError(
                "clean_count + flagged_count == 0 — a modality with no records cannot "
                "be summarized; omit it rather than fabricating an empty entry"
            )
        _validate_histogram(self.flag_counts, NormalizationFlag, name="flag_counts")
        _validate_histogram(self.method_counts, AlignmentMethod, name="method_counts")
        _validate_histogram(self.quality_counts, AlignmentQuality, name="quality_counts")
        if (self.flagged_count == 0) != (not self.flag_counts):
            raise ValueError(
                f"flagged_count={self.flagged_count} with flag_counts="
                f"{[(m.value, c) for m, c in self.flag_counts]!r} — flagged records and "
                "reason tokens exist together or not at all; anything else un-flags or "
                "invents quarantined data"
            )
        if self.flag_counts:
            total_flags = _histogram_total(self.flag_counts)
            if total_flags < self.flagged_count:
                raise ValueError(
                    f"flag_counts total {total_flags} < flagged_count "
                    f"{self.flagged_count} — every flagged record carries at least one "
                    "reason token (C2); a smaller histogram hides flags"
                )
            for member, count in self.flag_counts:
                if count > self.flagged_count:
                    raise ValueError(
                        f"flag_counts[{member.value!r}]={count} > flagged_count="
                        f"{self.flagged_count} — a record carries each reason token at "
                        "most once (C2), so this histogram counts records that never existed"
                    )
        if _histogram_total(self.method_counts) != _histogram_total(self.quality_counts):
            raise ValueError(
                f"method_counts total {_histogram_total(self.method_counts)} != "
                f"quality_counts total {_histogram_total(self.quality_counts)} — every "
                "alignment result records exactly one method and one quality verdict"
            )
        window = _histogram_count(self.method_counts, AlignmentMethod.WINDOW)
        if window and len(self.method_counts) > 1:
            raise ValueError(
                "method_counts mixes WINDOW with another method — C3 records WINDOW on "
                "every result of a window alignment (matches and misses), so a mixed "
                "histogram summarizes results that never existed together"
            )
        out_of_budget = _histogram_count(self.quality_counts, AlignmentQuality.OUT_OF_BUDGET)
        if window and out_of_budget:
            raise ValueError(
                "WINDOW method with an out_of_budget quality count — a window miss is "
                "no_target by C3's contract; out-of-budget WINDOW results cannot exist"
            )
        matched = _histogram_count(self.quality_counts, AlignmentQuality.MATCHED)
        offsets = (self.offset_min_ns, self.offset_max_ns, self.offset_mean_ns)
        if matched == 0:
            if any(v is not None for v in offsets):
                raise ValueError(
                    f"offset stats {offsets!r} with zero matched results — published "
                    "offsets are matched offsets; stats over nothing are fabricated"
                )
            return
        if any(v is None for v in offsets):
            raise ValueError(
                f"matched={matched} but offset stats are incomplete {offsets!r} — every "
                "match publishes a signed offset, so min/max/mean must all be recorded"
            )
        assert self.offset_min_ns is not None  # for the type-checker; guarded above
        assert self.offset_max_ns is not None
        assert self.offset_mean_ns is not None
        _validate_offset_ns(self.offset_min_ns, name="offset_min_ns")
        _validate_offset_ns(self.offset_max_ns, name="offset_max_ns")
        if isinstance(self.offset_mean_ns, bool) or not isinstance(self.offset_mean_ns, float):
            raise ValueError(
                f"offset_mean_ns must be a float, got {type(self.offset_mean_ns).__name__} "
                f"{self.offset_mean_ns!r} — from_run computes sum/len (always a float); "
                "anything else was not computed by this module"
            )
        if not math.isfinite(self.offset_mean_ns):
            raise ValueError(
                f"offset_mean_ns must be finite, got {self.offset_mean_ns!r} — a NaN/inf "
                "mean cannot come from bounded published offsets"
            )
        if self.offset_min_ns > self.offset_max_ns:
            raise ValueError(
                f"offset_min_ns={self.offset_min_ns} > offset_max_ns={self.offset_max_ns}"
                " — an inverted range summarizes offsets that never existed"
            )
        if not self.offset_min_ns <= self.offset_mean_ns <= self.offset_max_ns:
            raise ValueError(
                f"offset_mean_ns={self.offset_mean_ns} outside "
                f"[{self.offset_min_ns}, {self.offset_max_ns}] — a mean outside its own "
                "min/max is arithmetic fiction"
            )
        only_exact = (
            len(self.method_counts) == 1
            and self.method_counts[0][0] is AlignmentMethod.EXACT
        )
        if only_exact and (self.offset_min_ns != 0 or self.offset_max_ns != 0):
            raise ValueError(
                f"all-EXACT modality with nonzero offset stats "
                f"[{self.offset_min_ns}, {self.offset_max_ns}] — exact means offset 0; "
                "a nonzero offset labeled exact is a lie (C3's AlignmentResult contract)"
            )

    def matched_count(self) -> int:
        """Results that MATCHED within budget (re-derived from the histogram, never stored)."""
        return _histogram_count(self.quality_counts, AlignmentQuality.MATCHED)

    def result_count(self) -> int:
        """Total alignment results summarized for this modality."""
        return _histogram_total(self.quality_counts)

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form (stdlib-json-safe, deterministic key/token order)."""
        return {
            "clock_domain": self.clock_domain.value,
            "clean_count": self.clean_count,
            "flagged_count": self.flagged_count,
            "flag_counts": {m.value: c for m, c in self.flag_counts},
            "method_counts": {m.value: c for m, c in self.method_counts},
            "quality_counts": {m.value: c for m, c in self.quality_counts},
            "offset_min_ns": self.offset_min_ns,
            "offset_max_ns": self.offset_max_ns,
            "offset_mean_ns": self.offset_mean_ns,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> ModalityTiming:
        """Rebuild from :meth:`to_dict` output; unknown keys/tokens are refused loud."""
        missing = _MODALITY_KEYS - set(d)
        if missing:
            raise ValueError(f"modality-timing dict missing keys {sorted(missing)}: {dict(d)!r}")
        unknown = set(d) - _MODALITY_KEYS
        if unknown:
            raise ValueError(
                f"modality-timing dict has unknown keys {sorted(unknown)} — refusing to "
                "guess at foreign fields (a new field needs a TIMING_META_VERSION bump)"
            )
        min_obj, max_obj, mean_obj = (
            d["offset_min_ns"], d["offset_max_ns"], d["offset_mean_ns"],
        )
        mean_val: float | None
        if mean_obj is None:
            mean_val = None
        elif isinstance(mean_obj, bool) or not isinstance(mean_obj, float):
            raise ValueError(
                f"offset_mean_ns must be a float or null, got "
                f"{type(mean_obj).__name__} {mean_obj!r} — from_run computes sum/len "
                "(always a float); anything else was not written by this module"
            )
        else:
            mean_val = mean_obj
        return cls(
            clock_domain=_member_from_token(d["clock_domain"], ClockDomain, name="clock_domain"),
            clean_count=_validate_count(d["clean_count"], name="clean_count"),
            flagged_count=_validate_count(d["flagged_count"], name="flagged_count"),
            flag_counts=_histogram_from_dict(
                d["flag_counts"], NormalizationFlag, name="flag_counts"
            ),
            method_counts=_histogram_from_dict(
                d["method_counts"], AlignmentMethod, name="method_counts"
            ),
            quality_counts=_histogram_from_dict(
                d["quality_counts"], AlignmentQuality, name="quality_counts"
            ),
            offset_min_ns=(
                None if min_obj is None else _validate_offset_ns(min_obj, name="offset_min_ns")
            ),
            offset_max_ns=(
                None if max_obj is None else _validate_offset_ns(max_obj, name="offset_max_ns")
            ),
            offset_mean_ns=mean_val,
        )


_META_KEYS = frozenset({"timing_meta_version", "budget", "verdict", "modalities"})
_BUDGET_KEYS = frozenset({"max_skew_ns", "window_ns"})


def _derive_verdict(
    modalities: tuple[tuple[str, ModalityTiming], ...],
) -> SyncVerdict:
    """The ONE three-state rule (documented on :class:`SyncVerdict`), shared by
    ``from_run`` and construction re-derivation so they can never drift apart.

    QUARANTINED: any modality unusable — its whole timeline flagged (``clean_count == 0``)
    or alignment attempted with nothing matched. DEGRADED: usable but defective — any
    flagged record or any non-MATCHED result. ALIGNED_WITHIN_BUDGET: neither.
    """
    degraded = False
    for _, mod in modalities:
        if mod.clean_count == 0:
            return SyncVerdict.QUARANTINED
        if mod.result_count() > 0 and mod.matched_count() == 0:
            return SyncVerdict.QUARANTINED
        if mod.flagged_count > 0 or mod.result_count() != mod.matched_count():
            degraded = True
    return SyncVerdict.DEGRADED if degraded else SyncVerdict.ALIGNED_WITHIN_BUDGET


@dataclass(frozen=True, slots=True)
class TimingMeta:
    """The canonical timing metadata for ONE exported episode — audit-grade, never guessed.

    Failure mode: an exported dataset with no timing story cannot be audited; one with a
    hand-written story is worse (it lies with confidence). ``TimingMeta`` is built from
    real C2 records and C3 results (:meth:`from_run`) and validated at construction:

    * ``modalities`` is a sorted, uniquely-named tuple of per-modality summaries;
    * every modality that used WINDOW requires ``budget.window_ns`` (a window alignment
      without a window budget cannot have happened — C3 refuses it);
    * every published offset range fits the recorded budget (C3 never publishes an
      out-of-budget offset, so a wider range is forged);
    * ``verdict`` must equal what the counts derive (see :func:`derive_verdict` logic in
      :meth:`from_run`) — a contradictory verdict raises.

    Serialization is exact: ``from_dict(to_dict(m)) == m``, with unknown keys, tokens
    and versions refused loud. ``TIMING_META_VERSION`` stamps every dict.
    """

    modalities: tuple[tuple[str, ModalityTiming], ...]
    budget: AlignmentBudget
    verdict: SyncVerdict

    def __post_init__(self) -> None:
        if not isinstance(self.modalities, tuple):
            raise ValueError(
                f"modalities must be a tuple of (name, ModalityTiming) pairs, got "
                f"{type(self.modalities).__name__}"
            )
        if not self.modalities:
            raise ValueError(
                "modalities is empty — a timing summary over no modalities audits "
                "nothing; refusing to fabricate one"
            )
        prev_name: str | None = None
        for i, pair in enumerate(self.modalities):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError(
                    f"modalities[{i}] must be a (name, ModalityTiming) pair, got {pair!r}"
                )
            name, mod = pair
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"modalities[{i}] name must be a non-empty str, got {name!r} — an "
                    "unnamed modality cannot be audited"
                )
            if not isinstance(mod, ModalityTiming):
                raise ValueError(
                    f"modalities[{i}] value must be a ModalityTiming, got "
                    f"{type(mod).__name__} {mod!r}"
                )
            if prev_name is not None and name <= prev_name:
                raise ValueError(
                    f"modalities must be strictly sorted by name with no duplicates, "
                    f"got {name!r} after {prev_name!r} — order-dependent metadata "
                    "cannot be diffed or reproduced"
                )
            prev_name = name
        if not isinstance(self.budget, AlignmentBudget):
            raise ValueError(
                f"budget must be an AlignmentBudget, got {type(self.budget).__name__} "
                f"{self.budget!r} — a summary without its acceptance band cannot be audited"
            )
        if not isinstance(self.verdict, SyncVerdict):
            raise ValueError(
                f"verdict must be a SyncVerdict, got {type(self.verdict).__name__} "
                f"{self.verdict!r} — a foreign verdict token cannot be filtered on"
            )
        for name, mod in self.modalities:
            window = _histogram_count(mod.method_counts, AlignmentMethod.WINDOW) > 0
            if window and self.budget.window_ns is None:
                raise ValueError(
                    f"modality {name!r} records WINDOW results but budget.window_ns is "
                    "None — C3 refuses window alignment without a window budget, so "
                    "these results cannot have been produced under this budget"
                )
            if mod.offset_min_ns is None or mod.offset_max_ns is None:
                continue
            bound = self.budget.window_ns if window else self.budget.max_skew_ns
            assert bound is not None  # window=True implies window_ns present (above)
            if abs(mod.offset_min_ns) > bound or abs(mod.offset_max_ns) > bound:
                raise ValueError(
                    f"modality {name!r} offset range [{mod.offset_min_ns}, "
                    f"{mod.offset_max_ns}] exceeds the recorded budget bound {bound} — "
                    "C3 never publishes an out-of-budget offset, so this summary is forged"
                )
        derived = self._derive_verdict()
        if self.verdict is not derived:
            raise ValueError(
                f"verdict={self.verdict.value!r} contradicts the counts (derived "
                f"{derived.value!r}) — the verdict is computed, never asserted; a "
                "summary that flatters its own data is fabrication"
            )

    def _derive_verdict(self) -> SyncVerdict:
        """Apply the documented three-state rule (see :class:`SyncVerdict`) to the counts."""
        return _derive_verdict(self.modalities)

    # -- derived indicators (recomputed, never stored — they cannot desync) ---------------

    @property
    def flagged_record_count(self) -> int:
        """Records C2 flagged instead of repairing — dropped/reordered/skew indicators."""
        return sum(mod.flagged_count for _, mod in self.modalities)

    @property
    def out_of_budget_count(self) -> int:
        """Results whose nearest candidate existed but was too skewed to publish."""
        return sum(
            _histogram_count(mod.quality_counts, AlignmentQuality.OUT_OF_BUDGET)
            for _, mod in self.modalities
        )

    @property
    def missing_target_count(self) -> int:
        """Results with no candidate at all — the missing/dropped-modality indicator."""
        return sum(
            _histogram_count(mod.quality_counts, AlignmentQuality.NO_TARGET)
            for _, mod in self.modalities
        )

    @property
    def matched_count(self) -> int:
        """Results matched within budget, across all modalities."""
        return sum(mod.matched_count() for _, mod in self.modalities)

    # -- construction from a real run ------------------------------------------------------

    @classmethod
    def from_run(
        cls,
        records_by_modality: Mapping[str, Sequence[TimingRecord]],
        results_by_modality: Mapping[str, Sequence[AlignmentResult]],
        budget: AlignmentBudget,
        *,
        reference: str | None = None,
    ) -> TimingMeta:
        """Summarize one episode's REAL normalization + alignment output — the only builder.

        Every count is tallied from the ``TimingRecord`` / ``AlignmentResult`` values
        passed in; nothing is defaulted or estimated. Loud rejections:

        * results for a modality with no records — alignment output without
          normalization provenance cannot be audited;
        * a modality with records but NO alignment results, unless it is the explicit
          ``reference`` — a target modality whose C3 output is simply absent would
          otherwise summarize as clean, silently hiding an unaligned modality;
        * a modality with zero records — omit it, an empty summary entry is fabrication;
        * mixed clock domains inside one modality — refusing to pick one;
        * any non-``TimingRecord`` / non-``AlignmentResult`` element — bare values have
          no provenance to count.

        ``reference`` names the alignment REFERENCE timeline (the one other modalities
        are aligned against — it is not aligned against itself, so it alone may carry
        records without results). It must be one of ``records_by_modality``'s keys.
        Single-modality runs where that modality has results need no reference.
        """
        if not isinstance(budget, AlignmentBudget):
            raise ValueError(
                f"budget must be an AlignmentBudget, got {type(budget).__name__} "
                f"{budget!r} — a summary without its acceptance band cannot be audited"
            )
        if not records_by_modality:
            raise ValueError(
                "records_by_modality is empty — a run with no modalities cannot be "
                "summarized"
            )
        orphans = sorted(set(results_by_modality) - set(records_by_modality))
        if orphans:
            raise ValueError(
                f"alignment results for modalities with no records: {orphans} — "
                "results without normalization provenance cannot be audited"
            )
        if reference is not None and reference not in records_by_modality:
            raise ValueError(
                f"reference {reference!r} is not a records_by_modality key "
                f"({sorted(records_by_modality)}) — the reference timeline must be part "
                "of the summarized run"
            )
        entries: list[tuple[str, ModalityTiming]] = []
        for name in records_by_modality:
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"modality name must be a non-empty str, got {name!r} — an unnamed "
                    "modality cannot be audited"
                )
            records = records_by_modality[name]
            if not records:
                raise ValueError(
                    f"modality {name!r} has no records — omit it; an empty entry has "
                    "no domain and fabricates presence"
                )
            domains: set[ClockDomain] = set()
            clean = 0
            flagged = 0
            flag_counter: Counter[NormalizationFlag] = Counter()
            for i, record in enumerate(records):
                if not isinstance(record, TimingRecord):
                    raise ValueError(
                        f"records_by_modality[{name!r}][{i}] must be a TimingRecord, "
                        f"got {type(record).__name__} {record!r} — a bare value has no "
                        "flags or domain to count"
                    )
                domains.add(record.original.domain)
                if record.normalized_ns is None:
                    flagged += 1
                    flag_counter.update(record.flags)
                else:
                    clean += 1
            if len(domains) > 1:
                raise ValueError(
                    f"modality {name!r} mixes clock domains "
                    f"{sorted(d.value for d in domains)} — one modality reads one "
                    "clock; refusing to pick a domain for the summary"
                )
            method_counter: Counter[AlignmentMethod] = Counter()
            quality_counter: Counter[AlignmentQuality] = Counter()
            offsets: list[int] = []
            for i, result in enumerate(results_by_modality.get(name, ())):
                if not isinstance(result, AlignmentResult):
                    raise ValueError(
                        f"results_by_modality[{name!r}][{i}] must be an "
                        f"AlignmentResult, got {type(result).__name__} {result!r} — a "
                        "bare value has no method/quality provenance to count"
                    )
                method_counter[result.method] += 1
                quality_counter[result.quality] += 1
                if result.offset_ns is not None:
                    offsets.append(result.offset_ns)
            entries.append((
                name,
                ModalityTiming(
                    clock_domain=domains.pop(),
                    clean_count=clean,
                    flagged_count=flagged,
                    flag_counts=_histogram_from_counter(flag_counter),
                    method_counts=_histogram_from_counter(method_counter),
                    quality_counts=_histogram_from_counter(quality_counter),
                    offset_min_ns=min(offsets) if offsets else None,
                    offset_max_ns=max(offsets) if offsets else None,
                    offset_mean_ns=sum(offsets) / len(offsets) if offsets else None,
                ),
            ))
        # Checked after per-modality validation so junk shapes (empty records, bad
        # names/types, mixed domains) surface their own precise errors first.
        unaligned = sorted(
            name
            for name in records_by_modality
            if name != reference and not results_by_modality.get(name)
        )
        if unaligned:
            raise ValueError(
                f"modalities with records but no alignment results: {unaligned} — only "
                "the explicit reference timeline may go unaligned (pass reference=...); "
                "an absent C3 output would otherwise summarize as silently clean"
            )
        entries.sort(key=lambda pair: pair[0])
        modalities = tuple(entries)
        return cls(
            modalities=modalities, budget=budget, verdict=_derive_verdict(modalities)
        )

    # -- serialization (stdlib only, exact round-trip) -------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form; ``from_dict(to_dict(m)) == m`` exactly, keys deterministic."""
        return {
            "timing_meta_version": TIMING_META_VERSION,
            "budget": {
                "max_skew_ns": self.budget.max_skew_ns,
                "window_ns": self.budget.window_ns,
            },
            "verdict": self.verdict.value,
            "modalities": {name: mod.to_dict() for name, mod in self.modalities},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> TimingMeta:
        """Rebuild from :meth:`to_dict` output; every invariant re-runs via construction.

        Failure mode guarded: a truncated, foreign, or future-versioned dict must never
        load as a plausible summary. Missing keys, unknown keys, unknown tokens and an
        unknown ``timing_meta_version`` are all refused with the known set named —
        migration is a decision, never a guess.
        """
        missing = _META_KEYS - set(d)
        if missing:
            raise ValueError(f"timing-meta dict missing keys {sorted(missing)}: {dict(d)!r}")
        unknown = set(d) - _META_KEYS
        if unknown:
            raise ValueError(
                f"timing-meta dict has unknown keys {sorted(unknown)} — refusing to "
                "guess at foreign fields (a new field needs a TIMING_META_VERSION bump)"
            )
        version = d["timing_meta_version"]
        # bool is an int subclass and 1.0 == 1, so both are checked explicitly — a float
        # "version" matching by equality would defeat the strict version schema.
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != TIMING_META_VERSION
        ):
            raise ValueError(
                f"unsupported timing_meta_version {version!r}; this reader knows "
                f"version {TIMING_META_VERSION} — refusing to guess at another "
                "version's shape (write a migration instead)"
            )
        budget_obj = d["budget"]
        if not isinstance(budget_obj, Mapping):
            raise ValueError(
                f"timing-meta 'budget' must be a mapping, got "
                f"{type(budget_obj).__name__} {budget_obj!r}"
            )
        b_missing = _BUDGET_KEYS - set(budget_obj)
        b_unknown = set(budget_obj) - _BUDGET_KEYS
        if b_missing or b_unknown:
            raise ValueError(
                f"timing-meta 'budget' keys must be {sorted(_BUDGET_KEYS)}; missing "
                f"{sorted(b_missing)}, unknown {sorted(b_unknown)}"
            )
        max_skew_obj = budget_obj["max_skew_ns"]
        window_obj = budget_obj["window_ns"]
        if isinstance(max_skew_obj, bool) or not isinstance(max_skew_obj, int):
            raise ValueError(
                f"budget max_skew_ns must be an int, got "
                f"{type(max_skew_obj).__name__} {max_skew_obj!r}"
            )
        window_val: int | None
        if window_obj is None:
            window_val = None
        elif isinstance(window_obj, bool) or not isinstance(window_obj, int):
            raise ValueError(
                f"budget window_ns must be an int or null, got "
                f"{type(window_obj).__name__} {window_obj!r}"
            )
        else:
            window_val = window_obj
        modalities_obj = d["modalities"]
        if not isinstance(modalities_obj, Mapping):
            raise ValueError(
                f"timing-meta 'modalities' must be a mapping, got "
                f"{type(modalities_obj).__name__} {modalities_obj!r}"
            )
        entries: list[tuple[str, ModalityTiming]] = []
        for name, mod_obj in modalities_obj.items():
            if not isinstance(name, str) or not name:
                raise ValueError(f"modality name must be a non-empty str, got {name!r}")
            if not isinstance(mod_obj, Mapping):
                raise ValueError(
                    f"modality {name!r} must be a mapping, got "
                    f"{type(mod_obj).__name__} {mod_obj!r}"
                )
            entries.append((name, ModalityTiming.from_dict(mod_obj)))
        entries.sort(key=lambda pair: pair[0])
        return cls(
            modalities=tuple(entries),
            budget=AlignmentBudget(max_skew_ns=max_skew_obj, window_ns=window_val),
            verdict=_member_from_token(d["verdict"], SyncVerdict, name="verdict"),
        )


# -- the sidecar document (ONE shape for every exporter) -----------------------------------

_SIDECAR_KEYS = frozenset({"timing_meta_version", "episodes"})


def write_timing_sidecar(
    path: str | os.PathLike[str], metas: Mapping[str, TimingMeta]
) -> Path:
    """Write the canonical timing sidecar (``episode_id -> TimingMeta``) as JSON.

    ONE document shape for every exporter (lerobot puts it under ``meta/``, parquet at
    the dataset root), so audit tooling reads one format. Deterministic output
    (sorted keys, stable tokens): the same run writes byte-identical sidecars.
    """
    if not isinstance(metas, Mapping):
        raise ValueError(
            f"metas must be a mapping of episode_id -> TimingMeta, got "
            f"{type(metas).__name__} {metas!r}"
        )
    for episode_id, meta in metas.items():
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError(
                f"sidecar episode id must be a non-empty str, got {episode_id!r} — an "
                "unnamed episode cannot be matched to its data"
            )
        if not isinstance(meta, TimingMeta):
            raise ValueError(
                f"sidecar entry {episode_id!r} must be a TimingMeta, got "
                f"{type(meta).__name__} {meta!r} — a foreign blob cannot be audited"
            )
    episodes: dict[str, dict[str, object]] = {
        episode_id: metas[episode_id].to_dict() for episode_id in sorted(metas)
    }
    doc: dict[str, object] = {
        "timing_meta_version": TIMING_META_VERSION,
        "episodes": episodes,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def read_timing_sidecar(path: str | os.PathLike[str]) -> dict[str, TimingMeta] | None:
    """Read a timing sidecar back; ``None`` iff the file does not exist (legacy dataset).

    Absence is the ONLY silent case: datasets written before C5 have no sidecar and MUST
    keep loading unchanged. A sidecar that exists but cannot be parsed/validated raises
    ``ValueError`` — garbled provenance is corruption, never quietly "legacy".
    """
    sidecar = Path(path)
    if not sidecar.exists():
        return None
    try:
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"timing sidecar {sidecar} exists but is not valid JSON ({exc}) — a "
            "present-but-garbled sidecar is corruption, not a legacy dataset"
        ) from exc
    if not isinstance(doc, dict):
        raise ValueError(
            f"timing sidecar {sidecar} must hold a JSON object, got "
            f"{type(doc).__name__}"
        )
    missing = _SIDECAR_KEYS - set(doc)
    unknown = set(doc) - _SIDECAR_KEYS
    if missing or unknown:
        raise ValueError(
            f"timing sidecar {sidecar} keys must be {sorted(_SIDECAR_KEYS)}; missing "
            f"{sorted(missing)}, unknown {sorted(unknown)} — refusing to guess"
        )
    version = doc["timing_meta_version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != TIMING_META_VERSION
    ):
        raise ValueError(
            f"timing sidecar {sidecar} has unsupported timing_meta_version "
            f"{version!r}; this reader knows version {TIMING_META_VERSION} — write a "
            "migration instead of guessing"
        )
    episodes_obj = doc["episodes"]
    if not isinstance(episodes_obj, dict):
        raise ValueError(
            f"timing sidecar {sidecar} 'episodes' must be an object, got "
            f"{type(episodes_obj).__name__}"
        )
    out: dict[str, TimingMeta] = {}
    for episode_id, meta_obj in episodes_obj.items():
        if not episode_id:
            raise ValueError(f"timing sidecar {sidecar} has an empty episode id")
        if not isinstance(meta_obj, Mapping):
            raise ValueError(
                f"timing sidecar {sidecar} entry {episode_id!r} must be an object, "
                f"got {type(meta_obj).__name__}"
            )
        out[episode_id] = TimingMeta.from_dict(meta_obj)
    return out


def select_episode_timing(
    metas: Mapping[str, TimingMeta],
    *,
    written_ids: Set[str],
    known_ids: Set[str],
) -> tuple[dict[str, TimingMeta], list[str]]:
    """Split caller-supplied timing metas into (written into the dataset, omitted ids).

    Failure mode: a sidecar entry for an episode that was never offered for export is
    metadata about nothing — fabrication — so unknown ids raise. An entry for a KNOWN
    episode that was refused/empty (offered but not written) is returned in the omitted
    list so the exporter can log it: the sidecar only describes episodes that are
    actually in the dataset, and the omission is visible, never silent.
    """
    unknown = sorted(set(metas) - set(known_ids))
    if unknown:
        raise ValueError(
            f"timing meta for unknown episode id(s) {unknown} — metadata about an "
            "episode that was never offered for export is fabrication"
        )
    kept = {eid: meta for eid, meta in metas.items() if eid in written_ids}
    omitted = sorted(set(metas) - set(written_ids))
    return kept, omitted


def write_selected_timing_sidecar(
    path: Path,
    metas: Mapping[str, TimingMeta],
    *,
    written_ids: Set[str],
    known_ids: Set[str],
    log: logging.Logger,
    sidecar_label: str,
) -> None:
    """Select, warn about omissions, and write the sidecar — the ONE post-write flow.

    Failure mode: the lerobot and parquet exporters previously duplicated this
    select+warn+write sequence, so omission/logging behavior could silently drift
    between formats. Both exporters call this instead. Unknown ids raise (via
    :func:`select_episode_timing`); omitted-but-known ids are logged loudly, never
    silent; only episodes actually written appear in the sidecar.
    """
    kept, omitted = select_episode_timing(
        metas, written_ids=written_ids, known_ids=known_ids
    )
    for eid in omitted:
        log.warning(
            "timing meta for episode=%s NOT written to %s: the episode was refused or "
            "empty, so it is not in this dataset",
            eid,
            sidecar_label,
        )
    write_timing_sidecar(path, kept)
