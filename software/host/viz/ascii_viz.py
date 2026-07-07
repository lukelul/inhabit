"""ASCII bar visualizer for JointPodState telemetry.

Renders a compact terminal display of joint angles for an N-pod chain.
No ROS dependency — consumes :class:`~inhabit_bridge.conversion.PodFields`
so it can be tested and used standalone.

Ponytail: simplest that works. One function, no deps beyond stdlib.
"""
from __future__ import annotations

import math
import sys
from typing import TextIO

from inhabit_bridge.conversion import PodFields

# Full-scale range for the bar: +/- 180 deg (millideg int16 caps at ~32.767 deg,
# but we use the radian field which is derived and could be wider in future schema).
_BAR_WIDTH = 40
_RANGE_RAD = math.pi  # half-range: bar spans [-pi, +pi]


def _bar(angle_rad: float, width: int = _BAR_WIDTH) -> str:
    """Return an ASCII bar string showing angle position within [-pi, +pi]."""
    clamped = max(-_RANGE_RAD, min(_RANGE_RAD, angle_rad))
    # Map [-pi, +pi] -> [0, width-1]. Use round() (not int/floor) so 0 rad lands
    # exactly on the center column instead of one column left for even widths.
    pos = round((clamped + _RANGE_RAD) / (2 * _RANGE_RAD) * (width - 1))
    center = round((width - 1) / 2)
    bar = ["-"] * width
    bar[center] = "|"  # center mark (0 rad)
    bar[pos] = "#"
    return "".join(bar)


def format_pod(fields: PodFields) -> str:
    """One-line summary: node/chain, angle, status, ASCII bar."""
    deg = fields.angle_millideg / 1000.0
    flags = f"0x{fields.status_flags:02X}" if fields.status_flags else "ok"
    ck = "" if fields.checksum_valid else " CK!"
    return (
        f"pod {fields.node_id:>2}:{fields.chain_index:<2} "
        f"{deg:+8.2f} deg  [{_bar(fields.angle_rad)}] {flags}{ck}"
    )


def render_frame(pods: list[PodFields], out: TextIO | None = None) -> str:
    """Render all pods as a multi-line ASCII frame. Returns the rendered string.

    ``out`` defaults to the *current* ``sys.stdout`` resolved at call time, so
    capture helpers like :func:`contextlib.redirect_stdout` work as expected.
    """
    lines = [
        format_pod(p)
        for p in sorted(pods, key=lambda p: (p.chain_index, p.node_id))
    ]
    text = "\n".join(lines)
    if out is None:
        out = sys.stdout
    out.write(text + "\n")
    return text
