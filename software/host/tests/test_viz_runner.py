"""Tests for the viz runner (``python -m viz``) frame-building / render path.

These exercise the WIRING only: existing frozen modules (codec, transport,
conversion, ascii_viz) do the real work. We assert that a sample input reaches
``render_frame`` and produces the expected ASCII bars on stdout.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from transport.file import CANLOG_VERSION
from viz import __main__ as viz_main
from viz.runner import (
    frames_from_replay,
    frames_from_stdin,
    render_stream,
    render_stream_stats,
)


def _canlog_line(state: State, t_ns: int = 0) -> str:
    """Encode a State via the frozen codec into one .canlog JSONL record."""
    can_id, data = encode_state(state)
    return json.dumps(
        {"v": CANLOG_VERSION, "t_ns": t_ns, "id": can_id, "data": data.hex()}
    )


def _write_canlog(path: Path, states: list[State]) -> Path:
    path.write_text(
        "\n".join(_canlog_line(s, t_ns=i) for i, s in enumerate(states)) + "\n",
        encoding="utf-8",
    )
    return path


def test_render_stream_emits_bars_for_angles() -> None:
    """A stream of frames renders one '#' bar marker per pod with its angle."""
    states = [
        State(angle_raw_adc=2048, angle_millideg=22500, node_id=0, chain_index=0),
        State(angle_raw_adc=2048, angle_millideg=-15000, node_id=1, chain_index=1),
    ]
    frames = list(frames_from_stdin(io.StringIO("\n".join(_canlog_line(s) for s in states))))
    buf = io.StringIO()
    count = render_stream(frames, out=buf)

    out = buf.getvalue()
    assert count == 2
    # Final snapshot holds both pods; angles appear and each renders a bar.
    final = out.strip().split("\n")[-2:]
    assert any("+22.50 deg" in line and "#" in line for line in final)
    assert any("-15.00 deg" in line and "#" in line for line in final)
    assert all("[" in line and "]" in line for line in final)


def test_replay_path_builds_frames_from_file(tmp_path: Path) -> None:
    """frames_from_replay reuses FileReplayTransport to read a .canlog file."""
    log = _write_canlog(
        tmp_path / "episode.canlog",
        [State(angle_raw_adc=2048, angle_millideg=10000, node_id=0, chain_index=0)],
    )
    frames = list(frames_from_replay(log))
    assert len(frames) == 1
    buf = io.StringIO()
    render_stream(frames, out=buf)
    assert "+10.00 deg" in buf.getvalue()
    assert "#" in buf.getvalue()


def test_clear_emits_ansi_sequence() -> None:
    """--clear prepends an ANSI clear-screen before each snapshot."""
    state = State(angle_raw_adc=2048, angle_millideg=0, node_id=0, chain_index=0)
    frames = list(frames_from_stdin(io.StringIO(_canlog_line(state))))
    buf = io.StringIO()
    render_stream(frames, out=buf, clear=True)
    assert "\x1b[2J" in buf.getvalue()


def test_stdin_rejects_malformed_line() -> None:
    """A malformed canlog line raises ValueError with stdin:lineno context."""
    bad = io.StringIO("not json\n")
    try:
        list(frames_from_stdin(bad))
    except ValueError as exc:
        assert "stdin:1" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError for malformed line")


def test_main_replay_displays_frame(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """End-to-end: `python -m viz <file>` renders bars to stdout, exit 0."""
    log = _write_canlog(
        tmp_path / "sample.canlog",
        [State(angle_raw_adc=2048, angle_millideg=22500, node_id=2, chain_index=0)],
    )
    rc = viz_main.main([str(log)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "+22.50 deg" in captured.out
    assert "#" in captured.out
    assert "pod  2:0" in captured.out


def test_main_empty_source_reports_no_frames(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty .canlog yields no frames and a non-zero exit with a message."""
    empty = tmp_path / "empty.canlog"
    empty.write_text("", encoding="utf-8")
    rc = viz_main.main([str(empty)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no frames" in captured.err


# --- Production hardening: corrupt-frame resilience ---


def test_render_stream_survives_corrupt_frame() -> None:
    """A short/corrupt frame is skipped, not fatal. The viz keeps rendering."""
    good_state = State(angle_raw_adc=2048, angle_millideg=5000, node_id=0, chain_index=0)
    good_id, good_data = encode_state(good_state)
    frames = [
        CanFrame(can_id=good_id, data=good_data, rx_monotonic_ns=0),
        CanFrame(can_id=0x101, data=b"\x00\x01\x02", rx_monotonic_ns=1),  # short — corrupt
        CanFrame(can_id=good_id, data=good_data, rx_monotonic_ns=2),
    ]
    buf = io.StringIO()
    stats = render_stream_stats(frames, out=buf)
    assert stats.frames_ok == 2
    assert stats.frames_error == 1
    assert "+5.00 deg" in buf.getvalue()


def test_render_stream_stats_returns_hz() -> None:
    """StreamStats computes Hz from rx_monotonic_ns span."""
    state = State(angle_raw_adc=2048, angle_millideg=0, node_id=0, chain_index=0)
    cid, data = encode_state(state)
    # Two frames 10ms apart → 100 Hz.
    frames = [
        CanFrame(can_id=cid, data=data, rx_monotonic_ns=0),
        CanFrame(can_id=cid, data=data, rx_monotonic_ns=10_000_000),
    ]
    buf = io.StringIO()
    stats = render_stream_stats(frames, out=buf)
    assert stats.frames_ok == 2
    assert stats.frames_error == 0
    assert stats.elapsed_s == pytest.approx(0.01, abs=1e-6)
    # 2 frames, 1 interval of 10ms → 100 Hz.
    assert stats.hz == pytest.approx(100.0, rel=0.01)
    assert "Hz" in stats.summary()


def test_render_stream_stats_summary_shows_errors() -> None:
    """Summary line includes error count when frames are corrupt."""
    frames = [
        CanFrame(can_id=0x100, data=b"\xff", rx_monotonic_ns=0),  # corrupt
    ]
    buf = io.StringIO()
    stats = render_stream_stats(frames, out=buf)
    assert stats.frames_ok == 0
    assert stats.frames_error == 1
    assert "1 errors" in stats.summary()


def test_render_stream_caps_stderr_logging(capsys: pytest.CaptureFixture[str]) -> None:
    """After 10 corrupt frames, stderr logging is suppressed."""
    corrupt = [CanFrame(can_id=0x100, data=b"\xff", rx_monotonic_ns=i) for i in range(15)]
    render_stream_stats(corrupt, out=io.StringIO())
    captured = capsys.readouterr()
    # First 10 get individual messages, then one suppression notice.
    assert captured.err.count("skipping corrupt frame") == 10
    assert "suppressed" in captured.err


def test_render_stream_backward_compat() -> None:
    """render_stream still returns int (frames_ok) for backward compatibility."""
    state = State(angle_raw_adc=2048, angle_millideg=0, node_id=0, chain_index=0)
    frames = list(frames_from_stdin(io.StringIO(_canlog_line(state))))
    count = render_stream(frames, out=io.StringIO())
    assert isinstance(count, int)
    assert count == 1


def test_main_stats_flag_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--stats prints a summary line to stderr."""
    log = _write_canlog(
        tmp_path / "stats.canlog",
        [State(angle_raw_adc=2048, angle_millideg=0, node_id=0, chain_index=0)],
    )
    rc = viz_main.main([str(log), "--stats"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "1 frames" in captured.err
    assert "Hz" in captured.err


def test_main_missing_file_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    """A missing file exits 1 with a clear message, not a stack trace."""
    rc = viz_main.main(["does_not_exist_12345.canlog"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "does_not_exist_12345.canlog" in captured.err
