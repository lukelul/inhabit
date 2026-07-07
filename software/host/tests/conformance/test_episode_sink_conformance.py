"""EpisodeSink conformance — every registered sink must satisfy the lifecycle contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from inhabit_can.pvt import PVTSample
from logger.sinks import list_episode_sinks, make_episode_sink
from logger.sinks.interface import EpisodeSink


def _make_valid_sample(tick: int) -> PVTSample:
    return PVTSample(
        timestamp_ns=(tick + 1) * 10_000_000,
        episode_id="conform_ep",
        chain_index=0,
        joint_angle=tick * 0.0175,
        task_label="conform",
    )


_SINK_CONFIG: dict[str, dict[str, object]] = {
    "parquet-atomic": {"_needs_tmp": True},
    "inmem": {},
}


@pytest.fixture(params=list_episode_sinks(), ids=lambda n: f"sink:{n}")
def sink(request: pytest.FixtureRequest, tmp_path: Path) -> EpisodeSink:
    name = request.param
    cfg = _SINK_CONFIG.get(name, {})
    kwargs: dict[str, object] = {}
    if cfg.get("_needs_tmp"):
        kwargs["out_dir"] = str(tmp_path)
    return make_episode_sink(
        name, episode_id="conform_ep", task_label="conform", **kwargs,
    )


class TestEpisodeSinkConformance:
    def test_is_episode_sink(self, sink: EpisodeSink) -> None:
        assert isinstance(sink, EpisodeSink)

    def test_open_ingest_finalize_lifecycle(self, sink: EpisodeSink) -> None:
        sink.open()
        for tick in range(5):
            sink.ingest(_make_valid_sample(tick))
        result = sink.finalize()
        assert result is not None

    def test_double_finalize_raises(self, sink: EpisodeSink) -> None:
        sink.open()
        sink.ingest(_make_valid_sample(0))
        sink.ingest(_make_valid_sample(1))
        sink.finalize()
        with pytest.raises(RuntimeError):
            sink.finalize()

    def test_ingest_after_finalize_raises(self, sink: EpisodeSink) -> None:
        sink.open()
        sink.ingest(_make_valid_sample(0))
        sink.finalize()
        with pytest.raises(RuntimeError):
            sink.ingest(_make_valid_sample(1))
