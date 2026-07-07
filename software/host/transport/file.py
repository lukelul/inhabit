"""File-based CAN transport — record live frames and replay them with no hardware.

File format (``.canlog``): JSONL — one JSON object per line::

    {"v": 1, "t_ns": 123456789, "id": 256, "data": "d204c85800000058"}

* ``v``    — canlog schema version (see :data:`CANLOG_VERSION`).
* ``t_ns`` — monotonic nanosecond timestamp captured at RX time.
* ``id``   — CAN arbitration ID.
* ``data`` — hex-encoded 8-byte payload.

Human-readable, ``grep``-able, trivially parseable — no extra dependencies.

The explicit ``v`` discriminator is written from day one so future field changes
can be migrated cleanly instead of guessed. Records missing ``v`` are treated as
v1 (the pre-versioned layout was structurally identical apart from the field).
"""
from __future__ import annotations

import io
import json
import time
from collections.abc import Callable
from pathlib import Path

from inhabit_bridge.sources import CanFrame

from .interface import CanTransport

ClockNs = Callable[[], int]

#: Current ``.canlog`` schema version. Bump on any record-shape change and add a
#: migration branch in :func:`_load_canlog` rather than breaking old logs.
CANLOG_VERSION = 1

#: CAN schema v1 payload width (bytes) — see ``inhabit_can.codec``.
_FRAME_LEN = 8


class FileRecorder:
    """Append received :class:`CanFrame` objects to a ``.canlog`` file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._fh: io.TextIOWrapper | None = None
        self.frames_written: int = 0
        self.frames_rejected: int = 0

    def open(self) -> None:
        self._fh = open(self._path, "a", encoding="utf-8")
        self.frames_written = 0
        self.frames_rejected = 0

    def write(self, frame: CanFrame) -> None:
        if self._fh is None:
            raise RuntimeError("FileRecorder.write() called before open()")
        # Failure mode prevented: persisting a malformed (non-8-byte) frame would
        # produce a log that only blows up later at replay time in decode_state().
        # Reject at write time so bad data never reaches disk.
        if len(frame.data) != _FRAME_LEN:
            self.frames_rejected += 1
            raise ValueError("CAN frame must be 8 bytes")
        line = json.dumps(
            {
                "v": CANLOG_VERSION,
                "t_ns": frame.rx_monotonic_ns,
                "id": frame.can_id,
                "data": frame.data.hex(),
            },
            separators=(",", ":"),
        )
        self._fh.write(line + "\n")
        self._fh.flush()
        self.frames_written += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> FileRecorder:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _load_canlog(path: Path) -> list[tuple[int, int, bytes]]:
    """Parse a ``.canlog`` file into ``(t_ns, can_id, data)`` tuples."""
    entries: list[tuple[int, int, bytes]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                # Failure mode prevented: valid-but-non-object JSON (e.g. `[]` or
                # `"x"`) would hit `.get()` and escape as an uncaught AttributeError
                # instead of the intended ValueError with path:lineno context.
                if not isinstance(obj, dict):
                    raise ValueError("expected JSON object")
                # Missing "v" => pre-versioned record, treated as v1.
                version = int(obj.get("v", 1))
                if version != CANLOG_VERSION:
                    raise ValueError(
                        f"unsupported canlog version {version} (expected {CANLOG_VERSION})"
                    )
                data = bytes.fromhex(obj["data"])
                # Failure mode prevented: a truncated/over-long payload would slip
                # through here and only fail downstream at decode_state(); reject now.
                if len(data) != _FRAME_LEN:
                    raise ValueError("CAN frame must be 8 bytes")
                entries.append((int(obj["t_ns"]), int(obj["id"]), data))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ValueError(f"{path}:{lineno}: malformed canlog line: {exc}") from exc
    return entries


class FileReplayTransport(CanTransport):
    """Replay a ``.canlog`` file as a :class:`CanTransport` — zero hardware needed.

    Frames are re-stamped with a fresh monotonic clock at ``recv()`` time so
    downstream consumers see realistic, increasing timestamps (matching the
    time-sync contract: stamps come from the host monotonic clock at RX time).

    ``send()`` is a no-op (replay is read-only).

    Parameters
    ----------
    path:
        Path to a ``.canlog`` file.
    clock_ns:
        Injectable monotonic clock (defaults to ``time.monotonic_ns``).
    """

    def __init__(self, path: str | Path, clock_ns: ClockNs | None = None) -> None:
        self._path = Path(path)
        self._entries: list[tuple[int, int, bytes]] = []
        self._index = 0
        self._clock_ns: ClockNs = clock_ns if clock_ns is not None else time.monotonic_ns
        self._open = False

    def open(self) -> None:
        self._entries = _load_canlog(self._path)
        self._index = 0
        self._open = True

    def close(self) -> None:
        self._open = False
        self._entries = []
        self._index = 0

    def send(self, can_id: int, data: bytes) -> None:
        pass  # replay is read-only

    def recv(self, timeout_s: float = 1.0) -> CanFrame | None:
        if not self._open:
            raise RuntimeError("FileReplayTransport.recv() called before open()")
        if self._index >= len(self._entries):
            return None
        _t_ns, can_id, data = self._entries[self._index]
        self._index += 1
        return CanFrame(can_id=can_id, data=data, rx_monotonic_ns=int(self._clock_ns()))
