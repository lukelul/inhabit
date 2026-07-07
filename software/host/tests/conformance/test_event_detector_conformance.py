"""EventDetector conformance — every registered detector must satisfy these invariants."""
from __future__ import annotations

import pytest

from events import list_event_detectors, make_event_detector
from events.interface import EventDetector


@pytest.fixture(params=list_event_detectors(), ids=lambda n: f"detector:{n}")
def detector(request: pytest.FixtureRequest) -> EventDetector:
    return make_event_detector(request.param)


class TestEventDetectorConformance:
    def test_is_event_detector(self, detector: EventDetector) -> None:
        assert isinstance(detector, EventDetector)

    def test_detect_returns_list(self, detector: EventDetector) -> None:
        events = detector.detect([])
        assert isinstance(events, list)

    def test_schema_version_positive(self, detector: EventDetector) -> None:
        assert detector.schema_version > 0
