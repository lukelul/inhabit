"""Tests for the ASCII joint-angle visualizer."""
from __future__ import annotations

import contextlib
import io
import math

from inhabit_bridge.conversion import PodFields
from inhabit_can.codec import PROTO_VERSION
from viz.ascii_viz import _bar, format_pod, render_frame


def _pod(
    node_id: int = 0,
    chain_index: int = 0,
    millideg: int = 0,
    status: int = 0,
    valid: bool = True,
) -> PodFields:
    """Build a minimal PodFields for testing."""
    return PodFields(
        node_id=node_id,
        chain_index=chain_index,
        angle_raw_adc=2048,
        angle_millideg=millideg,
        angle_rad=millideg * math.pi / 180_000,
        status_flags=status,
        checksum_valid=valid,
        schema_version=PROTO_VERSION,
    )


def test_bar_center_at_zero() -> None:
    """Zero angle lands on center for odd width."""
    b = _bar(0.0, width=21)
    assert b[10] == "#"  # center position


def test_bar_center_at_zero_with_default_width() -> None:
    """Zero angle lands on center for the default even width."""
    b = _bar(0.0)
    center = b.index("#")
    assert center == round((len(b) - 1) / 2)


def test_bar_extremes_clamp() -> None:
    """Angles beyond +/-pi clamp to the bar edges."""
    b_pos = _bar(math.pi * 2, width=40)  # beyond +pi
    assert b_pos[-1] == "#"
    b_neg = _bar(-math.pi * 2, width=40)
    assert b_neg[0] == "#"


def test_format_pod_shows_angle_and_flags() -> None:
    """format_pod includes degree value, address, and 'ok' status."""
    line = format_pod(_pod(node_id=3, chain_index=1, millideg=22500))
    assert "+22.50 deg" in line
    assert "pod  3:1" in line
    assert "ok" in line


def test_format_pod_shows_checksum_fail() -> None:
    """Checksum failure appends CK! marker."""
    line = format_pod(_pod(valid=False))
    assert "CK!" in line


def test_format_pod_shows_status_hex() -> None:
    """Non-zero status_flags render as hex."""
    line = format_pod(_pod(status=0x04))
    assert "0x04" in line


def test_render_frame_sorts_by_chain_index() -> None:
    """Pods render in chain_index order regardless of input order."""
    pods = [_pod(node_id=1, chain_index=2), _pod(node_id=0, chain_index=0)]
    buf = io.StringIO()
    text = render_frame(pods, out=buf)
    lines = text.strip().split("\n")
    assert "pod  0:0" in lines[0]
    assert "pod  1:2" in lines[1]
    assert buf.getvalue() == text + "\n"


def test_render_frame_stable_order_same_chain_index() -> None:
    """Pods with equal chain_index sort deterministically by node_id."""
    pods = [_pod(node_id=5, chain_index=0), _pod(node_id=2, chain_index=0)]
    text = render_frame(pods, out=io.StringIO())
    lines = text.strip().split("\n")
    assert "pod  2:0" in lines[0]
    assert "pod  5:0" in lines[1]


def test_render_frame_uses_current_stdout() -> None:
    """Default output resolves sys.stdout at call time for redirect_stdout."""
    pods = [_pod()]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        text = render_frame(pods)
    assert buf.getvalue() == text + "\n"
