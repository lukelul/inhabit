"""``python -m viz`` — live ASCII joint-angle display.

Closes BENCHMARKS item 8 (no orphaned modules): the ASCII visualizer now has a
runner, so an operator can actually watch joint angles.

Usage
-----
Replay a recorded ``.canlog`` file::

    python -m viz path/to/episode.canlog

Pipe decoded canlog frames in on stdin (JSONL, one record per line)::

    cat episode.canlog | python -m viz -

Add ``--clear`` for an animated full-screen terminal view (ANSI clear between
snapshots); omit it for plain, captureable output.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .runner import frames_from_replay, frames_from_stdin, render_stream_stats


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m viz",
        description="Live ASCII joint-angle visualizer for Inhabit pod telemetry.",
    )
    parser.add_argument(
        "source",
        help="path to a .canlog file to replay, or '-' to read canlog JSONL from stdin",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="ANSI clear-screen before each snapshot (animated terminal view)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print a summary line (frames, Hz, errors) to stderr after rendering",
    )
    args = parser.parse_args(argv)

    if args.source == "-":
        frames = frames_from_stdin()
    else:
        frames = frames_from_replay(args.source)

    try:
        stats = render_stream_stats(frames, clear=args.clear)
    except (ValueError, FileNotFoundError) as exc:
        print(f"viz: {exc}", file=sys.stderr)
        return 1

    if args.stats or stats.frames_error:
        print(f"viz: {stats.summary()}", file=sys.stderr)

    if stats.frames_ok == 0:
        print("viz: no frames to display", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
