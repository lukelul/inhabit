"""SLCAN (serial-line CAN) transport — USB-CAN dongles on any OS via python-can.

Works with cheap USB-CAN adapters (FTDI, CH341, CANable, etc.) that speak the
SLCAN/LAWICEL protocol over a virtual serial port. No ``slcand`` / Linux
socketcan setup required — plug the dongle in, point at the serial port, go.

python-can is imported lazily so headless replay never needs it installed.
"""
from __future__ import annotations

import time

from inhabit_bridge.sources import CanFrame

from .interface import CanTransport


class SlcanTransport(CanTransport):
    """Bidirectional CAN over a serial SLCAN adapter (any OS).

    Parameters
    ----------
    port:
        Serial port path (e.g. ``/dev/ttyACM0``, ``/dev/ttyUSB0``, ``COM3``).
    bitrate:
        CAN bus bitrate in bits/s (default 500 kbit/s).
    """

    def __init__(self, port: str = "/dev/ttyACM0", bitrate: int = 500_000) -> None:
        self._port = port
        self._bitrate = bitrate
        self._bus: object | None = None

    def open(self) -> None:
        import can  # noqa: PLC0415

        self._bus = can.Bus(
            interface="slcan", channel=self._port, bitrate=self._bitrate
        )

    def close(self) -> None:
        if self._bus is not None:
            self._bus.shutdown()  # type: ignore[attr-defined]
            self._bus = None

    def send(self, can_id: int, data: bytes) -> None:
        if self._bus is None:
            raise RuntimeError("SlcanTransport.send() called before open()")
        if len(data) != 8:
            raise ValueError("CAN frame must be 8 bytes")
        import can  # noqa: PLC0415

        msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=False)
        self._bus.send(msg)  # type: ignore[attr-defined]

    def recv(self, timeout_s: float = 1.0) -> CanFrame | None:
        if self._bus is None:
            raise RuntimeError("SlcanTransport.recv() called before open()")
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
