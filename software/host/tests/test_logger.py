"""PVT episode logger tests.

DoD coverage:
- write -> read -> assert-equal round-trip for a multi-sample episode.
- jitter measured & logged; over-budget episode quarantined (not exported).
- within-budget episode passes.
- half-written/crash case stays quarantined (no readable episode in dataset).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from inhabit_can.pvt import (
    PVT_SCHEMA_VERSION,
    Episode,
    JointPodState,
    PVTSample,
    sample_from_pod_state,
)
from logger import (
    EpisodeRecorder,
    JitterBudget,
    QuarantineError,
    compute_jitter,
    read_episode,
    write_episode,
)
from logger.parquet_io import META_DETECTOR_VERSION  # noqa: F401 (kept for clarity)

PERIOD_NS = 10_000_000  # 100 Hz


def _pod_state(i: int, *, stamp_ns: int, valid: bool = True) -> JointPodState:
    return JointPodState(
        node_id=3,
        chain_index=3,
        angle_raw_adc=1000 + i,
        angle_millideg=(i * 37) % 360_000,
        angle_rad=math.sin(i / 10.0),
        status_flags=0,
        checksum_valid=valid,
        schema_version=1,
        header_stamp_ns=stamp_ns,
    )


def _clean_stream(n: int, start: int = 1_000_000_000) -> list[JointPodState]:
    """A perfectly periodic monotonic stream at 100 Hz."""
    return [_pod_state(i, stamp_ns=start + i * PERIOD_NS) for i in range(n)]


# --- round-trip -----------------------------------------------------------


def test_episode_roundtrip_multisample(tmp_path: Path) -> None:
    rec = EpisodeRecorder(
        "demo_round", tmp_path, task_label="insert_connector",
    )
    for st in _clean_stream(50):
        rec.ingest(st)
    result = rec.finalize()

    assert result.exported is True
    assert result.path is not None and result.path.exists()

    episode_in = rec.episode
    episode_out, meta = read_episode(result.path)

    # structural equality
    assert episode_out.episode_id == episode_in.episode_id
    assert episode_out.task_label == episode_in.task_label
    assert len(episode_out) == len(episode_in)

    # numerical + field equality, per sample
    for a, b in zip(episode_in.samples, episode_out.samples, strict=True):
        assert a.timestamp_ns == b.timestamp_ns
        assert a.chain_index == b.chain_index
        assert a.joint_angle == pytest.approx(b.joint_angle, rel=0, abs=0)
        assert a.episode_id == b.episode_id
        assert a.task_label == b.task_label
        assert a.schema_version == b.schema_version == PVT_SCHEMA_VERSION

    # provenance travelled in the footer
    assert meta["episode_id"] == "demo_round"
    assert meta["contact_detector_version"]
    assert meta["jitter_stats"]["n_samples"] == 50
    assert meta["jitter_budget"]["max_jitter_p99_ns"] == JitterBudget().max_jitter_p99_ns


def test_direct_write_read_equal(tmp_path: Path) -> None:
    """write_episode/read_episode round-trip including None fields."""
    ep = Episode("e0", task_label="grasp")
    ep.add(PVTSample(timestamp_ns=1, episode_id="e0", chain_index=0, joint_angle=0.5))
    ep.add(
        PVTSample(
            timestamp_ns=2,
            episode_id="e0",
            chain_index=1,
            joint_angle=-0.25,
            tactile_event="contact_start",
            camera_frame_id="frame_42",
        )
    )
    out = write_episode(ep, tmp_path / "e0.parquet")
    back, _ = read_episode(out)
    assert [s.as_row() for s in back.samples] == [s.as_row() for s in ep.samples]


# --- mapping --------------------------------------------------------------


def test_sample_from_pod_state_maps_radians() -> None:
    st = _pod_state(7, stamp_ns=555)
    s = sample_from_pod_state(st, episode_id="e", task_label="t")
    assert s.timestamp_ns == 555
    assert s.chain_index == 3
    assert s.joint_angle == st.angle_rad
    assert s.joint_velocity == 0.0  # proprioceptive-only defaults
    assert s.motor_current == 0.0
    assert s.task_label == "t"


# --- jitter measurement ---------------------------------------------------


def test_jitter_clean_stream_period_and_zero_jitter() -> None:
    ts = [s.header_stamp_ns for s in _clean_stream(100)]
    stats = compute_jitter(ts)
    assert stats.period_ns == PERIOD_NS
    assert stats.jitter_p99_ns == 0
    assert stats.dropouts == 0
    assert stats.backwards == 0


def test_within_budget_passes(tmp_path: Path) -> None:
    # small bounded jitter: each timestamp nudged by a deterministic value whose
    # resulting interval deviation stays well under the 2 ms p99 budget.
    rec = EpisodeRecorder("ok_jitter", tmp_path)
    nudges = [0, 200_000, -100_000, 150_000, -50_000]  # |interval dev| <= ~0.35 ms
    for i in range(40):
        rec.ingest(_pod_state(i, stamp_ns=i * PERIOD_NS + nudges[i % len(nudges)]))
    result = rec.finalize()
    assert result.exported is True, result.reasons
    assert result.reasons == []
    assert result.stats.jitter_p99_ns < JitterBudget().max_jitter_p99_ns


def test_over_budget_jitter_quarantined(tmp_path: Path) -> None:
    rec = EpisodeRecorder("bad_jitter", tmp_path)
    start = 0
    for i in range(40):
        # inject a 5 ms spike on every other sample -> p99 >> 2 ms budget
        wobble = 5_000_000 if i % 2 else 0
        rec.ingest(_pod_state(i, stamp_ns=start + i * PERIOD_NS + wobble))
    result = rec.finalize()

    assert result.exported is False
    assert any("jitter p99" in r for r in result.reasons)
    # NOTHING in the dataset dir; only a quarantine sidecar
    assert not (tmp_path / "bad_jitter.parquet").exists()
    assert (tmp_path / "quarantine" / "bad_jitter.quarantine.json").exists()


def test_dropout_quarantined(tmp_path: Path) -> None:
    rec = EpisodeRecorder("dropout_ep", tmp_path)
    ts = [i * PERIOD_NS for i in range(20)]
    ts = ts[:10] + [t + 5 * PERIOD_NS for t in ts[10:]]  # a big gap == missed frames
    for i, t in enumerate(ts):
        rec.ingest(_pod_state(i, stamp_ns=t))
    result = rec.finalize()
    assert result.exported is False
    assert any("dropout" in r for r in result.reasons)


def test_backwards_clock_quarantined(tmp_path: Path) -> None:
    rec = EpisodeRecorder("backwards_ep", tmp_path)
    ts = [0, PERIOD_NS, PERIOD_NS // 2, 3 * PERIOD_NS]  # third goes backwards
    for i, t in enumerate(ts):
        rec.ingest(_pod_state(i, stamp_ns=t))
    result = rec.finalize()
    assert result.exported is False
    assert any("backwards" in r for r in result.reasons)


def test_too_few_samples_quarantined(tmp_path: Path) -> None:
    rec = EpisodeRecorder("tiny_ep", tmp_path)
    rec.ingest(_pod_state(0, stamp_ns=0))
    result = rec.finalize()
    assert result.exported is False
    assert any("too few" in r for r in result.reasons)


def test_strict_raises_on_quarantine(tmp_path: Path) -> None:
    rec = EpisodeRecorder("strict_ep", tmp_path)
    rec.ingest(_pod_state(0, stamp_ns=0))
    with pytest.raises(QuarantineError):
        rec.finalize(strict=True)


# --- robustness -----------------------------------------------------------


def test_invalid_checksum_frames_dropped_from_timeline(tmp_path: Path) -> None:
    """A corrupt frame is counted and excluded from the sample timeline (it must not
    poison numerical data). The resulting hole is a real time gap; with a single drop
    it shows up as a 2x-period jitter deviation, so the recorder honestly flags it
    rather than papering over the missing data."""
    rec = EpisodeRecorder("csum_ep", tmp_path)
    for i in range(20):
        valid = i != 5  # one corrupt frame
        rec.ingest(_pod_state(i, stamp_ns=i * PERIOD_NS, valid=valid))
    result = rec.finalize()
    assert result.stats.n_samples == 19  # corrupt frame excluded
    assert rec._dropped_checksum == 1


def test_all_valid_checksum_exports(tmp_path: Path) -> None:
    rec = EpisodeRecorder("csum_ok", tmp_path)
    for i in range(20):
        rec.ingest(_pod_state(i, stamp_ns=i * PERIOD_NS, valid=True))
    result = rec.finalize()
    assert result.exported is True
    assert rec._dropped_checksum == 0


def test_dict_input_accepted(tmp_path: Path) -> None:
    rec = EpisodeRecorder("dict_ep", tmp_path)
    for i in range(5):
        rec.ingest(
            {
                "node_id": 1,
                "chain_index": 1,
                "angle_raw_adc": i,
                "angle_millideg": i,
                "angle_rad": float(i),
                "status_flags": 0,
                "checksum_valid": True,
                "schema_version": 1,
                "header_stamp_ns": i * PERIOD_NS,
            }
        )
    result = rec.finalize()
    assert result.exported is True
    assert result.stats.n_samples == 5


def test_ingest_after_finalize_errors(tmp_path: Path) -> None:
    rec = EpisodeRecorder("done_ep", tmp_path)
    for st in _clean_stream(3):
        rec.ingest(st)
    rec.finalize()
    with pytest.raises(RuntimeError):
        rec.ingest(_pod_state(99, stamp_ns=99 * PERIOD_NS))


# --- crash / half-write safety -------------------------------------------


def test_half_written_part_file_is_not_readable_as_episode(tmp_path: Path) -> None:
    """Simulate a crash mid-write: a leftover .part exists but the dataset has no
    readable episode. read_episode of the dataset path must fail; the .part is the
    only artifact and is ignored by readers (quarantined by construction)."""
    ep = Episode("crash_ep")
    for i in range(5):
        ep.add(
            PVTSample(
                timestamp_ns=i * PERIOD_NS,
                episode_id="crash_ep",
                chain_index=0,
                joint_angle=float(i),
            )
        )
    final = tmp_path / "crash_ep.parquet"
    part = final.with_suffix(".parquet.part")
    # write only the .part (as if the process died before os.replace)
    write_episode(ep, part)  # writes part.part then renames to part -> leaves a .part
    assert part.exists()
    assert not final.exists()  # final never appeared -> not in the dataset
    with pytest.raises(FileNotFoundError):
        read_episode(final)


def test_crash_before_finalize_leaves_no_episode(tmp_path: Path) -> None:
    """Recorder that never finalizes writes nothing to the dataset."""
    rec = EpisodeRecorder("never_final", tmp_path)
    for st in _clean_stream(10):
        rec.ingest(st)
    # no finalize() -> simulate crash
    assert list(tmp_path.glob("*.parquet")) == []
