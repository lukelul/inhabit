"""CAN transport layer — bidirectional send/recv over swappable backends.

Select a backend by name with :func:`make_transport` (see :mod:`transport.registry`)
instead of importing concrete classes; that keeps core code from branching on type.

Implementations:
  * :class:`SocketCanTransport` — real hardware via python-can (Linux socketcan).
  * :class:`SlcanTransport` — USB-CAN dongles via SLCAN/serial (any OS).
  * :class:`FileReplayTransport` — replay ``.canlog`` files with no hardware.
  * :class:`InMemTransport` — zero-dependency in-memory loopback queue (tests/sim).
  * :class:`FileRecorder` — record live frames to a ``.canlog`` file.
"""
from __future__ import annotations

from .file import FileRecorder, FileReplayTransport
from .inmem import InMemTransport
from .interface import CanTransport
from .registry import list_transports, make_transport
from .slcan import SlcanTransport
from .socketcan import SocketCanTransport

__all__ = [
    "CanTransport",
    "FileRecorder",
    "FileReplayTransport",
    "InMemTransport",
    "SlcanTransport",
    "SocketCanTransport",
    "list_transports",
    "make_transport",
]
