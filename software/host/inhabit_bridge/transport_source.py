"""Adapt a :class:`~transport.interface.CanTransport` into a :class:`CanSource`.

host/transport (PR #6) provides a *bidirectional* CAN layer (``recv``/``send``):

  * :class:`~transport.file.FileReplayTransport` -- replay a ``.canlog`` recording
    with zero hardware.
  * :class:`~transport.socketcan.SocketCanTransport` -- real Linux socketcan.

The bridge consumes the read-only iterator :class:`~inhabit_bridge.sources.CanSource`.
This thin adapter lets a transport be used wherever the bridge expects a source --
so host/transport is a first-class CAN input to the bridge -- WITHOUT duplicating
replay logic or re-implementing decoding (decoding stays in the frozen codec,
downstream in ``conversion``). It simply drains ``recv()`` and re-yields the
:class:`CanFrame` objects the transport already produces.

Time-sync contract is preserved end-to-end: the transport stamps each frame with
``rx_monotonic_ns`` from a single monotonic clock at RX time, and this adapter
passes those frames through untouched.
"""
from __future__ import annotations

from collections.abc import Iterator

from inhabit_bridge.sources import CanFrame, CanSource
from transport.interface import CanTransport


class TransportSource(CanSource):
    """Expose any :class:`CanTransport` as a read-only :class:`CanSource`.

    Parameters
    ----------
    transport:
        An (unopened) :class:`CanTransport`. ``open``/``close`` are delegated so
        the bridge's existing source lifecycle (open -> frames -> close) drives
        the transport unchanged.
    recv_timeout_s:
        Per-``recv`` timeout passed to the transport.
    stop_on_none:
        If ``True`` (default for finite sources like file replay), a ``None`` from
        ``recv`` -- i.e. the transport is exhausted -- ends iteration. If ``False``
        (live buses), ``None`` is a timeout and iteration continues, matching the
        never-ending behaviour of :class:`~inhabit_bridge.sources.SocketCanSource`.
    """

    def __init__(
        self,
        transport: CanTransport,
        recv_timeout_s: float = 1.0,
        stop_on_none: bool = True,
    ) -> None:
        self._transport = transport
        self._recv_timeout_s = recv_timeout_s
        self._stop_on_none = stop_on_none

    def open(self) -> None:
        self._transport.open()

    def frames(self) -> Iterator[CanFrame]:
        while True:
            frame = self._transport.recv(timeout_s=self._recv_timeout_s)
            if frame is None:
                if self._stop_on_none:
                    return
                continue
            yield frame

    def close(self) -> None:
        self._transport.close()
