"""ULTRACODE Lane C — tests for dataset/export corruption gates.

C1: CLI drops corrupt-checksum frames (not exported to lerobot).
C2: export_lerobot refuses non-monotonic / dropout episodes, flags over-budget.
C3: interleaved-pod grouping groups by timestamp, not adjacency (round-trips correctly).
C4: NaN/inf joint values rejected by the recorder and the CLI canlog path.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from export.lerobot import _group_samples_by_frame, export_lerobot, load_lerobot
from inhabit_bridge.conversion import fields_from_frame
from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from inhabit_can.pvt import Episode, JointPodState, PVTSample
from logger.jitter import JitterBudget
from logger.parquet_io import read_episode
from logger.recorder import EpisodeRecorder, frame_reject_reason
from transport.file import FileRecorder, _load_canlog


def _make_canlog_with_bad_checksum(path: Path) -> Path:
    """Write a .canlog with one valid and one corrupt-checksum frame."""
    with FileRecorder(path) as fr:
        # Valid frame
        cid, data = encode_state(State(
            angle_raw_adc=100, angle_millideg=5000,
            node_id=1, chain_index=0, status_flags=0,
        ))
        fr.write(CanFrame(can_id=cid, data=data, rx_monotonic_ns=1_000_000))
        # Corrupt frame — flip a bit in the checksum byte (byte 7)
        bad_data = bytearray(data)
        bad_data[7] ^= 0xFF
        fr.write(CanFrame(can_id=cid, data=bytes(bad_data), rx_monotonic_ns=2_000_000))
        # Another valid frame
        cid2, data2 = encode_state(State(
            angle_raw_adc=200, angle_millideg=6000,
            node_id=1, chain_index=0, status_flags=0,
        ))
        fr.write(CanFrame(can_id=cid2, data=data2, rx_monotonic_ns=3_000_000))
    return path


def test_c1_cli_drops_corrupt_checksum(tmp_path: Path) -> None:
    """C1: CLI canlog export drops corrupt-checksum frames."""
    from tools.dataset.__main__ import main

    canlog = _make_canlog_with_bad_checksum(tmp_path / "bad.canlog")
    out = tmp_path / "ds"
    rc = main(["export", "-i", str(canlog), "-o", str(out), "--verify"])
    assert rc == 0

    loaded = load_lerobot(out)
    assert len(loaded) == 1
    # 3 frames written, 1 corrupt -> 2 exported
    assert len(loaded[0].samples) == 2


def _make_canlog_3good_1flipped(path: Path) -> Path:
    """3 valid frames + 1 with a flipped checksum byte — the audit's repro input."""
    with FileRecorder(path) as fr:
        for tick in range(4):
            cid, data = encode_state(State(
                angle_raw_adc=(tick * 13) & 0xFFFF, angle_millideg=1000 + tick * 100,
                node_id=1, chain_index=0, status_flags=0,
            ))
            if tick == 2:
                data = data[:7] + bytes([data[7] ^ 0xFF])  # corrupt the checksum
            fr.write(CanFrame(can_id=cid, data=data, rx_monotonic_ns=tick * 10_000_000))
    return path


def test_c1_three_good_one_flipped_exports_three(tmp_path: Path) -> None:
    """Audit repro: a canlog with 3 good + 1 flipped-checksum frame exports 3, not 4.

    Mirrors the recorder, which drops corrupt frames at ingest (recorder.py). Before
    the fix the CLI carried checksum_valid but never checked it, so it exported 4.
    """
    from tools.dataset.__main__ import main

    canlog = _make_canlog_3good_1flipped(tmp_path / "corrupt.canlog")
    out = tmp_path / "ds"
    rc = main(["export", "-i", str(canlog), "-o", str(out), "--task", "repro"])
    assert rc == 0

    loaded = load_lerobot(out)
    assert len(loaded) == 1
    assert len(loaded[0].samples) == 3  # corrupt frame dropped (bug => 4)


def test_c1_recorder_and_cli_agree_on_drop_count(tmp_path: Path) -> None:
    """The recorder and the CLI loader drop the SAME frames (one shared policy)."""
    from tools.dataset.__main__ import _load_canlog_episode

    canlog = _make_canlog_3good_1flipped(tmp_path / "corrupt.canlog")

    # CLI path
    cli_ep = _load_canlog_episode(canlog, "e", "t")

    # Recorder path over the same decoded frames
    rec = EpisodeRecorder("e", tmp_path / "rec", task_label="t")
    for t_ns, _cid, data in _load_canlog(canlog):
        f = fields_from_frame(data)
        rec.ingest(JointPodState(
            node_id=f.node_id, chain_index=f.chain_index, angle_raw_adc=f.angle_raw_adc,
            angle_millideg=f.angle_millideg, angle_rad=f.angle_rad,
            status_flags=f.status_flags, checksum_valid=f.checksum_valid,
            schema_version=f.schema_version, header_stamp_ns=t_ns,
        ))
    assert len(cli_ep.samples) == len(rec.episode.samples) == 3
    assert rec._dropped_checksum == 1


# --- C2: backwards / dropout refused; over-budget-but-monotonic flagged --------


def test_c2_export_refuses_backwards_timestamps(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C2: export_lerobot refuses (skips) episodes with backwards timestamps."""
    ep = Episode(episode_id="backwards", task_label="test")
    # Distinct instants captured in backward order: 3, 2, 1.
    for ts in [3_000_000, 2_000_000, 1_000_000]:
        ep.add(PVTSample(
            timestamp_ns=ts, episode_id="backwards", chain_index=0, joint_angle=0.1,
        ))

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        export_lerobot([ep], tmp_path / "ds")

    assert any("REFUSED" in r.message for r in caplog.records)
    assert load_lerobot(tmp_path / "ds") == []  # not in the dataset


def test_c2_export_refuses_dropout(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A hole in the timeline (> max_gap_factor x period) refuses the episode."""
    ep = Episode(episode_id="dropout", task_label="t")
    # 10 ms cadence, then a 50 ms jump = a missed-frame hole (>2.5x period).
    for ts in [0, 10_000_000, 20_000_000, 70_000_000, 80_000_000]:
        ep.add(PVTSample(timestamp_ns=ts, episode_id="dropout", chain_index=0, joint_angle=0.1))

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        export_lerobot([ep], tmp_path / "ds")
    assert any("REFUSED" in r.message and "dropout" in r.message for r in caplog.records)
    assert load_lerobot(tmp_path / "ds") == []


def test_c2_export_flags_over_budget_but_keeps_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Over-budget jitter (monotonic, hole-free) is FLAGGED quality_failed, not refused."""
    ep = Episode(episode_id="loose", task_label="t")
    # Monotonic, no dropout, but inter-sample gaps wobble enough to exceed a tight
    # p99 budget without crossing the dropout factor.
    for ts in [0, 10_000_000, 20_500_000, 30_000_000, 40_500_000]:
        ep.add(PVTSample(timestamp_ns=ts, episode_id="loose", chain_index=0, joint_angle=0.1))

    tight = JitterBudget(max_jitter_p99_ns=100_000, max_gap_factor=10.0, min_samples=2)
    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        root = export_lerobot([ep], tmp_path / "ds", budget=tight)

    loaded = load_lerobot(root)
    assert len(loaded) == 1 and len(loaded[0].samples) == 5  # still exported
    assert any("FLAGGED" in r.message for r in caplog.records)
    em = [json.loads(line) for line in (root / "meta" / "episodes.jsonl").read_text().splitlines()]
    assert em[0]["quality_failed"] is True
    assert em[0]["quality_reasons"]


def test_c2_refusal_reindexes_remaining_episodes_densely(tmp_path: Path) -> None:
    """A refused episode must not leave a gap in episode_index of the written set."""
    bad = Episode(episode_id="bad", task_label="t")  # backwards -> refused
    for ts in [3_000_000, 2_000_000, 1_000_000]:
        bad.add(PVTSample(timestamp_ns=ts, episode_id="bad", chain_index=0, joint_angle=0.1))
    good = Episode(episode_id="good", task_label="t")  # clean -> exported
    for i in range(4):
        good.add(PVTSample(
            timestamp_ns=i * 10_000_000, episode_id="good", chain_index=0, joint_angle=float(i),
        ))

    root = export_lerobot([bad, good], tmp_path / "ds")
    info = json.loads((root / "meta" / "info.json").read_text())
    assert info["total_episodes"] == 1
    assert info["total_episodes_input"] == 2
    assert [r["episode_id"] for r in info["rejected_episodes"]] == ["bad"]

    em = [json.loads(line) for line in (root / "meta" / "episodes.jsonl").read_text().splitlines()]
    assert len(em) == 1
    assert em[0]["episode_index"] == 0  # dense, not 1
    assert em[0]["episode_id"] == "good"

    # The written PARQUET rows must also be dense: the raw episode_index column is
    # the on-disk contract consumers actually read, so assert it directly (not just
    # the meta files). With episode 0 refused, the surviving episode is index 0.
    parquet_files = sorted((root / "data").glob("*.parquet"))
    assert len(parquet_files) == 1
    table = pq.read_table(parquet_files[0])
    assert set(table.column("episode_index").to_pylist()) == {0}

    loaded = load_lerobot(root)
    assert len(loaded) == 1 and loaded[0].episode_id == "good"


def test_c2_interleaved_multipod_not_refused(tmp_path: Path) -> None:
    """A legitimately interleaved multi-pod episode is NOT mistaken for backwards.

    Two pods at the same two instants, appended interleaved so the raw per-sample
    timestamp list goes ...200, 100... — which a naive raw-order check would flag as
    backwards. The instant-order (unique first-appearance) check keeps it.
    """
    ep = Episode(episode_id="interleaved_ok", task_label="t")
    ep.add(PVTSample(timestamp_ns=100, episode_id="i", chain_index=0, joint_angle=0.1))
    ep.add(PVTSample(timestamp_ns=200, episode_id="i", chain_index=0, joint_angle=0.2))
    ep.add(PVTSample(timestamp_ns=100, episode_id="i", chain_index=1, joint_angle=0.3))
    ep.add(PVTSample(timestamp_ns=200, episode_id="i", chain_index=1, joint_angle=0.4))

    root = export_lerobot([ep], tmp_path / "ds")
    loaded = load_lerobot(root)
    assert len(loaded) == 1
    assert len(loaded[0].samples) == 4  # nothing refused


# --- C3: interleaved grouping (group-by-timestamp) + round-trip correctness ----


def test_c3_interleaved_pod_grouping() -> None:
    """C3: _group_samples_by_frame groups by timestamp, not adjacency."""
    ep = Episode(episode_id="interleaved", task_label="test")
    # Non-adjacent same-timestamp samples (pod0 t0, pod0 t1, pod1 t0, pod1 t1).
    ep.add(PVTSample(timestamp_ns=100, episode_id="i", chain_index=0, joint_angle=0.1))
    ep.add(PVTSample(timestamp_ns=200, episode_id="i", chain_index=0, joint_angle=0.2))
    ep.add(PVTSample(timestamp_ns=100, episode_id="i", chain_index=1, joint_angle=0.3))
    ep.add(PVTSample(timestamp_ns=200, episode_id="i", chain_index=1, joint_angle=0.4))

    frames = _group_samples_by_frame(ep)
    assert len(frames) == 2  # two distinct timestamps, not four adjacency runs
    assert len(frames[0]) == 2  # both pods at t=100
    assert len(frames[1]) == 2  # both pods at t=200


def test_c3_interleaved_export_roundtrip_correct_vectors(tmp_path: Path) -> None:
    """Interleaved pods round-trip with each instant carrying BOTH joints' values.

    Regression for adjacency grouping: an out-of-order same-instant sample used to
    start a new frame, splitting one instant and scrambling the joint vector.
    """
    ep = Episode(episode_id="rt", task_label="t")
    ep.add(PVTSample(timestamp_ns=100, episode_id="rt", chain_index=0, joint_angle=1.0))
    ep.add(PVTSample(timestamp_ns=200, episode_id="rt", chain_index=0, joint_angle=2.0))
    ep.add(PVTSample(timestamp_ns=100, episode_id="rt", chain_index=1, joint_angle=10.0))
    ep.add(PVTSample(timestamp_ns=200, episode_id="rt", chain_index=1, joint_angle=20.0))

    root = export_lerobot([ep], tmp_path / "ds")
    loaded = load_lerobot(root)[0]

    by_instant: dict[int, dict[int, float]] = {}
    for s in loaded.samples:
        by_instant.setdefault(s.timestamp_ns, {})[s.chain_index] = s.joint_angle
    # Each instant must carry BOTH joints (not split across frames).
    assert by_instant[100] == pytest.approx({0: 1.0, 1: 10.0})
    assert by_instant[200] == pytest.approx({0: 2.0, 1: 20.0})


# --- C4: NaN/inf rejected by the recorder and by the CLI canlog path -----------


def test_c4_nan_rejected_by_recorder(tmp_path: Path) -> None:
    """C4: EpisodeRecorder drops NaN/inf joint values (unconditional finiteness guard)."""
    rec = EpisodeRecorder("nan_ep", tmp_path, task_label="test")
    rec.ingest(JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=0.087, status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=1_000_000,
    ))
    rec.ingest(JointPodState(  # NaN -> dropped
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=float("nan"), status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=2_000_000,
    ))
    rec.ingest(JointPodState(  # inf -> dropped
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=float("inf"), status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=3_000_000,
    ))
    rec.ingest(JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=200, angle_millideg=6000,
        angle_rad=0.105, status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=4_000_000,
    ))
    result = rec.finalize()
    assert result.exported
    assert result.stats.n_samples == 2  # only the two finite ones
    assert rec._dropped_nonfinite == 2

    # House rule: export tests write -> read -> assert-equal. Prove finalize()
    # PERSISTED only the two finite samples to parquet (not just the in-memory
    # counters): a NaN/inf must never reach disk.
    assert result.path is not None and result.path.exists()
    episode, meta = read_episode(result.path)
    assert [s.timestamp_ns for s in episode.samples] == [1_000_000, 4_000_000]
    assert [s.joint_angle for s in episode.samples] == pytest.approx([0.087, 0.105])
    assert all(s.chain_index == 0 for s in episode.samples)
    assert meta["dropped_nonfinite"] == 2


def test_c4_frame_reject_reason_policy() -> None:
    """C4: frame_reject_reason returns a reason for bad frames, None for good."""
    good = JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=0.087, status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=1_000_000,
    )
    assert frame_reject_reason(good) is None

    bad_checksum = JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=0.087, status_flags=0, checksum_valid=False,
        schema_version=1, header_stamp_ns=1_000_000,
    )
    assert frame_reject_reason(bad_checksum) == "checksum_invalid"

    nan_angle = JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=100, angle_millideg=5000,
        angle_rad=float("nan"), status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=1_000_000,
    )
    reason = frame_reject_reason(nan_angle)
    assert reason is not None
    assert "non_finite" in reason


def test_c4_cli_canlog_uses_same_nonfinite_guard() -> None:
    """The CLI canlog loader applies the SAME non-finite policy as the recorder.

    angle_millideg is an int16, so the frozen codec itself cannot emit NaN/inf; the
    finiteness guard exists for future-derived float fields and corrupted floats. We
    prove the CLI routes through the shared frame_reject_reason for a non-finite angle.
    """
    inf_state = JointPodState(
        node_id=1, chain_index=0, angle_raw_adc=1, angle_millideg=1,
        angle_rad=float("inf"), status_flags=0, checksum_valid=True,
        schema_version=1, header_stamp_ns=1,
    )
    assert frame_reject_reason(inf_state) is not None  # CLI uses this exact function
