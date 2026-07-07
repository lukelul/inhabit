"""Tests for host/transport/ — CanTransport interface, file record/replay round-trip.

All tests run headless (no hardware, no ROS). The frozen codec is the oracle.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from inhabit_bridge.bridge_node import _make_source
from inhabit_bridge.sources import CanFrame
from inhabit_bridge.transport_source import TransportSource
from inhabit_can.codec import State, decode_state, encode_state
from transport.file import CANLOG_VERSION, FileRecorder, FileReplayTransport, _load_canlog
from transport.interface import CanTransport
from transport.slcan import SlcanTransport


def _make_frame(node_id: int = 0, millideg: int = 15000, chain: int = 0) -> tuple[int, bytes]:
    return encode_state(
        State(
            angle_raw_adc=2048,
            angle_millideg=millideg,
            node_id=node_id,
            chain_index=chain,
            status_flags=0,
        )
    )


# --- FileRecorder + FileReplayTransport round-trip ---


def test_record_replay_round_trip(tmp_path: Path) -> None:
    """Record frames to a .canlog, replay them, and verify codec output matches."""
    logfile = tmp_path / "test.canlog"
    cid0, data0 = _make_frame(node_id=0, millideg=10000, chain=0)
    cid1, data1 = _make_frame(node_id=1, millideg=-5000, chain=1)

    frames_in = [
        CanFrame(can_id=cid0, data=data0, rx_monotonic_ns=1_000_000),
        CanFrame(can_id=cid1, data=data1, rx_monotonic_ns=2_000_000),
    ]

    # Record
    with FileRecorder(logfile) as rec:
        for f in frames_in:
            rec.write(f)

    # Verify file is valid JSONL
    lines = logfile.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert obj["v"] == CANLOG_VERSION
        assert "t_ns" in obj
        assert "id" in obj
        assert "data" in obj

    # Replay with deterministic clock
    counter = {"n": 0}

    def fake_clock() -> int:
        counter["n"] += 1
        return counter["n"] * 500

    transport = FileReplayTransport(logfile, clock_ns=fake_clock)
    with transport:
        out0 = transport.recv()
        out1 = transport.recv()
        out2 = transport.recv()  # exhausted

    assert out0 is not None
    assert out1 is not None
    assert out2 is None

    # Raw round-trip: serialized can_id + payload bytes survive record -> replay
    # exactly. Decoded-field checks alone would miss regressions in can_id or the
    # raw byte layout, so assert the wire bytes themselves.
    assert out0.can_id == frames_in[0].can_id
    assert out0.data == frames_in[0].data
    assert out1.can_id == frames_in[1].can_id
    assert out1.data == frames_in[1].data

    # Timestamps come from the injected clock, not the file
    assert out0.rx_monotonic_ns == 500
    assert out1.rx_monotonic_ns == 1000

    # Codec round-trip: decoded data matches originals
    s0 = decode_state(out0.data)
    s1 = decode_state(out1.data)
    assert s0.node_id == 0
    assert s0.angle_millideg == 10000
    assert s0.valid is True
    assert s1.node_id == 1
    assert s1.angle_millideg == -5000
    assert s1.valid is True


def test_replay_requires_open(tmp_path: Path) -> None:
    logfile = tmp_path / "empty.canlog"
    logfile.write_text("", encoding="utf-8")
    transport = FileReplayTransport(logfile)
    try:
        transport.recv()
    except RuntimeError as exc:
        assert "before open()" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when recv() called before open()")


def test_replay_empty_file(tmp_path: Path) -> None:
    logfile = tmp_path / "empty.canlog"
    logfile.write_text("", encoding="utf-8")
    with FileReplayTransport(logfile) as t:
        assert t.recv() is None


def test_recorder_requires_open(tmp_path: Path) -> None:
    rec = FileRecorder(tmp_path / "x.canlog")
    cid, data = _make_frame()
    try:
        rec.write(CanFrame(can_id=cid, data=data, rx_monotonic_ns=0))
    except RuntimeError as exc:
        assert "before open()" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when write() called before open()")


def test_load_canlog_rejects_malformed(tmp_path: Path) -> None:
    logfile = tmp_path / "bad.canlog"
    logfile.write_text('{"t_ns": 1, "id": 256}\n', encoding="utf-8")  # missing "data"
    try:
        _load_canlog(logfile)
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("expected ValueError for malformed canlog")


def test_load_canlog_rejects_non_object_json(tmp_path: Path) -> None:
    """Valid-but-non-object JSON fails as a contextual ValueError, not AttributeError."""
    logfile = tmp_path / "array.canlog"
    logfile.write_text("[]\n", encoding="utf-8")  # valid JSON, but not an object
    try:
        _load_canlog(logfile)
    except ValueError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-object canlog record")


def test_recorder_rejects_non_8_byte(tmp_path: Path) -> None:
    """write() refuses payloads that the codec could never decode."""
    cid, _ = _make_frame()
    with FileRecorder(tmp_path / "x.canlog") as rec:
        try:
            rec.write(CanFrame(can_id=cid, data=b"\x00" * 4, rx_monotonic_ns=0))
        except ValueError as exc:
            assert "8 bytes" in str(exc)
        else:
            raise AssertionError("expected ValueError for non-8-byte frame")


def test_load_canlog_rejects_non_8_byte(tmp_path: Path) -> None:
    """A log with a short payload fails at load, not later at decode time."""
    logfile = tmp_path / "short.canlog"
    logfile.write_text('{"v":1,"t_ns":1,"id":256,"data":"0011"}\n', encoding="utf-8")
    try:
        _load_canlog(logfile)
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("expected ValueError for short payload")


def test_load_canlog_rejects_unknown_version(tmp_path: Path) -> None:
    """An unrecognized schema version is rejected, not silently misread."""
    logfile = tmp_path / "future.canlog"
    logfile.write_text(
        '{"v":999,"t_ns":1,"id":256,"data":"d204c85800000058"}\n', encoding="utf-8"
    )
    try:
        _load_canlog(logfile)
    except ValueError as exc:
        assert "version" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown canlog version")


def test_replay_send_is_noop(tmp_path: Path) -> None:
    """send() on a replay transport silently does nothing (read-only)."""
    logfile = tmp_path / "empty.canlog"
    logfile.write_text("", encoding="utf-8")
    with FileReplayTransport(logfile) as t:
        t.send(0x100, b"\x00" * 8)  # should not raise


def test_file_replay_is_can_transport(tmp_path: Path) -> None:
    """FileReplayTransport is a proper CanTransport subclass."""
    logfile = tmp_path / "empty.canlog"
    logfile.write_text("", encoding="utf-8")
    t = FileReplayTransport(logfile)
    assert isinstance(t, CanTransport)


def test_recorder_appends(tmp_path: Path) -> None:
    """Multiple open/close cycles append, not overwrite."""
    logfile = tmp_path / "append.canlog"
    cid, data = _make_frame(node_id=0)
    frame = CanFrame(can_id=cid, data=data, rx_monotonic_ns=100)

    with FileRecorder(logfile) as rec:
        rec.write(frame)
    with FileRecorder(logfile) as rec:
        rec.write(frame)

    lines = logfile.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


# --- SlcanTransport ---


def test_slcan_transport_is_can_transport() -> None:
    """SlcanTransport implements the CanTransport ABC."""
    assert issubclass(SlcanTransport, CanTransport)


def test_slcan_transport_requires_open() -> None:
    """recv/send before open raises RuntimeError."""
    t = SlcanTransport(port="/dev/null")
    try:
        t.recv()
    except RuntimeError as exc:
        assert "before open()" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    try:
        t.send(0x100, b"\x00" * 8)
    except RuntimeError as exc:
        assert "before open()" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_slcan_send_rejects_non_8_byte() -> None:
    """SlcanTransport.send() validates 8-byte payload."""
    t = SlcanTransport()
    t._bus = MagicMock()  # fake open
    try:
        t.send(0x100, b"\x00" * 4)
    except ValueError as exc:
        assert "8 bytes" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-8-byte frame")


# --- FileRecorder frame counters ---


def test_recorder_counts_written_frames(tmp_path: Path) -> None:
    """frames_written tracks successful writes."""
    logfile = tmp_path / "count.canlog"
    cid, data = _make_frame()
    frame = CanFrame(can_id=cid, data=data, rx_monotonic_ns=0)

    with FileRecorder(logfile) as rec:
        assert rec.frames_written == 0
        rec.write(frame)
        rec.write(frame)
        rec.write(frame)
        assert rec.frames_written == 3
        assert rec.frames_rejected == 0


def test_recorder_counts_rejected_frames(tmp_path: Path) -> None:
    """frames_rejected tracks 8-byte validation failures."""
    logfile = tmp_path / "reject.canlog"
    cid, _ = _make_frame()

    with FileRecorder(logfile) as rec:
        try:
            rec.write(CanFrame(can_id=cid, data=b"\x00" * 4, rx_monotonic_ns=0))
        except ValueError:
            pass
        assert rec.frames_rejected == 1
        assert rec.frames_written == 0


# --- bridge_node slcan source ---


def test_make_source_slcan() -> None:
    """_make_source('slcan') returns a TransportSource wrapping SlcanTransport."""
    src = _make_source("slcan", channel="/dev/ttyACM0")
    assert isinstance(src, TransportSource)
    assert isinstance(src._transport, SlcanTransport)
