"""Tests for ``sim-tactile`` / ``sim-frames`` — scenario-driven PVT sensor sources (B5).

Mirrors ``test_sensors.py`` / ``test_sensors_replay.py``: the shared modality-independent
conformance harness (``assert_sensor_source_conforms``), plus the guards that make the
scenario-driven pair trustworthy:

* a scripted-contact episode carries the expected FROZEN ``tactile_event`` tokens at the
  scripted timestamps (and ``None`` in the ``approach``/``settle`` gaps);
* ``camera_frame_id`` is monotonic, unique, and zero-padded;
* determinism (same construction => identical sequence; re-open replays identical data);
* streams are finite (they end exactly when the scenario timeline ends);
* ``PVT_SCHEMA_VERSION`` is untouched — these sources populate ALREADY-FROZEN fields.

Headless, zero hardware, stdlib + frozen ``PVTSample`` only. NO numpy (P-B invariant).
"""
from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample
from sensors import (
    SENSOR_SOURCE_CONTRACT_VERSION,
    SensorKind,
    SensorSource,
    SimFramesSource,
    SimTactileSource,
    list_sensor_sources,
    make_sensor_source,
)
from sim.scenario import CONTACT_KINDS, PICK_PLACE, SLIP_RECOVERY, ContactPhase, ContactScenario

# Reuse the modality-independent conformance harness from the sim-proprio suite instead of
# re-implementing it — one source of truth for "what a SensorSource must do".
from tests.test_sensors import assert_sensor_source_conforms

# ---------------------------------------------------------------------------
# Scripted fixture scenario: every FROZEN contact token, on a hand-checkable grid.
# Phases tile [0, 0.6) in 0.1 s windows; sampled at 50 ms each phase hosts exactly
# two samples, so the expected token sequence is written out longhand below.
# ---------------------------------------------------------------------------

_SCRIPTED = ContactScenario(
    name="scripted_all_tokens",
    phases=(
        ContactPhase(kind="approach", start_s=0.0, duration_s=0.1),
        ContactPhase(kind="contact_start", start_s=0.1, duration_s=0.1),
        ContactPhase(kind="slip", start_s=0.2, duration_s=0.1),
        ContactPhase(kind="impact", start_s=0.3, duration_s=0.1),
        ContactPhase(kind="release", start_s=0.4, duration_s=0.1),
        ContactPhase(kind="settle", start_s=0.5, duration_s=0.1),
    ),
)

_PERIOD_50MS = 50_000_000


def _collect_tactile(**kwargs: Any) -> list[PVTSample]:
    src = SimTactileSource(**kwargs)
    with src:
        return list(src.stream())


def _collect_frames(**kwargs: Any) -> list[PVTSample]:
    src = SimFramesSource(**kwargs)
    with src:
        return list(src.stream())


# ---------------------------------------------------------------------------
# Conformance (through the shared harness) — direct and registry-built (no kwargs).
# ---------------------------------------------------------------------------


def test_sim_tactile_conforms() -> None:
    assert_sensor_source_conforms(
        lambda: SimTactileSource(),
        expected_kind=SensorKind.TACTILE,
        sample_type=PVTSample,
    )


def test_sim_frames_conforms() -> None:
    assert_sensor_source_conforms(
        lambda: SimFramesSource(),
        expected_kind=SensorKind.VISUAL,
        sample_type=PVTSample,
    )


def test_registry_built_sources_conform_with_no_kwargs() -> None:
    """The registry path (what the generic conformance suite uses) needs no kwargs."""
    assert_sensor_source_conforms(
        lambda: make_sensor_source("sim-tactile"),
        expected_kind=SensorKind.TACTILE,
        sample_type=PVTSample,
    )
    assert_sensor_source_conforms(
        lambda: make_sensor_source("sim-frames"),
        expected_kind=SensorKind.VISUAL,
        sample_type=PVTSample,
    )


# ---------------------------------------------------------------------------
# sim-tactile: scripted tokens at scripted timestamps (the B5 acceptance test)
# ---------------------------------------------------------------------------


def test_scripted_episode_carries_expected_tokens_at_scripted_timestamps() -> None:
    """Sampling the scripted scenario at 50 ms yields the exact token-per-timestamp map.

    Timestamps step 0, 50 ms, ..., 550 ms (12 samples, two per 0.1 s phase); the sample at
    600 ms would sit AT total_duration_s (half-open timeline), so the stream ends before it.
    """
    samples = _collect_tactile(scenario=_SCRIPTED, start_ns=0, period_ns=_PERIOD_50MS)
    assert [s.timestamp_ns for s in samples] == [i * _PERIOD_50MS for i in range(12)]
    assert [s.tactile_event for s in samples] == [
        None, None,                        # approach       [0.0, 0.1)
        "contact_start", "contact_start",  # contact_start  [0.1, 0.2)
        "slip", "slip",                    # slip           [0.2, 0.3)
        "impact", "impact",                # impact         [0.3, 0.4)
        "release", "release",              # release        [0.4, 0.5)
        None, None,                        # settle         [0.5, 0.6)
    ]
    # A tactile source never fabricates visual data.
    assert all(s.camera_frame_id is None for s in samples)


def test_tokens_appear_in_stream_order_matching_the_script() -> None:
    """First appearances of the four FROZEN tokens follow the scripted phase order."""
    samples = _collect_tactile(scenario=_SCRIPTED, start_ns=0, period_ns=_PERIOD_50MS)
    seen: list[str] = []
    for s in samples:
        if s.tactile_event is not None and s.tactile_event not in seen:
            seen.append(s.tactile_event)
    assert seen == list(CONTACT_KINDS)
    # And every emitted token is drawn from the FROZEN vocabulary — nothing invented.
    assert {s.tactile_event for s in samples if s.tactile_event is not None} <= set(CONTACT_KINDS)


def test_phase_boundary_belongs_to_the_starting_phase() -> None:
    """A sample stamped exactly at a phase boundary carries the STARTING phase's token."""
    # 100 ms period lands each sample exactly on a boundary of the 0.1 s-grid script.
    samples = _collect_tactile(scenario=_SCRIPTED, start_ns=0, period_ns=100_000_000)
    assert [s.tactile_event for s in samples] == [
        None, "contact_start", "slip", "impact", "release", None,
    ]


def test_tactile_labels_track_injected_clock() -> None:
    """Labels are a function of the INJECTED clock, not an internal index (one timeline)."""
    # Jump straight from the approach into the impact window: elapsed 0 s, 50 ms, 310 ms.
    ticks = iter([1_000, 50_001_000, 310_001_000])
    samples: list[PVTSample] = []
    src = SimTactileSource(scenario=_SCRIPTED, clock_ns=lambda: next(ticks))
    with src:
        for _ in range(3):
            s = src.read()
            assert s is not None
            samples.append(s)
    assert [s.tactile_event for s in samples] == [None, None, "impact"]
    assert [s.timestamp_ns for s in samples] == [1_000, 50_001_000, 310_001_000]


def test_default_tactile_scenario_emits_all_four_tokens() -> None:
    """The no-kwargs default (SLIP_RECOVERY) observably emits every FROZEN token."""
    samples = _collect_tactile()
    emitted = {s.tactile_event for s in samples if s.tactile_event is not None}
    assert emitted == set(CONTACT_KINDS)


# ---------------------------------------------------------------------------
# sim-frames: monotonic, unique, zero-padded frame ids
# ---------------------------------------------------------------------------


def test_camera_frame_ids_monotonic_unique_zero_padded() -> None:
    samples = _collect_frames()
    ids: list[str] = []
    for s in samples:
        assert s.camera_frame_id is not None
        ids.append(s.camera_frame_id)
    assert len(set(ids)) == len(ids), "frame ids must be unique within a stream"
    assert ids == sorted(ids), "zero-padded ids must sort lexicographically == numerically"
    # Exact format: prefix + dense zero-padded counter from 0.
    assert ids == [f"frame_{i:06d}" for i in range(len(ids))]
    # A visual source never fabricates tactile events.
    assert all(s.tactile_event is None for s in samples)


def test_frames_prefix_is_configurable() -> None:
    samples = _collect_frames(frame_prefix="cam0_")
    assert samples[0].camera_frame_id == "cam0_000000"
    assert samples[-1].camera_frame_id == f"cam0_{len(samples) - 1:06d}"


def test_frame_stream_is_finite_and_scenario_bounded() -> None:
    """PICK_PLACE lasts 1.8 s; at the default 40 ms period that is exactly 45 frames."""
    samples = _collect_frames(scenario=PICK_PLACE, start_ns=0, period_ns=40_000_000)
    assert len(samples) == 45
    assert samples[-1].timestamp_ns == 44 * 40_000_000  # 1.76 s < 1.8 s; 1.8 s is excluded


def test_tactile_stream_is_finite_and_scenario_bounded() -> None:
    """SLIP_RECOVERY lasts 1.4 s; at the default 5 ms period that is exactly 280 samples."""
    samples = _collect_tactile(scenario=SLIP_RECOVERY, start_ns=0, period_ns=5_000_000)
    assert len(samples) == 280


def test_read_after_exhaustion_keeps_returning_none() -> None:
    src = SimTactileSource(scenario=_SCRIPTED, start_ns=0, period_ns=_PERIOD_50MS)
    with src:
        while src.read() is not None:
            pass
        assert src.read() is None
        assert src.read() is None  # exhaustion is sticky (no clock ticks burned)


# ---------------------------------------------------------------------------
# Determinism — the hard requirement
# ---------------------------------------------------------------------------


def _strip_ts(samples: list[PVTSample]) -> list[PVTSample]:
    """Copy samples with timestamp zeroed — compare the scripted DATA, not the clock."""
    return [dataclasses.replace(s, timestamp_ns=0) for s in samples]


def test_same_construction_is_byte_identical() -> None:
    a = _collect_tactile(scenario=_SCRIPTED, start_ns=0, period_ns=_PERIOD_50MS)
    b = _collect_tactile(scenario=_SCRIPTED, start_ns=0, period_ns=_PERIOD_50MS)
    assert a == b
    assert [s.to_json() for s in a] == [s.to_json() for s in b]
    fa = _collect_frames()
    fb = _collect_frames()
    assert fa == fb
    assert [s.to_json() for s in fa] == [s.to_json() for s in fb]
    # Export-contract round-trip: each emitted sample must reconstruct exactly via
    # PVTSample.from_row(as_row(...)), so the frozen fields these sources populate — the
    # tactile_event tokens and camera_frame_id — survive serialization intact, not just
    # compare equal across two identical in-memory runs.
    assert all(PVTSample.from_row(s.as_row()) == s for s in a)
    assert all(PVTSample.from_row(s.as_row()) == s for s in fa)


def test_reopen_replays_identical_data_with_advancing_clock() -> None:
    """Re-opening replays identical labels/frame ids; the clock is never rewound."""
    src = SimFramesSource(start_ns=0, period_ns=40_000_000)
    with src:
        first = list(src.stream())
    with src:
        second = list(src.stream())
    assert _strip_ts(first) == _strip_ts(second)  # frame ids reset => identical replay
    assert second[0].timestamp_ns > first[-1].timestamp_ns  # monotonic across re-opens


# ---------------------------------------------------------------------------
# Frozen schema untouched
# ---------------------------------------------------------------------------


def test_pvt_schema_version_unchanged_and_stamped() -> None:
    """B5 populates ALREADY-FROZEN fields — the schema version must still be 1."""
    assert PVT_SCHEMA_VERSION == 1
    # A period equal to the scenario length fits exactly ONE sample (t=0; the next stamp
    # lands AT total_duration_s, which the half-open timeline excludes).
    [t] = _collect_tactile(scenario=_SCRIPTED, period_ns=600_000_000)
    [f] = _collect_frames(scenario=PICK_PLACE, period_ns=1_800_000_000)
    for s in (t, f):
        assert isinstance(s, PVTSample)
        assert s.schema_version == PVT_SCHEMA_VERSION


def test_episode_chain_and_task_label_stamped() -> None:
    samples = _collect_tactile(
        scenario=_SCRIPTED, episode_id="demo_7", chain_index=2, task_label="grasp_cube",
        period_ns=_PERIOD_50MS,
    )
    assert all(s.episode_id == "demo_7" for s in samples)
    assert all(s.chain_index == 2 for s in samples)
    assert all(s.task_label == "grasp_cube" for s in samples)


# ---------------------------------------------------------------------------
# Lifecycle / fail-loud
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [SimTactileSource, SimFramesSource])
def test_read_and_stream_before_open_raise(
    cls: type[SimTactileSource] | type[SimFramesSource],
) -> None:
    src: SensorSource = cls()
    with pytest.raises(RuntimeError, match="before open"):
        src.read()
    with pytest.raises(RuntimeError, match="before open"):
        list(src.stream())


def test_stream_ends_cleanly_when_closed_mid_iteration() -> None:
    src = SimTactileSource()  # 280 default samples — far from exhaustion
    src.open()
    gen = src.stream()
    assert next(gen) is not None
    src.close()
    with pytest.raises(StopIteration):
        next(gen)


@pytest.mark.parametrize("cls", [SimTactileSource, SimFramesSource])
def test_non_positive_period_rejected(
    cls: type[SimTactileSource] | type[SimFramesSource],
) -> None:
    with pytest.raises(ValueError, match="period_ns must be > 0"):
        cls(period_ns=0)


def test_invalid_scenario_rejected_at_construction() -> None:
    """A nonsensical script fails loud at construction, never at sample stamping."""
    bad = ContactScenario(
        name="grabs_forever",
        phases=(
            ContactPhase(kind="approach", start_s=0.0, duration_s=0.1),
            ContactPhase(kind="contact_start", start_s=0.1, duration_s=0.1),
        ),
    )
    with pytest.raises(ValueError, match="no matching later 'release'"):
        SimTactileSource(scenario=bad)
    with pytest.raises(ValueError, match="no matching later 'release'"):
        SimFramesSource(scenario=bad)


# ---------------------------------------------------------------------------
# Metadata / registry
# ---------------------------------------------------------------------------


def test_metadata_reports_kind_name_schema_and_rate() -> None:
    t = SimTactileSource().metadata()
    assert t.kind is SensorKind.TACTILE
    assert t.name == "sim-tactile"
    assert t.device_id == "sim_tactile_pad"
    assert t.sample_schema_version == PVT_SCHEMA_VERSION
    assert t.nominal_rate_hz == pytest.approx(200.0)
    assert t.contract_version == SENSOR_SOURCE_CONTRACT_VERSION

    f = SimFramesSource().metadata()
    assert f.kind is SensorKind.VISUAL
    assert f.name == "sim-frames"
    assert f.device_id == "sim_camera"
    assert f.sample_schema_version == PVT_SCHEMA_VERSION
    assert f.nominal_rate_hz == pytest.approx(25.0)
    assert f.contract_version == SENSOR_SOURCE_CONTRACT_VERSION


def test_registry_lists_and_builds_both_sources() -> None:
    names = list_sensor_sources()
    assert "sim-tactile" in names
    assert "sim-frames" in names
    assert names == sorted(names)
    assert isinstance(make_sensor_source("sim-tactile"), SimTactileSource)
    assert isinstance(make_sensor_source("sim-frames"), SimFramesSource)
