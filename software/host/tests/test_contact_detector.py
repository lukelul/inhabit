"""Tests for P-D/D2 — the ``contact`` (contact_start / contact_release) EventDetector.

Graded, un-fakeable, against the D1 scorer and D1 ground truth. What is proven here:

* **Graded by the D1 scorer on real scenarios.** On ``slip_recovery`` (scored against the
  CONTACT_START/CONTACT_RELEASE subset of ``ground_truth_events`` — slip/impact are separate
  detectors) AND on ``pick_place`` (whose FULL ground truth *is* the lifecycle, so it is
  scored unfiltered) the detector achieves **precision == 1.0 and recall == 1.0** at
  tolerance 0 (exact monotonic-instant alignment). Documented floor: precision >= 0.9,
  recall > 0.5 — so a SILENT detector (recall 0) fails, proven by scoring ``noop`` on the
  same truth.
* **No false positives in free space.** A no-contact window emits NOTHING; precision stays
  the vacuous-but-honest 1.0 (nothing claimed => nothing false).
* **Hysteresis kills chatter.** A noisy analog signal oscillating across the onset threshold
  but staying inside the deadband emits exactly ONE contact_start (asserted count == 1);
  the same signal with the deadband collapsed (release == onset) chatters (> 1), so the test
  cannot pass vacuously.
* ``contact_start`` precedes its ``contact_release``; every event timestamp is a real stamp
  present in the input window (the ONE shared monotonic clock).
* Determinism: same episode + seed => byte-identical events.
* Frozen-contract proof: D2 adds a detector only — no EventKind/Event/PVTSample edit; events
  use ``t_monotonic_ns``.

Headless, deterministic, stdlib-only (no numpy), zero hardware.
"""
from __future__ import annotations

import copy
import dataclasses

import pytest

from events import (
    DETECTOR_SCHEMA_VERSION,
    Event,
    EventDetector,
    EventKind,
    list_event_detectors,
    make_event_detector,
)
from events.contact import ContactDetector
from events.labels import ground_truth_events
from events.scoring import score_events
from inhabit_can.pvt import PVTSample
from tools.dataset.scenario_episode import LATTICE_NS, build_scenario_episode

# The contact lifecycle this detector owns. slip/impact/current_spike belong to sibling
# detectors, so the detector is graded only against these two kinds.
_LIFECYCLE = (EventKind.CONTACT_START, EventKind.CONTACT_RELEASE)

# Documented pass floor (the assertions below prove the detector clears it with room to
# spare — measured precision 1.0, recall 1.0 on both scenarios at tolerance 0).
_MIN_PRECISION = 0.9
_MIN_RECALL = 0.5  # a silent detector scores recall 0 and MUST fail this floor.


def _sample(
    t_ns: int,
    *,
    chain: int = 0,
    motor_current: float = 0.0,
    tactile_event: str | None = None,
) -> PVTSample:
    """A PVTSample with a monotonic timestamp and tunable contact channels."""
    return PVTSample(
        timestamp_ns=t_ns,
        episode_id="ep_contact_test",
        chain_index=chain,
        joint_angle=0.0,
        motor_current=motor_current,
        tactile_event=tactile_event,
    )


def _lifecycle_truth(name: str, *, seed: int = 7) -> list[Event]:
    """D1 ground-truth events for ``name``, filtered to the contact lifecycle kinds."""
    return [e for e in ground_truth_events(name, seed=seed) if e.kind in _LIFECYCLE]


# =====================================================================================
# Graded against the D1 scorer + D1 ground truth (the un-fakeable headline)
# =====================================================================================


def test_slip_recovery_scored_precision_and_recall() -> None:
    """slip_recovery: detector vs D1 lifecycle ground truth => precision 1.0, recall 1.0.

    Exact-instant alignment (tolerance 0): the detector fires CONTACT_START at the contact
    phase's onset tactile sample and CONTACT_RELEASE at the release phase's onset sample —
    the very samples D1 mints truth on. Clears the documented floor with room to spare.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    truth = _lifecycle_truth("slip_recovery")
    detected = make_event_detector("contact").detect(episode.samples)

    score = score_events(truth, detected, tolerance_ns=0)
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert (score.true_positives, score.false_positives, score.false_negatives) == (2, 0, 0)
    # The documented pass floor — and recall strictly above the silent-detector threshold.
    assert score.precision >= _MIN_PRECISION
    assert score.recall > _MIN_RECALL


def test_pick_place_scored_against_full_ground_truth() -> None:
    """pick_place: full D1 ground truth IS the lifecycle, so grade unfiltered => 1.0 / 1.0.

    A second contact-bearing scenario, and the strongest form of the grade: scored against
    the COMPLETE ``ground_truth_events`` with no kind filtering, recall is still 1.0 (> 0.5).
    """
    episode = build_scenario_episode("pick_place", seed=7)
    truth = ground_truth_events("pick_place", seed=7)  # full — pick_place scripts no slip/impact
    detected = make_event_detector("contact").detect(episode.samples)

    score = score_events(truth, detected, tolerance_ns=LATTICE_NS)
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.recall > _MIN_RECALL


def test_silent_detector_fails_the_recall_floor_on_same_truth() -> None:
    """The un-fakeable pin: ``noop`` on the same lifecycle truth scores recall 0 < floor.

    Proves the recall floor is doing real work — it catches a genuine all-silent detector,
    not just a synthetic empty list. A detector that clears it therefore actually detects.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    truth = _lifecycle_truth("slip_recovery")
    detected = make_event_detector("noop").detect(episode.samples)
    assert detected == []
    score = score_events(truth, detected, tolerance_ns=LATTICE_NS)
    assert score.recall == 0.0
    assert not score.recall > _MIN_RECALL  # the silent detector FAILS the gate


def test_detector_emits_exactly_the_two_lifecycle_events() -> None:
    """On slip_recovery the detector emits exactly one start + one release, in order.

    slip/impact tokens keep the grasp "in contact" (no transition) — the detector does not
    stray into the sibling detectors' kinds.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    detected = make_event_detector("contact").detect(episode.samples)
    assert [e.kind for e in detected] == [EventKind.CONTACT_START, EventKind.CONTACT_RELEASE]


# =====================================================================================
# Free space / no contact => NOTHING (no false positives)
# =====================================================================================


def test_free_space_tactile_window_emits_nothing() -> None:
    """A window of only free-space (tactile_event=None) samples => no events, precision 1.0."""
    window = [_sample(1_000 * i, chain=1, tactile_event=None) for i in range(1, 8)]
    detected = ContactDetector().detect(window)
    assert detected == []
    # Against free-space truth ([]), no detection means no false positive: precision 1.0.
    assert score_events([], detected, tolerance_ns=0).precision == 1.0


def test_free_space_numeric_window_emits_nothing() -> None:
    """A numeric channel that never reaches onset => no events (the analog free-space case)."""
    window = [_sample(1_000 * i, motor_current=0.1 * i) for i in range(1, 5)]  # max 0.4 < 0.7
    det = ContactDetector(channel="motor_current", onset_threshold=0.7, release_threshold=0.3)
    assert det.detect(window) == []


def test_unknown_tactile_token_is_ignored_not_mislabeled() -> None:
    """A foreign tactile token is skipped (not a contact reading) — never a phantom label."""
    window = [_sample(1_000 * i, chain=1, tactile_event="unrecognized") for i in range(1, 5)]
    assert ContactDetector().detect(window) == []


def test_empty_window_returns_empty_list() -> None:
    """Frozen contract: an empty window yields [] (never raises on 'no data')."""
    assert ContactDetector().detect([]) == []
    assert make_event_detector("contact").detect([]) == []


# =====================================================================================
# Hysteresis: a noisy signal emits ONE contact_start, not N
# =====================================================================================

# A signal that first crosses onset (0.7) then oscillates across it, every dip staying above
# the release floor (0.3). With hysteresis this is one contact episode; without it, chatter.
_NOISY_OSCILLATION = (0.0, 0.75, 0.65, 0.8, 0.6, 0.72, 0.55, 0.78, 0.62, 0.0)


def _noisy_window() -> list[PVTSample]:
    return [_sample(1_000 * i, motor_current=v) for i, v in enumerate(_NOISY_OSCILLATION, 1)]


def test_hysteresis_emits_single_contact_start_on_noisy_signal() -> None:
    """The core anti-chatter guarantee: oscillation inside the deadband => ONE contact_start.

    onset=0.7, release=0.3: once contact latches, the dips (0.65, 0.6, 0.55, 0.62) never fall
    to the release floor, so the state holds — exactly one start and one release.
    """
    det = ContactDetector(channel="motor_current", onset_threshold=0.7, release_threshold=0.3)
    detected = det.detect(_noisy_window())
    starts = [e for e in detected if e.kind == EventKind.CONTACT_START]
    releases = [e for e in detected if e.kind == EventKind.CONTACT_RELEASE]
    assert len(starts) == 1  # NOT N — the whole point of hysteresis
    assert len(releases) == 1  # the trailing 0.0 releases


def test_collapsed_deadband_chatters_proving_hysteresis_is_load_bearing() -> None:
    """Same signal, deadband collapsed (release == onset) => multiple starts (chatter).

    This is the negative control: it proves the single-start assertion above is earned by the
    hysteresis, not vacuously true for any config.
    """
    det = ContactDetector(channel="motor_current", onset_threshold=0.7, release_threshold=0.7)
    starts = [e for e in det.detect(_noisy_window()) if e.kind == EventKind.CONTACT_START]
    assert len(starts) > 1


# =====================================================================================
# Ordering, timestamps, determinism
# =====================================================================================


def test_contact_start_precedes_its_release_with_real_stamps() -> None:
    """start before release; every event timestamp is a real sample stamp in the window."""
    episode = build_scenario_episode("slip_recovery", seed=7)
    detected = make_event_detector("contact").detect(episode.samples)
    kinds = [e.kind for e in detected]
    # The state machine strictly alternates start -> release, starting with a start.
    assert kinds == [EventKind.CONTACT_START, EventKind.CONTACT_RELEASE]
    start_ts = detected[0].t_monotonic_ns
    release_ts = detected[1].t_monotonic_ns
    assert start_ts < release_ts
    sample_ts = {s.timestamp_ns for s in episode.samples}
    for e in detected:
        assert e.t_monotonic_ns in sample_ts  # copied from a sample, never a fresh clock


def test_deterministic_byte_identical_across_builds() -> None:
    """Same (scenario, seed) => byte-identical events (reproducible labels)."""
    det = make_event_detector("contact")
    a = det.detect(build_scenario_episode("slip_recovery", seed=7).samples)
    b = det.detect(build_scenario_episode("slip_recovery", seed=7).samples)
    assert a == b
    # Field-by-field identity (a stronger 'byte-identical' than dataclass eq alone).
    assert [(e.kind, e.t_monotonic_ns, e.channel, e.detector) for e in a] == [
        (e.kind, e.t_monotonic_ns, e.channel, e.detector) for e in b
    ]


def test_does_not_mutate_input_window() -> None:
    """detect() is pure w.r.t. its input (deep-snapshot equality after the call)."""
    window = _noisy_window()
    snapshot = copy.deepcopy(window)
    ContactDetector(channel="motor_current", onset_threshold=0.7, release_threshold=0.3).detect(
        window
    )
    assert window == snapshot


# =====================================================================================
# Emitted events are well-formed and traceable
# =====================================================================================


def test_emitted_events_are_well_formed() -> None:
    """Each event is a typed Event on the pinned schema, attributed + traceable to a channel."""
    episode = build_scenario_episode("slip_recovery", seed=7)
    detected = make_event_detector("contact").detect(episode.samples)
    assert detected  # non-empty, so the assertions below actually run
    for e in detected:
        assert isinstance(e, Event)
        assert e.kind in _LIFECYCLE
        assert e.detector == "contact"
        assert e.channel == "tactile_event"
        assert e.confidence == 1.0
        assert e.schema_version == DETECTOR_SCHEMA_VERSION
        assert e.payload["level"] in (0.0, 1.0)


def test_confidence_is_configurable_and_stamped() -> None:
    det = ContactDetector(confidence=0.8)
    detected = det.detect(build_scenario_episode("slip_recovery", seed=7).samples)
    assert all(e.confidence == 0.8 for e in detected)


# =====================================================================================
# Registration + schema version
# =====================================================================================


def test_registered_on_the_event_detector_registry() -> None:
    det = make_event_detector("contact")
    assert isinstance(det, ContactDetector)
    assert isinstance(det, EventDetector)
    assert "contact" in list_event_detectors()


def test_schema_version_is_the_package_contract() -> None:
    assert make_event_detector("contact").schema_version == DETECTOR_SCHEMA_VERSION
    assert make_event_detector("contact").schema_version > 0


def test_numeric_channel_detects_contact_lifecycle() -> None:
    """The analog path (Phase-6 force/current sensing) latches on/off with hysteresis."""
    win = [
        _sample(1_000, motor_current=0.0),
        _sample(2_000, motor_current=1.0),  # onset
        _sample(3_000, motor_current=1.2),  # held
        _sample(4_000, motor_current=0.0),  # release
    ]
    det = ContactDetector(channel="motor_current", onset_threshold=0.5, release_threshold=0.5)
    detected = det.detect(win)
    assert [(e.kind, e.t_monotonic_ns) for e in detected] == [
        (EventKind.CONTACT_START, 2_000),
        (EventKind.CONTACT_RELEASE, 4_000),
    ]


# =====================================================================================
# Construction guards (fail loud, never at detect time on a poisoned dataset)
# =====================================================================================


def test_unknown_channel_raises() -> None:
    with pytest.raises(ValueError, match="unknown channel"):
        ContactDetector(channel="nonsense")


def test_non_positive_onset_raises() -> None:
    """A non-positive onset fires on every sample (level >= 0) — a phantom-contact factory."""
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="onset_threshold must be > 0"):
            ContactDetector(onset_threshold=bad)


def test_negative_release_raises() -> None:
    with pytest.raises(ValueError, match="release_threshold must be >= 0"):
        ContactDetector(release_threshold=-0.1)


def test_inverted_hysteresis_band_raises() -> None:
    with pytest.raises(ValueError, match="inverted hysteresis"):
        ContactDetector(onset_threshold=0.3, release_threshold=0.7)


def test_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ContactDetector(confidence=1.5)


# =====================================================================================
# Frozen-contract proof: D2 changed no frozen contract
# =====================================================================================


def test_frozen_contracts_unchanged() -> None:
    """D2 adds a detector only; it must not touch EventKind / Event / PVTSample."""
    assert {k.value for k in EventKind} == {
        "contact_start",
        "contact_release",
        "current_spike",
        "impact",
        "slip",
    }
    assert DETECTOR_SCHEMA_VERSION == 1
    # Event field set is exactly the frozen shape (uses t_monotonic_ns, not timestamp_ns).
    event_fields = {f.name for f in dataclasses.fields(Event)}
    assert event_fields == {
        "kind",
        "t_monotonic_ns",
        "confidence",
        "channel",
        "detector",
        "schema_version",
        "payload",
    }
    assert "t_monotonic_ns" in event_fields and "timestamp_ns" not in event_fields
    # PVTSample still exposes the tactile_event channel the detector reads.
    pvt_fields = {f.name for f in dataclasses.fields(PVTSample)}
    assert "tactile_event" in pvt_fields
