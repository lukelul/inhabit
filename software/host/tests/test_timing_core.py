"""Tests for the P-C/C1 clock & timebase core (``host/timing``).

The failure modes under test are the P-C invariants themselves — each test FAILS if the
implementation guesses, repeats, clamps, coerces or reorders time:

* **Monotonicity:** ``LatticeClock`` strictly increases on the exact lattice;
  ``ScriptedClock`` replays exactly its script; a non-increasing script is a constructor
  error, and exhaustion is a loud typed error (never a repeated/clamped stamp).
* **Ordering:** same-domain stamps order by ``raw_ns`` (property-checked against int
  ordering); ordering across DIFFERENT domains raises — cross-domain order is meaningless
  until C2 normalizes.
* **Boundaries:** 0, negative, bool, non-int and > 2**63-1 are each rejected with a
  distinct message; 1 and 2**63-1 are accepted exactly.
* **Wall-vs-monotonic separation:** ``require_monotonic`` is a hard gate (ValueError, not
  a warning) and passes the exact int through for MONOTONIC.
* **Serialization:** ``to_dict``/``from_dict`` round-trips exactly (incl. through JSON);
  an unknown domain token is rejected, never guessed.
* **Determinism:** two identically-constructed clocks emit byte-identical sequences.
* **Seam compatibility:** both clocks satisfy the existing ``ClockNs`` seam and drive
  ``SimProprioSource`` without edits to the SensorSource ABC.
"""
from __future__ import annotations

import itertools
import json
import random

import pytest

from sensors.interface import ClockNs
from sensors.sim_proprio import SimProprioSource
from timing import (
    MAX_STAMP_NS,
    MIN_STAMP_NS,
    ClockDomain,
    ClockExhausted,
    LatticeClock,
    ScriptedClock,
    Stamp,
    require_monotonic,
    validate_stamp_ns,
)

# -- ClockDomain: stable serialization tokens ------------------------------------------


def test_domain_tokens_are_stable() -> None:
    """The tokens are on-disk contract — this test failing means a versioned decision."""
    assert ClockDomain.MONOTONIC.value == "monotonic"
    assert ClockDomain.WALL.value == "wall"
    assert ClockDomain.SOURCE.value == "source"
    # StrEnum: the member IS its token (what lands in JSON/metadata without .value).
    assert f"{ClockDomain.MONOTONIC}" == "monotonic"


# -- Stamp: boundary/overflow validation ------------------------------------------------


@pytest.mark.parametrize("domain", list(ClockDomain))
def test_zero_stamp_rejected_every_domain(domain: ClockDomain) -> None:
    """0 is the 'never stamped' sentinel — no domain may carry it."""
    with pytest.raises(ValueError, match="never stamped"):
        Stamp(0, domain)


@pytest.mark.parametrize("domain", list(ClockDomain))
def test_negative_stamp_rejected_every_domain(domain: ClockDomain) -> None:
    with pytest.raises(ValueError, match="backwards or underflowed"):
        Stamp(-1, domain)


def test_bool_stamp_rejected_as_bool_not_as_int() -> None:
    """bool is an int subclass — it must be rejected AS bool (True would forge 1 ns)."""
    with pytest.raises(ValueError, match="bool"):
        Stamp(True, ClockDomain.MONOTONIC)
    with pytest.raises(ValueError, match="bool"):
        Stamp(False, ClockDomain.MONOTONIC)  # rejected as bool, not as zero


@pytest.mark.parametrize("bad", [1.5, 1.0, "100", None])
def test_non_int_stamp_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="int nanosecond count"):
        Stamp(bad, ClockDomain.MONOTONIC)  # type: ignore[arg-type]


def test_overflow_stamp_rejected() -> None:
    with pytest.raises(ValueError, match="int64"):
        Stamp(2**63, ClockDomain.MONOTONIC)


@pytest.mark.parametrize("domain", list(ClockDomain))
def test_boundary_values_accepted(domain: ClockDomain) -> None:
    """1 and 2**63-1 are the inclusive limits — both must construct exactly."""
    assert Stamp(MIN_STAMP_NS, domain).raw_ns == 1
    assert Stamp(MAX_STAMP_NS, domain).raw_ns == 2**63 - 1


def test_rejection_messages_are_distinct() -> None:
    """Each failure class has its own greppable message (never one vague error)."""
    messages = []
    for bad in (0, -5, True, 2.5, 2**63):
        with pytest.raises(ValueError) as exc:
            validate_stamp_ns(bad)
        messages.append(str(exc.value))
    assert len(set(messages)) == 5


def test_validate_stamp_ns_names_the_field() -> None:
    """The ``name`` kwarg labels the offending field so clock errors point at the arg."""
    with pytest.raises(ValueError, match="start_ns"):
        validate_stamp_ns(0, name="start_ns")


def test_foreign_domain_rejected() -> None:
    """A plain string is NOT a domain — labeling must be explicit, never coerced."""
    with pytest.raises(ValueError, match="must be a ClockDomain"):
        Stamp(1, "monotonic")  # type: ignore[arg-type]


# -- Stamp: ordering (same domain only) --------------------------------------------------


def test_same_domain_orders_by_raw_ns() -> None:
    a = Stamp(100, ClockDomain.MONOTONIC)
    b = Stamp(200, ClockDomain.MONOTONIC)
    assert a < b and a <= b and b > a and b >= a
    assert not (b < a) and not (a > b)
    assert a <= Stamp(100, ClockDomain.MONOTONIC)
    assert sorted([b, a]) == [a, b]  # sorted() works within one domain


def test_ordering_matches_int_ordering_property() -> None:
    """Property-style: for random valid pairs, Stamp order == int order, all four ops."""
    rng = random.Random(0xC1)
    for _ in range(200):
        x = rng.randint(MIN_STAMP_NS, MAX_STAMP_NS)
        y = rng.randint(MIN_STAMP_NS, MAX_STAMP_NS)
        sx, sy = Stamp(x, ClockDomain.SOURCE), Stamp(y, ClockDomain.SOURCE)
        assert (sx < sy) == (x < y)
        assert (sx <= sy) == (x <= y)
        assert (sx > sy) == (x > y)
        assert (sx >= sy) == (x >= y)


@pytest.mark.parametrize("op", ["lt", "le", "gt", "ge"])
def test_cross_domain_ordering_raises(op: str) -> None:
    """wall < monotonic is noise, not a boolean — every ordering op must raise."""
    wall = Stamp(100, ClockDomain.WALL)
    mono = Stamp(200, ClockDomain.MONOTONIC)
    with pytest.raises(ValueError, match="cannot order stamps across clock domains"):
        getattr(wall, f"__{op}__")(mono)


def test_ordering_against_bare_int_raises_typeerror() -> None:
    """A bare int has no domain — comparing against one must fail loud, not coerce."""
    s = Stamp(100, ClockDomain.MONOTONIC)
    with pytest.raises(TypeError, match="unorderable"):
        s < 200  # noqa: B015  # the raise IS the assertion


def test_cross_domain_equality_is_false_not_an_error() -> None:
    """Equality asks 'same labeled value?' — a legal question across domains (=> False)."""
    assert Stamp(100, ClockDomain.WALL) != Stamp(100, ClockDomain.MONOTONIC)
    assert Stamp(100, ClockDomain.WALL) == Stamp(100, ClockDomain.WALL)
    # Frozen value semantics: hashable, so stamps can key sets/dicts.
    assert len({Stamp(1, d) for d in ClockDomain}) == 3


# -- Wall-vs-monotonic separation ---------------------------------------------------------


def test_require_monotonic_passes_exact_int_through() -> None:
    got = require_monotonic(Stamp(MAX_STAMP_NS, ClockDomain.MONOTONIC))
    assert got == MAX_STAMP_NS
    assert type(got) is int


@pytest.mark.parametrize("domain", [ClockDomain.WALL, ClockDomain.SOURCE])
def test_require_monotonic_rejects_non_monotonic(domain: ClockDomain) -> None:
    """A wall/source stamp in a monotonic slot is a LOUD error, never a warning."""
    with pytest.raises(ValueError, match="monotonic stamp required"):
        require_monotonic(Stamp(123, domain))


def test_require_monotonic_rejects_bare_int() -> None:
    with pytest.raises(TypeError, match="needs a Stamp"):
        require_monotonic(123)  # type: ignore[arg-type]


# -- Serialization: exact round-trip ------------------------------------------------------


@pytest.mark.parametrize("domain", list(ClockDomain))
@pytest.mark.parametrize("raw", [MIN_STAMP_NS, 1_000_000_007, MAX_STAMP_NS])
def test_to_dict_from_dict_round_trips_exactly(raw: int, domain: ClockDomain) -> None:
    s = Stamp(raw, domain)
    d = s.to_dict()
    assert d == {"raw_ns": raw, "domain": domain.value}  # stable token, exact int
    assert Stamp.from_dict(d) == s
    # And through actual JSON text (the export path) — still exact, incl. 2**63-1.
    assert Stamp.from_dict(json.loads(json.dumps(d))) == s


def test_from_dict_rejects_unknown_domain_token() -> None:
    """An unknown token is rejected, never guessed/defaulted."""
    with pytest.raises(ValueError, match="unknown clock-domain token"):
        Stamp.from_dict({"raw_ns": 1, "domain": "gps"})


def test_from_dict_rejects_missing_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        Stamp.from_dict({"raw_ns": 1})
    with pytest.raises(ValueError, match="missing keys"):
        Stamp.from_dict({"domain": "wall"})


def test_from_dict_rejects_non_str_domain_and_bad_raw() -> None:
    with pytest.raises(ValueError, match="must be a str token"):
        Stamp.from_dict({"raw_ns": 1, "domain": 3})
    with pytest.raises(ValueError, match="int nanosecond count"):
        Stamp.from_dict({"raw_ns": 1.5, "domain": "wall"})
    with pytest.raises(ValueError, match="bool"):
        Stamp.from_dict({"raw_ns": True, "domain": "wall"})


# -- LatticeClock -------------------------------------------------------------------------


def test_lattice_clock_strictly_increases_on_exact_lattice() -> None:
    clock = LatticeClock(1_000_000_000, 10_000_000)
    draws = [clock() for _ in range(1000)]
    assert draws == [1_000_000_000 + i * 10_000_000 for i in range(1000)]
    assert all(b > a for a, b in itertools.pairwise(draws))  # strict increase


def test_lattice_clock_first_call_returns_start_ns() -> None:
    """Matches the SimRobot / _SteppingClock convention: tick 0 IS start_ns."""
    assert LatticeClock(42, 7)() == 42


@pytest.mark.parametrize(
    ("start_ns", "period_ns", "match"),
    [
        (0, 10, "start_ns"),  # zero start would emit the 'never stamped' sentinel
        (-5, 10, "start_ns"),
        (True, 10, "start_ns"),  # bool forgery
        (10, 0, "period_ns"),  # zero period breaks strict monotonicity
        (10, -1, "period_ns"),
        (10, 2.5, "period_ns"),  # non-int
        (2**63, 10, "start_ns"),  # already past int64
    ],
)
def test_lattice_clock_rejects_bad_construction(
    start_ns: int, period_ns: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        LatticeClock(start_ns, period_ns)


def test_lattice_clock_fails_loud_on_int64_overflow() -> None:
    """Refuses to emit an unrepresentable stamp — and keeps refusing (no wrap/clamp)."""
    clock = LatticeClock(MAX_STAMP_NS - 10, 6)
    assert clock() == MAX_STAMP_NS - 10
    assert clock() == MAX_STAMP_NS - 4
    with pytest.raises(ClockExhausted, match="overflow"):
        clock()
    with pytest.raises(ClockExhausted, match="overflow"):
        clock()  # still failing, not wrapped/clamped


def test_lattice_clock_emits_the_exact_ceiling() -> None:
    """2**63-1 itself is valid — the clock emits it, then fails on the NEXT tick."""
    clock = LatticeClock(MAX_STAMP_NS, 1)
    assert clock() == MAX_STAMP_NS
    with pytest.raises(ClockExhausted, match="overflow"):
        clock()


# -- ScriptedClock ------------------------------------------------------------------------


def test_scripted_clock_replays_exactly_its_script() -> None:
    script = [5, 17, 18, 1_000, MAX_STAMP_NS]
    clock = ScriptedClock(script)
    assert [clock() for _ in range(len(script))] == script


def test_scripted_clock_exhaustion_fails_loud() -> None:
    """Past the script end: a typed loud error — never a repeated/clamped stamp."""
    clock = ScriptedClock([10, 20])
    assert (clock(), clock()) == (10, 20)
    with pytest.raises(ClockExhausted, match="exhausted after 2"):
        clock()
    with pytest.raises(ClockExhausted):  # and it STAYS exhausted
        clock()


@pytest.mark.parametrize(
    "bad_script",
    [
        [10, 10],  # duplicate stamp — not strictly increasing
        [10, 5],  # backwards
        [10, 20, 20, 30],  # plateau mid-script
    ],
)
def test_scripted_clock_rejects_non_increasing_script(bad_script: list[int]) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        ScriptedClock(bad_script)


def test_scripted_clock_rejects_invalid_stamp_values() -> None:
    with pytest.raises(ValueError, match=r"stamps\[0\]"):
        ScriptedClock([0, 10])  # zero sentinel
    with pytest.raises(ValueError, match=r"stamps\[1\]"):
        ScriptedClock([10, True])  # bool forgery, named at its index
    with pytest.raises(ValueError, match=r"stamps\[1\]"):
        ScriptedClock([10, 2**63])  # past int64


def test_scripted_clock_rejects_empty_script() -> None:
    with pytest.raises(ValueError, match="at least one stamp"):
        ScriptedClock([])


# -- Determinism: identical construction => identical sequence ----------------------------


def test_identically_constructed_clocks_are_byte_identical() -> None:
    """No hidden wall time / global state: the sequence is a function of the args only."""
    a, b = LatticeClock(1_000, 500), LatticeClock(1_000, 500)
    assert [a() for _ in range(500)] == [b() for _ in range(500)]

    script = list(range(1, 100, 3))
    c, d = ScriptedClock(script), ScriptedClock(script)
    assert [c() for _ in range(len(script))] == [d() for _ in range(len(script))]


# -- ClockNs seam + domain exposure --------------------------------------------------------


def test_clocks_satisfy_the_clockns_seam() -> None:
    """Both clocks type- and value-check as the existing injectable ``ClockNs`` seam."""
    lattice: ClockNs = LatticeClock(1_000, 500)  # assignment IS the mypy assertion
    scripted: ClockNs = ScriptedClock([7, 9])
    assert lattice() == 1_000
    assert scripted() == 7


def test_clocks_expose_monotonic_domain() -> None:
    """C2+ can read .domain instead of assuming — both are MONOTONIC by construction."""
    assert LatticeClock(1, 1).domain is ClockDomain.MONOTONIC
    assert ScriptedClock([1]).domain is ClockDomain.MONOTONIC
    assert Stamp(LatticeClock(5, 5)(), LatticeClock.domain).domain is ClockDomain.MONOTONIC


def test_lattice_clock_drives_sim_proprio_source() -> None:
    """Integration: LatticeClock injects into the UNTOUCHED SensorSource seam and every
    emitted PVTSample is stamped on the exact lattice (no ABC edits needed)."""
    src = SimProprioSource(seed=1, count=5, clock_ns=LatticeClock(1_000_000, 5_000_000))
    with src:
        stamps = [s.timestamp_ns for s in src.stream()]
    assert stamps == [1_000_000 + i * 5_000_000 for i in range(5)]
