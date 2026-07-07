"""CanTransport conformance — replay + in-mem transports must satisfy these invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from transport import FileReplayTransport, InMemTransport, make_transport
from transport.file import FileRecorder
from transport.interface import CanTransport


def _make_frames() -> list[CanFrame]:
    frames = []
    for tick in range(5):
        cid, data = encode_state(State(
            angle_raw_adc=tick * 100, angle_millideg=tick * 1000,
            node_id=1, chain_index=0, status_flags=0,
        ))
        frames.append(CanFrame(can_id=cid, data=data, rx_monotonic_ns=tick * 10_000_000))
    return frames


def _write_canlog(path: Path, frames: list[CanFrame]) -> Path:
    with FileRecorder(path) as fr:
        for f in frames:
            fr.write(f)
    return path


class TestFileReplayConformance:
    def test_is_can_transport(self, tmp_path: Path) -> None:
        _write_canlog(tmp_path / "t.canlog", _make_frames())
        assert isinstance(FileReplayTransport(tmp_path / "t.canlog"), CanTransport)

    def test_recv_before_open_raises(self, tmp_path: Path) -> None:
        _write_canlog(tmp_path / "t.canlog", _make_frames())
        with pytest.raises(RuntimeError):
            FileReplayTransport(tmp_path / "t.canlog").recv()

    def test_context_manager_recv(self, tmp_path: Path) -> None:
        _write_canlog(tmp_path / "t.canlog", _make_frames())
        with FileReplayTransport(tmp_path / "t.canlog") as t:
            assert t.recv() is not None

    def test_close_idempotent(self, tmp_path: Path) -> None:
        _write_canlog(tmp_path / "t.canlog", _make_frames())
        t = FileReplayTransport(tmp_path / "t.canlog")
        t.open()
        t.close()
        t.close()

    def test_timestamps_monotonic(self, tmp_path: Path) -> None:
        _write_canlog(tmp_path / "t.canlog", _make_frames())
        with FileReplayTransport(tmp_path / "t.canlog") as t:
            prev = -1
            while (f := t.recv()) is not None:
                assert f.rx_monotonic_ns > prev
                prev = f.rx_monotonic_ns

    def test_round_trip_field_equality(self, tmp_path: Path) -> None:
        written = _make_frames()
        _write_canlog(tmp_path / "t.canlog", written)
        with FileReplayTransport(tmp_path / "t.canlog") as t:
            for expected in written:
                actual = t.recv()
                assert actual is not None
                assert actual.can_id == expected.can_id
                assert actual.data == expected.data
            assert t.recv() is None

    def test_send_is_noop(self, tmp_path: Path) -> None:
        written = _make_frames()
        _write_canlog(tmp_path / "t.canlog", written)
        with FileReplayTransport(tmp_path / "t.canlog") as t:
            first = t.recv()
            assert first is not None
            t.send(0x100, b"\x00" * 8)  # must not affect replay state
            second = t.recv()
            assert second is not None
            assert second.can_id == written[1].can_id  # next frame unchanged
            assert second.data == written[1].data


class TestInMemTransportConformance:
    def test_is_can_transport(self) -> None:
        assert isinstance(InMemTransport(), CanTransport)

    def test_loopback(self) -> None:
        t = InMemTransport()
        t.open()
        t.send(0x100, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        f = t.recv(timeout_s=0.1)
        assert f is not None
        assert f.can_id == 0x100
        assert f.data == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    def test_recv_empty_returns_none(self) -> None:
        t = InMemTransport()
        t.open()
        assert t.recv(timeout_s=0.01) is None

    def test_registry_discovery(self) -> None:
        t = make_transport("inmem")
        assert isinstance(t, InMemTransport)
