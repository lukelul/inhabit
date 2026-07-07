"""SocketCAN transport — real hardware on Linux via python-can.

python-can is imported lazily inside :meth:`open` so the module loads without
the dependency installed (same pattern as ``sources.SocketCanSource``).
"""
from __future__ import annotations

import time

from inhabit_bridge.sources import CanFrame

from .interface import CanTransport


class SocketCanTransport(CanTransport):
    """Bidirectional CAN over Linux socketcan."""

    def __init__(self, channel: str = "can0", bitrate: int = 500_000) -> None:
        self._channel = channel
        self._bitrate = bitrate
        self._bus: object | None = None

    def open(self) -> None:
        import can  # noqa: PLC0415

        self._bus = can.Bus(
            interface="socketcan", channel=self._channel, bitrate=self._bitrate
        )

    def close(self) -> None:
        if self._bus is not None:
            self._bus.shutdown()  # type: ignore[attr-defined]
            self._bus = None

    def send(self, can_id: int, data: bytes) -> None:
        if self._bus is None:
            raise RuntimeError("SocketCanTransport.send() called before open()")
        # Failure mode prevented: a non-8-byte frame would silently pass the bus
        # but be dropped by recv() and rejected by decode_state() — unreplayable,
        # undecodable garbage. Reject at the boundary, matching codec strictness.
        if len(data) != 8:
            raise ValueError("CAN frame must be 8 bytes")
        import can  # noqa: PLC0415

        msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=False)
        self._bus.send(msg)  # type: ignore[attr-defined]

    def recv(self, timeout_s: float = 1.0) -> CanFrame | None:
        if self._bus is None:
            raise RuntimeError("SocketCanTransport.recv() called before open()")
        msg = self._bus.recv(timeout=timeout_s)  # type: ignore[attr-defined]
        if msg is None:
            return None
        data = bytes(msg.data)
        if len(data) != 8:
            return None
        return CanFrame(
            can_id=int(msg.arbitration_id),
            data=data,
            rx_monotonic_ns=time.monotonic_ns(),
        )
