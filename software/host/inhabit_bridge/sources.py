"""CAN source abstraction (ROS-independent).

One interface, swappable implementations -- never branch on robot type in core
code (host/CLAUDE.md). The bridge node consumes whatever :class:`CanSource` it
is handed.

Time-sync contract
------------------
Each yielded frame carries ``rx_monotonic_ns``: the host receive time read from
a SINGLE MONOTONIC clock (``time.monotonic_ns``) at the moment the frame is
pulled off the bus. This is NEVER wall-clock time. It is the anchor that
``bridge_node`` writes into ``header.stamp`` and that downstream PVT logging
uses to align CAN, video, and tactile streams.

Sources:
  * :class:`ReplaySource` -- headless, zero hardware. Replays a list of raw
    8-byte frames. This is the path that must work without any robot or ROS.
  * :class:`SimSource`    -- synthesizes valid frames (sweeping angle) for a
    set of pods; useful for live demos with no recording.
  * :class:`SocketCanSource` -- thin real-hardware variant (Linux socketcan via
    python-can) behind the same interface. Import is lazy so the module loads
    without python-can installed.
"""
from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from inhabit_can.codec import State, encode_state

# A clock returning monotonic nanoseconds. Injectable so tests can assert exact
# stamps; defaults to time.monotonic_ns in real sources. NEVER wall clock.
ClockNs = Callable[[], int]


@dataclass(frozen=True)
class CanFrame:
    """A received CAN frame plus its monotonic host RX timestamp.

    ``can_id`` is informational; decoding uses ``data`` only (the codec embeds
    node_id in the payload). ``rx_monotonic_ns`` comes from ``time.monotonic_ns``.
    """

    can_id: int
    data: bytes
    rx_monotonic_ns: int


class CanSource(ABC):
    """Yield received CAN frames, each stamped at RX with a monotonic clock."""

    @abstractmethod
    def open(self) -> None:
        """Acquire the underlying transport (no-op for replay)."""

    @abstractmethod
    def frames(self) -> Iterator[CanFrame]:
        """Yield :class:`CanFrame` objects until the source is exhausted/closed."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying transport (no-op for replay)."""

    def __enter__(self) -> CanSource:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ReplaySource(CanSource):
    """Replay pre-captured raw 8-byte CAN payloads. Headless, zero hardware.

    Parameters
    ----------
    frames_data:
        Iterable of ``(can_id, data)`` tuples. ``data`` is the raw 8-byte
        payload that will be decoded by the frozen codec downstream.
    clock_ns:
        Monotonic clock returning nanoseconds; defaults to ``time.monotonic_ns``.
        Injectable so tests can assert exact stamps.
    """

    def __init__(
        self,
        frames_data: list[tuple[int, bytes]],
        clock_ns: ClockNs | None = None,
    ) -> None:
        self._frames_data = list(frames_data)
        self._clock_ns: ClockNs = clock_ns if clock_ns is not None else time.monotonic_ns
        self._open = False

    def open(self) -> None:
        self._open = True

    def frames(self) -> Iterator[CanFrame]:
        if not self._open:
            raise RuntimeError("ReplaySource.frames() called before open()")
        for can_id, data in self._frames_data:
            yield CanFrame(can_id=can_id, data=data, rx_monotonic_ns=int(self._clock_ns()))

    def close(self) -> None:
        self._open = False


class SimSource(CanSource):
    """Synthesize valid frames for ``num_pods`` pods, sweeping angle over time.

    Generates ``count`` frames per pod (interleaved by sample). Encoded with the
    frozen codec so checksums are valid. Useful for headless live demos.
    """

    def __init__(self, num_pods: int = 2, count: int = 10, clock_ns: ClockNs | None = None) -> None:
        self._num_pods = num_pods
        self._count = count
        self._clock_ns: ClockNs = clock_ns if clock_ns is not None else time.monotonic_ns
        self._open = False

    def open(self) -> None:
        self._open = True

    def frames(self) -> Iterator[CanFrame]:
        if not self._open:
            raise RuntimeError("SimSource.frames() called before open()")
        for i in range(self._count):
            for node_id in range(self._num_pods):
                # angle_millideg is int16 in the v1 schema (~+/-32.767 deg).
                deg = 30.0 * math.sin((i + node_id) * 0.2)
                millideg = int(deg * 1000.0)
                raw = int((deg + 180.0) / 360.0 * 4095.0) & 0xFFFF
                cid, data = encode_state(
                    State(
                        angle_raw_adc=raw,
                        angle_millideg=millideg,
                        node_id=node_id,
                        chain_index=node_id,
                        status_flags=0,
                    )
                )
                yield CanFrame(can_id=cid, data=data, rx_monotonic_ns=int(self._clock_ns()))

    def close(self) -> None:
        self._open = False


class SocketCanSource(CanSource):
    """Real-hardware variant (Linux socketcan via python-can), same interface.

    python-can is imported lazily inside :meth:`open` so this module (and the
    headless replay path) load without python-can installed. Requires a Jazzy /
    Linux environment with a configured ``can`` interface to actually run.
    """

    def __init__(self, channel: str = "can0", bitrate: int = 500_000) -> None:
        self._channel = channel
        self._bitrate = bitrate
        self._bus: object | None = None

    def open(self) -> None:
        import can  # noqa: PLC0415  (lazy: keep optional dep off the headless path)

        self._bus = can.Bus(interface="socketcan", channel=self._channel, bitrate=self._bitrate)

    def frames(self) -> Iterator[CanFrame]:
        if self._bus is None:
            raise RuntimeError("SocketCanSource.frames() called before open()")
        bus = self._bus
        while True:
            msg = bus.recv(timeout=1.0)  # type: ignore[attr-defined]
            if msg is None:
                continue
            data = bytes(msg.data)
            if len(data) != 8:
                continue  # not a v1 pod frame; skip
            yield CanFrame(
                can_id=int(msg.arbitration_id),
                data=data,
                rx_monotonic_ns=time.monotonic_ns(),
            )

    def close(self) -> None:
        if self._bus is not None:
            self._bus.shutdown()  # type: ignore[attr-defined]
            self._bus = None
