"""CanTransport — bidirectional CAN interface (send + recv).

Unlike :class:`~inhabit_bridge.sources.CanSource` (read-only iterator), a
transport supports both directions, making it suitable for future command paths
while still serving as a frame source for the bridge.

Every received frame carries ``rx_monotonic_ns`` from a SINGLE MONOTONIC clock
(``time.monotonic_ns``), consistent with the time-sync contract in sources.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from inhabit_bridge.sources import CanFrame


class CanTransport(ABC):
    """Bidirectional CAN transport — one interface, swappable backends."""

    @abstractmethod
    def open(self) -> None:
        """Acquire the underlying transport."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying transport."""

    @abstractmethod
    def send(self, can_id: int, data: bytes) -> None:
        """Transmit a CAN frame."""

    @abstractmethod
    def recv(self, timeout_s: float = 1.0) -> CanFrame | None:
        """Receive one CAN frame, or ``None`` on timeout."""

    def __enter__(self) -> CanTransport:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
