"""Tests for P-D/D4 — the IMPACT detector (abrupt velocity discontinuity).

An impact is a *strike*: a large single-sample jump in joint velocity (a jerk spike),
distinct from the smooth force/velocity ramp of an ordinary ``contact_start`` (D2). These
tests are un-fakeable in BOTH directions — a silent detector fails recall, a spammer fails
precision — graded through D1's scorer against D1's scenario ground truth.

The simulation-fidelity gap this suite is honest about
------------------------------------------------------
The built ``slip_recovery`` episode encodes its impact ONLY as the categorical
``PVTSample.tactile_event = "impact"`` token (see ``sensors.sim_scenario``); its proprio
stream is a smooth sine with NO velocity discontinuity. A genuine velocity-discontinuity
detector therefore emits NOTHING on the raw episode — which
:func:`test_raw_slip_recovery_emits_nothing_proves_velocity_based` asserts, proving the
detector reads the *velocity signal*, not the label token (a token-reader would be a fake).

To grade the detector we enrich that episode with the physical signature the token-only sim
omits: at the script-derived impact onset we place the strike's velocity discontinuity on the
proprioceptive stream (:func:`_slip_recovery_with_strike`). The onset instant comes from the
SCENARIO SCRIPT (the first proprio sample inside the ``impact`` phase window), never from the
detector, so the detector must independently rediscover it from the velocity signal. The
scorer's tolerance absorbs exactly the 10 ms proprio→tactile lattice offset baked into the
sim's round-robin timeline (proprio leads tactile by one ``LATTICE_NS`` step), which is why a
detection on the proprio stream lands one lattice step before the tactile-stamped truth.

Measured on ``slip_recovery`` (seed 7, jerk_threshold 5.0): **IMPACT precision = 1.00,
recall = 1.00** (recall > 0.5, so a silent detector cannot pass). See
:func:`test_slip_recovery_impact_precision_recall_meets_threshold`.

Headless, deterministic, stdlib-only (no numpy), zero hardware.
"""
from __future__ import annotations

import copy
import dataclasses

import pytest

from events import (
    DETECTOR_SCHEMA_VERSION,
    Event,
    EventKind,
    list_event_detectors,
    make_event_detector,
)
from events.impact import ImpactDetector
from events.labels import ground_truth_events
from events.scoring import score_events
from inhabit_can.pvt import Episode, PVTSample
from sim.scenario import example_scenario
from tools.dataset.scenario_episode import LATTICE_NS, build_scenario_episode

# ------------------------------------------------------------------------------------
# fixtures / helpers
# ------------------------------------------------------------------------------------

#: Magnitude of the injected strike's velocity step (rad/s) — far above the smooth-sine
#: jerk (~0.15) and clamped proprio noise (~0.06), so the strike is the ONLY discontinuity.
_STRIKE = 20.0
#: The detector threshold used for grading: comfortably between smooth motion and the strike.
_JERK_THRESHOLD = 5.0
#: Scorer tolerance: absorbs the sim's fixed 10 ms proprio→tactile lattice offset (the detector
#: reads the proprio stream; D1 truth is stamped on the tactile stream one LATTICE_NS earlier)
#: plus a small margin. LATTICE_NS is 10 ms; 15 ms is one and a half lattice steps.
_TOLERANCE_NS = 15_000_000


def _sample(
    t_ns: int, *, chain_index: int = 0, joint_velocity: float = 0.0, joint_angle: float = 0.0
) -> PVTSample:
    """A minimal PVTSample with a monotonic timestamp and tunable proprio channels."""
    return PVTSample(
        timestamp_ns=t_ns,
        episode_id="ep_impact_test",
        chain_index=chain_index,
        joint_angle=joint_angle,
        joint_velocity=joint_velocity,
    )


def _first_proprio_in_impact_window(episode: Episode) -> int:
    """The monotonic timestamp of the first proprio (chain 0) sample inside the impact phase.

    Derived from the SCENARIO SCRIPT — the same source-of-truth logic ``events.labels`` uses
    for ground truth — so the injection instant is principled and independent of the detector.
    """
    scenario = example_scenario("slip_recovery")
    impact_phase = next(ph for ph in scenario.phases if ph.kind == "impact")
    proprio = sorted(
        (s for s in episode.samples if s.chain_index == 0), key=lambda s: s.timestamp_ns
    )
    anchor = proprio[0].timestamp_ns
    onset = next(
        s
        for s in proprio
        if impact_phase.start_s <= (s.timestamp_ns - anchor) / 1e9 < impact_phase.end_s
    )
    return onset.timestamp_ns


def _slip_recovery_with_strike(seed: int = 7) -> tuple[Episode, int]:
    """``slip_recovery`` enriched with the strike's proprio velocity discontinuity.

    Returns ``(episode, injection_ts)``. At the script-derived impact onset we step the
    proprioceptive ``joint_velocity`` by ``-_STRIKE`` for that sample onward — a single
    velocity discontinuity (one jerk) modelling the collision the token-only sim omits. All
    other streams/samples are the real, unmodified episode, so the detector runs the full
    interleaved multi-chain window exactly as it would in production.
    """
    episode = build_scenario_episode("slip_recovery", seed=seed)
    inj_ts = _first_proprio_in_impact_window(episode)
    enriched = Episode(episode_id=episode.episode_id, task_label=episode.task_label)
    for s in episode.samples:
        if s.chain_index == 0 and s.timestamp_ns >= inj_ts:
            enriched.add(dataclasses.replace(s, joint_velocity=s.joint_velocity - _STRIKE))
        else:
            enriched.add(s)
    return enriched, inj_ts


# ====================================================================================
# 1. slip_recovery grading — precision AND recall through D1's scorer
# ====================================================================================


def test_slip_recovery_impact_precision_recall_meets_threshold() -> None:
    """IMPACT on enriched slip_recovery meets a documented precision AND recall threshold.

    Measured: precision = 1.00, recall = 1.00 (recall > 0.5, so an all-silent detector — which
    scores recall 0 — cannot pass). Scored against D1's independently-derived ground truth.
    """
    truth = [e for e in ground_truth_events("slip_recovery", seed=7) if e.kind is EventKind.IMPACT]
    episode, _ = _slip_recovery_with_strike(seed=7)
    detected = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(
        episode.samples
    )
    # Every detection is an IMPACT (the detector only mints this kind).
    assert detected, "detector must fire on the strike (a silent detector fails recall)"
    assert all(e.kind is EventKind.IMPACT for e in detected)

    score = score_events(truth, detected, tolerance_ns=_TOLERANCE_NS)
    assert score.recall > 0.5  # the un-fakeable floor: a silent detector scores 0 here
    assert score.recall == pytest.approx(1.0)
    assert score.precision == pytest.approx(1.0)
    assert (score.true_positives, score.false_positives, score.false_negatives) == (1, 0, 0)


def test_injection_instant_is_one_lattice_step_before_tactile_truth() -> None:
    """The proprio strike lands exactly one LATTICE_NS before the tactile-stamped truth.

    This documents WHY the grading tolerance is ~1.5 lattice steps: the detector reads the
    proprio stream, D1 truth is stamped on the tactile stream, and the sim's round-robin puts
    proprio one lattice step (10 ms) ahead of tactile — a fixed, deterministic offset.
    """
    _, inj_ts = _slip_recovery_with_strike(seed=7)
    truth_impact = next(
        e for e in ground_truth_events("slip_recovery", seed=7) if e.kind is EventKind.IMPACT
    )
    assert truth_impact.t_monotonic_ns - inj_ts == LATTICE_NS  # exactly 10 ms
    assert LATTICE_NS < _TOLERANCE_NS  # so the offset is within tolerance


def test_full_score_penalises_missing_other_kinds_but_impact_is_clean() -> None:
    """Scored across ALL kinds, IMPACT is a clean 1 TP; the impact detector correctly does

    NOT claim the other scripted kinds (contact_start/slip/release) — those are D2/D3's job.
    """
    truth = ground_truth_events("slip_recovery", seed=7)
    episode, _ = _slip_recovery_with_strike(seed=7)
    detected = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(
        episode.samples
    )
    score = score_events(truth, detected, tolerance_ns=_TOLERANCE_NS)
    by_kind = {ks.kind: ks for ks in score.per_kind}
    assert by_kind[EventKind.IMPACT].true_positives == 1
    assert by_kind[EventKind.IMPACT].false_positives == 0
    # The impact detector claims nothing for the other kinds — so those are pure misses, not
    # false positives (it never hallucinates a contact_start on the strike).
    assert score.false_positives == 0


# ====================================================================================
# 2. Smooth contact ramp -> NO impact (separates impact from contact_start)
# ====================================================================================


def test_smooth_contact_ramp_emits_no_impact() -> None:
    """A smooth velocity ramp (each step below threshold) yields NO impact.

    This is the discriminator against D2's ``contact_start``: rising gradually is a contact
    ramp, not a strike. Precision stays perfect — no phantom impacts on smooth motion.
    """
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    # Velocity climbs by 0.2 rad/s per sample from 0 to ~6 — a smooth reach; every single-sample
    # jerk is 0.2 << 5.0, so no discontinuity crosses the threshold.
    window = [_sample(1_000_000 * (i + 1), joint_velocity=0.2 * i) for i in range(30)]
    assert det.detect(window) == []


# ====================================================================================
# 3. Free space -> nothing
# ====================================================================================


def test_free_space_flat_velocity_emits_nothing() -> None:
    """A flat, near-zero free-space window has no discontinuity => no label."""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [_sample(1_000_000 * (i + 1), joint_velocity=0.0) for i in range(20)]
    assert det.detect(window) == []


def test_empty_window_emits_nothing() -> None:
    """No data => empty list, never an exception (the EventDetector contract)."""
    assert make_event_detector("impact").detect([]) == []


def test_non_finite_velocity_emits_no_phantom_impact() -> None:
    """A NaN reading (sensor dropout) must NOT emit an impact. ``abs(NaN) < threshold`` is
    False, so without the finite guard a NaN delta would fall through and label a PHANTOM
    strike — the opposite of fail-safe. (CodeRabbit #66.)"""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [
        _sample(1_000_000, joint_velocity=0.0),
        _sample(2_000_000, joint_velocity=float("nan")),  # dropout: delta is NaN
        _sample(3_000_000, joint_velocity=0.0),  # recovery: delta is NaN again
    ]
    assert det.detect(window) == []


def test_raw_slip_recovery_emits_nothing_proves_velocity_based() -> None:
    """On the RAW token-only slip_recovery, the detector emits nothing — it is velocity-based.

    The ``impact`` token IS present on the tactile stream here, but the proprio velocity is a
    smooth sine, so a genuine velocity-discontinuity detector fires nothing. A token-reading
    fake would (wrongly) fire; this asserts we are not that fake.
    """
    episode = build_scenario_episode("slip_recovery", seed=7)
    detected = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(
        episode.samples
    )
    assert detected == []


# ====================================================================================
# 4. Synthetic velocity step at a known instant -> exactly one IMPACT at that stamp
# ====================================================================================


def test_hand_placed_velocity_step_emits_exactly_one_impact_at_the_stamp() -> None:
    """A single velocity step at a known instant => exactly ONE impact at that timestamp."""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    step_ts = 4_000_000
    window = [
        _sample(1_000_000, joint_velocity=0.0),
        _sample(2_000_000, joint_velocity=0.0),
        _sample(3_000_000, joint_velocity=0.0),
        _sample(step_ts, joint_velocity=10.0),  # step 0 -> 10: |delta| = 10 >= 5 -> IMPACT
        _sample(5_000_000, joint_velocity=10.0),  # held: |delta| = 0 -> silent
        _sample(6_000_000, joint_velocity=10.0),
    ]
    events = det.detect(window)
    assert len(events) == 1
    assert events[0].kind is EventKind.IMPACT
    assert events[0].t_monotonic_ns == step_ts
    assert events[0].channel == "joint_velocity"
    assert events[0].payload == {"delta": 10.0, "jerk_threshold": _JERK_THRESHOLD}


def test_negative_velocity_step_fires_on_magnitude() -> None:
    """A large DROP in velocity is just as much a strike (abs magnitude)."""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [_sample(1_000, joint_velocity=8.0), _sample(2_000, joint_velocity=0.0)]
    events = det.detect(window)
    assert len(events) == 1
    assert events[0].t_monotonic_ns == 2_000
    assert events[0].payload["delta"] == -8.0


def test_threshold_boundary_is_inclusive_then_exclusive() -> None:
    """A jerk exactly AT the threshold fires; just below does not."""
    det = make_event_detector("impact", jerk_threshold=5.0)
    at_edge = det.detect([_sample(1_000, joint_velocity=0.0), _sample(2_000, joint_velocity=5.0)])
    assert len(at_edge) == 1
    just_under = det.detect(
        [_sample(1_000, joint_velocity=0.0), _sample(2_000, joint_velocity=4.999)]
    )
    assert just_under == []


# ====================================================================================
# 5. Per-chain independence — no phantom cross-stream jerk
# ====================================================================================


def test_per_chain_differencing_ignores_cross_stream_level_changes() -> None:
    """Interleaved chains at different flat levels do NOT manufacture a jerk.

    Naive consecutive-sample differencing over the merged window (chain 0 at 0, chain 1 at 50,
    alternating) would fire on every row. Per-chain differencing sees each chain flat => none.
    """
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [
        _sample(1_000, chain_index=0, joint_velocity=0.0),
        _sample(1_100, chain_index=1, joint_velocity=50.0),
        _sample(2_000, chain_index=0, joint_velocity=0.0),
        _sample(2_100, chain_index=1, joint_velocity=50.0),
        _sample(3_000, chain_index=0, joint_velocity=0.0),
        _sample(3_100, chain_index=1, joint_velocity=50.0),
    ]
    assert det.detect(window) == []


def test_only_the_chain_with_the_strike_fires() -> None:
    """In a multi-chain window, only the chain carrying the discontinuity produces an impact."""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [
        _sample(1_000, chain_index=0, joint_velocity=0.0),
        _sample(1_100, chain_index=1, joint_velocity=0.0),
        _sample(2_000, chain_index=0, joint_velocity=30.0),  # chain 0 strike
        _sample(2_100, chain_index=1, joint_velocity=0.0),  # chain 1 flat
    ]
    events = det.detect(window)
    assert len(events) == 1
    assert events[0].t_monotonic_ns == 2_000


# ====================================================================================
# 6. Refractory — one physical strike (with a rebound) = one label
# ====================================================================================


def test_spike_and_rebound_are_two_jerks_without_refractory() -> None:
    """A spike up then back down is TWO discontinuities; default (no refractory) labels both."""
    det = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD)
    window = [
        _sample(1_000_000, joint_velocity=0.0),
        _sample(2_000_000, joint_velocity=20.0),  # up-jerk
        _sample(3_000_000, joint_velocity=0.0),  # down-jerk (rebound)
    ]
    events = det.detect(window)
    assert [e.t_monotonic_ns for e in events] == [2_000_000, 3_000_000]


def test_refractory_collapses_a_rebound_to_one_impact() -> None:
    """With a refractory dwell, the strike's rebound within the dwell is suppressed -> 1 label."""
    det = make_event_detector(
        "impact", jerk_threshold=_JERK_THRESHOLD, refractory_ns=2_000_000
    )
    window = [
        _sample(1_000_000, joint_velocity=0.0),
        _sample(2_000_000, joint_velocity=20.0),  # up-jerk -> fires
        _sample(3_000_000, joint_velocity=0.0),  # rebound 1 ms later -> within 2 ms dwell -> mute
    ]
    events = det.detect(window)
    assert len(events) == 1
    assert events[0].t_monotonic_ns == 2_000_000


def test_refractory_resets_after_the_dwell_for_a_second_strike() -> None:
    """A separate strike after the dwell fires again (refractory suppresses only the ring)."""
    det = make_event_detector(
        "impact", jerk_threshold=_JERK_THRESHOLD, refractory_ns=2_000_000
    )
    window = [
        _sample(1_000_000, joint_velocity=0.0),
        _sample(2_000_000, joint_velocity=20.0),  # strike 1 -> fires
        _sample(3_000_000, joint_velocity=20.0),  # held (no jerk)
        _sample(10_000_000, joint_velocity=0.0),  # strike 2, 8 ms later (past dwell) -> fires
    ]
    events = det.detect(window)
    assert [e.t_monotonic_ns for e in events] == [2_000_000, 10_000_000]


def test_refractory_is_per_chain() -> None:
    """A refractory dwell on one chain never suppresses a simultaneous strike on another."""
    det = make_event_detector(
        "impact", jerk_threshold=_JERK_THRESHOLD, refractory_ns=5_000_000
    )
    window = [
        _sample(1_000_000, chain_index=0, joint_velocity=0.0),
        _sample(1_000_000, chain_index=1, joint_velocity=0.0),
        _sample(2_000_000, chain_index=0, joint_velocity=20.0),  # chain 0 strike
        _sample(2_000_000, chain_index=1, joint_velocity=20.0),  # chain 1 strike (own dwell)
    ]
    events = det.detect(window)
    assert {(e.t_monotonic_ns) for e in events} == {2_000_000}
    assert len(events) == 2  # one per chain, neither suppresses the other


# ====================================================================================
# 7. Determinism
# ====================================================================================


def test_deterministic_same_episode_same_events() -> None:
    """Same episode + seed => byte-identical events (reproducible labels)."""
    episode, _ = _slip_recovery_with_strike(seed=7)
    a = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(episode.samples)
    b = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(episode.samples)
    assert a == b
    assert [(e.kind, e.t_monotonic_ns, e.detector, e.channel) for e in a] == [
        (e.kind, e.t_monotonic_ns, e.detector, e.channel) for e in b
    ]


def test_detect_does_not_mutate_window() -> None:
    """detect() is pure w.r.t. its input — a deep snapshot is unchanged after detection."""
    episode, _ = _slip_recovery_with_strike(seed=7)
    window = list(episode.samples)
    snapshot = copy.deepcopy(window)
    make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(window)
    assert window == snapshot


def test_custom_channel_monitors_joint_angle_rate() -> None:
    """The channel is configurable: a discontinuity in joint_angle also reads as a strike."""
    det = make_event_detector("impact", channel="joint_angle", jerk_threshold=1.0)
    window = [_sample(1_000, joint_angle=0.0), _sample(2_000, joint_angle=3.0)]
    events = det.detect(window)
    assert len(events) == 1
    assert events[0].channel == "joint_angle"


# ====================================================================================
# 8. Construction guards — fail loud, never poison the dataset at detect time
# ====================================================================================


def test_unknown_channel_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown channel"):
        ImpactDetector(channel="nonsense")


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_non_positive_threshold_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="jerk_threshold must be > 0"):
        ImpactDetector(jerk_threshold=bad)
    with pytest.raises(ValueError, match="jerk_threshold must be > 0"):
        make_event_detector("impact", jerk_threshold=bad)


def test_negative_refractory_raises() -> None:
    with pytest.raises(ValueError, match="refractory_ns must be >= 0"):
        ImpactDetector(refractory_ns=-1)


def test_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ImpactDetector(confidence=1.5)


# ====================================================================================
# 9. Registry / conformance
# ====================================================================================


def test_impact_is_registered_and_makeable() -> None:
    assert "impact" in list_event_detectors()
    det = make_event_detector("impact")
    assert isinstance(det, ImpactDetector)
    assert det.name == "impact"


def test_schema_version_matches_contract() -> None:
    assert make_event_detector("impact").schema_version == DETECTOR_SCHEMA_VERSION


# ====================================================================================
# 10. Frozen-contract proof — D4 adds a plugin only; edits no frozen contract
# ====================================================================================


def test_emitted_event_uses_t_monotonic_ns_from_a_sample() -> None:
    """Every event copies t_monotonic_ns from a real window sample (the one shared clock)."""
    episode, _ = _slip_recovery_with_strike(seed=7)
    sample_ts = {s.timestamp_ns for s in episode.samples}
    events = make_event_detector("impact", jerk_threshold=_JERK_THRESHOLD).detect(
        episode.samples
    )
    for e in events:
        # The field is named t_monotonic_ns (frozen Event contract), and it aligns to a sample.
        assert e.t_monotonic_ns in sample_ts


def test_frozen_contracts_unchanged() -> None:
    """D4 must not touch EventKind / Event / PVTSample (no new kinds/fields)."""
    assert {k.value for k in EventKind} == {
        "contact_start",
        "contact_release",
        "current_spike",
        "impact",
        "slip",
    }
    assert DETECTOR_SCHEMA_VERSION == 1
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
    # The detector emits into the FROZEN IMPACT kind and stamps the contract schema version.
    ev = Event(kind=EventKind.IMPACT, t_monotonic_ns=1)
    assert ev.schema_version == DETECTOR_SCHEMA_VERSION
