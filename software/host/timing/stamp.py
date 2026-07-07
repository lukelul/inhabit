"""Clock domains and domain-labeled timestamps — the P-C timing vocabulary (C1).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **Wall-clock leakage => cross-modal misalignment.** A wall-clock (or device-local) stamp
  slipped into a slot that expects host-monotonic nanoseconds shifts one modality's timeline
  against the others — silently, because both are "just ints". Here every timestamp is a
  :class:`Stamp` carrying its :class:`ClockDomain`, and :func:`require_monotonic` makes a
  non-monotonic stamp a **loud ValueError**, never a warning.
* **Zero / negative / backwards stamps => poisoned datasets.** ``0`` is the "never stamped"
  sentinel (the ``SimAdapter`` gap documented in ``docs/sdk/ROBOT_SDK_MAPPING.md`` §4.7) and
  a negative value means an underflowed/backwards clock. Both are rejected at construction
  (:func:`validate_stamp_ns`), so a poisoned stamp cannot exist as a value — the frozen-schema
  convention ``PVTSample.timestamp_ns`` and ``SimRobot`` already follow.
* **Cross-domain comparison => meaningless ordering.** ``wall < monotonic`` compares two
  unrelated timelines; whatever boolean falls out is noise. Ordering two :class:`Stamp`
  values from DIFFERENT domains raises — normalization onto one timeline is C2's job, and
  until then the order is undefined by design.

Scope (PONYTAIL). This is the *vocabulary*, not the engine: no normalization (C2), no
alignment (C3). Stdlib only, no numpy — the P-C invariant. The FROZEN ``PVTSample`` is
untouched; its ``timestamp_ns`` is, by contract, a :data:`ClockDomain.MONOTONIC` value.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "MAX_STAMP_NS",
    "MIN_STAMP_NS",
    "ClockDomain",
    "Stamp",
    "require_monotonic",
    "validate_stamp_ns",
]

# Valid range for any stamp, in nanoseconds. The floor is 1 (a zero stamp is the "never
# stamped" sentinel — see module docstring); the ceiling is int64 max, because stamps must
# round-trip through on-disk encodings (parquet/arrow int64) without silent truncation.
MIN_STAMP_NS = 1
MAX_STAMP_NS = 2**63 - 1


class ClockDomain(StrEnum):
    """Which clock a timestamp was read from — the label that makes an int a timestamp.

    A :class:`~enum.StrEnum` (mirroring ``SensorKind``) so each domain serializes to a
    stable, human-readable token. **The token values are serialization-stable contract:**
    they appear in exported metadata and on-disk records, so renaming one is a versioned
    decision (``docs/decisions/00XX-*.md`` record + migration), never a refactor.

    Members
    -------
    MONOTONIC:
        The ONE canonical host clock (``time.monotonic_ns`` on the ingesting host). The
        only domain accepted where alignment-grade time is required — this is what
        ``PVTSample.timestamp_ns`` and ``CanFrame.rx_monotonic_ns`` carry.
    WALL:
        Wall-clock time (e.g. ``time.time_ns``). Representable for *provenance* (when did
        this episode happen, in human terms) but NEVER accepted where monotonic is
        required: NTP steps, DST and manual adjustment make it jump, which would silently
        misalign modalities.
    SOURCE:
        A device/SDK-local clock (camera hardware timestamps, a robot controller's tick
        counter). Meaningful only within that source until C2 normalizes it onto the
        monotonic timeline; the label keeps it quarantined until then.
    """

    MONOTONIC = "monotonic"
    WALL = "wall"
    SOURCE = "source"


def validate_stamp_ns(value: object, *, name: str = "raw_ns") -> int:
    """Validate one nanosecond stamp value; return it as ``int`` or raise ``ValueError``.

    Failure mode per rejection (each gets a distinct, greppable message):

    * ``bool`` — ``True``/``False`` silently coerce to ``1``/``0`` and would forge a stamp
      out of a flag (``bool`` is an ``int`` subclass, so this must be checked FIRST).
    * non-``int`` — a ``float`` cannot hold nanosecond exactness above ~2**53 and a ``str``
      is not a timestamp at all; coercing would hide the caller's bug.
    * ``0`` — the "never stamped" sentinel; accepting it poisons alignment.
    * negative — an underflowed or backwards clock.
    * ``> 2**63-1`` — would overflow int64 in on-disk encodings (parquet/arrow) and come
      back silently truncated.

    ``name`` labels the offending field in the message (``raw_ns``, ``start_ns``, ...).
    """
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be an int nanosecond count, got bool {value!r} — a bool would "
            "silently coerce to 0/1 and forge a stamp out of a flag"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int nanosecond count, got {type(value).__name__} "
            f"{value!r} — non-int stamps lose nanosecond exactness"
        )
    if value == 0:
        raise ValueError(
            f"{name} must be >= {MIN_STAMP_NS}, got 0 — zero is the 'never stamped' "
            "sentinel and accepting it poisons alignment"
        )
    if value < 0:
        raise ValueError(
            f"{name} must be >= {MIN_STAMP_NS}, got {value} — a negative stamp implies a "
            "backwards or underflowed clock"
        )
    if value > MAX_STAMP_NS:
        raise ValueError(
            f"{name} must be <= 2**63-1 ({MAX_STAMP_NS}), got {value} — a stamp past "
            "int64 cannot round-trip through on-disk encodings without truncation"
        )
    return value


@dataclass(frozen=True, slots=True)
class Stamp:
    """One domain-labeled nanosecond timestamp — an int that knows which clock it came from.

    Failure mode: a bare ``int`` timestamp carries no provenance, so a wall-clock or
    device-local value can silently stand in for host-monotonic time and misalign the PVT
    streams. A ``Stamp`` binds ``raw_ns`` to its :class:`ClockDomain` at construction and
    validates the value (via :func:`validate_stamp_ns`), so an invalid or unlabeled stamp
    cannot exist as a value.

    Ordering is defined ONLY within a single domain (``raw_ns`` order); ordering stamps
    from different domains raises ``ValueError`` — see the module docstring. Equality is
    structural (``raw_ns`` AND ``domain``), so a wall stamp never equals a monotonic stamp,
    and that comparison is allowed (it answers "same labeled value?", not "which first?").

    Frozen + slotted: a stamp is a value, not state, so it is hashable and safe to share.
    """

    raw_ns: int
    domain: ClockDomain

    def __post_init__(self) -> None:
        # Fail loud at construction (never downstream): a Stamp that exists is valid.
        validate_stamp_ns(self.raw_ns)
        if not isinstance(self.domain, ClockDomain):
            raise ValueError(
                f"domain must be a ClockDomain, got {type(self.domain).__name__} "
                f"{self.domain!r} — an unlabeled/foreign domain cannot be ordered against "
                "anything or normalized by C2"
            )

    # -- ordering (same-domain only) ------------------------------------------------------

    def _raw_in_same_domain(self, other: object, op: str) -> int:
        """Return ``other.raw_ns`` iff ``other`` is a Stamp in THIS stamp's domain.

        Raises ``TypeError`` for a non-Stamp (a bare int has no domain — labeling it is the
        caller's job) and ``ValueError`` for a cross-domain Stamp (two clocks, no common
        timeline until C2 normalizes — any boolean we returned would be noise).
        """
        if not isinstance(other, Stamp):
            raise TypeError(
                f"unorderable: Stamp {op} {type(other).__name__} — only a Stamp in the "
                "same clock domain has a defined ordering (wrap raw ints in a Stamp)"
            )
        if other.domain is not self.domain:
            raise ValueError(
                f"cannot order stamps across clock domains ({self.domain.value!r} {op} "
                f"{other.domain.value!r}) — cross-domain ordering is meaningless until "
                "both are normalized onto the monotonic timeline (C2)"
            )
        return other.raw_ns

    def __lt__(self, other: object) -> bool:
        return self.raw_ns < self._raw_in_same_domain(other, "<")

    def __le__(self, other: object) -> bool:
        return self.raw_ns <= self._raw_in_same_domain(other, "<=")

    def __gt__(self, other: object) -> bool:
        return self.raw_ns > self._raw_in_same_domain(other, ">")

    def __ge__(self, other: object) -> bool:
        return self.raw_ns >= self._raw_in_same_domain(other, ">=")

    # -- serialization (stdlib only, exact round-trip) ------------------------------------

    def to_dict(self) -> dict[str, int | str]:
        """Plain-``dict`` form for JSON/metadata: ``{"raw_ns": int, "domain": token}``.

        ``raw_ns`` stays an exact int (never float — see :func:`validate_stamp_ns`) and the
        domain serializes to its stable :class:`ClockDomain` token, so
        ``from_dict(to_dict(s)) == s`` exactly.
        """
        return {"raw_ns": self.raw_ns, "domain": self.domain.value}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Stamp:
        """Rebuild from :meth:`to_dict` output such that ``from_dict(to_dict(s)) == s``.

        Failure mode guarded: a truncated/foreign dict would otherwise surface as an opaque
        ``KeyError`` deep in a load path, and an unknown domain token would either crash
        cryptically or — far worse — be guessed. Fail loud with the offending value; an
        unknown token is rejected, never mapped to a default domain.
        """
        missing = {"raw_ns", "domain"} - set(d)
        if missing:
            raise ValueError(f"stamp dict missing keys {sorted(missing)}: {dict(d)!r}")
        token = d["domain"]
        if not isinstance(token, str):
            raise ValueError(
                f"stamp 'domain' must be a str token, got {type(token).__name__} "
                f"{token!r}"
            )
        try:
            domain = ClockDomain(token)
        except ValueError:
            raise ValueError(
                f"unknown clock-domain token {token!r}; known tokens: "
                f"{[m.value for m in ClockDomain]} — refusing to guess a domain"
            ) from None
        return cls(raw_ns=validate_stamp_ns(d["raw_ns"]), domain=domain)


def require_monotonic(stamp: Stamp) -> int:
    """Unwrap a stamp that MUST be host-monotonic; loud ``ValueError`` otherwise.

    Failure mode: wall/source-clock leakage into a monotonic slot => cross-modal
    misalignment. This is the type-level gate — code that needs alignment-grade time calls
    this instead of reaching for ``.raw_ns``, so a WALL or SOURCE stamp in that position is
    an error (never a warning, never a silent pass-through). A MONOTONIC stamp passes its
    exact int through unchanged.
    """
    if not isinstance(stamp, Stamp):
        raise TypeError(
            f"require_monotonic needs a Stamp, got {type(stamp).__name__} — a bare value "
            "has no clock domain to check"
        )
    if stamp.domain is not ClockDomain.MONOTONIC:
        raise ValueError(
            f"monotonic stamp required, got domain {stamp.domain.value!r} "
            f"(raw_ns={stamp.raw_ns}) — a non-monotonic stamp on the canonical timeline "
            "would silently misalign modalities; normalize it first (C2)"
        )
    return stamp.raw_ns
