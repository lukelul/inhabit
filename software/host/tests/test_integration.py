"""End-to-end integration test across all three tracks' contracts.

Wires the seams together as pure Python (no ROS, no hardware) so CI catches any
break at a track boundary:

    firmware/codec   inhabit_can.codec.encode_state  -> raw 8-byte CAN frame
    Track 2 bridge   inhabit_bridge.conversion.fields_from_frame -> PodFields
    Contract B       -> inhabit_can.pvt.JointPodState (+ monotonic header_stamp_ns)
    Track 3 data     EpisodeRecorder.ingest/finalize -> parquet
    round-trip       read_episode -> assert equal

The CAN codec is the shared contract; this proves a frame the firmware would emit
flows all the way to a round-trippable ML episode.
"""
from __future__ import annotations

import math
from pathlib import Path

from inhabit_bridge.conversion import fields_from_frame
from inhabit_can.codec import State, encode_state
from inhabit_can.pvt import JointPodState
from logger.parquet_io import read_episode
from logger.recorder import EpisodeRecorder

PERIOD_NS = 10_000_000  # 100 Hz
N = 50
EP = "integ_000001"
TASK = "insert"


def _pod_state(frame: bytes, stamp_ns: int) -> JointPodState:
    """codec frame -> bridge fields -> Contract B JointPodState (+ monotonic stamp)."""
    f = fields_from_frame(frame)
    return JointPodState(
        node_id=f.node_id,
        chain_index=f.chain_index,
        angle_raw_adc=f.angle_raw_adc,
        angle_millideg=f.angle_millideg,
        angle_rad=f.angle_rad,
        status_flags=f.status_flags,
        checksum_valid=f.checksum_valid,
        schema_version=f.schema_version,
        header_stamp_ns=stamp_ns,
    )


def test_codec_to_episode_round_trip(tmp_path: Path) -> None:
    base = 1_000_000_000  # fixed monotonic base; deterministic for CI
    expected_angles: list[float] = []
    states: list[JointPodState] = []

    for i in range(N):
        millideg = round(20000 * math.sin(i / N * math.pi))  # within int16 range
        raw = (i * 37) & 0xFFFF
        can_id, frame = encode_state(
            State(raw, millideg, node_id=3, chain_index=1, status_flags=0)
        )
        assert can_id == 0x103
        assert len(frame) == 8
        st = _pod_state(frame, base + i * PERIOD_NS)
        assert st.checksum_valid  # frozen-codec round-trip must be valid
        assert st.node_id == 3 and st.chain_index == 1
        states.append(st)
        expected_angles.append(st.angle_rad)

    rec = EpisodeRecorder(EP, tmp_path, task_label=TASK)
    for st in states:
        rec.ingest(st)
    result = rec.finalize()

    assert result.exported, f"should pass jitter budget; reasons={result.reasons}"
    assert result.path is not None and result.path.exists()
    assert result.stats.n_samples == N

    ep, _meta = read_episode(result.path)
    assert ep.episode_id == EP
    assert ep.task_label == TASK
    assert len(ep.samples) == N
    for i, s in enumerate(ep.samples):
        assert s.timestamp_ns == base + i * PERIOD_NS, f"ts mismatch @ {i}"
        assert s.chain_index == 1
        assert abs(s.joint_angle - expected_angles[i]) < 1e-9, f"angle @ {i}"
        assert s.task_label == TASK
        assert s.episode_id == EP


def test_corrupt_checksum_frame_dropped(tmp_path: Path) -> None:
    """A frame with a broken checksum must be flagged and kept off the timeline."""
    _id, good = encode_state(State(123, 456, node_id=3, chain_index=1, status_flags=0))
    bad = bytearray(good)
    bad[7] ^= 0xFF  # corrupt the checksum byte

    bad_fields = fields_from_frame(bytes(bad))
    assert not bad_fields.checksum_valid

    rec = EpisodeRecorder("integ_drop", tmp_path, task_label=None)
    # one corrupt frame, then N good frames at 100 Hz
    rec.ingest(_pod_state(bytes(bad), 0))
    base = 1_000_000_000
    for i in range(N):
        _id2, frame = encode_state(State(i, i * 10, node_id=3, chain_index=1, status_flags=0))
        rec.ingest(_pod_state(frame, base + i * PERIOD_NS))
    result = rec.finalize()

    assert result.exported
    assert result.stats.n_samples == N  # corrupt frame excluded, timeline intact
