"""Deterministic timing-fault injection over clean stamp timelines — the chaos bench (P-C/C4).

Failure modes this module exists to prevent (lead-with-the-failure-mode):

* **Undetected timing disturbance => silently misaligned training data.** Real pipelines
  jitter, stall, drop, duplicate, reorder and skew — and a measurement stack that has only
  ever seen clean lattices will happily bless a disturbed episode. This module manufactures
  each disturbance ON PURPOSE, as a value (:class:`FaultSpec`), so the tests can prove the
  EXISTING instruments (``logger.jitter.compute_jitter`` / ``JitterBudget``, monotonicity /
  uniqueness / count checks, offset-vs-reference) actually catch every fault shape — before
  a real robot produces one.
* **Non-deterministic chaos => unreproducible bench.** A chaos test that draws from the
  process-global RNG cannot be re-run, bisected, or committed as a fixture. Every stochastic
  fault here draws from a :class:`~sim.rng.SeededRng` sub-stream spawned per fault
  (``fault[<i>]:<kind>``), so the same ``(stamps, spec, seed)`` triple yields a byte-identical
  disturbed timeline on any machine, and adding a fault to a chain never shifts another
  fault's draws.
* **A chaos layer that silently repairs => forged stamps.** A fault may produce an INVALID
  sequence — non-monotonic, duplicated, holed — that is the point, and it is handed to the
  measurement untouched. But each individual value stays a valid nanosecond int: a fault
  that would push a stamp past ``2**63-1`` (or below 1) RAISES instead of clamping or
  dropping the value, because a silently clamped stamp is exactly the forged time this
  phase exists to ban.

Scope (PONYTAIL — the disturbance layer only). Measurement lives in ``logger.jitter`` and
plain set/order checks; alignment/quarantine verdicts are C3/C7's job. Stdlib only, NO
numpy (the P-C invariant). The FROZEN ``PVTSample`` / adapter / codec surfaces are untouched
— faults operate on bare ``int`` nanosecond timelines (the B2/B5 ``timestamp_ns`` streams).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from sim.rng import SeededRng
from timing.clocks import LatticeClock
from timing.stamp import MAX_STAMP_NS, MIN_STAMP_NS, validate_stamp_ns

__all__ = [
    "BENCH_FIXTURES",
    "BURST_STALL_200MS",
    "CAMERA_VARIABLE_33MS",
    "CAN_JITTER_MILD",
    "SKEWED_SOURCE_CLOCK",
    "BenchFixture",
    "FaultKind",
    "FaultSpec",
    "apply_faults",
    "lattice_stamps",
]


class FaultKind(StrEnum):
    """The timing-fault vocabulary — one stable token per disturbance shape.

    A :class:`~enum.StrEnum` (mirroring ``ClockDomain``/``SensorKind``) so each fault kind
    serializes to a stable, greppable token in bench reports and sub-stream labels. Adding a
    kind is additive; renaming one would silently break committed bench fixtures, so tokens
    are treated as contract.

    Members
    -------
    JITTER:
        Bounded ± per-stamp perturbation, clamped so it can NEVER reorder the timeline
        (reordering is its own fault) — the USB-CAN / scheduler wiggle shape.
    FIXED_DELAY:
        Constant latency added to every stamp — one modality arriving uniformly late.
        Invisible to single-stream interval measurement BY DESIGN; only an offset against a
        reference timeline detects it (the tests prove both facts).
    BURST_DELAY:
        A scripted window of stamps shifted by one large delay — the camera-freeze /
        CAN-bus-stall shape (big gap in, late frames colliding with on-time ones out).
    DROP:
        Stamps removed — every k-th (deterministic) or seeded-random per stamp.
    DUPLICATE:
        One stamp repeated at the same instant — the duplicate-frame-id shape.
    REORDER:
        Two adjacent stamps swapped at a seeded position inside a bounded window —
        out-of-order delivery.
    SKEWED_CLOCK:
        Constant offset plus linear drift — a source clock that disagrees with the host
        clock and slowly diverges. Like FIXED_DELAY, only visible against a reference.
    VARIABLE_FRAME_TIME:
        Per-interval multiplicative wobble — the camera auto-exposure shape (frame time
        breathes around nominal; the timeline stays monotonic but is no longer a lattice).
    """

    JITTER = "jitter"
    FIXED_DELAY = "fixed_delay"
    BURST_DELAY = "burst_delay"
    DROP = "drop"
    DUPLICATE = "duplicate"
    REORDER = "reorder"
    SKEWED_CLOCK = "skewed_clock"
    VARIABLE_FRAME_TIME = "variable_frame_time"


# Every optional FaultSpec parameter, and which kinds may set which. A parameter set on the
# wrong kind is rejected loud in __post_init__ — it would otherwise be silently ignored,
# which is a bench that quietly does not test what its author believes it tests.
_PARAM_FIELDS: tuple[str, ...] = (
    "magnitude_ns",
    "delay_ns",
    "window_start",
    "window_len",
    "every_k",
    "probability",
    "at_index",
    "offset_ns",
    "drift_ppm",
    "wobble",
)

_ALLOWED_PARAMS: dict[FaultKind, frozenset[str]] = {
    FaultKind.JITTER: frozenset({"magnitude_ns"}),
    FaultKind.FIXED_DELAY: frozenset({"delay_ns"}),
    FaultKind.BURST_DELAY: frozenset({"delay_ns", "window_start", "window_len"}),
    FaultKind.DROP: frozenset({"every_k", "probability"}),
    FaultKind.DUPLICATE: frozenset({"at_index"}),
    FaultKind.REORDER: frozenset({"window_start", "window_len"}),
    FaultKind.SKEWED_CLOCK: frozenset({"offset_ns", "drift_ppm"}),
    FaultKind.VARIABLE_FRAME_TIME: frozenset({"wobble"}),
}


def _require_int(value: object, name: str, *, minimum: int | None = None) -> int:
    """Validate one required int parameter; loud ``ValueError`` otherwise.

    Failure mode: a ``bool``/``float``/missing parameter silently coerced would produce a
    fault profile the author did not script (``True`` becoming a 1 ns delay). ``bool`` is
    checked first because it IS an ``int`` subclass.
    """
    if value is None:
        raise ValueError(f"{name} is required for this fault kind but was not provided")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be an int, got {type(value).__name__} {value!r} — a coerced "
            "parameter would script a fault profile the author never wrote"
        )
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _require_float(value: object, name: str) -> float:
    """Validate one required real-number parameter; loud ``ValueError`` otherwise.

    Rejects NaN/±inf too: bounded params (wobble/probability) would already fail their
    range checks on NaN, but an UNbounded float like ``drift_ppm`` would carry a
    non-finite value straight into ``round(...)`` — a fault profile no author scripted.
    One gate here covers every float parameter, present and future.
    """
    if value is None:
        raise ValueError(f"{name} is required for this fault kind but was not provided")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(
            f"{name} must be a real number, got {type(value).__name__} {value!r}"
        )
    if not math.isfinite(value):
        raise ValueError(
            f"{name} must be finite, got {value!r} — a NaN/inf parameter scripts a "
            "fault profile no author wrote"
        )
    return float(value)


@dataclass(frozen=True, slots=True)
class FaultSpec:
    """One deterministic disturbance profile over a clean stamp sequence (a value, not state).

    Failure mode: an under-specified or silently-defaulted fault is a bench that tests
    nothing — so every parameter relevant to :attr:`kind` is REQUIRED, every irrelevant
    parameter must stay ``None`` (setting one raises: it would be ignored, and an ignored
    knob is a lie), and identity-shaped parameterizations (zero magnitude/delay/wobble,
    both-zero skew, ``probability`` 0/1) are rejected up front. Frozen + slotted so a spec
    is hashable, shareable, and immutable once validated — the committed bench fixtures
    depend on that.

    Parameters per kind (all others must be ``None``)
    -------------------------------------------------
    - ``JITTER``: ``magnitude_ns >= 1`` — symmetric per-stamp perturbation bound.
    - ``FIXED_DELAY``: ``delay_ns >= 1``.
    - ``BURST_DELAY``: ``delay_ns >= 1``, ``window_start >= 0``, ``window_len >= 1``
      (stamp indices ``[window_start, window_start+window_len)`` are delayed; a window
      running off the end of the sequence is a stall that never recovers — allowed).
    - ``DROP``: exactly ONE of ``every_k >= 2`` (indices ``k-1, 2k-1, ...`` removed) or
      ``0 < probability < 1`` (seeded per-stamp removal).
    - ``DUPLICATE``: ``at_index >= 0`` — that stamp appears twice, consecutively.
    - ``REORDER``: ``window_start >= 0``, ``window_len >= 2`` — one seeded adjacent swap
      inside ``[window_start, window_start+window_len)``.
    - ``SKEWED_CLOCK``: BOTH ``offset_ns`` (int, may be negative) and ``drift_ppm`` (float,
      may be negative), not both zero. Output: ``t + offset + drift_ppm·(t - t0)/1e6``.
    - ``VARIABLE_FRAME_TIME``: ``0 < wobble < 1`` — each interval scales by a seeded
      ``uniform(1-wobble, 1+wobble)`` (floored at 1 ns: exposure time never reverses).
    """

    kind: FaultKind
    magnitude_ns: int | None = None
    delay_ns: int | None = None
    window_start: int | None = None
    window_len: int | None = None
    every_k: int | None = None
    probability: float | None = None
    at_index: int | None = None
    offset_ns: int | None = None
    drift_ppm: float | None = None
    wobble: float | None = None

    def __post_init__(self) -> None:
        # Fail loud at construction (never mid-bench): a FaultSpec that exists is valid.
        if not isinstance(self.kind, FaultKind):
            raise ValueError(
                f"kind must be a FaultKind, got {type(self.kind).__name__} {self.kind!r} "
                f"— known kinds: {[k.value for k in FaultKind]} (refusing to guess)"
            )
        provided = {name for name in _PARAM_FIELDS if getattr(self, name) is not None}
        extras = provided - _ALLOWED_PARAMS[self.kind]
        if extras:
            raise ValueError(
                f"parameters {sorted(extras)} are not used by fault kind "
                f"{self.kind.value!r} — they would be silently ignored, which is a bench "
                "that does not test what it claims (caller bug)"
            )
        match self.kind:
            case FaultKind.JITTER:
                _require_int(self.magnitude_ns, "magnitude_ns", minimum=1)
            case FaultKind.FIXED_DELAY:
                _require_int(self.delay_ns, "delay_ns", minimum=1)
            case FaultKind.BURST_DELAY:
                _require_int(self.delay_ns, "delay_ns", minimum=1)
                _require_int(self.window_start, "window_start", minimum=0)
                _require_int(self.window_len, "window_len", minimum=1)
            case FaultKind.DROP:
                if (self.every_k is None) == (self.probability is None):
                    raise ValueError(
                        "drop requires exactly ONE of every_k / probability — neither is "
                        "an empty fault, both is an ambiguous one"
                    )
                if self.every_k is not None:
                    # every_k == 1 would drop EVERY stamp: an empty timeline, not a fault.
                    _require_int(self.every_k, "every_k", minimum=2)
                else:
                    p = _require_float(self.probability, "probability")
                    if not 0.0 < p < 1.0:
                        raise ValueError(
                            f"probability must be strictly inside (0, 1), got {p} — 0 is "
                            "the identity footgun and 1 drops the whole timeline"
                        )
            case FaultKind.DUPLICATE:
                _require_int(self.at_index, "at_index", minimum=0)
            case FaultKind.REORDER:
                _require_int(self.window_start, "window_start", minimum=0)
                # A swap needs two stamps, so a reorder window shorter than 2 is a no-op.
                _require_int(self.window_len, "window_len", minimum=2)
            case FaultKind.SKEWED_CLOCK:
                offset = _require_int(self.offset_ns, "offset_ns")
                drift = _require_float(self.drift_ppm, "drift_ppm")
                if offset == 0 and drift == 0.0:
                    raise ValueError(
                        "skewed_clock with offset_ns=0 and drift_ppm=0 is the identity — "
                        "a fault spec that disturbs nothing is a caller bug"
                    )
            case FaultKind.VARIABLE_FRAME_TIME:
                w = _require_float(self.wobble, "wobble")
                if not 0.0 < w < 1.0:
                    raise ValueError(
                        f"wobble must be strictly inside (0, 1), got {w} — 0 is the "
                        "identity footgun and >= 1 lets an interval collapse to nothing"
                    )


# ---------------------------------------------------------------------------------------
# fault application — small pure functions, one per kind (no class tree)
# ---------------------------------------------------------------------------------------


def _checked(value: int, kind: FaultKind) -> int:
    """Bounds-gate one output stamp: raise (never clamp/drop) outside ``[1, 2**63-1]``.

    Failure mode: a fault that clamps an out-of-range result forges a stamp that was never
    scripted — the exact silent repair P-C bans. Out-of-range is a loud error naming the
    fault, deterministic for a given ``(stamps, spec, seed)``.
    """
    if value > MAX_STAMP_NS:
        raise ValueError(
            f"{kind.value} fault would push a stamp past 2**63-1 ({value} > {MAX_STAMP_NS})"
            " — refusing to clamp or drop it (a silently repaired stamp is forged time)"
        )
    if value < MIN_STAMP_NS:
        raise ValueError(
            f"{kind.value} fault would push a stamp below {MIN_STAMP_NS} (got {value}) — "
            "refusing to clamp or drop it (a silently repaired stamp is forged time)"
        )
    return value


def _require_strictly_increasing(stamps: Sequence[int], kind: FaultKind) -> None:
    """Gate for faults whose definition needs a monotonic base (jitter's no-reorder clamp,
    variable-frame-time's interval scaling). A non-monotonic base makes those definitions
    meaningless, so it raises — apply order-breaking faults LAST in a chain."""
    for i in range(1, len(stamps)):
        if stamps[i] <= stamps[i - 1]:
            raise ValueError(
                f"{kind.value} is defined on a strictly increasing base timeline, but "
                f"stamps[{i}]={stamps[i]} <= stamps[{i - 1}]={stamps[i - 1]} — apply "
                "order-breaking faults (reorder/duplicate/burst) after this one, not before"
            )


def _fault_jitter(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """± bounded per-stamp perturbation, clamped so the timeline can NEVER reorder.

    Each stamp moves by a seeded ``randint(-magnitude, +magnitude)``, then is clamped into
    the half-open band between the midpoints to its clean neighbours (band ``i`` ends at
    ``(t[i]+t[i+1])//2``, band ``i+1`` starts one past it), so outputs stay strictly
    increasing by construction — reordering is :data:`FaultKind.REORDER`'s job, and a jitter
    fixture that sometimes reorders would make the bench's per-fault attribution ambiguous.
    The first band is floored at ``MIN_STAMP_NS``; a final stamp pushed past the int64
    ceiling raises via :func:`_checked` (never clamps).
    """
    _require_strictly_increasing(stamps, spec.kind)
    magnitude = cast(int, spec.magnitude_ns)  # validated non-None by __post_init__
    n = len(stamps)
    out: list[int] = []
    for i, t in enumerate(stamps):
        drawn = t + rng.randint(-magnitude, magnitude)
        lo = (stamps[i - 1] + t) // 2 + 1 if i > 0 else max(MIN_STAMP_NS, t - magnitude)
        hi = (t + stamps[i + 1]) // 2 if i < n - 1 else t + magnitude
        out.append(_checked(max(lo, min(hi, drawn)), spec.kind))
    return out


def _fault_fixed_delay(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Constant latency on every stamp — uniformly late, intervals untouched.

    Deliberately invisible to single-stream interval measurement (``compute_jitter`` sees
    identical stats): the tests prove that, and prove the offset-vs-reference instrument
    is what catches it. Overflow past the int64 ceiling raises (never clamps)."""
    delay = cast(int, spec.delay_ns)  # validated non-None by __post_init__
    return [_checked(t + delay, spec.kind) for t in stamps]


def _fault_burst_delay(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """A scripted window shifted by one large delay — camera-freeze / CAN-stall shape.

    Stamps at indices ``[window_start, window_start+window_len)`` gain ``delay_ns``; the
    result typically has a large gap where the stall began and delayed stamps colliding
    with (or passing) on-time ones where it ended — an INVALID sequence, on purpose. A
    window that starts past the end would disturb nothing and raises (silent no-op bench);
    a window running off the end is a stall that never recovers and is allowed.
    """
    delay = cast(int, spec.delay_ns)  # validated non-None by __post_init__
    start = cast(int, spec.window_start)
    length = cast(int, spec.window_len)
    if start >= len(stamps):
        raise ValueError(
            f"burst_delay window_start {start} is past the end of a {len(stamps)}-stamp "
            "sequence — the burst would silently touch nothing (caller bug)"
        )
    end = start + length
    return [
        _checked(t + delay, spec.kind) if start <= i < end else t
        for i, t in enumerate(stamps)
    ]


def _fault_drop(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Remove stamps: every k-th index (deterministic) or seeded-random per stamp.

    Removal is the fault itself — never a silent repair of bad values (inputs were already
    validated). The seeded path draws once per stamp, so the drop pattern is a pure
    function of ``(seed, len(stamps))`` and reproduces exactly.
    """
    if spec.every_k is not None:
        k = spec.every_k
        return [t for i, t in enumerate(stamps) if (i + 1) % k != 0]
    p = cast(float, spec.probability)  # validated non-None by __post_init__
    return [t for t in stamps if rng.uniform(0.0, 1.0) >= p]


def _fault_duplicate(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Repeat the stamp at ``at_index`` — two samples claiming the same instant.

    The duplicate-frame-id shape: a zero-length interval that a uniqueness check (or
    ``compute_jitter``'s ``backwards`` counter, which counts ``dt <= 0``) must flag. An
    index past the end raises — it would silently duplicate nothing."""
    at = cast(int, spec.at_index)  # validated >= 0 by __post_init__
    if at >= len(stamps):
        raise ValueError(
            f"duplicate at_index {at} is past the end of a {len(stamps)}-stamp sequence "
            "— the fault would silently touch nothing (caller bug)"
        )
    out = list(stamps)
    out.insert(at, stamps[at])
    return out


def _fault_reorder(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Swap one seeded adjacent pair inside the window — out-of-order delivery.

    The swap position is ``window_start + randint(0, window_len-2)``, so the disturbed
    timeline is a pure permutation of the input (count- and set-preserving — the signature
    that distinguishes reorder from drop/duplicate in the detection tests). A window
    exceeding the sequence raises: a swap needs both neighbours to exist.
    """
    start = cast(int, spec.window_start)  # validated by __post_init__
    length = cast(int, spec.window_len)
    if start + length > len(stamps):
        raise ValueError(
            f"reorder window [{start}, {start + length}) exceeds the {len(stamps)}-stamp "
            "sequence — a swap needs both neighbours to exist (caller bug)"
        )
    j = start + rng.randint(0, length - 2)
    out = list(stamps)
    out[j], out[j + 1] = out[j + 1], out[j]
    return out


def _fault_skewed_clock(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Constant offset + linear drift anchored at the first stamp — a skewed source clock.

    ``out = t + offset_ns + round(drift_ppm * (t - t0) / 1e6)``: at the first stamp the
    skew is exactly ``offset_ns`` and it diverges linearly from there — the shape of a
    camera/controller clock that was never disciplined to the host. Intervals barely
    change (drift adds ~``drift_ppm`` parts per million per interval), so like FIXED_DELAY
    this is only reliably visible against a reference timeline — the tests prove both.
    Out-of-range results raise (a negative offset can underflow the epoch floor).
    """
    offset = cast(int, spec.offset_ns)  # validated non-None by __post_init__
    drift_ppm = cast(float, spec.drift_ppm)
    if not stamps:
        return []
    t0 = stamps[0]
    return [
        _checked(t + offset + round(drift_ppm * (t - t0) / 1e6), spec.kind) for t in stamps
    ]


def _fault_variable_frame_time(stamps: list[int], spec: FaultSpec, rng: SeededRng) -> list[int]:
    """Per-interval multiplicative wobble — the camera auto-exposure shape.

    Rebuilds the timeline from its intervals: each clean interval scales by a seeded
    ``uniform(1-wobble, 1+wobble)`` and is floored at 1 ns (exposure time breathes, it
    never reverses — order-breaking is REORDER's job), so the output stays strictly
    increasing but is no longer a lattice; the wobble accumulates as phase drift. Requires
    a strictly increasing base (interval scaling is meaningless on a broken timeline).
    """
    _require_strictly_increasing(stamps, spec.kind)
    wobble = cast(float, spec.wobble)  # validated non-None by __post_init__
    if not stamps:
        return []
    out: list[int] = [stamps[0]]
    for i in range(1, len(stamps)):
        interval = stamps[i] - stamps[i - 1]
        factor = rng.uniform(1.0 - wobble, 1.0 + wobble)
        out.append(_checked(out[-1] + max(1, round(interval * factor)), spec.kind))
    return out


_APPLIERS: dict[FaultKind, Callable[[list[int], FaultSpec, SeededRng], list[int]]] = {
    FaultKind.JITTER: _fault_jitter,
    FaultKind.FIXED_DELAY: _fault_fixed_delay,
    FaultKind.BURST_DELAY: _fault_burst_delay,
    FaultKind.DROP: _fault_drop,
    FaultKind.DUPLICATE: _fault_duplicate,
    FaultKind.REORDER: _fault_reorder,
    FaultKind.SKEWED_CLOCK: _fault_skewed_clock,
    FaultKind.VARIABLE_FRAME_TIME: _fault_variable_frame_time,
}


def apply_faults(
    stamps: Sequence[int],
    spec: FaultSpec | Sequence[FaultSpec] | None,
    rng: SeededRng,
) -> list[int]:
    """Apply zero or more fault specs to a stamp timeline — pure and deterministic.

    Failure mode: a chaos bench whose disturbance depends on hidden state (RNG cursor,
    call order) cannot be reproduced or bisected. This function is a pure function of
    ``(stamps, spec, rng.seed)``: every fault draws from its own child stream
    ``rng.spawn(f"fault[<i>]:<kind>")`` — never from ``rng`` directly — so repeated calls
    with the SAME rng object return identical output, and extending a chain never shifts
    an earlier fault's draws.

    ``spec`` may be ``None`` or empty (identity: the validated input values, unchanged —
    the fault-off path the bench diffs against), a single :class:`FaultSpec`, or a sequence
    applied in order. Order matters: faults needing a monotonic base (jitter,
    variable_frame_time) raise if an earlier fault already broke ordering. Input stamps are
    validated individually (each an in-range int — :func:`~timing.stamp.validate_stamp_ns`);
    the output may be an invalid SEQUENCE (that is the point) but every value stays a valid
    nanosecond int — a fault that would leave range raises, never clamps or drops.
    """
    out = [validate_stamp_ns(s, name=f"stamps[{i}]") for i, s in enumerate(stamps)]
    if spec is None:
        return out
    specs: list[FaultSpec] = [spec] if isinstance(spec, FaultSpec) else list(spec)
    for i, one in enumerate(specs):
        if not isinstance(one, FaultSpec):
            raise ValueError(
                f"spec[{i}] must be a FaultSpec, got {type(one).__name__} {one!r} — an "
                "unvalidated fault profile cannot be reproduced or attributed"
            )
        out = _APPLIERS[one.kind](out, one, rng.spawn(f"fault[{i}]:{one.kind.value}"))
    return out


# ---------------------------------------------------------------------------------------
# canonical bench fixtures — LatticeClock base + named FaultSpecs (reused by C3/C7)
# ---------------------------------------------------------------------------------------


def lattice_stamps(
    n_stamps: int, *, start_ns: int = 1_000_000_000, period_ns: int = 10_000_000
) -> list[int]:
    """The clean reference timeline: ``n_stamps`` ticks of a :class:`LatticeClock`.

    The zero-jitter base every fixture disturbs and every detection test diffs against.
    ``start_ns``/``period_ns`` are validated by the clock itself; ``n_stamps`` must be a
    non-negative int (a negative count is a caller bug, not an empty timeline).
    """
    if isinstance(n_stamps, bool) or not isinstance(n_stamps, int) or n_stamps < 0:
        raise ValueError(f"n_stamps must be an int >= 0, got {n_stamps!r}")
    clock = LatticeClock(start_ns, period_ns)
    return [clock() for _ in range(n_stamps)]


@dataclass(frozen=True, slots=True)
class BenchFixture:
    """One canonical disturbed timeline: LatticeClock base + named FaultSpec + fixed seed.

    Failure mode: ad-hoc chaos scattered through C3/C7 tests would drift apart — each suite
    "testing chaos" against a different, unnameable disturbance. A fixture pins the whole
    recipe as ONE frozen value (base lattice, fault, seed), so :meth:`clean` /
    :meth:`disturbed` rebuild byte-identical timelines anywhere, and a bench report can
    cite the fixture by name.
    """

    name: str
    start_ns: int
    period_ns: int
    n_stamps: int
    spec: FaultSpec
    seed: int

    def __post_init__(self) -> None:
        # Fail loud at construction: a fixture that exists can always build.
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"name must be a non-empty str, got {self.name!r}")
        validate_stamp_ns(self.start_ns, name="start_ns")
        validate_stamp_ns(self.period_ns, name="period_ns")
        # < 2 stamps has no interval, hence no timing signal to disturb or measure.
        bad_count = isinstance(self.n_stamps, bool) or not isinstance(self.n_stamps, int)
        if bad_count or self.n_stamps < 2:
            raise ValueError(f"n_stamps must be an int >= 2, got {self.n_stamps!r}")
        if not isinstance(self.spec, FaultSpec):
            raise ValueError(
                f"spec must be a FaultSpec, got {type(self.spec).__name__} {self.spec!r}"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError(f"seed must be an int, got {self.seed!r}")

    def clean(self) -> list[int]:
        """The undisturbed base lattice — the reference the detection instruments diff against."""
        return lattice_stamps(self.n_stamps, start_ns=self.start_ns, period_ns=self.period_ns)

    def disturbed(self) -> list[int]:
        """The disturbed timeline — deterministic: every call rebuilds the identical list."""
        return apply_faults(self.clean(), self.spec, SeededRng(self.seed))


#: Mild USB-CAN arrival jitter on a 100 Hz telemetry lattice: ±0.2 ms per stamp. Measurably
#: non-zero jitter, yet inside the default 2 ms-p99 JitterBudget — the "disturbed but still
#: exportable" reference case.
CAN_JITTER_MILD = BenchFixture(
    name="can_jitter_mild",
    start_ns=1_000_000_000,
    period_ns=10_000_000,
    n_stamps=200,
    spec=FaultSpec(kind=FaultKind.JITTER, magnitude_ns=200_000),
    seed=104,
)

#: A ~30 fps camera whose frame time breathes ±4% around 33.33 ms (auto-exposure shape):
#: monotonic, measurably wobbly, still within the default budget.
CAMERA_VARIABLE_33MS = BenchFixture(
    name="camera_variable_33ms",
    start_ns=1_000_000_000,
    period_ns=33_333_333,
    n_stamps=90,
    spec=FaultSpec(kind=FaultKind.VARIABLE_FRAME_TIME, wobble=0.04),
    seed=104,
)

#: A 200 ms stall in the middle of a 100 Hz stream (camera freeze / CAN bus stall): 20
#: stamps delivered 200 ms late. Produces BOTH a dropout-scale gap and backwards intervals
#: — the must-quarantine reference case.
BURST_STALL_200MS = BenchFixture(
    name="burst_stall_200ms",
    start_ns=1_000_000_000,
    period_ns=10_000_000,
    n_stamps=200,
    spec=FaultSpec(
        kind=FaultKind.BURST_DELAY, window_start=100, window_len=20, delay_ns=200_000_000
    ),
    seed=104,
)

#: A source clock 5 ms ahead of the host and drifting +500 ppm (~1 ms/2 s): intervals look
#: clean in isolation — only the offset-vs-reference instrument catches it. The reference
#: case for why alignment needs a reference timeline, not just interval stats.
SKEWED_SOURCE_CLOCK = BenchFixture(
    name="skewed_source_clock",
    start_ns=1_000_000_000,
    period_ns=10_000_000,
    n_stamps=200,
    spec=FaultSpec(kind=FaultKind.SKEWED_CLOCK, offset_ns=5_000_000, drift_ppm=500.0),
    seed=104,
)

#: The canonical fixtures by name — the registry C3/C7 iterate to prove align-or-quarantine.
BENCH_FIXTURES: dict[str, BenchFixture] = {
    fixture.name: fixture
    for fixture in (CAN_JITTER_MILD, CAMERA_VARIABLE_33MS, BURST_STALL_200MS, SKEWED_SOURCE_CLOCK)
}
