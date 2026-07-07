"""In-memory CAN transport — a zero-dependency loopback queue.

No bus, no files, no OS deps: :meth:`InMemTransport.send` enqueues a frame and
:meth:`InMemTransport.recv` dequeues it FIFO, re-stamped with the host monotonic
clock at RX time (the same time-sync contract as
:mod:`inhabit_bridge.sources` / :class:`FileReplayTransport`).

Why it exists — the failure it prevents: every other transport needs hardware
(socketcan/slcan) or a file on disk (replay), so a test or sim that just wants to
push a few frames through a ``CanTransport`` has nowhere to send them. A flaky bus
or a missing fixture then masquerades as a logic bug. ``InMemTransport`` is the
deterministic, dependency-free stand-in: seed it (or ``send`` into it) and ``recv``
gives the frames straight back. It is also the second registered ``CanTransport``
plugin, so the conformance suite always has ≥2 implementations to exercise.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable

from inhabit_bridge.sources import CanFrame

from .interface import CanTransport

# Injectable monotonic clock (nanoseconds). Defaults to ``time.monotonic_ns``; tests
# pass a deterministic counter so RX stamps are reproducible.
ClockNs = Callable[[], int]


class InMemTransport(CanTransport):
    """A FIFO loopback :class:`CanTransport` backed by an in-memory queue.

    Parameters
    ----------
    frames:
        Optional initial ``(can_id, data)`` pairs to pre-seed the queue before
        :meth:`open`. Bytes are copied defensively so a caller mutating its buffer
        cannot corrupt a queued frame.
    clock_ns:
        Injectable monotonic clock (defaults to :func:`time.monotonic_ns`).
    """

    def __init__(
        self,
        frames: Iterable[tuple[int, bytes]] | None = None,
        clock_ns: ClockNs | None = None,
    ) -> None:
        self._queue: deque[tuple[int, bytes]] = deque()
        if frames is not None:
            self._queue.extend((can_id, bytes(data)) for can_id, data in frames)
        self._clock_ns: ClockNs = clock_ns if clock_ns is not None else time.monotonic_ns
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        # Fail loud on use-after-close: a drained queue must not silently look "idle".
        self._open = False
        self._queue.clear()

    def send(self, can_id: int, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("InMemTransport.send() called before open()")
        self._queue.append((can_id, bytes(data)))

    def recv(self, timeout_s: float = 1.0) -> CanFrame | None:
        if not self._open:
            raise RuntimeError("InMemTransport.recv() called before open()")
        if not self._queue:
            return None  # empty queue == timeout; mirrors the other transports.
        can_id, data = self._queue.popleft()
        return CanFrame(can_id=can_id, data=data, rx_monotonic_ns=int(self._clock_ns()))
