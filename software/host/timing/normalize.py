"""Timestamp normalization — flagged-never-repaired records on one timeline (C2).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **Silent repair => fake synchronization poisoning training data undetectably.** A
  normalizer that clamps an overflowing stamp, reorders a backwards one, drops a
  duplicate, or guesses an unknown skew produces a timeline that LOOKS aligned but is
  fiction — a model trained on it learns cross-modal timing that never happened, and no
  audit can tell. Here a stamp that cannot be cleanly normalized survives as a
  :class:`TimingRecord` with ``normalized_ns=None`` and an explicit
  :class:`NormalizationFlag` reason token — never altered, never dropped, never reordered
  — so downstream (C3 alignment, episode quarantine) can see it and route around it.
* **Wall-clock as a timeline => misalignment by clock step.** NTP corrections, DST and
  manual adjustment make wall time jump both directions; any wall→monotonic mapping is a
  guess. :class:`Normalizer` REJECTS :data:`~timing.stamp.ClockDomain.WALL` at
  construction (C1's :func:`~timing.stamp.require_monotonic` philosophy): wall time is
  episode *provenance*, never a normalizable timeline.
* **Unrecorded skew => unauditable sync.** A SOURCE stamp mapped onto the monotonic
  timeline with an offset nobody wrote down cannot be re-derived or audited later. Every
  record produced from an offset-mapped source carries the applied ``skew_ns``; a SOURCE
  stamp with NO known offset is flagged :data:`NormalizationFlag.UNKNOWN_SKEW` — the
  normalized value is never guessed.

Scope (PONYTAIL): the record and the normalizer only — no alignment, windows or
interpolation (C3), no fault injection (C4). Stdlib only, no numpy (the P-C invariant).
The FROZEN ``PVTSample`` is untouched; ``TimingRecord`` is the NEW structure that lives
alongside it.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from timing.stamp import (
    MAX_STAMP_NS,
    MIN_STAMP_NS,
    ClockDomain,
    Stamp,
    validate_stamp_ns,
)

__all__ = [
    "NormalizationFlag",
    "Normalizer",
    "TimingRecord",
]


class NormalizationFlag(StrEnum):
    """Reason a record could NOT be cleanly normalized — provenance, never a repair.

    Failure mode: a bare ``normalized_ns=None`` says *that* normalization failed but not
    *why*, so downstream cannot distinguish a reset source clock from a missing offset and
    cannot quarantine intelligently. Each flag is one machine-readable reason token.

    A :class:`~enum.StrEnum` (mirroring :class:`~timing.stamp.ClockDomain`): **the token
    values are serialization-stable contract** — they land in exported metadata, so
    renaming one is a versioned decision (``docs/decisions/00XX-*.md`` + migration), never
    a refactor. Deliberately NO catch-all "other": an unclassifiable failure means this
    enum (and the normalizer emitting it) must grow a precise token first.

    Members
    -------
    BACKWARDS_IN_SOURCE:
        The stamp is <= the source sequence's previous clean high-water mark — the source
        clock stalled, jumped back, or reset. The record keeps its ORIGINAL stamp,
        un-reordered and un-clamped; placing it on the timeline would forge order.
    UNKNOWN_SKEW:
        A SOURCE-domain stamp with no known source→monotonic offset. The normalized value
        cannot be computed — guessing one would silently shift a whole modality.
    SKEW_OUT_OF_RANGE:
        Applying the known offset produced a value outside the representable stamp range
        (``[1, 2**63-1]``). Clamping would forge a stamp at the range edge; the record is
        flagged instead, with the attempted ``skew_ns`` recorded for audit.
    """

    BACKWARDS_IN_SOURCE = "backwards_in_source"
    UNKNOWN_SKEW = "unknown_skew"
    SKEW_OUT_OF_RANGE = "skew_out_of_range"


def _validate_skew_ns(value: object, *, name: str = "skew_ns") -> int:
    """Validate a source→monotonic offset; return it as ``int`` or raise ``ValueError``.

    Failure mode: unlike a stamp, a skew may legitimately be zero or negative (the source
    clock may lead the host clock), so :func:`~timing.stamp.validate_stamp_ns` is the
    wrong gate — but a bool, float or past-int64 skew would still forge/lose nanoseconds
    exactly like a bad stamp. Same rejection classes, skew-shaped range.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be an int nanosecond offset, got bool {value!r} — a bool would "
            "silently coerce to 0/1 and forge an offset out of a flag"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int nanosecond offset, got {type(value).__name__} "
            f"{value!r} — non-int offsets lose nanosecond exactness"
        )
    if not -MAX_STAMP_NS <= value <= MAX_STAMP_NS:
        raise ValueError(
            f"{name} must be within ±(2**63-1), got {value} — an offset past int64 "
            "cannot round-trip through on-disk encodings without truncation"
        )
    return value


_RECORD_KEYS = frozenset({"original", "normalized_ns", "flags", "skew_ns"})


@dataclass(frozen=True, slots=True)
class TimingRecord:
    """The canonical internal timing record: one stamp, normalized or honestly flagged.

    Failure mode: a bare "normalized" int with no provenance cannot be audited — was it
    identity, offset-mapped, or quietly repaired? A ``TimingRecord`` binds the ORIGINAL
    stamp (as received, any domain), the host-monotonic ``normalized_ns`` (or ``None``),
    the reason ``flags`` when normalization failed, and the applied ``skew_ns`` when an
    offset was used — so every value on the timeline can be re-derived and checked.

    Invariants (enforced at construction — a violating record cannot exist as a value):

    * clean ⊕ flagged: ``normalized_ns is None`` **iff** ``flags`` is non-empty. A record
      is either clean or flagged — never both ("normalized anyway" is exactly the silent
      repair this layer forbids), never neither (an un-normalized record without a reason
      token is a silent hole in the timeline).
    * monotonic identity: a MONOTONIC original with no flags has
      ``normalized_ns == original.raw_ns`` and ``skew_ns is None`` — monotonic input is
      never altered, and an identity normalization has no skew to record.
    * ``UNKNOWN_SKEW`` contradicts a recorded ``skew_ns`` — flagged unknown AND carrying
      an offset is a lie in one direction or the other.

    Produced by :class:`Normalizer` (which never emits a WALL record — wall time is
    rejected at its boundary); frozen + slotted value semantics like ``Stamp``.
    """

    original: Stamp
    normalized_ns: int | None
    flags: tuple[NormalizationFlag, ...] = ()
    skew_ns: int | None = None

    def __post_init__(self) -> None:
        # Fail loud at construction (never downstream): a TimingRecord that exists is
        # internally consistent. Each check names the invariant it enforces.
        if not isinstance(self.original, Stamp):
            raise ValueError(
                f"original must be a Stamp, got {type(self.original).__name__} "
                f"{self.original!r} — a bare value has no clock domain and cannot be "
                "audited against its normalization"
            )
        if not isinstance(self.flags, tuple):
            raise ValueError(
                f"flags must be a tuple of NormalizationFlag, got "
                f"{type(self.flags).__name__} — a mutable flags container would let a "
                "flagged record be quietly 'cleaned' after construction"
            )
        for i, flag in enumerate(self.flags):
            if not isinstance(flag, NormalizationFlag):
                raise ValueError(
                    f"flags[{i}] must be a NormalizationFlag, got "
                    f"{type(flag).__name__} {flag!r} — a foreign token cannot be "
                    "serialized stably or acted on by quarantine"
                )
        if len(set(self.flags)) != len(self.flags):
            raise ValueError(
                f"flags contains duplicates: {[f.value for f in self.flags]!r} — each "
                "reason token appears once; duplicated provenance is noise"
            )
        if self.normalized_ns is not None:
            validate_stamp_ns(self.normalized_ns, name="normalized_ns")
        if (self.normalized_ns is None) != bool(self.flags):
            if self.normalized_ns is None:
                raise ValueError(
                    "normalized_ns is None but flags is empty — an un-normalized record "
                    "without a reason token is a silent hole in the timeline"
                )
            raise ValueError(
                f"normalized_ns={self.normalized_ns} alongside flags "
                f"{[f.value for f in self.flags]!r} — a record is clean or flagged, "
                "never both; a 'normalized anyway' value is silent repair"
            )
        if self.skew_ns is not None:
            _validate_skew_ns(self.skew_ns)
            if NormalizationFlag.UNKNOWN_SKEW in self.flags:
                raise ValueError(
                    f"skew_ns={self.skew_ns} on a record flagged 'unknown_skew' — a "
                    "record cannot both carry an offset and claim not to know it"
                )
        if self.original.domain is ClockDomain.MONOTONIC:
            if self.skew_ns is not None:
                raise ValueError(
                    f"skew_ns={self.skew_ns} on a MONOTONIC original — identity "
                    "normalization has no source→monotonic offset; a recorded skew here "
                    "claims a conversion that never happened"
                )
            if not self.flags and self.normalized_ns != self.original.raw_ns:
                raise ValueError(
                    f"MONOTONIC identity violated: normalized_ns={self.normalized_ns} != "
                    f"original.raw_ns={self.original.raw_ns} — monotonic input is never "
                    "altered; any difference is silent repair"
                )
        # SOURCE consistency: a CLEAN source-domain record must be auditable — the applied
        # offset recorded, and the normalized value exactly re-derivable as raw + skew.
        # Without this a deserialized/hand-built record could claim a normalization the
        # arithmetic contradicts (forged synchronization), which the Normalizer itself can
        # never produce but from_dict would otherwise happily load.
        if self.original.domain is ClockDomain.SOURCE and not self.flags:
            if self.skew_ns is None:
                raise ValueError(
                    "clean SOURCE record without skew_ns — a source-domain normalization "
                    "must record the applied source→monotonic offset or be flagged "
                    "'unknown_skew'; an unrecorded offset cannot be audited"
                )
            if self.normalized_ns != self.original.raw_ns + self.skew_ns:
                raise ValueError(
                    f"SOURCE consistency violated: normalized_ns={self.normalized_ns} != "
                    f"original.raw_ns + skew_ns = {self.original.raw_ns + self.skew_ns} — "
                    "the normalized value must be exactly re-derivable from the recorded "
                    "offset; anything else is a forged normalization"
                )

    # -- serialization (stdlib only, exact round-trip) ------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Plain-``dict`` form for JSON/metadata; ``from_dict(to_dict(r)) == r`` exactly.

        ``original`` nests :meth:`Stamp.to_dict`; ``flags`` serialize as their stable
        tokens (a JSON list — rebuilt as a tuple on load); ints stay exact, ``None``
        stays ``None``.
        """
        return {
            "original": self.original.to_dict(),
            "normalized_ns": self.normalized_ns,
            "flags": [flag.value for flag in self.flags],
            "skew_ns": self.skew_ns,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> TimingRecord:
        """Rebuild from :meth:`to_dict` output such that ``from_dict(to_dict(r)) == r``.

        Failure mode guarded: a truncated/foreign dict surfacing as an opaque ``KeyError``
        deep in a load path, or — far worse — an unknown flag token being guessed or
        silently dropped, which would un-flag a quarantined record. Every unknown token is
        refused with the known-token list; all field invariants re-run via construction.
        """
        missing = _RECORD_KEYS - set(d)
        if missing:
            raise ValueError(
                f"timing-record dict missing keys {sorted(missing)}: {dict(d)!r}"
            )
        original_obj = d["original"]
        if not isinstance(original_obj, Mapping):
            raise ValueError(
                f"timing-record 'original' must be a stamp dict, got "
                f"{type(original_obj).__name__} {original_obj!r}"
            )
        flags_obj = d["flags"]
        if isinstance(flags_obj, str) or not isinstance(flags_obj, (list, tuple)):
            raise ValueError(
                f"timing-record 'flags' must be a list of flag tokens, got "
                f"{type(flags_obj).__name__} {flags_obj!r}"
            )
        flags: list[NormalizationFlag] = []
        for i, token in enumerate(flags_obj):
            if not isinstance(token, str):
                raise ValueError(
                    f"flags[{i}] must be a str token, got {type(token).__name__} "
                    f"{token!r}"
                )
            try:
                flags.append(NormalizationFlag(token))
            except ValueError:
                raise ValueError(
                    f"unknown normalization-flag token {token!r}; known tokens: "
                    f"{[m.value for m in NormalizationFlag]} — refusing to guess "
                    "(dropping it would un-flag a quarantined record)"
                ) from None
        normalized_obj = d["normalized_ns"]
        skew_obj = d["skew_ns"]
        return cls(
            original=Stamp.from_dict(original_obj),
            normalized_ns=(
                None
                if normalized_obj is None
                else validate_stamp_ns(normalized_obj, name="normalized_ns")
            ),
            flags=tuple(flags),
            skew_ns=None if skew_obj is None else _validate_skew_ns(skew_obj),
        )


class Normalizer:
    """Converts one source's raw stamp sequence into :class:`TimingRecord`\\ s.

    Failure mode: the core invariant is **never silently repair** — a normalizer that
    reorders, clamps, drops or guesses produces fake synchronization that poisons
    training data undetectably. Every input stamp yields exactly one record, in input
    order; a stamp that cannot be cleanly normalized comes back FLAGGED with its original
    value intact, so sequence length and order are always preserved.

    One ``Normalizer`` describes one source: its :class:`~timing.stamp.ClockDomain` and,
    for SOURCE, an optional known ``offset_ns`` (the source→monotonic skew, from a
    handshake or calibration). :meth:`normalize` is a pure function of its input — no
    state carries across calls — so one call is one source sequence, and re-normalizing
    already-normalized monotonic values is identity (idempotence).

    WALL is rejected here at construction: wall time steps under NTP/DST/manual
    adjustment, so any wall→monotonic mapping would be a guess. Wall stamps are episode
    provenance ("when, in human terms"), never a normalizable timeline — see
    :func:`~timing.stamp.require_monotonic` for the same gate on the consuming side.
    """

    __slots__ = ("_domain", "_offset_ns")

    def __init__(
        self, source_domain: ClockDomain, *, offset_ns: int | None = None
    ) -> None:
        # Fail loud at construction (never mid-sequence) on any source description that
        # could only produce guessed timelines.
        if not isinstance(source_domain, ClockDomain):
            raise ValueError(
                f"source_domain must be a ClockDomain, got "
                f"{type(source_domain).__name__} {source_domain!r} — an unlabeled domain "
                "cannot say which normalization rule applies"
            )
        if source_domain is ClockDomain.WALL:
            raise ValueError(
                "wall-clock stamps are never a normalizable timeline: NTP corrections, "
                "DST and manual adjustment make wall time step both directions, so any "
                "wall→monotonic mapping is a guess — fake synchronization that poisons "
                "training data. Record wall time as episode provenance metadata; "
                "normalize MONOTONIC or SOURCE stamps only"
            )
        if offset_ns is not None:
            if source_domain is not ClockDomain.SOURCE:
                raise ValueError(
                    f"offset_ns={offset_ns} with domain "
                    f"{source_domain.value!r} — an offset is the source→monotonic skew "
                    "and only meaningful for SOURCE; a skewed 'monotonic' input is not "
                    "monotonic (label it SOURCE)"
                )
            _validate_skew_ns(offset_ns, name="offset_ns")
        self._domain = source_domain
        self._offset_ns = offset_ns

    @property
    def domain(self) -> ClockDomain:
        """The clock domain this normalizer's input stamps are read from."""
        return self._domain

    @property
    def offset_ns(self) -> int | None:
        """The known source→monotonic offset, or ``None`` (SOURCE without one, or MONOTONIC)."""
        return self._offset_ns

    def normalize(self, raw_stamps_ns: Iterable[int]) -> tuple[TimingRecord, ...]:
        """One record per input stamp, in INPUT order — flagged where honesty demands.

        Per-domain behavior (never silently repair):

        * MONOTONIC: identity (``normalized_ns == raw``). A stamp <= the sequence's
          previous clean high-water mark is flagged ``BACKWARDS_IN_SOURCE`` with
          ``normalized_ns=None`` — never reordered, clamped or dropped; the record
          survives WITH its flag so downstream can quarantine.
        * SOURCE with ``offset_ns``: ``normalized_ns = raw + offset`` with ``skew_ns``
          recorded; a result outside ``[1, 2**63-1]`` is flagged ``SKEW_OUT_OF_RANGE``
          (never clamped). Backwards-in-source is still flagged.
        * SOURCE without ``offset_ns``: every record flagged ``UNKNOWN_SKEW`` — the
          normalized value cannot be computed and is never guessed.

        Backwards detection uses the highest raw value accepted as forward progress so
        far: after a source-clock jump backwards (e.g. a device reset), stamps stay
        flagged until the source passes its previous high-water mark — accepting the
        post-reset run as "clean" would splice two incompatible timelines together.

        Invalid raw values (bool/non-int/0/negative/>int64) raise ``ValueError`` from
        C1's :func:`~timing.stamp.validate_stamp_ns`, labeled with the stamp's index —
        construction-time rejection, consistent with ``Stamp``/the clocks.
        """
        records: list[TimingRecord] = []
        offset_ns = self._offset_ns
        high_water_ns: int | None = None  # highest raw accepted as forward source progress
        for i, raw in enumerate(raw_stamps_ns):
            original = Stamp(
                validate_stamp_ns(raw, name=f"raw_stamps_ns[{i}]"), self._domain
            )
            backwards = high_water_ns is not None and original.raw_ns <= high_water_ns
            if not backwards:
                high_water_ns = original.raw_ns
            flags: list[NormalizationFlag] = []
            if backwards:
                flags.append(NormalizationFlag.BACKWARDS_IN_SOURCE)
            skew_ns: int | None
            normalized_ns: int | None
            if self._domain is ClockDomain.MONOTONIC:
                skew_ns = None
                normalized_ns = original.raw_ns
            elif offset_ns is None:  # SOURCE with no known source→monotonic offset
                skew_ns = None
                normalized_ns = None
                flags.append(NormalizationFlag.UNKNOWN_SKEW)
            else:  # SOURCE with a known offset: map, record the skew, never clamp
                skew_ns = offset_ns
                candidate_ns = original.raw_ns + offset_ns
                if MIN_STAMP_NS <= candidate_ns <= MAX_STAMP_NS:
                    normalized_ns = candidate_ns
                else:
                    normalized_ns = None
                    flags.append(NormalizationFlag.SKEW_OUT_OF_RANGE)
            if flags:
                normalized_ns = None  # flagged records never publish a value
            records.append(
                TimingRecord(
                    original=original,
                    normalized_ns=normalized_ns,
                    flags=tuple(flags),
                    skew_ns=skew_ns,
                )
            )
        return tuple(records)
