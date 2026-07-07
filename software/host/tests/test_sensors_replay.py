"""Tests for the ``replay`` SensorSource — deterministic playback of a recorded sequence.

Mirrors ``test_sensors.py`` (the sim-proprio suite) and the ``ReplayAdapter`` tests: the
same reusable conformance harness (``assert_sensor_source_conforms``), plus the guards that
make replay trustworthy — determinism across runs, INDEPENDENT-copy isolation, read/stream
agreement, clean close/exhaustion, an empty recording, and rejection of time-sync-poisoning
recordings (non-positive / backwards / NaN ``timestamp_ns``).

Headless, zero hardware, stdlib + frozen ``PVTSample`` only.
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample
from sensors import (
    SENSOR_SOURCE_CONTRACT_VERSION,
    ReplaySource,
    SensorKind,
    SensorSource,
    list_sensor_sources,
    make_sensor_source,
)

# Reuse the modality-independent conformance harness from the sim-proprio suite instead of
# re-implementing it — one source of truth for "what a SensorSource must do".
from tests.test_sensors import assert_sensor_source_conforms


def _recording(n: int = 5, *, start_ns: int = 1_000, step_ns: int = 5_000_000) -> list[PVTSample]:
    """A clean recording: positive, strictly increasing host timestamps (never zero)."""
    return [
        PVTSample(
            timestamp_ns=start_ns + i * step_ns,
            episode_id="replay_demo",
            chain_index=0,
            joint_angle=float(i),
            joint_velocity=0.1 * i,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Conformance (through the shared harness) — needs >=1 sample to conform.
# ---------------------------------------------------------------------------


def test_replay_conforms() -> None:
    assert_sensor_source_conforms(
        lambda: ReplaySource(_recording(8)),
        expected_kind=SensorKind.PROPRIO,
        sample_type=PVTSample,
    )


def test_registry_built_replay_conforms() -> None:
    """A replay source obtained via the registry conforms identically (no special-casing).

    ``make_sensor_source`` forwards kwargs, so we hand it a recording just like any caller.
    """
    assert_sensor_source_conforms(
        lambda: make_sensor_source("replay", samples=_recording(6)),
        expected_kind=SensorKind.PROPRIO,
        sample_type=PVTSample,
    )


# ---------------------------------------------------------------------------
# Determinism + independent-copy isolation — the trust guarantees.
# ---------------------------------------------------------------------------


def test_replay_is_deterministic_across_runs() -> None:
    """Two runs over the SAME recording emit structurally identical sequences."""
    rec = _recording(10)
    # Bind the concrete ``ReplaySource`` (not the widened ``__enter__`` return) so the
    # narrowed ``stream() -> Iterator[PVTSample]`` type is visible for ``.to_json()`` below.
    a = ReplaySource(rec)
    with a:
        first = list(a.stream())
    b = ReplaySource(rec)
    with b:
        second = list(b.stream())
    assert first == second
    # And the JSON serialization is byte-identical (true byte-equality, not just ==).
    assert [s.to_json() for s in first] == [s.to_json() for s in second]


def test_replay_reproduces_input_exactly() -> None:
    """Replay is faithful: emitted samples equal the recording it was handed."""
    rec = _recording(4)
    with ReplaySource(rec) as src:
        out = list(src.stream())
    assert out == rec


def test_reopen_replays_identical_sequence() -> None:
    """Re-opening rewinds the cursor => the exact same sequence replays again."""
    src = ReplaySource(_recording(5))
    with src:
        first = list(src.stream())
    with src:
        second = list(src.stream())
    assert first == second


def test_read_returns_independent_copy() -> None:
    """Mutating a returned sample must NOT corrupt the recording — a re-read is unaffected.

    This is the aliasing guard: read() deep-copies, so downstream mutation cannot leak back
    into the stored recording (which would break determinism / poison later consumers).
    """
    rec = _recording(3)
    src = ReplaySource(rec)
    src.open()
    got = src.read()
    assert got is not None
    original_angle = got.joint_angle
    got.joint_angle = 999.0  # scribble on the returned copy
    got.task_label = "mutated"
    # Re-open and re-read the same index: unchanged by the mutation above.
    src.open()
    again = src.read()
    assert again is not None
    assert again.joint_angle == original_angle
    assert again.task_label is None


def test_caller_mutating_input_after_construction_does_not_leak() -> None:
    """The constructor snapshots its input, so later caller mutation cannot corrupt replay."""
    rec = _recording(3)
    src = ReplaySource(rec)
    rec[0].joint_angle = -123.0  # mutate the ORIGINAL list after construction
    with src:
        out = list(src.stream())
    assert out[0].joint_angle == 0.0  # snapshot preserved the original value


# ---------------------------------------------------------------------------
# read/stream agreement + clean close/exhaustion.
# ---------------------------------------------------------------------------


def test_read_and_stream_agree() -> None:
    """stream() is exactly read-until-None; the two paths yield the same samples."""
    rec = _recording(7)
    with ReplaySource(rec) as a:
        read_out = []
        while (s := a.read()) is not None:
            read_out.append(s)
    with ReplaySource(rec) as b:
        stream_out = list(b.stream())
    assert read_out == stream_out


def test_stream_exhausts_and_read_returns_none_after() -> None:
    rec = _recording(2)
    with ReplaySource(rec) as src:
        assert len(list(src.stream())) == 2
        assert src.read() is None  # exhausted — no wraparound


def test_stream_ends_cleanly_when_closed_mid_iteration() -> None:
    """Closing mid-stream ends the generator (StopIteration), not a RuntimeError."""
    src = ReplaySource(_recording(100))
    src.open()
    gen = src.stream()
    assert next(gen) is not None
    src.close()
    with pytest.raises(StopIteration):
        next(gen)


def test_stream_stops_cleanly_on_with_block_exit() -> None:
    src = ReplaySource(_recording(100))
    with src:
        gen = src.stream()
        assert next(gen) is not None
    with pytest.raises(StopIteration):
        next(gen)


def test_read_after_close_raises() -> None:
    """After close(), read() fires the fail-loud lifecycle guard again."""
    src = ReplaySource(_recording(3))
    src.open()
    src.close()
    with pytest.raises(RuntimeError, match="before open"):
        src.read()


# ---------------------------------------------------------------------------
# Empty recording — legal, exhausts immediately.
# ---------------------------------------------------------------------------


def test_empty_recording_exhausts_immediately() -> None:
    src = ReplaySource([])  # empty is allowed
    assert len(src) == 0
    with src:
        assert src.read() is None
        assert list(src.stream()) == []


def test_default_construction_is_empty() -> None:
    """No-arg construction (as the conformance fixture uses) yields an empty source."""
    src = ReplaySource()
    with src:
        assert list(src.stream()) == []


# ---------------------------------------------------------------------------
# Fail-loud recording validation — reject time-sync-poisoning recordings.
# ---------------------------------------------------------------------------


def test_non_positive_timestamp_rejected() -> None:
    rec = [PVTSample(timestamp_ns=0, episode_id="e", chain_index=0, joint_angle=1.0)]
    with pytest.raises(ValueError, match="positive host timestamps"):
        ReplaySource(rec)


def test_negative_timestamp_rejected() -> None:
    rec = [PVTSample(timestamp_ns=-5, episode_id="e", chain_index=0, joint_angle=1.0)]
    with pytest.raises(ValueError, match="positive host timestamps"):
        ReplaySource(rec)


def test_backwards_timestamp_rejected() -> None:
    rec = [
        PVTSample(timestamp_ns=2_000, episode_id="e", chain_index=0, joint_angle=0.0),
        PVTSample(timestamp_ns=1_000, episode_id="e", chain_index=0, joint_angle=1.0),
    ]
    with pytest.raises(ValueError, match="non-decreasing"):
        ReplaySource(rec)


def test_equal_timestamps_allowed() -> None:
    """Non-decreasing means EQUAL stamps are fine (e.g. multiple sensors on one tick)."""
    rec = [
        PVTSample(timestamp_ns=1_000, episode_id="e", chain_index=0, joint_angle=0.0),
        PVTSample(timestamp_ns=1_000, episode_id="e", chain_index=1, joint_angle=1.0),
    ]
    with ReplaySource(rec) as src:
        assert len(list(src.stream())) == 2


def test_nan_timestamp_rejected() -> None:
    """NaN compares False against everything, so it must be caught by the explicit finite check."""
    rec = [
        PVTSample(
            timestamp_ns=math.nan,  # type: ignore[arg-type]
            episode_id="e",
            chain_index=0,
            joint_angle=1.0,
        )
    ]
    with pytest.raises(ValueError, match="finite host timestamps"):
        ReplaySource(rec)


# ---------------------------------------------------------------------------
# Metadata / kind invariant / contract version.
# ---------------------------------------------------------------------------


def test_metadata_reports_schema_kind_and_no_rate() -> None:
    meta = ReplaySource(_recording(1), device_id="pod_07").metadata()
    assert meta.kind is SensorKind.PROPRIO
    assert meta.name == "replay"
    assert meta.device_id == "pod_07"
    assert meta.sample_schema_version == PVT_SCHEMA_VERSION
    assert meta.nominal_rate_hz is None  # event/recording-driven
    assert meta.contract_version == SENSOR_SOURCE_CONTRACT_VERSION
    # SensorMetadata is frozen (cheap, inspectable, immutable).
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.kind = SensorKind.VISUAL  # type: ignore[misc]


def test_kind_invariant() -> None:
    """Class-level kind equals metadata().kind — readable without opening."""
    src = ReplaySource(_recording(1))
    assert ReplaySource.kind is SensorKind.PROPRIO
    assert src.kind is src.metadata().kind


def test_read_before_open_raises() -> None:
    src = ReplaySource(_recording(1))
    with pytest.raises(RuntimeError, match="before open"):
        src.read()


def test_stream_before_open_raises() -> None:
    src = ReplaySource(_recording(1))
    with pytest.raises(RuntimeError, match="before open"):
        list(src.stream())


# ---------------------------------------------------------------------------
# Registry wiring — the second built-in is discoverable and conformant.
# ---------------------------------------------------------------------------


def test_list_sensor_sources_includes_replay_and_is_sorted() -> None:
    names = list_sensor_sources()
    assert "replay" in names
    assert "sim-proprio" in names
    assert names == sorted(names)


def test_at_least_two_builtin_sources_registered() -> None:
    """P-A exit criterion: the SensorSource extension point has >=2 built-in plugins."""
    assert {"replay", "sim-proprio"} <= set(list_sensor_sources())


def test_make_sensor_source_returns_replay() -> None:
    src = make_sensor_source("replay", samples=_recording(3))
    assert isinstance(src, SensorSource)
    assert isinstance(src, ReplaySource)
    assert src.kind is SensorKind.PROPRIO
