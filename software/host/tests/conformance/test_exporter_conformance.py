"""Exporter conformance — every registered exporter must round-trip episodes."""
from __future__ import annotations

from pathlib import Path

import pytest

from export.base import Exporter
from export.registry import list_exporters, make_exporter
from inhabit_can.pvt import Episode, PVTSample


def _make_episode() -> Episode:
    ep = Episode(episode_id="conform_ep", task_label="conform_task")
    for tick in range(10):
        ep.add(PVTSample(
            timestamp_ns=1_000_000 + tick * 10_000_000,
            episode_id="conform_ep",
            chain_index=0,
            joint_angle=tick * 0.1,
            task_label="conform_task",
        ))
    return ep


@pytest.fixture(params=list_exporters(), ids=lambda n: f"exporter:{n}")
def exporter(request: pytest.FixtureRequest) -> Exporter:
    return make_exporter(request.param)


class TestExporterConformance:
    def test_is_exporter(self, exporter: Exporter) -> None:
        assert isinstance(exporter, Exporter)

    def test_round_trip(self, exporter: Exporter, tmp_path: Path) -> None:
        ep = _make_episode()
        root = exporter.export([ep], tmp_path / "ds")
        loaded = exporter.load(root)
        assert len(loaded) == 1
        assert loaded[0].episode_id == ep.episode_id
        assert len(loaded[0].samples) == len(ep.samples)

    def test_round_trip_field_equality(self, exporter: Exporter, tmp_path: Path) -> None:
        ep = _make_episode()
        root = exporter.export([ep], tmp_path / "ds")
        loaded = exporter.load(root)[0]
        assert loaded.episode_id == ep.episode_id
        assert loaded.task_label == ep.task_label
        for orig, back in zip(ep.samples, loaded.samples, strict=True):
            assert orig.timestamp_ns == back.timestamp_ns
            assert orig.chain_index == back.chain_index
            assert abs(orig.joint_angle - back.joint_angle) < 1e-9
            assert orig.task_label == back.task_label
            assert orig.episode_id == back.episode_id

    def test_empty_export(self, exporter: Exporter, tmp_path: Path) -> None:
        root = exporter.export([], tmp_path / "empty")
        loaded = exporter.load(root)
        assert loaded == []
