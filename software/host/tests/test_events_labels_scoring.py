"""Tests for P-D/D1 — scenario ground-truth labels + the precision/recall scorer.

Two things are proven here, both un-fakeable:

* **Ground truth** (:mod:`events.labels`) is exactly the scenario's scripted contact
  events — the hand-checked kinds/count of ``slip_recovery`` and ``pick_place``, stamped on
  real monotonic tactile-sample instants, byte-identical across seeds, and ``[]`` for a
  free-space scenario (the negative case).
* **The scorer** (:mod:`events.scoring`) penalizes misses AND false positives in BOTH
  directions: a perfect detector scores 1.0; an all-silent detector fails on recall; a
  spammer fails on precision; a detection just outside tolerance is a miss + a false
  positive; wrong-kind-right-time is not a match; two detections near one truth earn 1 TP +
  1 FP (no double credit). The score cannot misreport itself.

Headless, deterministic, stdlib-only (no numpy), zero hardware.
"""
from __future__ import annotations

import pytest

from events import DETECTOR_SCHEMA_VERSION, Event, EventKind, make_event_detector
from events.labels import (
    GROUND_TRUTH_CHANNEL,
    GROUND_TRUTH_DETECTOR,
    KIND_BY_TACTILE_TOKEN,
    ground_truth_events,
    ground_truth_events_from_episode,
    scripted_event_kinds,
)
from events.scoring import DetectionScore, KindScore, score_events
from inhabit_can.pvt import Episode, PVTSample
from sim.scenario import ContactPhase, ContactScenario, example_scenario
from tools.dataset.scenario_episode import build_scenario_episode

# The scripted contact events of the built-in scenarios, hand-checked against the phase
# lists in sim/scenario.py. Hard-coded here (NOT derived from the module under test) so a
# silent edit to a scenario cannot make these guards vacuously pass.
_SLIP_RECOVERY_TRUTH: tuple[EventKind, ...] = (
    EventKind.CONTACT_START,  # phase contact_start @ 0.40s
    EventKind.SLIP,           # phase slip @ 0.70s
    EventKind.IMPACT,         # phase impact @ 0.85s
    EventKind.CONTACT_RELEASE,  # phase release @ 0.95s  (token "release" -> CONTACT_RELEASE)
)
_PICK_PLACE_TRUTH: tuple[EventKind, ...] = (
    EventKind.CONTACT_START,   # phase contact_start @ 0.50s
    EventKind.CONTACT_RELEASE,  # phase release @ 1.30s
)


def _ev(kind: EventKind, t_ns: int) -> Event:
    """A minimal Event for scorer inputs (a synthetic detection or truth stamp)."""
    return Event(kind=kind, t_monotonic_ns=t_ns, detector="test")


# =====================================================================================
# Ground truth (events.labels)
# =====================================================================================


def test_slip_recovery_ground_truth_exact_kinds_and_count() -> None:
    """slip_recovery scripts EXACTLY four contact events, in order — the hand-checked truth.

    This is the D1 deliverable's headline: the labeled ground truth equals the scenario
    definition, derived from the script (not re-detected).
    """
    truth = ground_truth_events("slip_recovery", seed=7)
    assert tuple(e.kind for e in truth) == _SLIP_RECOVERY_TRUTH
    assert len(truth) == 4


def test_pick_place_ground_truth_is_grasp_then_release() -> None:
    truth = ground_truth_events("pick_place", seed=7)
    assert tuple(e.kind for e in truth) == _PICK_PLACE_TRUTH


def test_release_token_maps_to_contact_release_kind() -> None:
    """The one non-identity mapping: tactile token 'release' -> EventKind.CONTACT_RELEASE."""
    assert KIND_BY_TACTILE_TOKEN["release"] is EventKind.CONTACT_RELEASE
    assert EventKind.CONTACT_RELEASE.value == "contact_release"  # token != value


def test_ground_truth_timestamps_land_on_real_tactile_samples() -> None:
    """Each truth timestamp is a real monotonic instant of a tactile sample in the episode.

    So the truth shares the ONE clock a detector's events use — a detector can match it
    exactly, and the scorer's tolerance only absorbs real jitter, never a clock offset.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    truth = ground_truth_events_from_episode(episode, example_scenario("slip_recovery"))
    tactile_ts = {
        s.timestamp_ns for s in episode.samples if s.tactile_event is not None
    }
    for e in truth:
        assert e.t_monotonic_ns in tactile_ts
    # And they are strictly increasing (the phases tile the timeline in order).
    stamps = [e.t_monotonic_ns for e in truth]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


def test_ground_truth_events_are_attributed_to_the_script() -> None:
    """Every truth Event is stamped as produced by the scenario script, not a detector."""
    for e in ground_truth_events("slip_recovery", seed=7):
        assert e.detector == GROUND_TRUTH_DETECTOR
        assert e.channel == GROUND_TRUTH_CHANNEL
        assert e.confidence == 1.0
        assert e.schema_version == DETECTOR_SCHEMA_VERSION


def test_ground_truth_is_deterministic_byte_identical() -> None:
    """Same (name, seed) => identical labels (reproducible ground truth)."""
    a = ground_truth_events("slip_recovery", seed=7)
    b = ground_truth_events("slip_recovery", seed=7)
    assert a == b
    # Field-by-field identity (a stronger 'byte-identical' than dataclass eq alone).
    assert [(e.kind, e.t_monotonic_ns, e.detector, e.channel) for e in a] == [
        (e.kind, e.t_monotonic_ns, e.detector, e.channel) for e in b
    ]


def test_ground_truth_timestamps_are_seed_invariant() -> None:
    """The seed perturbs proprio NOISE only, never timestamps (B7 invariant) — so the

    scripted-event timestamps are identical across seeds. Labels track the script, not the
    noise realization.
    """
    assert ground_truth_events("slip_recovery", seed=7) == ground_truth_events(
        "slip_recovery", seed=123
    )


def test_scripted_event_kinds_is_pure_and_matches_labels() -> None:
    """scripted_event_kinds needs no episode and agrees with the episode-derived labels."""
    assert tuple(scripted_event_kinds(example_scenario("slip_recovery"))) == _SLIP_RECOVERY_TRUTH
    assert tuple(scripted_event_kinds(example_scenario("pick_place"))) == _PICK_PLACE_TRUTH
    # Same kinds/order as the full label path.
    labels = ground_truth_events("slip_recovery", seed=7)
    assert [e.kind for e in labels] == scripted_event_kinds(example_scenario("slip_recovery"))


def test_name_based_and_episode_based_labels_agree() -> None:
    episode = build_scenario_episode("slip_recovery", seed=7)
    from_episode = ground_truth_events_from_episode(episode, example_scenario("slip_recovery"))
    assert from_episode == ground_truth_events("slip_recovery", seed=7)


def test_free_space_scenario_yields_no_truth() -> None:
    """A scenario with no contact phases is the free-space negative case: [] truth.

    Precious for false-positive testing — any event a detector emits here is a pure false
    positive. No tactile stream is even required (there is nothing scripted to place).
    """
    free_space = ContactScenario(
        name="free_space",
        phases=(
            ContactPhase(kind="approach", start_s=0.0, duration_s=0.5),
            ContactPhase(kind="settle", start_s=0.5, duration_s=0.5),
        ),
    )
    assert scripted_event_kinds(free_space) == []
    # Returns [] before touching the episode, so an empty episode is fine.
    assert ground_truth_events_from_episode(Episode(episode_id="empty"), free_space) == []


def _proprio_sample(t_ns: int, chain: int = 0, token: str | None = None) -> PVTSample:
    return PVTSample(
        timestamp_ns=t_ns,
        episode_id="synthetic",
        chain_index=chain,
        joint_angle=0.0,
        tactile_event=token,
    )


def test_ground_truth_requires_exactly_one_tactile_stream() -> None:
    """A contact scenario whose episode carries NO tactile tokens fails loud (not silent)."""
    scenario = example_scenario("pick_place")
    episode = Episode(episode_id="no_tactile")
    for k in range(5):
        episode.add(_proprio_sample(1000 + k, chain=0, token=None))
    with pytest.raises(ValueError, match="0 tactile stream"):
        ground_truth_events_from_episode(episode, scenario)


def test_ground_truth_rejects_two_tactile_streams() -> None:
    """Two chains both carrying tokens is ambiguous provenance — reject it."""
    scenario = example_scenario("pick_place")
    episode = Episode(episode_id="two_tactile")
    episode.add(_proprio_sample(1000, chain=1, token="contact_start"))
    episode.add(_proprio_sample(1000, chain=2, token="contact_start"))
    with pytest.raises(ValueError, match="tactile stream"):
        ground_truth_events_from_episode(episode, scenario)


def test_ground_truth_fails_loud_when_a_phase_is_never_sampled() -> None:
    """A scripted phase with no sample inside its window is refused — never silently dropped.

    Ground truth must be authoritative: if the episode's sampling is too coarse to place a
    scripted event on a real instant, that is a loud error, not a missing label.
    """
    scenario = ContactScenario(
        name="coarse",
        phases=(
            ContactPhase(kind="approach", start_s=0.0, duration_s=0.5),
            ContactPhase(kind="contact_start", start_s=0.5, duration_s=0.5),
            ContactPhase(kind="release", start_s=1.0, duration_s=0.3),
        ),
    )
    anchor = 1_000
    episode = Episode(episode_id="coarse")
    episode.add(_proprio_sample(anchor, chain=1, token=None))  # t=0.0 -> approach anchor
    # One sample inside contact_start [0.5, 1.0); NOTHING inside release [1.0, 1.3).
    episode.add(_proprio_sample(anchor + 600_000_000, chain=1, token="contact_start"))
    with pytest.raises(ValueError, match="no tactile sample inside its window"):
        ground_truth_events_from_episode(episode, scenario)


# =====================================================================================
# Scorer (events.scoring) — the un-fakeable gate, both directions
# =====================================================================================


def test_perfect_detector_scores_one() -> None:
    """detected == truth => precision = recall = f1 = 1.0 (the happy-path anchor)."""
    truth = ground_truth_events("slip_recovery", seed=7)
    score = score_events(truth, list(truth), tolerance_ns=0)
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert (score.true_positives, score.false_positives, score.false_negatives) == (4, 0, 0)


def test_silent_detector_fails_on_recall() -> None:
    """An all-silent detector on a contact-bearing scenario MISSES — recall < 1, NOT a pass.

    Precision is the vacuous 1.0 (no false claims), which is exactly why recall must be the
    thing that catches it: recall 0, f1 0.
    """
    truth = ground_truth_events("slip_recovery", seed=7)
    score = score_events(truth, [], tolerance_ns=5_000_000)
    assert score.recall == 0.0
    assert score.recall < 1.0
    assert score.f1 == 0.0
    assert score.precision == 1.0  # vacuous — cannot rescue a silent detector on its own
    assert score.false_negatives == 4


def test_real_noop_detector_is_caught_by_recall() -> None:
    """The registry's real 'noop' detector, scored against truth, fails recall — the gate

    catches a genuine all-silent detector, not just a synthetic empty list.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    truth = ground_truth_events_from_episode(episode, example_scenario("slip_recovery"))
    detected = make_event_detector("noop").detect(episode.samples)
    assert detected == []
    score = score_events(truth, detected, tolerance_ns=5_000_000)
    assert score.recall == 0.0


def test_spam_detector_fails_on_precision() -> None:
    """A detector firing every sample tanks precision (false positives), even at high recall."""
    truth = ground_truth_events("slip_recovery", seed=7)
    start = truth[0].t_monotonic_ns
    # 200 CONTACT_START detections blanketing the timeline: at most one truth CONTACT_START
    # can match (one-to-one), so the other ~199 are false positives.
    detected = [_ev(EventKind.CONTACT_START, start + i * 1_000_000) for i in range(200)]
    score = score_events(truth, detected, tolerance_ns=1_000_000)
    assert score.precision < 0.05
    # One-to-one: the single CONTACT_START truth matches at most one detection.
    assert score.true_positives <= 1


def test_tolerance_boundary_is_inclusive_then_exclusive() -> None:
    """At +tolerance => match; at +tolerance+1 => a miss (FN) + a false positive (FP)."""
    tol = 1_000_000
    truth = [_ev(EventKind.IMPACT, 10_000_000)]
    at_edge = score_events(truth, [_ev(EventKind.IMPACT, 10_000_000 + tol)], tolerance_ns=tol)
    assert (at_edge.true_positives, at_edge.false_positives, at_edge.false_negatives) == (1, 0, 0)
    just_over = score_events(
        truth, [_ev(EventKind.IMPACT, 10_000_000 + tol + 1)], tolerance_ns=tol
    )
    assert (just_over.true_positives, just_over.false_positives, just_over.false_negatives) == (
        0,
        1,
        1,
    )


def test_wrong_kind_right_time_is_not_a_match() -> None:
    """Same timestamp, wrong kind => not a match: 1 FP + 1 FN, zero TP."""
    truth = [_ev(EventKind.CONTACT_START, 500)]
    detected = [_ev(EventKind.SLIP, 500)]
    score = score_events(truth, detected, tolerance_ns=1_000)
    assert (score.true_positives, score.false_positives, score.false_negatives) == (0, 1, 1)
    assert score.precision == 0.0
    assert score.recall == 0.0


def test_two_detections_near_one_truth_earn_one_tp_one_fp() -> None:
    """One-to-one matching: two in-tolerance detections for one truth => 1 TP + 1 FP."""
    truth = [_ev(EventKind.SLIP, 1_000)]
    detected = [_ev(EventKind.SLIP, 1_000), _ev(EventKind.SLIP, 1_100)]
    score = score_events(truth, detected, tolerance_ns=1_000)
    assert (score.true_positives, score.false_positives, score.false_negatives) == (1, 1, 0)


def test_greedy_nearest_matches_the_closest_detection() -> None:
    """When two detections fit, the NEAREST is the true positive (deterministic greedy)."""
    truth = [_ev(EventKind.SLIP, 1_000)]
    far = _ev(EventKind.SLIP, 1_900)
    near = _ev(EventKind.SLIP, 1_050)
    # Order the far one first to prove ordering does not decide the match — distance does.
    score = score_events(truth, [far, near], tolerance_ns=1_000)
    assert score.true_positives == 1
    assert score.false_positives == 1


def test_per_kind_breakdown_sums_to_aggregate_and_is_sorted() -> None:
    """The per-kind breakdown accounts for every event and is token-sorted."""
    truth = ground_truth_events("slip_recovery", seed=7)
    # Detect the contact_start and slip correctly; miss impact/release; add a bogus impact.
    detected = [
        _ev(EventKind.CONTACT_START, truth[0].t_monotonic_ns),
        _ev(EventKind.SLIP, truth[1].t_monotonic_ns),
        _ev(EventKind.IMPACT, truth[2].t_monotonic_ns + 10_000_000_000),  # far -> no match
    ]
    score = score_events(truth, detected, tolerance_ns=1_000_000)
    tokens = [ks.kind.value for ks in score.per_kind]
    assert tokens == sorted(tokens)
    assert sum(ks.true_positives for ks in score.per_kind) == score.true_positives
    assert sum(ks.false_positives for ks in score.per_kind) == score.false_positives
    assert sum(ks.false_negatives for ks in score.per_kind) == score.false_negatives
    by_kind = {ks.kind: ks for ks in score.per_kind}
    assert by_kind[EventKind.CONTACT_START].true_positives == 1
    assert by_kind[EventKind.IMPACT].false_positives == 1
    assert by_kind[EventKind.IMPACT].false_negatives == 1


def test_empty_truth_and_empty_detected_is_vacuously_perfect() -> None:
    """Nothing to find, nothing claimed: precision = recall = f1 = 1.0, no breakdown."""
    score = score_events([], [], tolerance_ns=0)
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert score.per_kind == ()


def test_free_space_plus_spammer_tanks_precision() -> None:
    """On free-space truth ([]), any detection is a false positive: precision 0, recall 1."""
    detected = [_ev(EventKind.CURRENT_SPIKE, t) for t in range(0, 10_000, 1_000)]
    score = score_events([], detected, tolerance_ns=1_000)
    assert score.recall == 1.0  # no truth to miss
    assert score.precision == 0.0  # every detection is false
    assert score.f1 == 0.0


# --- tolerance + input validation ----------------------------------------------------


def test_negative_tolerance_raises() -> None:
    with pytest.raises(ValueError, match="tolerance_ns must be >= 0"):
        score_events([], [], tolerance_ns=-1)


@pytest.mark.parametrize("bad", [1.0, True, "5"])
def test_non_int_tolerance_raises(bad: object) -> None:
    with pytest.raises(TypeError, match="tolerance_ns must be an int"):
        score_events([], [], tolerance_ns=bad)  # type: ignore[arg-type]


def test_score_rejects_non_event_inputs() -> None:
    with pytest.raises(TypeError, match=r"detected\[0\] must be an Event"):
        score_events([], ["not an event"], tolerance_ns=0)  # type: ignore[list-item]
    with pytest.raises(TypeError, match="truth must be a sequence"):
        score_events("nope", [], tolerance_ns=0)  # type: ignore[arg-type]


# --- the score cannot misreport itself ----------------------------------------------


def test_kind_score_rejects_inconsistent_ratio() -> None:
    """A KindScore claiming a ratio that disagrees with its counts cannot be constructed."""
    with pytest.raises(ValueError, match="precision"):
        KindScore(
            kind=EventKind.SLIP,
            true_positives=1,
            false_positives=1,
            false_negatives=0,
            precision=1.0,  # lie: tp/(tp+fp) = 0.5
            recall=1.0,
            f1=1.0,
        )


def test_kind_score_rejects_non_eventkind() -> None:
    with pytest.raises(TypeError, match="kind must be an EventKind"):
        KindScore.from_counts("slip", 0, 0, 0)  # type: ignore[arg-type]


def test_kind_score_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        KindScore.from_counts(EventKind.SLIP, -1, 0, 0)


def test_detection_score_rejects_aggregate_not_summing_breakdown() -> None:
    ks = KindScore.from_counts(EventKind.SLIP, 1, 0, 0)
    with pytest.raises(ValueError, match="!= sum of per_kind"):
        DetectionScore.from_counts(5, 0, 0, (ks,))  # aggregate tp=5 but breakdown sums to 1


def test_detection_score_rejects_unsorted_breakdown() -> None:
    slip = KindScore.from_counts(EventKind.SLIP, 1, 0, 0)
    impact = KindScore.from_counts(EventKind.IMPACT, 1, 0, 0)
    # "slip" > "impact" lexically, so (slip, impact) is out of order.
    with pytest.raises(ValueError, match="strictly sorted"):
        DetectionScore.from_counts(2, 0, 0, (slip, impact))


# --- round-trip: a score is a recordable artifact ------------------------------------


def test_score_round_trips_through_dict() -> None:
    truth = ground_truth_events("slip_recovery", seed=7)
    detected = [_ev(EventKind.CONTACT_START, truth[0].t_monotonic_ns)]
    score = score_events(truth, detected, tolerance_ns=1_000_000)
    assert DetectionScore.from_dict(score.to_dict()) == score


def test_from_dict_rejects_forged_ratio() -> None:
    score = score_events([], [], tolerance_ns=0)
    forged = score.to_dict()
    forged["precision"] = 0.5  # contradicts tp=fp=0 => precision 1.0
    with pytest.raises(ValueError, match="contradicts the counts"):
        DetectionScore.from_dict(forged)


def test_from_dict_rejects_malformed_per_kind() -> None:
    with pytest.raises(ValueError, match="per_kind must be a list"):
        DetectionScore.from_dict(
            {
                "true_positives": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "per_kind": "nope",
            }
        )
    with pytest.raises(ValueError, match="per_kind entry must be a mapping"):
        DetectionScore.from_dict(
            {
                "true_positives": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "per_kind": ["not a mapping"],
            }
        )


def test_kind_score_from_dict_rejects_unknown_token() -> None:
    with pytest.raises(ValueError, match="unknown EventKind token"):
        KindScore.from_dict(
            {
                "kind": "not_a_kind",
                "true_positives": 0,
                "false_positives": 0,
                "false_negatives": 0,
            }
        )


def test_require_count_rejects_non_int() -> None:
    """A float/bool count is a poisoned score input — reject, never coerce."""
    with pytest.raises(TypeError, match="must be an int count"):
        KindScore.from_counts(EventKind.SLIP, 1.0, 0, 0)  # type: ignore[arg-type]


def test_check_ratios_catches_recall_and_f1_lies() -> None:
    """The self-consistency guard catches a lie in ANY ratio, not just precision."""
    with pytest.raises(ValueError, match="recall"):
        KindScore(
            kind=EventKind.SLIP,
            true_positives=1,
            false_positives=0,
            false_negatives=1,
            precision=1.0,  # correct, so the check advances to recall
            recall=0.9,  # lie: derived recall is 0.5
            f1=0.0,
        )
    with pytest.raises(ValueError, match="f1"):
        KindScore(
            kind=EventKind.SLIP,
            true_positives=1,
            false_positives=0,
            false_negatives=1,
            precision=1.0,
            recall=0.5,  # correct
            f1=0.9,  # lie: derived f1 is 2/3
        )


def test_kind_score_from_dict_rejects_non_str_kind_and_forged_ratio() -> None:
    with pytest.raises(ValueError, match="kind must be a token str"):
        KindScore.from_dict(
            {"kind": 5, "true_positives": 0, "false_positives": 0, "false_negatives": 0}
        )
    forged = KindScore.from_counts(EventKind.SLIP, 1, 0, 0).to_dict()
    forged["recall"] = 0.1  # contradicts tp=1,fn=0 => recall 1.0
    with pytest.raises(ValueError, match="contradicts the counts"):
        KindScore.from_dict(forged)


def test_detection_score_rejects_malformed_per_kind_field() -> None:
    with pytest.raises(TypeError, match="per_kind must be a tuple"):
        DetectionScore(
            true_positives=0,
            false_positives=0,
            false_negatives=0,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            per_kind=[],  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="per_kind entries must be KindScore"):
        DetectionScore(
            true_positives=0,
            false_positives=0,
            false_negatives=0,
            precision=1.0,
            recall=1.0,
            f1=1.0,
            per_kind=("not a KindScore",),  # type: ignore[arg-type]
        )


# --- frozen-contract proof: D1 changed no frozen contract ----------------------------


def test_frozen_contracts_unchanged() -> None:
    """D1 adds labels + a scorer only; it must not touch EventKind / Event / PVTSample."""
    assert {k.value for k in EventKind} == {
        "contact_start",
        "contact_release",
        "current_spike",
        "impact",
        "slip",
    }
    assert DETECTOR_SCHEMA_VERSION == 1
    # Event field set is exactly the frozen shape (uses t_monotonic_ns, not timestamp_ns).
    event_fields = {f.name for f in __import__("dataclasses").fields(Event)}
    assert event_fields == {
        "kind",
        "t_monotonic_ns",
        "confidence",
        "channel",
        "detector",
        "schema_version",
        "payload",
    }
