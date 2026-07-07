"""Tests for host/events/ — EventDetector ABC, typed events, registry, stubs.

Headless, deterministic, no hardware. Covers:
  * noop emits nothing; threshold emits typed events at/above threshold, none below
    (boundary inclusive, tested on both sides);
  * events carry a monotonic timestamp copied from the triggering sample + a typed kind;
  * Event validation (confidence range, kind type) + immutability;
  * registry register / make / unknown->ValueError / duplicate-guard;
  * list_event_detectors is sorted and includes noop + threshold;
  * a parametrized conformance-style suite over the built-in detectors.
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
    NoopDetector,
    ThresholdDetector,
    list_event_detectors,
    make_event_detector,
)
from inhabit_can.pvt import PVTSample
from inhabit_core import Registry

# --- helpers ---------------------------------------------------------------


def _sample(t_ns: int, *, motor_current: float = 0.0, joint_velocity: float = 0.0) -> PVTSample:
    """A PVTSample with a monotonic timestamp and a tunable channel."""
    return PVTSample(
        timestamp_ns=t_ns,
        episode_id="ep_test",
        chain_index=0,
        joint_angle=0.0,
        joint_velocity=joint_velocity,
        motor_current=motor_current,
    )


# --- noop detector ---------------------------------------------------------


def test_noop_returns_empty_on_signal() -> None:
    """noop never invents a label, even on a window full of large currents."""
    det = make_event_detector("noop")
    window = [_sample(i * 1000, motor_current=99.0) for i in range(5)]
    assert det.detect(window) == []


def test_noop_returns_empty_on_empty_window() -> None:
    assert make_event_detector("noop").detect([]) == []


# --- threshold detector: boundary behaviour --------------------------------


def test_threshold_emits_at_threshold_inclusive() -> None:
    """A sample exactly AT the threshold counts as a crossing (>= is inclusive)."""
    det = make_event_detector("threshold", threshold=1.0)
    events = det.detect([_sample(5_000, motor_current=1.0)])
    assert len(events) == 1
    assert events[0].kind is EventKind.CURRENT_SPIKE
    assert events[0].t_monotonic_ns == 5_000


def test_threshold_emits_above_threshold() -> None:
    det = make_event_detector("threshold", threshold=1.0)
    events = det.detect([_sample(7_000, motor_current=2.5)])
    assert len(events) == 1
    assert events[0].payload == {"value": 2.5, "threshold": 1.0}


def test_threshold_silent_below_threshold() -> None:
    """Just below the threshold => no event (the other side of the boundary)."""
    det = make_event_detector("threshold", threshold=1.0)
    assert det.detect([_sample(9_000, motor_current=0.999)]) == []


def test_threshold_uses_absolute_value() -> None:
    """Magnitude crossing: a large NEGATIVE current still triggers."""
    det = make_event_detector("threshold", threshold=1.0)
    events = det.detect([_sample(1_000, motor_current=-3.0)])
    assert len(events) == 1
    assert events[0].payload["value"] == -3.0


def test_threshold_one_event_per_crossing_sample_in_order() -> None:
    """One event per crossing sample, oldest-first, only for samples that cross."""
    det = make_event_detector("threshold", threshold=2.0)
    window = [
        _sample(1_000, motor_current=0.5),  # below
        _sample(2_000, motor_current=2.0),  # at -> event
        _sample(3_000, motor_current=5.0),  # above -> event
        _sample(4_000, motor_current=1.0),  # below
    ]
    events = det.detect(window)
    assert [e.t_monotonic_ns for e in events] == [2_000, 3_000]


def test_threshold_deterministic() -> None:
    """Same window + config => identical events (reproducible labels)."""
    window = [_sample(i * 1000, motor_current=float(i)) for i in range(6)]
    a = make_event_detector("threshold", threshold=3.0).detect(window)
    b = make_event_detector("threshold", threshold=3.0).detect(window)
    assert a == b


def test_threshold_custom_channel_and_kind() -> None:
    """Monitor velocity and label crossings as IMPACT (a velocity discontinuity)."""
    det = make_event_detector(
        "threshold", channel="joint_velocity", threshold=0.5, kind=EventKind.IMPACT
    )
    events = det.detect([_sample(1_000, joint_velocity=0.8)])
    assert len(events) == 1
    assert events[0].kind is EventKind.IMPACT
    assert events[0].channel == "joint_velocity"


def test_threshold_unknown_channel_raises() -> None:
    """A typo'd channel fails loud at construction, not silently at detect time."""
    with pytest.raises(ValueError, match="unknown channel"):
        ThresholdDetector(channel="nonsense")


def test_threshold_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        ThresholdDetector(confidence=1.5)


def test_threshold_must_be_positive() -> None:
    """A non-positive threshold fires on every sample (abs(value) >= 0 is always true),
    poisoning the contact dataset — reject it at construction, not at detect time."""
    for bad in (-1.0, 0.0):
        with pytest.raises(ValueError, match="threshold"):
            ThresholdDetector(threshold=bad)
        with pytest.raises(ValueError, match="threshold"):
            make_event_detector("threshold", threshold=bad)


def test_threshold_negative_does_not_emit_phantom_events() -> None:
    """Regression: before the guard, threshold=-1 emitted a phantom event for every
    free-space (all-zero) sample. Construction must now refuse it outright."""
    with pytest.raises(ValueError, match="threshold"):
        ThresholdDetector(threshold=-1.0, channel="motor_current")


def test_threshold_empty_window() -> None:
    assert make_event_detector("threshold").detect([]) == []


# --- Event dataclass: typing, validation, immutability ---------------------


def test_event_defaults_carry_schema_version() -> None:
    e = Event(kind=EventKind.CONTACT_START, t_monotonic_ns=42)
    assert e.schema_version == DETECTOR_SCHEMA_VERSION
    assert e.confidence == 1.0
    assert e.payload == {}


def test_event_is_frozen() -> None:
    """Labels are append-only evidence: an Event cannot be mutated after creation."""
    e = Event(kind=EventKind.IMPACT, t_monotonic_ns=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.confidence = 0.5  # type: ignore[misc]


def test_event_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        Event(kind=EventKind.IMPACT, t_monotonic_ns=1, confidence=-0.1)


def test_event_rejects_non_eventkind() -> None:
    with pytest.raises(TypeError, match="EventKind"):
        Event(kind="contact_start", t_monotonic_ns=1)  # type: ignore[arg-type]


def test_eventkind_values_are_stable_tokens() -> None:
    """Kinds serialise to stable human-readable tokens for parquet/JSON export."""
    assert EventKind.CONTACT_START.value == "contact_start"
    assert EventKind.CONTACT_RELEASE.value == "contact_release"
    assert EventKind.CURRENT_SPIKE.value == "current_spike"
    assert EventKind.IMPACT.value == "impact"


# --- registry: register / make / unknown / duplicate -----------------------


def test_make_unknown_detector_raises_with_available_names() -> None:
    with pytest.raises(ValueError, match="Unknown event detector") as exc:
        make_event_detector("does_not_exist")
    # The error lists the available built-ins so the failure is self-explaining.
    assert "noop" in str(exc.value)
    assert "threshold" in str(exc.value)


def test_list_event_detectors_sorted_includes_builtins() -> None:
    names = list_event_detectors()
    assert names == sorted(names)
    assert "noop" in names
    assert "threshold" in names


def test_registry_register_make_roundtrip() -> None:
    """A fresh registry registers, makes, and guards duplicates — the A1 contract."""
    reg: Registry[EventDetector] = Registry("event detector")
    reg.register("noop", NoopDetector)
    assert isinstance(reg.make("noop"), NoopDetector)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("noop", NoopDetector)


def test_registry_unknown_on_empty() -> None:
    reg: Registry[EventDetector] = Registry("event detector")
    with pytest.raises(ValueError, match="Unknown event detector"):
        reg.make("noop")


# --- conformance-style suite over the built-in detectors -------------------
# A3 generalizes this into the shared harness; here we assert the EventDetector
# invariants every plugin must satisfy. Pin to the BUILT-IN detectors rather than
# parametrizing over list_event_detectors(): binding the suite to whatever
# inhabit.event_detectors entry points happen to be installed would break the
# deterministic contract and could fail as soon as an external detector needs
# constructor args. A separate test asserts the built-ins are actually registered.
BUILTIN_DETECTORS = ("noop", "threshold")


def test_builtin_detectors_are_registered() -> None:
    assert set(BUILTIN_DETECTORS) <= set(list_event_detectors())


@pytest.fixture(params=BUILTIN_DETECTORS)
def detector(request: pytest.FixtureRequest) -> EventDetector:
    return make_event_detector(request.param)


def _mixed_window() -> list[PVTSample]:
    """A window that should exercise both 'fire' and 'silent' code paths."""
    return [
        _sample(1_000, motor_current=0.0, joint_velocity=0.0),
        _sample(2_000, motor_current=5.0, joint_velocity=2.0),
        _sample(3_000, motor_current=0.1, joint_velocity=0.1),
    ]


def test_conformance_is_eventdetector(detector: EventDetector) -> None:
    assert isinstance(detector, EventDetector)


def test_conformance_detect_returns_list(detector: EventDetector) -> None:
    out = detector.detect(_mixed_window())
    assert isinstance(out, list)


def test_conformance_events_well_typed(detector: EventDetector) -> None:
    """Every emitted event is a typed Event with a monotonic ts, valid kind/confidence."""
    for ev in detector.detect(_mixed_window()):
        assert isinstance(ev, Event)
        assert isinstance(ev.kind, EventKind)
        assert isinstance(ev.t_monotonic_ns, int)
        assert 0.0 <= ev.confidence <= 1.0
        assert ev.schema_version == DETECTOR_SCHEMA_VERSION


def test_conformance_empty_window_empty_list(detector: EventDetector) -> None:
    """No data => no labels, never an exception."""
    assert detector.detect([]) == []


def test_conformance_does_not_mutate_window(detector: EventDetector) -> None:
    """detect() is pure w.r.t. its input window.

    Use a DEEP snapshot: ``list(window)`` only copies the outer list, so an in-place
    mutation of a (non-frozen) PVTSample would be reflected in both and pass falsely.
    """
    window = _mixed_window()
    snapshot = copy.deepcopy(window)
    detector.detect(window)
    assert window == snapshot


def test_conformance_timestamps_are_from_samples(detector: EventDetector) -> None:
    """Every event timestamp matches a sample in the window (one shared clock)."""
    window = _mixed_window()
    sample_ts = {s.timestamp_ns for s in window}
    for ev in detector.detect(window):
        assert ev.t_monotonic_ns in sample_ts


def test_conformance_deterministic(detector: EventDetector) -> None:
    window = _mixed_window()
    assert detector.detect(window) == detector.detect(window)


def test_conformance_schema_version_matches_contract(detector: EventDetector) -> None:
    assert detector.schema_version == DETECTOR_SCHEMA_VERSION
