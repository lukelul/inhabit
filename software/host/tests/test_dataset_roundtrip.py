"""Round-trip test: SimAdapter -> lerobot export -> load -> assert equal.

Verifies the full data pipeline: synthetic episode generation, lerobot-format
parquet export, and faithful reload — no hardware required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# tools/ is outside host/; add repo root so the import resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.dataset import SimAdapter
from tools.dataset.sim_adapter import SimConfig

from inhabit_can.pvt import Episode, PVTSample

from export.lerobot import export_lerobot, load_lerobot


def test_single_episode_roundtrip(tmp_path: Path) -> None:
    """Generate one episode, export to lerobot format, load back, assert equal."""
    adapter = SimAdapter(SimConfig(n_joints=3, n_samples=50, task_label="sim_reach"))
    episode = adapter.generate_episode(episode_id="test_ep_001")

    export_lerobot([episode], tmp_path / "dataset")
    loaded = load_lerobot(tmp_path / "dataset")

    assert len(loaded) == 1
    ep = loaded[0]
    assert ep.episode_id == episode.episode_id
    assert ep.task_label == episode.task_label
    assert len(ep.samples) == len(episode.samples)

    for orig, back in zip(episode.samples, ep.samples, strict=True):
        assert orig.timestamp_ns == back.timestamp_ns
        assert orig.chain_index == back.chain_index
        assert orig.joint_angle == pytest.approx(back.joint_angle)
        assert orig.joint_velocity == pytest.approx(back.joint_velocity)
        assert orig.motor_current == pytest.approx(back.motor_current)
        assert orig.estimated_torque == pytest.approx(back.estimated_torque)
        assert orig.task_label == back.task_label


def test_multi_episode_roundtrip(tmp_path: Path) -> None:
    """Multiple episodes with different configs round-trip correctly."""
    adapter = SimAdapter()
    episodes = [
        adapter.generate_episode(
            episode_id=f"ep_{i}",
            config=SimConfig(n_joints=2, n_samples=20, task_label=f"task_{i}"),
        )
        for i in range(3)
    ]

    export_lerobot(episodes, tmp_path / "ds")
    loaded = load_lerobot(tmp_path / "ds")

    assert len(loaded) == 3
    for orig, back in zip(episodes, loaded, strict=True):
        assert orig.episode_id == back.episode_id
        assert orig.task_label == back.task_label
        assert len(orig.samples) == len(back.samples)


def test_lerobot_meta_files_written(tmp_path: Path) -> None:
    """Export creates the expected meta files."""
    adapter = SimAdapter(SimConfig(n_joints=2, n_samples=10))
    episode = adapter.generate_episode(episode_id="meta_test")
    root = export_lerobot([episode], tmp_path / "ds")

    assert (root / "meta" / "info.json").exists()
    assert (root / "meta" / "episodes.jsonl").exists()
    assert (root / "meta" / "tasks.jsonl").exists()
    assert list((root / "data").glob("*.parquet"))


def test_empty_episodes_no_crash(tmp_path: Path) -> None:
    """Exporting an empty list produces no data files but doesn't crash."""
    root = export_lerobot([], tmp_path / "empty")
    loaded = load_lerobot(root)
    assert loaded == []


def test_sparse_chain_index_roundtrip(tmp_path: Path) -> None:
    """Sparse / non-zero-based joint indices round-trip as themselves.

    Regression: v1 reconstructed chain_index from row position, so joints 2 and 5
    would reload as 0 and 1 — corrupting which physical joint each row belongs to.
    """
    ep = Episode(episode_id="sparse", task_label="t")
    for ts in (1_000_000_000, 1_010_000_000):
        ep.add(PVTSample(timestamp_ns=ts, episode_id="sparse", chain_index=5, joint_angle=0.5))
        ep.add(PVTSample(timestamp_ns=ts, episode_id="sparse", chain_index=2, joint_angle=0.2))

    export_lerobot([ep], tmp_path / "ds")
    loaded = load_lerobot(tmp_path / "ds")[0]

    assert sorted({s.chain_index for s in loaded.samples}) == [2, 5]
    for s in loaded.samples:
        expected = 0.5 if s.chain_index == 5 else 0.2
        assert s.joint_angle == pytest.approx(expected)


def test_info_json_timing_is_derived(tmp_path: Path) -> None:
    """info.json fps is derived from sample cadence, with monotonic clock metadata."""
    # 10 ms spacing -> 100 Hz; must NOT be the hard-coded default.
    adapter = SimAdapter(SimConfig(n_joints=2, n_samples=20, frequency_hz=100.0))
    episode = adapter.generate_episode(episode_id="timing")
    root = export_lerobot([episode], tmp_path / "ds")

    info = json.loads((root / "meta" / "info.json").read_text())
    assert info["fps"] == pytest.approx(100.0)
    assert info["schema_version"] == 3
    tb = info["time_base"]
    assert tb["clock_source"] == "monotonic_host"
    assert tb["timestamp_field"] == "timestamp_ns"
    assert "measured_jitter_ns" in tb


def test_sim_config_rejects_invalid() -> None:
    """Invalid SimConfig fails fast with ValueError, not Zero/IndexError."""
    with pytest.raises(ValueError, match="frequency_hz"):
        SimAdapter().generate_episode(config=SimConfig(frequency_hz=0.0))
    with pytest.raises(ValueError, match="phase_offsets"):
        SimAdapter().generate_episode(config=SimConfig(n_joints=3, phase_offsets=[0.0]))
    with pytest.raises(ValueError, match="at least 1 ns"):
        SimAdapter().generate_episode(config=SimConfig(frequency_hz=2e9))


def test_cli_sim_export_roundtrip(tmp_path: Path) -> None:
    """CLI: --sim export produces a valid lerobot dataset that round-trips."""
    from tools.dataset.__main__ import main

    rc = main(["export", "--sim", "-o", str(tmp_path / "cli_ds"), "--verify"])
    assert rc == 0
    # Verify the dataset files exist
    assert (tmp_path / "cli_ds" / "meta" / "info.json").exists()
    assert list((tmp_path / "cli_ds" / "data").glob("*.parquet"))


def test_cli_parquet_export_roundtrip(tmp_path: Path) -> None:
    """CLI: .parquet input -> lerobot export round-trips."""
    from logger.parquet_io import write_episode
    from tools.dataset.__main__ import main

    # Write a per-episode parquet first
    adapter = SimAdapter(SimConfig(n_joints=2, n_samples=20, task_label="cli_test"))
    episode = adapter.generate_episode(episode_id="cli_ep")
    pq_path = tmp_path / "cli_ep.parquet"
    write_episode(episode, pq_path)

    rc = main(["export", "-i", str(pq_path), "-o", str(tmp_path / "cli_ds"), "--verify"])
    assert rc == 0


def test_sim_adapter_deterministic() -> None:
    """Same config + episode_id produces identical episodes."""
    cfg = SimConfig(n_joints=2, n_samples=30)
    a = SimAdapter(cfg).generate_episode(episode_id="det")
    b = SimAdapter(cfg).generate_episode(episode_id="det")
    for sa, sb in zip(a.samples, b.samples, strict=True):
        assert sa.as_row() == sb.as_row()
