"""Tests for the P-C/C2 timestamp normalization layer (``host/timing/normalize.py``).

The failure mode under test IS the core invariant: **silent repair — fake synchronization
poisoning training data undetectably.** Every test here FAILS if the implementation
clamps, reorders, drops, guesses or quietly "fixes" a stamp:

* **Ordering preserved:** records come back in INPUT order (never re-sorted); clean
  monotone input yields clean records whose ``normalized_ns`` preserve order.
* **Idempotence:** normalizing twice is identity; feeding clean normalized values back
  through a MONOTONIC normalizer reproduces the same records exactly.
* **Flagged-not-fixed:** a backwards stamp survives WITH its flag, ``normalized_ns=None``
  and the ORIGINAL stamp un-repaired; nothing is dropped; later good stamps still clean.
* **Per-class invalid rejection:** bool/non-int/0/negative/>int64 raws raise via C1's
  validator; WALL is rejected at the Normalizer boundary; unknown flag tokens are refused.
* **SOURCE skew:** ``normalized == raw + offset`` exactly with ``skew_ns`` recorded;
  overflow/underflow is FLAGGED, never clamped; no offset ⇒ ``UNKNOWN_SKEW`` everywhere.
* **TimingRecord invariants:** clean ⊕ flagged exclusivity, MONOTONIC identity, exact
  ``to_dict``/``from_dict`` round-trip (incl. flags, incl. through JSON).
"""
from __future__ import annotations

import json
import random

import pytest

from timing import (
    MAX_STAMP_NS,
    MIN_STAMP_NS,
    ClockDomain,
    NormalizationFlag,
    Normalizer,
    Stamp,
    TimingRecord,
)

BACKWARDS = NormalizationFlag.BACKWARDS_IN_SOURCE
UNKNOWN = NormalizationFlag.UNKNOWN_SKEW
OUT_OF_RANGE = NormalizationFlag.SKEW_OUT_OF_RANGE


def _mono(raw_ns: int) -> Stamp:
    return Stamp(raw_ns, ClockDomain.MONOTONIC)


def _src(raw_ns: int) -> Stamp:
    return Stamp(raw_ns, ClockDomain.SOURCE)


def _strictly_increasing(rng: random.Random, n: int) -> list[int]:
    """A random strictly-increasing valid stamp sequence (property-test input)."""
    stamps: list[int] = []
    current = rng.randint(MIN_STAMP_NS, 10**12)
    for _ in range(n):
        stamps.append(current)
        current += rng.randint(1, 10**9)
    return stamps


# -- NormalizationFlag: stable serialization tokens ---------------------------------------


def test_flag_tokens_are_stable() -> None:
    """The tokens are on-disk contract — this test failing means a versioned decision."""
    assert NormalizationFlag.BACKWARDS_IN_SOURCE.value == "backwards_in_source"
    assert NormalizationFlag.UNKNOWN_SKEW.value == "unknown_skew"
    assert NormalizationFlag.SKEW_OUT_OF_RANGE.value == "skew_out_of_range"
    # StrEnum: the member IS its token (what lands in JSON/metadata without .value).
    assert f"{NormalizationFlag.UNKNOWN_SKEW}" == "unknown_skew"


def test_no_catch_all_flag() -> None:
    """Exactly the tokens the normalizer emits — no vague 'other' to hide failures in."""
    assert {m.value for m in NormalizationFlag} == {
        "backwards_in_source",
        "unknown_skew",
        "skew_out_of_range",
    }


# -- TimingRecord: clean ⊕ flagged exclusivity ---------------------------------------------


def test_clean_record_constructs_and_is_a_value() -> None:
    rec = TimingRecord(original=_mono(100), normalized_ns=100)
    assert rec.flags == () and rec.skew_ns is None
    assert hash(rec) == hash(TimingRecord(original=_mono(100), normalized_ns=100))


def test_neither_clean_nor_flagged_rejected() -> None:
    """None without a reason token is a silent hole in the timeline."""
    with pytest.raises(ValueError, match="without a reason token"):
        TimingRecord(original=_mono(100), normalized_ns=None, flags=())


def test_both_clean_and_flagged_rejected() -> None:
    """A 'normalized anyway' value next to a flag is exactly the silent repair we forbid."""
    with pytest.raises(ValueError, match="clean or flagged"):
        TimingRecord(original=_mono(100), normalized_ns=100, flags=(BACKWARDS,))


def test_flagged_record_constructs() -> None:
    rec = TimingRecord(original=_mono(100), normalized_ns=None, flags=(BACKWARDS,))
    assert rec.normalized_ns is None and rec.flags == (BACKWARDS,)


# -- TimingRecord: MONOTONIC identity + skew invariants ------------------------------------


def test_monotonic_identity_enforced() -> None:
    """A clean MONOTONIC record whose normalized differs from raw is silent repair."""
    with pytest.raises(ValueError, match="MONOTONIC identity violated"):
        TimingRecord(original=_mono(100), normalized_ns=101)


def test_monotonic_original_rejects_skew() -> None:
    """A skew on a monotonic stamp claims a conversion that never happened."""
    with pytest.raises(ValueError, match="MONOTONIC"):
        TimingRecord(original=_mono(100), normalized_ns=100, skew_ns=0)


def test_unknown_skew_flag_contradicts_recorded_skew() -> None:
    with pytest.raises(ValueError, match="claim not to know"):
        TimingRecord(original=_src(100), normalized_ns=None, flags=(UNKNOWN,), skew_ns=5)


def test_source_record_carries_skew() -> None:
    rec = TimingRecord(original=_src(100), normalized_ns=150, skew_ns=50)
    assert rec.normalized_ns == 150 and rec.skew_ns == 50
    # Zero and negative skews are legitimate offsets (source clock may lead the host).
    assert TimingRecord(original=_src(100), normalized_ns=40, skew_ns=-60).skew_ns == -60
    assert TimingRecord(original=_src(100), normalized_ns=100, skew_ns=0).skew_ns == 0


# -- TimingRecord: field validation --------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, 2**63])
def test_normalized_ns_validated_per_class(bad: object) -> None:
    """normalized_ns goes through C1's validator — every rejection class, by name."""
    with pytest.raises(ValueError, match="normalized_ns"):
        TimingRecord(original=_src(100), normalized_ns=bad, skew_ns=1)  # type: ignore[arg-type]


def test_original_must_be_a_stamp() -> None:
    """A bare int has no clock domain — the record cannot audit it."""
    with pytest.raises(ValueError, match="must be a Stamp"):
        TimingRecord(original=100, normalized_ns=100)  # type: ignore[arg-type]


def test_flags_must_be_a_tuple() -> None:
    """A mutable flags container would let a flagged record be quietly 'cleaned'."""
    with pytest.raises(ValueError, match="must be a tuple"):
        TimingRecord(original=_mono(1), normalized_ns=None, flags=[BACKWARDS])  # type: ignore[arg-type]


def test_flag_members_must_be_normalization_flags() -> None:
    """The raw token string is NOT a flag — labeling must be explicit, never coerced."""
    with pytest.raises(ValueError, match=r"flags\[0\]"):
        TimingRecord(
            original=_mono(1), normalized_ns=None, flags=("backwards_in_source",)  # type: ignore[arg-type]
        )


def test_duplicate_flags_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        TimingRecord(original=_mono(1), normalized_ns=None, flags=(BACKWARDS, BACKWARDS))


@pytest.mark.parametrize("bad_skew", [True, 1.5, MAX_STAMP_NS + 1, -(MAX_STAMP_NS + 1)])
def test_skew_ns_validated_per_class(bad_skew: object) -> None:
    with pytest.raises(ValueError, match="skew_ns"):
        TimingRecord(original=_src(100), normalized_ns=150, skew_ns=bad_skew)  # type: ignore[arg-type]


def test_skew_bounds_accepted_exactly() -> None:
    """±(2**63-1) are the inclusive skew limits — both must construct."""
    rec = TimingRecord(original=_src(1), normalized_ns=MAX_STAMP_NS, skew_ns=MAX_STAMP_NS - 1)
    assert rec.skew_ns == MAX_STAMP_NS - 1
    rec2 = TimingRecord(
        original=_src(MAX_STAMP_NS),
        normalized_ns=None,
        flags=(OUT_OF_RANGE,),
        skew_ns=-MAX_STAMP_NS,
    )
    assert rec2.skew_ns == -MAX_STAMP_NS
    # Symmetric +MAX bound: raw=1 + skew=+MAX overflows the stamp range, so the record is
    # honestly flagged — but the extreme positive offset itself must be representable.
    rec3 = TimingRecord(
        original=_src(1),
        normalized_ns=None,
        flags=(OUT_OF_RANGE,),
        skew_ns=MAX_STAMP_NS,
    )
    assert rec3.skew_ns == MAX_STAMP_NS


def test_clean_source_record_requires_skew() -> None:
    """A clean SOURCE record without a recorded offset is unauditable — must not construct.

    The Normalizer never emits one (SOURCE without offset is flagged unknown_skew), so this
    guards the deserialization/hand-construction path: from_dict must not be able to load a
    source-domain normalization whose applied offset is unrecorded.
    """
    with pytest.raises(ValueError, match="clean SOURCE record without skew_ns"):
        TimingRecord(original=_src(100), normalized_ns=150, skew_ns=None)


def test_clean_source_record_normalized_must_be_rederivable() -> None:
    """normalized_ns must equal raw + skew exactly — anything else is forged normalization."""
    with pytest.raises(ValueError, match="SOURCE consistency violated"):
        TimingRecord(original=_src(100), normalized_ns=151, skew_ns=50)  # 100+50 != 151
    # And the exact arithmetic constructs fine (the invariant, not a blanket rejection).
    ok = TimingRecord(original=_src(100), normalized_ns=150, skew_ns=50)
    assert ok.normalized_ns == ok.original.raw_ns + (ok.skew_ns or 0)


# -- TimingRecord: exact serialization round-trip ------------------------------------------


@pytest.mark.parametrize(
    "rec",
    [
        TimingRecord(original=_mono(100), normalized_ns=100),
        TimingRecord(original=_mono(MAX_STAMP_NS), normalized_ns=MAX_STAMP_NS),
        TimingRecord(original=_mono(50), normalized_ns=None, flags=(BACKWARDS,)),
        TimingRecord(original=_src(100), normalized_ns=170, skew_ns=70),
        TimingRecord(original=_src(100), normalized_ns=None, flags=(UNKNOWN,)),
        TimingRecord(
            original=_src(9),
            normalized_ns=None,
            flags=(BACKWARDS, OUT_OF_RANGE),
            skew_ns=-100,
        ),
    ],
)
def test_to_dict_from_dict_round_trips_exactly(rec: TimingRecord) -> None:
    d = rec.to_dict()
    assert TimingRecord.from_dict(d) == rec
    # And through actual JSON text (the export path) — still exact, flags included.
    assert TimingRecord.from_dict(json.loads(json.dumps(d))) == rec


def test_to_dict_shape_is_stable() -> None:
    """The serialized keys/tokens are contract — downstream metadata reads them."""
    rec = TimingRecord(original=_src(100), normalized_ns=None, flags=(UNKNOWN,))
    assert rec.to_dict() == {
        "original": {"raw_ns": 100, "domain": "source"},
        "normalized_ns": None,
        "flags": ["unknown_skew"],
        "skew_ns": None,
    }


def test_from_dict_rejects_unknown_flag_token() -> None:
    """An unknown token is refused, never guessed — dropping it would un-flag a record."""
    d = TimingRecord(original=_mono(50), normalized_ns=None, flags=(BACKWARDS,)).to_dict()
    d["flags"] = ["time_travel"]
    with pytest.raises(ValueError, match="unknown normalization-flag token"):
        TimingRecord.from_dict(d)


def test_from_dict_rejects_missing_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        TimingRecord.from_dict({"normalized_ns": 1})


def test_from_dict_rejects_malformed_fields() -> None:
    good = TimingRecord(original=_mono(100), normalized_ns=100).to_dict()
    for key, bad, match in [
        ("original", 100, "must be a stamp dict"),
        ("flags", "unknown_skew", "must be a list"),  # a str would iterate as chars
        ("flags", [3], r"flags\[0\] must be a str"),
        ("normalized_ns", 1.5, "normalized_ns"),
        ("skew_ns", True, "skew_ns"),
    ]:
        d = dict(good)
        d[key] = bad
        with pytest.raises(ValueError, match=match):
            TimingRecord.from_dict(d)


# -- Normalizer: construction boundary ------------------------------------------------------


def test_wall_rejected_at_the_boundary() -> None:
    """Wall time is provenance, never a normalizable timeline — loud, at construction."""
    with pytest.raises(ValueError, match="never a normalizable timeline"):
        Normalizer(ClockDomain.WALL)


def test_foreign_domain_rejected() -> None:
    with pytest.raises(ValueError, match="must be a ClockDomain"):
        Normalizer("monotonic")  # type: ignore[arg-type]


def test_offset_on_monotonic_rejected() -> None:
    """A skewed 'monotonic' input is not monotonic — label it SOURCE instead."""
    with pytest.raises(ValueError, match="only meaningful for SOURCE"):
        Normalizer(ClockDomain.MONOTONIC, offset_ns=5)


@pytest.mark.parametrize("bad_offset", [True, 2.5, MAX_STAMP_NS + 1, -(MAX_STAMP_NS + 1)])
def test_bad_offset_rejected_at_construction(bad_offset: object) -> None:
    with pytest.raises(ValueError, match="offset_ns"):
        Normalizer(ClockDomain.SOURCE, offset_ns=bad_offset)  # type: ignore[arg-type]


def test_normalizer_exposes_its_source_description() -> None:
    n = Normalizer(ClockDomain.SOURCE, offset_ns=-40)
    assert n.domain is ClockDomain.SOURCE and n.offset_ns == -40
    assert Normalizer(ClockDomain.MONOTONIC).offset_ns is None


# -- Normalizer: MONOTONIC identity + ordering ----------------------------------------------


def test_monotonic_input_is_identity_in_input_order() -> None:
    stamps = [100, 250, 400, MAX_STAMP_NS]
    records = Normalizer(ClockDomain.MONOTONIC).normalize(stamps)
    assert [r.original.raw_ns for r in records] == stamps  # input order, nothing dropped
    assert [r.normalized_ns for r in records] == stamps  # identity, exact ints
    assert all(r.flags == () and r.skew_ns is None for r in records)
    assert all(r.original.domain is ClockDomain.MONOTONIC for r in records)


def test_ordering_preserved_property() -> None:
    """Property-style: random monotone input ⇒ clean records, order preserved exactly."""
    rng = random.Random(0xC2)
    for _ in range(50):
        stamps = _strictly_increasing(rng, rng.randint(1, 40))
        records = Normalizer(ClockDomain.MONOTONIC).normalize(stamps)
        assert len(records) == len(stamps)
        assert [r.normalized_ns for r in records] == stamps  # == input ⇒ same order
        assert all(r.flags == () for r in records)


def test_idempotence_normalize_twice_is_identity() -> None:
    """normalize(normalize(xs)) == normalize(xs) for clean monotonic input."""
    rng = random.Random(0xC2C2)
    normalizer = Normalizer(ClockDomain.MONOTONIC)
    for _ in range(20):
        stamps = _strictly_increasing(rng, 25)
        once = normalizer.normalize(stamps)
        renormalized = normalizer.normalize(
            [r.normalized_ns for r in once if r.normalized_ns is not None]
        )
        assert renormalized == once  # same records exactly — re-normalizing changes nothing
        assert normalizer.normalize(stamps) == once  # and the call itself is stateless


# -- Normalizer: flagged, never fixed --------------------------------------------------------


def test_backwards_stamp_flagged_not_fixed() -> None:
    """The proof test: bad input survives WITH its flag — never repaired or dropped."""
    stamps = [100, 200, 150, 300]
    records = Normalizer(ClockDomain.MONOTONIC).normalize(stamps)
    assert len(records) == len(stamps)  # nothing dropped
    assert [r.original.raw_ns for r in records] == stamps  # nothing reordered/altered
    bad = records[2]
    assert bad.flags == (BACKWARDS,)
    assert bad.normalized_ns is None  # flagged, no value published
    assert bad.original == _mono(150)  # the ORIGINAL survives un-repaired
    # Subsequent good stamps still normalize cleanly.
    assert records[3].flags == () and records[3].normalized_ns == 300


def test_duplicate_stamp_is_backwards() -> None:
    """<= previous: a duplicate is flagged too — repeated time is forged time."""
    records = Normalizer(ClockDomain.MONOTONIC).normalize([100, 100, 101])
    assert records[1].flags == (BACKWARDS,) and records[1].normalized_ns is None
    assert records[0].flags == () and records[2].flags == ()


def test_backwards_run_stays_flagged_until_past_high_water() -> None:
    """After a source-clock reset, stamps stay flagged until the previous clean
    high-water mark is passed — accepting the post-reset run would splice two
    incompatible timelines together."""
    records = Normalizer(ClockDomain.MONOTONIC).normalize([100, 200, 150, 180, 250])
    assert [r.flags for r in records] == [(), (), (BACKWARDS,), (BACKWARDS,), ()]
    assert records[4].normalized_ns == 250


@pytest.mark.parametrize("domain", [ClockDomain.MONOTONIC, ClockDomain.SOURCE])
@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "100", 2**63])
def test_invalid_raw_values_raise_per_class(domain: ClockDomain, bad: object) -> None:
    """Invalid raws are construction-time ValueErrors via C1's validator, named by index."""
    normalizer = Normalizer(domain)
    with pytest.raises(ValueError, match=r"raw_stamps_ns\[1\]"):
        normalizer.normalize([10, bad])  # type: ignore[list-item]


# -- Normalizer: SOURCE with a known offset --------------------------------------------------


def test_source_offset_applied_exactly_with_skew_recorded() -> None:
    records = Normalizer(ClockDomain.SOURCE, offset_ns=1_000).normalize([10, 20, 30])
    assert [r.normalized_ns for r in records] == [1_010, 1_020, 1_030]  # raw+offset exactly
    assert all(r.skew_ns == 1_000 for r in records)  # applied skew is auditable
    assert all(r.original.domain is ClockDomain.SOURCE for r in records)


def test_source_offset_property_exact_and_ordered() -> None:
    """Property-style: normalized == raw + offset for every clean record, order kept."""
    rng = random.Random(0x50FF)
    for _ in range(50):
        offset = rng.randint(-(10**9), 10**9)
        stamps = _strictly_increasing(rng, 20)
        if stamps[0] + offset < MIN_STAMP_NS:  # keep this case clean (underflow tested below)
            offset = -stamps[0] + 1
        records = Normalizer(ClockDomain.SOURCE, offset_ns=offset).normalize(stamps)
        assert [r.normalized_ns for r in records] == [s + offset for s in stamps]
        assert all(r.skew_ns == offset for r in records)


def test_source_overflow_flagged_never_clamped() -> None:
    """A stamp whose mapped value passes int64 is flagged — a clamp would forge time."""
    offset = 100
    stamps = [MAX_STAMP_NS - 150, MAX_STAMP_NS - 100, MAX_STAMP_NS - 50]
    records = Normalizer(ClockDomain.SOURCE, offset_ns=offset).normalize(stamps)
    assert records[0].normalized_ns == MAX_STAMP_NS - 50
    assert records[1].normalized_ns == MAX_STAMP_NS  # the exact ceiling is still valid
    bad = records[2]
    assert bad.flags == (OUT_OF_RANGE,)
    assert bad.normalized_ns is None  # NOT clamped to MAX_STAMP_NS
    assert bad.skew_ns == offset  # the attempted skew stays auditable
    assert bad.original.raw_ns == MAX_STAMP_NS - 50  # original untouched


def test_source_underflow_flagged_never_clamped() -> None:
    """A negative offset that maps below 1 is flagged — 0/negative stamps cannot exist."""
    records = Normalizer(ClockDomain.SOURCE, offset_ns=-100).normalize([50, 101, 200])
    assert records[0].flags == (OUT_OF_RANGE,) and records[0].normalized_ns is None
    assert records[1].normalized_ns == 1  # the exact floor is still valid
    assert records[2].normalized_ns == 100


def test_source_backwards_still_flagged_with_offset() -> None:
    records = Normalizer(ClockDomain.SOURCE, offset_ns=5).normalize([100, 90, 200])
    assert records[1].flags == (BACKWARDS,)
    assert records[1].normalized_ns is None and records[1].skew_ns == 5
    assert records[2].normalized_ns == 205


def test_source_backwards_and_out_of_range_both_flagged() -> None:
    """Two independent failures ⇒ two reason tokens — provenance is never collapsed."""
    records = Normalizer(ClockDomain.SOURCE, offset_ns=-100).normalize([500, 50])
    assert records[1].flags == (BACKWARDS, OUT_OF_RANGE)
    assert records[1].normalized_ns is None


def test_source_clean_output_feeds_monotonic_normalizer_as_identity() -> None:
    """Idempotence across domains: once on the monotonic timeline, always identity."""
    source_records = Normalizer(ClockDomain.SOURCE, offset_ns=7).normalize([10, 20, 30])
    values = [r.normalized_ns for r in source_records if r.normalized_ns is not None]
    mono_records = Normalizer(ClockDomain.MONOTONIC).normalize(values)
    assert [r.normalized_ns for r in mono_records] == values
    assert all(r.flags == () for r in mono_records)


# -- Normalizer: SOURCE without an offset ----------------------------------------------------


def test_source_without_offset_flags_every_record() -> None:
    """No offset ⇒ the normalized value cannot be computed and is never guessed."""
    stamps = [10, 20, 30]
    records = Normalizer(ClockDomain.SOURCE).normalize(stamps)
    assert len(records) == len(stamps)
    for record, raw in zip(records, stamps, strict=True):
        assert UNKNOWN in record.flags
        assert record.normalized_ns is None  # never guessed
        assert record.skew_ns is None
        assert record.original == _src(raw)  # originals kept, in order


def test_source_without_offset_backwards_gets_both_flags() -> None:
    records = Normalizer(ClockDomain.SOURCE).normalize([100, 90])
    assert records[0].flags == (UNKNOWN,)
    assert records[1].flags == (BACKWARDS, UNKNOWN)


# -- End-to-end: normalizer output round-trips through serialization -------------------------


def test_normalizer_output_round_trips_through_json() -> None:
    """Every record a normalizer can emit survives to_dict → JSON → from_dict exactly."""
    records = list(Normalizer(ClockDomain.SOURCE, offset_ns=-100).normalize([500, 50, 600]))
    records += Normalizer(ClockDomain.MONOTONIC).normalize([100, 90, 200])
    records += Normalizer(ClockDomain.SOURCE).normalize([10, 5])
    payload = json.dumps([r.to_dict() for r in records])
    restored = [TimingRecord.from_dict(d) for d in json.loads(payload)]
    assert restored == records


def test_empty_sequence_yields_empty_records() -> None:
    """No stamps ⇒ no records — an empty source is not an error, just empty."""
    assert Normalizer(ClockDomain.MONOTONIC).normalize([]) == ()
