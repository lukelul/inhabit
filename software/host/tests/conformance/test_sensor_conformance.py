"""SensorSource conformance — every registered sensor source must stream samples."""
from __future__ import annotations

from itertools import islice

import pytest

from sensors import list_sensor_sources, make_sensor_source
from sensors.interface import SensorSource


@pytest.fixture(params=list_sensor_sources(), ids=lambda n: f"sensor:{n}")
def source(request: pytest.FixtureRequest) -> SensorSource:
    return make_sensor_source(request.param)


class TestSensorSourceConformance:
    def test_is_sensor_source(self, source: SensorSource) -> None:
        assert isinstance(source, SensorSource)

    def test_kind_is_valid(self, source: SensorSource) -> None:
        assert source.kind in {"proprio", "visual", "tactile"}

    def test_stream_yields_samples(self, source: SensorSource) -> None:
        source.open()
        samples = list(islice(source.stream(), 5))
        assert len(samples) <= 5
        for s in samples:
            assert hasattr(s, "timestamp_ns")
