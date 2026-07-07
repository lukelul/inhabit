"""Tests for the contact scenario spec (P-B/B4).

The failure mode under test is a **physically-nonsensical or ambiguous last-centimeter
script that silently mislabels samples downstream**. B5 will drive these scenarios onto the
FROZEN ``PVTSample.tactile_event`` / ``camera_frame_id`` timeline, so the spec must:

* reject every invalid script at spec time with a clear :class:`ValueError`
  (overlaps, gaps, negative/zero windows, unknown kinds, unbalanced grasp),
* answer "which tactile token is active at time t?" unambiguously across a timeline,
* round-trip exactly as a value (dataclass eq AND stdlib-json), and
* stay byte-identical to its committed golden fixture.

Everything is stdlib-only and deterministic (no numpy — a hard P-B invariant).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim.scenario import (
    CONTACT_KINDS,
    EXAMPLE_SCENARIOS,
    PHASE_KINDS,
    PICK_PLACE,
    SLIP_RECOVERY,
    ContactPhase,
    ContactScenario,
    example_scenario,
)
from tests.fixtures.make_scenario_fixture import (
    FIXTURE_PATH,
    render_golden,
    write_fixture,
)

# The tactile tokens the spec MUST reuse verbatim from the FROZEN PVTSample vocabulary.
# Hard-coded here (not imported from the module under test) so a silent edit to the module's
# CONTACT_KINDS can never make this guard vacuously pass.
_FROZEN_TACTILE_TOKENS = ("contact_start", "slip", "impact", "release")


def _valid_pick_place() -> ContactScenario:
    """A fresh, minimal valid scenario for mutation in negative tests."""
    return ContactScenario(
        name="unit",
        phases=(
            ContactPhase(kind="approach", start_s=0.0, duration_s=0.5),
            ContactPhase(kind="contact_start", start_s=0.5, duration_s=0.5),
            ContactPhase(kind="release", start_s=1.0, duration_s=0.3),
            ContactPhase(kind="settle", start_s=1.3, duration_s=0.2),
        ),
    )


# -- contract: the spec reuses exactly the frozen tactile tokens -----------------------------


def test_contact_kinds_are_exactly_the_frozen_tactile_tokens() -> None:
    """The contact kinds ARE the frozen PVTSample.tactile_event vocabulary — no invention."""
    assert set(CONTACT_KINDS) == set(_FROZEN_TACTILE_TOKENS)
    # And the non-contact filler kinds are NOT tactile tokens (they map to None downstream).
    assert set(PHASE_KINDS) - set(CONTACT_KINDS) == {"approach", "settle"}


# -- validate(): rejects each invalid case ---------------------------------------------------


def test_validate_accepts_examples() -> None:
    """Every built-in example scenario passes validation (realistic B5 inputs)."""
    for scenario in EXAMPLE_SCENARIOS.values():
        scenario.validate()  # must not raise


def test_validate_rejects_empty_name() -> None:
    """An unnamed scenario cannot be referenced/round-tripped — reject it."""
    s = ContactScenario(name="", phases=(ContactPhase("approach", 0.0, 1.0),))
    with pytest.raises(ValueError, match="non-empty"):
        s.validate()


def test_validate_rejects_empty_phase_list() -> None:
    """An empty script has no timeline to stamp — almost always a construction bug."""
    with pytest.raises(ValueError, match="at least one phase"):
        ContactScenario(name="empty").validate()


def test_validate_rejects_unknown_kind() -> None:
    """A typo'd/invented token would leak a non-frozen value into tactile_event."""
    s = ContactScenario(name="bad", phases=(ContactPhase("grab", 0.0, 1.0),))
    with pytest.raises(ValueError, match="unknown kind"):
        s.validate()


@pytest.mark.parametrize("bad_duration", [0.0, -0.5])
def test_validate_rejects_non_positive_duration(bad_duration: float) -> None:
    """A zero/negative window can't host a sample."""
    s = ContactScenario(name="bad", phases=(ContactPhase("approach", 0.0, bad_duration),))
    with pytest.raises(ValueError, match="non-positive duration"):
        s.validate()


def test_validate_rejects_negative_start() -> None:
    """A phase starting before the timeline origin is meaningless."""
    # start<0 also makes phase-0 not start at 0.0; the negative-start check fires first.
    s = ContactScenario(name="bad", phases=(ContactPhase("approach", -0.1, 1.0),))
    with pytest.raises(ValueError, match="negative start_s"):
        s.validate()


def test_validate_rejects_first_phase_not_at_zero() -> None:
    """The timeline must start at the origin so active_at and B5 share one zero."""
    s = ContactScenario(name="bad", phases=(ContactPhase("approach", 0.5, 1.0),))
    with pytest.raises(ValueError, match="gap before phase 0"):
        s.validate()


def test_validate_rejects_gap_between_phases() -> None:
    """A gap leaves an unlabeled hole in the timeline."""
    s = ContactScenario(
        name="bad",
        phases=(
            ContactPhase("approach", 0.0, 0.5),
            ContactPhase("contact_start", 0.7, 0.3),  # gap: 0.5 -> 0.7
            ContactPhase("release", 1.0, 0.2),
        ),
    )
    with pytest.raises(ValueError, match="gap before phase 1"):
        s.validate()


def test_validate_rejects_overlapping_phases() -> None:
    """An overlap makes 'which event at t' ambiguous."""
    s = ContactScenario(
        name="bad",
        phases=(
            ContactPhase("approach", 0.0, 0.5),
            ContactPhase("contact_start", 0.3, 0.5),  # overlaps: starts before 0.5
            ContactPhase("release", 0.8, 0.2),
        ),
    )
    with pytest.raises(ValueError, match="overlaps/precedes"):
        s.validate()


def test_validate_rejects_contact_start_without_release() -> None:
    """A grasp that never lets go is physically nonsensical."""
    s = ContactScenario(
        name="stuck",
        phases=(
            ContactPhase("approach", 0.0, 0.5),
            ContactPhase("contact_start", 0.5, 0.5),
            ContactPhase("settle", 1.0, 0.3),  # no release
        ),
    )
    with pytest.raises(ValueError, match="never lets go"):
        s.validate()


def test_validate_rejects_release_without_contact_start() -> None:
    """Letting go of nothing (release with no open grasp) is also nonsensical."""
    s = ContactScenario(
        name="ghost",
        phases=(
            ContactPhase("approach", 0.0, 0.5),
            ContactPhase("release", 0.5, 0.3),  # nothing was grabbed
            ContactPhase("settle", 0.8, 0.2),
        ),
    )
    with pytest.raises(ValueError, match="no open 'contact_start'"):
        s.validate()


@pytest.mark.parametrize("event", ["slip", "impact"])
def test_validate_rejects_mid_contact_event_with_no_open_grasp(event: str) -> None:
    """A slip/impact with nothing gripped is physically nonsensical — mid-contact events
    are only valid inside an active grasp (between a contact_start and its release)."""
    s = ContactScenario(
        name="floating",
        phases=(
            ContactPhase("approach", 0.0, 0.5),
            ContactPhase(event, 0.5, 0.3),  # slip/impact with no open contact_start
            ContactPhase("settle", 0.8, 0.2),
        ),
    )
    with pytest.raises(ValueError, match="no open grasp"):
        s.validate()


def test_validate_accepts_nested_slip_impact_between_grasp_and_release() -> None:
    """Mid-grasp slip/impact are legal events inside an open grasp (the wedge signal)."""
    SLIP_RECOVERY.validate()  # must not raise (grasp -> slip -> impact -> release)


# -- active_at / tactile_event_at ------------------------------------------------------------


def test_total_duration_is_end_of_last_phase() -> None:
    assert PICK_PLACE.total_duration_s == pytest.approx(1.8)
    assert ContactScenario(name="e").total_duration_s == 0.0


def test_active_at_returns_correct_phase_across_timeline() -> None:
    """The active phase is the half-open window [start, end) containing t."""
    s = _valid_pick_place()
    assert s.active_at(0.0).kind == "approach"  # type: ignore[union-attr]
    assert s.active_at(0.25).kind == "approach"  # type: ignore[union-attr]
    assert s.active_at(0.5).kind == "contact_start"  # type: ignore[union-attr]  # boundary -> next
    assert s.active_at(0.99).kind == "contact_start"  # type: ignore[union-attr]
    assert s.active_at(1.0).kind == "release"  # type: ignore[union-attr]
    assert s.active_at(1.3).kind == "settle"  # type: ignore[union-attr]


def test_active_at_outside_timeline_is_none() -> None:
    """Before 0 or at/after total_duration returns None (nothing scripted there)."""
    s = _valid_pick_place()
    assert s.active_at(-0.01) is None
    assert s.active_at(s.total_duration_s) is None  # end is exclusive
    assert s.active_at(s.total_duration_s + 1.0) is None


def test_tactile_event_at_returns_frozen_token_or_none() -> None:
    """tactile_event_at gives exactly what B5 writes into PVTSample.tactile_event."""
    s = _valid_pick_place()
    # Non-contact windows -> None (never a token).
    assert s.tactile_event_at(0.25) is None  # approach
    assert s.tactile_event_at(1.4) is None  # settle
    assert s.tactile_event_at(-1.0) is None  # off timeline
    # Contact windows -> the frozen token.
    assert s.tactile_event_at(0.5) == "contact_start"
    assert s.tactile_event_at(1.0) == "release"
    # Every token it ever returns is a frozen tactile token.
    tokens = {
        s.tactile_event_at(t / 100.0)
        for t in range(0, int(s.total_duration_s * 100) + 5)
    }
    assert (tokens - {None}) <= set(_FROZEN_TACTILE_TOKENS)


def test_slip_and_impact_fire_at_scripted_times() -> None:
    """The richer scenario surfaces slip then impact at their scripted windows."""
    assert SLIP_RECOVERY.tactile_event_at(0.75) == "slip"
    assert SLIP_RECOVERY.tactile_event_at(0.90) == "impact"
    assert SLIP_RECOVERY.tactile_event_at(1.00) == "release"


# -- round-trip: dataclass equality and JSON -------------------------------------------------


@pytest.mark.parametrize("scenario", list(EXAMPLE_SCENARIOS.values()))
def test_dict_round_trip_equality(scenario: ContactScenario) -> None:
    """from_dict(to_dict(s)) == s — the value identity the golden rests on."""
    assert ContactScenario.from_dict(scenario.to_dict()) == scenario


@pytest.mark.parametrize("scenario", list(EXAMPLE_SCENARIOS.values()))
def test_json_round_trip_equality(scenario: ContactScenario) -> None:
    """loads(dumps(s)) == s AND the JSON text itself round-trips exactly."""
    text = scenario.dumps()
    assert ContactScenario.loads(text) == scenario
    # Re-dumping the reparsed value yields identical text (stable serialization).
    assert ContactScenario.loads(text).dumps() == text


def test_list_phases_coerced_to_tuple_and_equal() -> None:
    """Constructing with a plain list is ergonomic yet yields the same immutable value.

    Guards the __post_init__ list->tuple coercion: a scenario built from a list must equal
    one built from the identical tuple (and be hashable), so equality stays stable regardless
    of how a caller passes phases.
    """
    phases = [ContactPhase("approach", 0.0, 1.0)]
    from_list = ContactScenario(name="x", phases=phases)  # type: ignore[arg-type]
    from_tuple = ContactScenario(name="x", phases=tuple(phases))
    assert from_list == from_tuple
    assert isinstance(from_list.phases, tuple)
    assert hash(from_list) == hash(from_tuple)  # frozen value is hashable


def test_phase_is_a_value_with_equality() -> None:
    """Phases compare by value so scenario equality is meaningful."""
    assert ContactPhase("slip", 0.1, 0.2) == ContactPhase("slip", 0.1, 0.2)
    assert ContactPhase("slip", 0.1, 0.2) != ContactPhase("impact", 0.1, 0.2)


def test_int_times_coerce_to_float_on_load() -> None:
    """An int time in JSON (e.g. 0) loads as the same value a 0.0 literal produces."""
    d = {"name": "x", "phases": [{"kind": "approach", "start_s": 0, "duration_s": 1}]}
    loaded = ContactScenario.from_dict(d)
    assert loaded == ContactScenario(name="x", phases=(ContactPhase("approach", 0.0, 1.0),))
    assert isinstance(loaded.phases[0].start_s, float)


# -- from_dict fail-loud ---------------------------------------------------------------------


def test_from_dict_rejects_missing_scenario_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        ContactScenario.from_dict({"name": "x"})  # no 'phases'


def test_from_dict_rejects_non_list_phases() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        ContactScenario.from_dict({"name": "x", "phases": {"kind": "approach"}})


def test_phase_from_dict_rejects_missing_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        ContactPhase.from_dict({"kind": "approach", "start_s": 0.0})  # no duration_s


# -- example registry ------------------------------------------------------------------------


def test_example_scenario_lookup() -> None:
    assert example_scenario("pick_place") is PICK_PLACE
    assert example_scenario("slip_recovery") is SLIP_RECOVERY


def test_example_scenario_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        example_scenario("does_not_exist")


# -- golden fixture: byte-identity -----------------------------------------------------------


def test_golden_fixture_is_committed() -> None:
    """The golden JSON must exist on disk as a committed regression baseline."""
    assert FIXTURE_PATH.exists(), f"missing committed golden {FIXTURE_PATH}"


def test_golden_fixture_is_byte_identical_to_generator(tmp_path: Path) -> None:
    """Regenerating the golden is byte-identical to the committed copy.

    Guards against the committed golden drifting from make_scenario_fixture / the spec
    (e.g. someone edits PICK_PLACE without regenerating), which would make the baseline a lie.
    """
    regenerated = write_fixture(tmp_path / "regen.scenario.json")
    assert regenerated.read_bytes() == FIXTURE_PATH.read_bytes()
    # And LF-only: no CRLF leaked in on any platform.
    assert b"\r\n" not in FIXTURE_PATH.read_bytes()


def test_golden_fixture_round_trips_to_the_scenario() -> None:
    """The committed golden parses back to exactly the built-in PICK_PLACE value."""
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert ContactScenario.loads(text) == PICK_PLACE
    # render_golden (writer's source of truth) matches the committed bytes' text.
    assert render_golden() == text


def test_golden_fixture_is_valid_json_and_validates() -> None:
    """The golden is well-formed JSON and its scenario passes validate()."""
    loaded = ContactScenario.from_dict(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    loaded.validate()
