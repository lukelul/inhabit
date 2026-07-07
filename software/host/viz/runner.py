"""Wiring for the ASCII joint-angle visualizer (``python -m host.viz``).

The visualizer (:mod:`viz.ascii_viz`) was orphaned: it could render
:class:`~inhabit_bridge.conversion.PodFields`, but nothing fed it real frames,
so an operator could not actually watch live joint angles. This module is the
thin glue that closes that gap — *wiring only, no new rendering logic*.

Data path (all existing, frozen-contract modules reused):

    .canlog file / stdin (JSONL)
        -> CanFrame (.data = raw 8-byte v1 payload)
            -> fields_from_frame()  [frozen codec -> PodFields]
                -> render_frame()   [viz.ascii_viz]

A "frame" shown to the operator is the latest known PodFields for every pod
seen so far, keyed by ``node_id``. Each incoming CAN frame updates one pod and
re-renders the whole chain — exactly how a live telemetry display behaves.

Frozen contracts (imported, never edited): the CAN codec, ``JointPodState.msg``,
``RobotAdapter``, and ``PVTSample``. The viz only CONSUMES.
"""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from inhabit_bridge.conversion import PodFields, fields_from_frame
from inhabit_bridge.sources import CanFrame
from transport.file import FileReplayTransport

from .ascii_viz import render_frame


@dataclass
class StreamStats:
    """Accumulated stats from a render_stream run."""

    frames_ok: int = 0
    frames_error: int = 0
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.frames_ok + self.frames_error

    @property
    def hz(self) -> float:
        # N frames span N-1 intervals; rate = intervals / elapsed.
        if self.elapsed_s > 0 and self.frames_ok > 1:
            return (self.frames_ok - 1) / self.elapsed_s
        return 0.0

    def summary(self) -> str:
        """One-line summary suitable for a status footer."""
        parts = [f"{self.frames_ok} frames", f"{self.hz:.1f} Hz"]
        if self.frames_error:
            parts.append(f"{self.frames_error} errors")
        return " | ".join(parts)


def frames_from_replay(path: str | Path) -> Iterator[CanFrame]:
    """Yield :class:`CanFrame` objects from a ``.canlog`` file via replay.

    Reuses :class:`~transport.file.FileReplayTransport` so the file format,
    versioning, and validation all live in one place (never re-implemented here).
    """
    transport = FileReplayTransport(path)
    transport.open()
    try:
        while True:
            frame = transport.recv()
            if frame is None:
                return
            yield frame
    finally:
        transport.close()


def frames_from_stdin(stream: TextIO | None = None) -> Iterator[CanFrame]:
    """Yield :class:`CanFrame` objects from canlog JSONL on a text stream.

    Each non-blank line is one ``.canlog`` record (see :mod:`transport.file`):
    ``{"id": <int>, "data": "<hex>", "t_ns": <int>}``. Only ``id`` and ``data``
    are required for rendering; ``t_ns`` is optional. Blank lines are skipped.
    """
    if stream is None:
        stream = sys.stdin
    for lineno, raw_line in enumerate(stream, 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("expected JSON object")
            data = bytes.fromhex(obj["data"])
            can_id = int(obj["id"])
            t_ns = int(obj.get("t_ns", 0))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ValueError(f"stdin:{lineno}: malformed canlog line: {exc}") from exc
        yield CanFrame(can_id=can_id, data=data, rx_monotonic_ns=t_ns)


def render_stream(
    frames: Iterable[CanFrame],
    out: TextIO | None = None,
    clear: bool = False,
) -> int:
    """Render CAN frames as live ASCII chain snapshots. Returns frame count.

    Backwards-compatible: still returns ``int`` (frames_ok count).
    Use :func:`render_stream_stats` for the full :class:`StreamStats`.
    """
    return render_stream_stats(frames, out=out, clear=clear).frames_ok


def render_stream_stats(
    frames: Iterable[CanFrame],
    out: TextIO | None = None,
    clear: bool = False,
) -> StreamStats:
    """Render CAN frames as live ASCII snapshots. Returns :class:`StreamStats`.

    Maintains the latest :class:`PodFields` per ``node_id`` and re-renders the
    whole chain on every successfully decoded frame.

    **Production hardening:** a corrupt or short frame logs to stderr and
    increments ``stats.frames_error`` instead of crashing the display. This is
    critical for long ML recording sessions on a noisy bus — the viz must
    survive bad frames, not die on the first one.

    ``clear`` emits an ANSI clear-screen before each snapshot (for an animated
    terminal view); off by default so captured / piped output stays plain.
    """
    if out is None:
        out = sys.stdout
    pods: dict[int, PodFields] = {}
    stats = StreamStats()
    _MAX_LOGGED_ERRORS = 10
    first_ns: int | None = None
    last_ns: int = 0
    t0 = time.monotonic()
    for frame in frames:
        # Track stream timeline from rx_monotonic_ns for accurate Hz.
        if first_ns is None:
            first_ns = frame.rx_monotonic_ns
        last_ns = frame.rx_monotonic_ns
        try:
            fields = fields_from_frame(frame.data)
        except Exception as exc:
            stats.frames_error += 1
            if len(stats.errors) < _MAX_LOGGED_ERRORS:
                stats.errors.append(f"frame {stats.total}: {exc}")
                print(f"viz: skipping corrupt frame: {exc}", file=sys.stderr)
            elif len(stats.errors) == _MAX_LOGGED_ERRORS:
                stats.errors.append("(further errors suppressed)")
                print("viz: further corrupt-frame errors suppressed", file=sys.stderr)
            continue
        pods[fields.node_id] = fields
        if clear:
            out.write("\x1b[2J\x1b[H")
        render_frame(list(pods.values()), out=out)
        stats.frames_ok += 1
    # Prefer stream-timeline elapsed (rx_monotonic_ns span); fall back to wall.
    if first_ns is not None and last_ns > first_ns:
        stats.elapsed_s = (last_ns - first_ns) / 1e9
    else:
        stats.elapsed_s = time.monotonic() - t0
    return stats
