"""Wiring test: host/transport file replay -> bridge conversion -> JointPodState.

Proves host/transport is a first-class bridge input. Frames are recorded to a
``.canlog`` with the real :class:`~transport.file.FileRecorder`, replayed through
:class:`~transport.file.FileReplayTransport`, exposed via the bridge
:class:`~inhabit_bridge.transport_source.TransportSource`, and converted with the
ROS-independent ``build_message``. The oracle for every published field is the
FROZEN codec ``decode_state`` -- decoding is never re-implemented here.

Runs as plain Python (no ROS install): a stub message type mirrors the generated
``inhabit_msgs/JointPodState``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from inhabit_bridge.bridge_node import _make_source, build_message
from inhabit_bridge.sources import CanFrame
from inhabit_bridge.transport_source import TransportSource
from inhabit_can.codec import State, decode_state, encode_state
from transport.file import FileRecorder, FileReplayTransport


# --- Stub mirroring inhabit_msgs/JointPodState (no ROS needed) ---
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


def _frame(node_id: int, millideg: int, raw: int, chain: int) -> tuple[int, bytes]:
    return encode_state(
        State(
            angle_raw_adc=raw,
            angle_millideg=millideg,
            node_id=node_id,
            chain_index=chain,
            status_flags=0,
        )
    )


def _record(path: Path, frames: list[tuple[int, bytes]]) -> None:
    with FileRecorder(path) as rec:
        for i, (cid, data) in enumerate(frames):
            rec.write(CanFrame(can_id=cid, data=data, rx_monotonic_ns=(i + 1) * 1_000))


def test_file_replay_transport_feeds_bridge_conversion(tmp_path: Path) -> None:
    """End-to-end: .canlog -> TransportSource -> build_message == decode_state."""
    logfile = tmp_path / "run.canlog"
    raw_frames = [
        _frame(node_id=0, millideg=10_000, raw=2048, chain=0),
        _frame(node_id=1, millideg=-5_000, raw=1024, chain=1),
        _frame(node_id=2, millideg=22_500, raw=4000, chain=2),
    ]
    _record(logfile, raw_frames)

    # Drive the transport through the bridge's CanSource interface.
    source = TransportSource(FileReplayTransport(logfile), stop_on_none=True)
    with source:
        msgs = [build_message(f, StubJointPodState) for f in source.frames()]

    assert len(msgs) == len(raw_frames)
    for msg, (_cid, data) in zip(msgs, raw_frames, strict=True):
        ref = decode_state(data)  # frozen codec is the oracle
        assert msg.node_id == ref.node_id
        assert msg.chain_index == ref.chain_index
        assert msg.angle_raw_adc == ref.angle_raw_adc
        assert msg.angle_millideg == ref.angle_millideg
        assert msg.status_flags == ref.status_flags
        assert msg.checksum_valid is ref.valid is True
        assert msg.schema_version == 1


def test_make_source_file_resolves_transport_source(tmp_path: Path) -> None:
    """source:=file path:=X yields a TransportSource that replays the recording."""
    logfile = tmp_path / "one.canlog"
    cid, data = _frame(node_id=3, millideg=12_345, raw=2000, chain=0)
    _record(logfile, [(cid, data)])

    source = _make_source("file", channel="can0", path=str(logfile))
    assert isinstance(source, TransportSource)
    with source:
        frames = list(source.frames())
    assert len(frames) == 1
    assert decode_state(frames[0].data).angle_millideg == 12_345


def test_make_source_file_requires_path() -> None:
    """source:=file without a path fails loud, not with an empty stream."""
    try:
        _make_source("file", channel="can0", path="")
    except ValueError as exc:
        assert "path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError when source='file' has no path")


def test_make_source_socketcan_is_transport_backed() -> None:
    """source:=socketcan is now wired through host/transport (no hardware needed)."""
    source = _make_source("socketcan", channel="can1", path="")
    assert isinstance(source, TransportSource)


def test_make_source_unknown_rejected() -> None:
    try:
        _make_source("bogus", channel="can0", path="")
    except ValueError as exc:
        assert "unknown can source" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown source")
