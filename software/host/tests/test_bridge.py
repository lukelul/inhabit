"""Tests for inhabit_bridge: raw CAN frame -> JointPodState fields.

These run as plain Python (no ROS install). A stub message class mirrors the
generated ``inhabit_msgs/JointPodState`` so ``build_message`` is exercised
end-to-end. The oracle for every field is the FROZEN codec ``decode_state()``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from inhabit_bridge.bridge_node import build_message, stamp_from_monotonic_ns
from inhabit_bridge.conversion import fields_from_frame
from inhabit_bridge.sources import CanFrame, ReplaySource, SimSource
from inhabit_can.codec import PROTO_VERSION, State, decode_state, encode_state


# --- Stub message type mirroring inhabit_msgs/JointPodState (no ROS needed) ---
@dataclass
class _Time:
    sec: int = 0
    nanosec: int = 0


@dataclass
class _Header:
    stamp: _Time = field(default_factory=_Time)
    frame_id: str = ""


@dataclass
class StubJointPodState:
    header: _Header = field(default_factory=_Header)
    node_id: int = 0
    chain_index: int = 0
    angle_raw_adc: int = 0
    angle_millideg: int = 0
    angle_rad: float = 0.0
    status_flags: int = 0
    checksum_valid: bool = False
    schema_version: int = 0


def _frame(
    node_id: int, millideg: int, raw: int = 1234, chain: int = 0, status: int = 0
) -> tuple[int, bytes]:
    return encode_state(
        State(
            angle_raw_adc=raw,
            angle_millideg=millideg,
            node_id=node_id,
            chain_index=chain,
            status_flags=status,
        )
    )


def test_fields_match_codec_for_known_frame() -> None:
    # angle_millideg is int16 in the frozen v1 schema (~+/-32.767 deg).
    _cid, data = _frame(node_id=3, millideg=22500, raw=2048, chain=1, status=0)
    fields = fields_from_frame(data)
    ref = decode_state(data)

    assert fields.node_id == ref.node_id == 3
    assert fields.chain_index == ref.chain_index == 1
    assert fields.angle_raw_adc == ref.angle_raw_adc == 2048
    assert fields.angle_millideg == ref.angle_millideg == 22500
    assert fields.status_flags == ref.status_flags
    assert fields.checksum_valid is ref.valid is True
    assert fields.schema_version == PROTO_VERSION == 1


def test_angle_rad_derivation() -> None:
    # 22.500 deg -> pi/8 rad (within int16 millideg range)
    _cid, data = _frame(node_id=0, millideg=22500)
    fields = fields_from_frame(data)
    assert math.isclose(fields.angle_rad, math.pi / 8, rel_tol=1e-9)

    # negative angle: -30.000 deg -> -pi/6 rad
    _cid, data = _frame(node_id=0, millideg=-30000)
    fields = fields_from_frame(data)
    assert math.isclose(fields.angle_rad, -math.pi / 6, rel_tol=1e-9)


def test_bad_checksum_flag_false_still_decodes() -> None:
    _cid, data = _frame(node_id=5, millideg=1000)
    bad = bytearray(data)
    bad[0] ^= 0x01  # corrupt payload, checksum no longer matches
    fields = fields_from_frame(bytes(bad))
    # Frame still decodes; flag reflects corruption (fail loud, not silent drop).
    assert fields.checksum_valid is False
    assert decode_state(bytes(bad)).valid is False


def test_build_message_populates_all_fields_and_monotonic_stamp() -> None:
    cid, data = _frame(node_id=2, millideg=30000, raw=1500, chain=2, status=0x04)
    rx_ns = 1_500_000_750  # 1 s, 500000750 ns
    frame = CanFrame(can_id=cid, data=data, rx_monotonic_ns=rx_ns)
    msg = build_message(frame, StubJointPodState, frame_id="pod_chain")

    assert msg.header.frame_id == "pod_chain"
    assert msg.header.stamp.sec == 1
    assert msg.header.stamp.nanosec == 500_000_750
    assert (msg.header.stamp.sec, msg.header.stamp.nanosec) == stamp_from_monotonic_ns(rx_ns)
    ref = decode_state(data)
    assert msg.node_id == ref.node_id
    assert msg.chain_index == ref.chain_index
    assert msg.angle_raw_adc == ref.angle_raw_adc
    assert msg.angle_millideg == ref.angle_millideg
    assert msg.status_flags == ref.status_flags
    assert msg.checksum_valid is ref.valid
    assert msg.schema_version == PROTO_VERSION


def test_stamp_split_round_trips() -> None:
    for ns in (0, 999_999_999, 1_000_000_000, 12_345_678_901):
        sec, nanosec = stamp_from_monotonic_ns(ns)
        assert 0 <= nanosec < 1_000_000_000
        assert sec * 1_000_000_000 + nanosec == ns


def test_replay_source_stamps_monotonic_and_is_deterministic() -> None:
    counter = {"n": 0}

    def fake_clock() -> int:
        counter["n"] += 1
        return counter["n"] * 1000  # strictly increasing ns

    _c0, d0 = _frame(node_id=0, millideg=0)
    _c1, d1 = _frame(node_id=1, millideg=1000)
    src = ReplaySource([(_c0, d0), (_c1, d1)], clock_ns=fake_clock)
    with src:
        out = list(src.frames())
    assert [f.rx_monotonic_ns for f in out] == [1000, 2000]  # monotonic increasing
    # Each frame decodes back to its source via the frozen codec.
    assert decode_state(out[0].data).node_id == 0
    assert decode_state(out[1].data).node_id == 1


def test_replay_source_requires_open() -> None:
    src = ReplaySource([])
    try:
        next(iter(src.frames()))
    except RuntimeError as exc:
        assert "before open()" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError when frames() called before open()")


def test_sim_source_produces_valid_publishable_messages() -> None:
    src = SimSource(num_pods=2, count=3)
    with src:
        frames = list(src.frames())
    assert len(frames) == 6  # 2 pods x 3 samples
    for f in frames:
        msg = build_message(f, StubJointPodState)
        assert msg.checksum_valid is True  # sim frames are well-formed
        assert msg.schema_version == PROTO_VERSION
        assert msg.header.stamp.sec >= 0
