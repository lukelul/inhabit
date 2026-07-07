"""Tests for the transport registry (P-A/A2).

Covers the registry contract (make/unknown/list), the in-memory loopback transport,
and that the hardware-backed transports (socketcan/slcan) can be *constructed* by name
without their optional deps installed — the lazy-import guarantee that lets a
no-hardware host build a transport object and only fail (loudly) at ``open()``.
"""
from __future__ import annotations

import itertools
import sys
import types
from pathlib import Path

import pytest

from inhabit_bridge.sources import CanFrame
from transport import (
    CanTransport,
    FileReplayTransport,
    InMemTransport,
    SlcanTransport,
    SocketCanTransport,
    list_transports,
    make_transport,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.canlog"


# --------------------------------------------------------------------------------------
# Registry contract
# --------------------------------------------------------------------------------------
class TestRegistry:
    def test_list_transports_sorted_and_complete(self) -> None:
        names = list_transports()
        assert names == sorted(names), "names must be sorted"
        assert {"file", "socketcan", "slcan", "inmem"} <= set(names)

    def test_make_unknown_raises_valueerror_listing_options(self) -> None:
        with pytest.raises(ValueError) as exc:
            make_transport("does-not-exist")
        msg = str(exc.value)
        assert "does-not-exist" in msg
        # The error must guide the caller to a real choice.
        assert "inmem" in msg

    def test_make_returns_cantransport_subtypes(self) -> None:
        assert isinstance(make_transport("inmem"), InMemTransport)
        assert isinstance(make_transport("file", path=FIXTURE), FileReplayTransport)
        # Every built-in is a CanTransport.
        for name in ("file", "socketcan", "slcan", "inmem"):
            kwargs = {"path": FIXTURE} if name == "file" else {}
            assert isinstance(make_transport(name, **kwargs), CanTransport)

    def test_kwargs_forwarded_to_constructor(self) -> None:
        # socketcan/slcan accept config kwargs; make() must forward them verbatim.
        sc = make_transport("socketcan", channel="can1", bitrate=250_000)
        assert isinstance(sc, SocketCanTransport)
        sl = make_transport("slcan", port="/dev/ttyUSB9", bitrate=250_000)
        assert isinstance(sl, SlcanTransport)


# --------------------------------------------------------------------------------------
# Hardware transports: construct without optional deps (lazy-import guarantee)
# --------------------------------------------------------------------------------------
class TestLazyHardwareTransports:
    def test_socketcan_constructs_without_python_can(self) -> None:
        # Constructing must not import python-can; only open() may. Build it, never open.
        t = make_transport("socketcan", channel="can0")
        assert isinstance(t, SocketCanTransport)

    def test_slcan_constructs_without_pyserial(self) -> None:
        t = make_transport("slcan", port="/dev/ttyACM0")
        assert isinstance(t, SlcanTransport)


# --------------------------------------------------------------------------------------
# InMemTransport — FIFO loopback
# --------------------------------------------------------------------------------------
class TestInMemTransport:
    def test_send_then_recv_roundtrips_fifo(self) -> None:
        clock = itertools.count(1000, 10)  # deterministic monotonic stamps
        t = make_transport("inmem", clock_ns=lambda: next(clock))
        assert isinstance(t, InMemTransport)
        t.open()
        t.send(0x101, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        t.send(0x102, b"\xaa\xbb")
        f1 = t.recv()
        f2 = t.recv()
        assert isinstance(f1, CanFrame) and isinstance(f2, CanFrame)
        assert (f1.can_id, f1.data) == (0x101, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        assert (f2.can_id, f2.data) == (0x102, b"\xaa\xbb")
        # Stamps come from the injected clock and strictly increase (time-sync contract).
        assert f1.rx_monotonic_ns == 1000
        assert f2.rx_monotonic_ns == 1010

    def test_recv_on_empty_returns_none(self) -> None:
        t = make_transport("inmem")
        t.open()
        assert t.recv() is None

    def test_preseed_via_constructor(self) -> None:
        t = InMemTransport(frames=[(0x200, b"\xde\xad"), (0x201, b"\xbe\xef")])
        t.open()
        assert t.recv().can_id == 0x200  # type: ignore[union-attr]
        assert t.recv().can_id == 0x201  # type: ignore[union-attr]
        assert t.recv() is None

    def test_send_copies_data_defensively(self) -> None:
        t = InMemTransport()
        t.open()
        buf = bytearray(b"\x01\x02")
        # Deliberately pass a mutable bytearray (send's contract is bytes; bytearray is
        # tolerated at runtime via the defensive bytes() copy). This is exactly what we
        # want to prove: mutating the caller's buffer afterwards must not change the frame.
        t.send(0x300, buf)  # type: ignore[arg-type]
        buf[0] = 0xFF  # mutate caller buffer after send
        frame = t.recv()
        assert frame is not None
        assert frame.data == b"\x01\x02", "queued frame must not see later mutation"

    def test_use_before_open_raises(self) -> None:
        t = InMemTransport()
        with pytest.raises(RuntimeError):
            t.send(0x101, b"\x00")
        with pytest.raises(RuntimeError):
            t.recv()

    def test_close_drains_and_blocks(self) -> None:
        t = InMemTransport()
        t.open()
        t.send(0x101, b"\x00")
        t.close()
        with pytest.raises(RuntimeError):
            t.recv()  # use-after-close must fail loud, not look idle

    def test_context_manager_opens_and_closes(self) -> None:
        with InMemTransport(frames=[(0x101, b"\x00")]) as t:
            assert t.recv() is not None
        # After exiting the context the transport is closed.
        with pytest.raises(RuntimeError):
            t.recv()


# --------------------------------------------------------------------------------------
# Hardware transports with a mocked python-can bus (no real hardware)
# --------------------------------------------------------------------------------------
@pytest.fixture
def fake_can(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Install a fake ``can`` module so socketcan/slcan ``open()`` succeeds offline.

    Mirrors the python-can surface the transports use: ``can.Bus(**kw)`` and
    ``can.Message(arbitration_id, data, is_extended_id)``. Created buses are recorded
    on ``module.buses`` so tests can inspect config / sent frames / inbox without
    touching the transport's private ``_bus``.
    """
    buses: list[_FakeBus] = []

    class _FakeMessage:
        def __init__(
            self, arbitration_id: int, data: bytes, is_extended_id: bool = False
        ) -> None:
            self.arbitration_id = arbitration_id
            self.data = bytes(data)
            self.is_extended_id = is_extended_id

    class _FakeBus:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.sent: list[_FakeMessage] = []
            self.inbox: list[_FakeMessage] = []
            self.shutdown_called = False
            buses.append(self)

        def send(self, msg: _FakeMessage) -> None:
            self.sent.append(msg)

        def recv(self, timeout: float | None = None) -> _FakeMessage | None:
            return self.inbox.pop(0) if self.inbox else None

        def shutdown(self) -> None:
            self.shutdown_called = True

    module = types.SimpleNamespace(Bus=_FakeBus, Message=_FakeMessage, buses=buses)
    monkeypatch.setitem(sys.modules, "can", module)
    return module


@pytest.mark.parametrize("name", ["socketcan", "slcan"])
class TestMockedCanBus:
    def test_open_creates_bus_with_config(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name, bitrate=250_000)
        t.open()
        bus = fake_can.buses[-1]
        assert bus.kwargs["interface"] == name
        assert bus.kwargs["bitrate"] == 250_000

    def test_send_validates_and_forwards(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name)
        t.open()
        t.send(0x101, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        bus = fake_can.buses[-1]
        assert len(bus.sent) == 1
        assert bus.sent[0].arbitration_id == 0x101
        # Non-8-byte frames are rejected at the boundary (codec strictness).
        with pytest.raises(ValueError):
            t.send(0x101, b"\x00")

    def test_recv_wraps_message_and_times_out(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name)
        t.open()
        fake_can.buses[-1].inbox.append(fake_can.Message(0x102, b"\xaa" * 8))
        frame = t.recv(timeout_s=0.1)
        assert isinstance(frame, CanFrame)
        assert frame.can_id == 0x102
        assert frame.data == b"\xaa" * 8
        assert frame.rx_monotonic_ns > 0
        assert t.recv() is None  # empty inbox behaves like a timeout

    def test_recv_drops_wrong_length_frame(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name)
        t.open()
        fake_can.buses[-1].inbox.append(fake_can.Message(0x102, b"\xaa" * 4))
        assert t.recv() is None  # malformed width -> dropped, not garbage-decoded

    def test_send_recv_before_open_raise(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name)
        with pytest.raises(RuntimeError):
            t.send(0x101, b"\x00" * 8)
        with pytest.raises(RuntimeError):
            t.recv()

    def test_close_shuts_down_and_is_idempotent(
        self, fake_can: types.SimpleNamespace, name: str
    ) -> None:
        t = make_transport(name)
        t.open()
        bus = fake_can.buses[-1]
        t.close()
        assert bus.shutdown_called
        t.close()  # second close must not raise


def test_hardware_transports_degrade_cleanly_without_python_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force ``import can`` to fail, simulating a host without python-can installed.
    # The failure mode prevented: a confusing crash at import time. Instead the
    # transport builds fine and raises a clear ImportError only when you open().
    monkeypatch.setitem(sys.modules, "can", None)
    for name in ("socketcan", "slcan"):
        t = make_transport(name)
        with pytest.raises(ImportError):
            t.open()


# --------------------------------------------------------------------------------------
# FileReplayTransport via the registry
# --------------------------------------------------------------------------------------
class TestFileReplayViaRegistry:
    def test_file_transport_replays_fixture(self) -> None:
        t = make_transport("file", path=FIXTURE)
        t.open()
        try:
            frame = t.recv()
            assert isinstance(frame, CanFrame)
            assert len(frame.data) == 8  # schema-v1 payload width
            assert frame.rx_monotonic_ns > 0
        finally:
            t.close()
