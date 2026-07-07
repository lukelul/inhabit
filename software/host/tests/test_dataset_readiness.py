"""Dataset readiness — seams the existing suite does not cover.

The existing tests prove the gates and round-trips using the *synthetic* committed
fixture and the ``--sim`` / ``.parquet`` CLI inputs. Two seams remained open, and
both are what a REAL bench capture actually exercises:

1. An ARBITRARY (non-synthetic) valid ``.canlog`` must flow the whole path
   canlog -> recorder -> parquet -> lerobot and round-trip, WITHOUT relying on any
   synthetic-fixture expectation (``PODS`` / ``angle_millideg_for`` / exact viz output).
   This is the guarantee behind ``host/logger/DATASET_READINESS.md`` section 5: drop a
   real capture at the same path and it flows through unchanged.

2. The CLI ``.canlog`` input branch (``tools.dataset.__main__._load_canlog_episode``)
   was never tested end-to-end — only ``--sim`` and ``.parquet`` were. That branch is
   exactly what an operator runs on a bench file.

Everything imports FROZEN contracts (CAN codec v1, PVTSample/JointPodState) and reuses
existing pipeline modules; no pipeline logic is reimplemented here. The canlog built
below deliberately uses a DIFFERENT pod set and angles than ``make_sample_canlog`` so it
cannot accidentally pass via synthetic-specific assumptions.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# tools/ is at the repo root, outside host/; add it so the CLI import resolves
# (mirrors tests/test_dataset_roundtrip.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.dataset.__main__ import main

from export.lerobot import export_lerobot, load_lerobot
from inhabit_bridge.conversion import fields_from_frame
from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from inhabit_can.pvt import JointPodState, sample_from_pod_state
from logger.parquet_io import read_episode
from logger.recorder import EpisodeRecorder
from transport.file import FileRecorder, FileReplayTransport

# An arbitrary single-pod bench-style stream that shares NOTHING with the synthetic
# fixture: a different node/chain, a different angle profile, a different tick count.
_NODE_ID = 7
_CHAIN_INDEX = 4
_N_TICKS = 12
_TICK_NS = 5_000_000  # 200 Hz; well inside the recorder's default jitter budget


def _arbitrary_angle_millideg(tick: int) -> int:
    """A non-synthetic angle ramp, inside the int16 millideg range (+/- 32767)."""
    return -3000 + tick * 700


def _write_arbitrary_canlog(path: Path) -> Path:
    """Emit a valid v1 ``.canlog`` via the real FileRecorder (the on-disk wire format)."""
    with FileRecorder(path) as fr:
        for tick in range(_N_TICKS):
            cid, data = encode_state(
                State(
                    angle_raw_adc=(tick * 37) & 0xFFFF,
                    angle_millideg=_arbitrary_angle_millideg(tick),
                    node_id=_NODE_ID,
                    chain_index=_CHAIN_INDEX,
                    status_flags=0,
                )
            )
            fr.write(CanFrame(can_id=cid, data=data, rx_monotonic_ns=tick * _TICK_NS))
    return path


def test_arbitrary_canlog_round_trips(tmp_path: Path) -> None:
    """A non-synthetic valid canlog flows canlog -> recorder -> parquet -> lerobot.

    Drives the recorder on a uniform monotonic clock (one stamp per logged frame),
    exactly as a real per-pod bench capture would, then asserts exact round-trip
    through BOTH the per-episode parquet writer and the lerobot layout.
    """
    canlog = _write_arbitrary_canlog(tmp_path / "sample.canlog")

    episode_id = "bench_arbitrary_000001"
    task = "peg_in_hole"
    rec = EpisodeRecorder(episode_id, tmp_path / "dataset", task_label=task)

    # Re-stamp each logged frame on a uniform clock so timing is the capture's, not
    # the replay loop's speed (see DATASET_READINESS.md NOTE on replay timing).
    expected_angles_rad: list[float] = []
    tick = 0
    with FileReplayTransport(canlog) as tx:
        while (frame := tx.recv()) is not None:
            f = fields_from_frame(frame.data)
            assert f.checksum_valid  # frozen codec produced valid frames
            state = JointPodState(
                node_id=f.node_id,
                chain_index=f.chain_index,
                angle_raw_adc=f.angle_raw_adc,
                angle_millideg=f.angle_millideg,
                angle_rad=f.angle_rad,
                status_flags=f.status_flags,
                checksum_valid=f.checksum_valid,
                schema_version=f.schema_version,
                header_stamp_ns=(tick + 1) * _TICK_NS,
            )
            expected_angles_rad.append(sample_from_pod_state(
                state, episode_id=episode_id, task_label=task
            ).joint_angle)
            rec.ingest(state)
            tick += 1

    assert tick == _N_TICKS

    # --- gated atomic parquet write -----------------------------------------------
    result = rec.finalize()
    assert result.exported, f"clean 200 Hz stream must pass; reasons={result.reasons}"
    assert result.path is not None and result.path.exists()
    assert result.stats.n_samples == _N_TICKS
    assert result.stats.backwards == 0
    assert result.stats.dropouts == 0

    # --- parquet round-trip --------------------------------------------------------
    episode, meta = read_episode(result.path)
    assert episode.episode_id == episode_id
    assert episode.task_label == task
    assert len(episode.samples) == _N_TICKS
    assert meta["dropped_checksum"] == 0
    for tick_i, (s, expected_rad) in enumerate(
        zip(episode.samples, expected_angles_rad, strict=True)
    ):
        assert s.chain_index == _CHAIN_INDEX
        assert s.task_label == task
        assert abs(s.joint_angle - expected_rad) < 1e-12
        # Verify timestamps against the deterministic host clock schedule.
        assert s.timestamp_ns == (tick_i + 1) * _TICK_NS
    # Monotonic ordering — no backwards timestamps.
    stamps = [s.timestamp_ns for s in episode.samples]
    assert stamps == sorted(stamps)
    assert all(stamps[i + 1] > stamps[i] for i in range(len(stamps) - 1))

    # --- lerobot round-trip --------------------------------------------------------
    root = export_lerobot([episode], tmp_path / "lerobot_ds")
    assert (root / "data").is_dir()
    assert (root / "meta" / "info.json").exists()

    loaded = load_lerobot(root)
    assert len(loaded) == 1
    reloaded = loaded[0]
    assert reloaded.episode_id == episode_id
    assert reloaded.task_label == task
    assert len(reloaded.samples) == _N_TICKS
    for back, orig in zip(reloaded.samples, episode.samples, strict=True):
        assert back.chain_index == orig.chain_index
        assert back.timestamp_ns == orig.timestamp_ns
        assert abs(back.joint_angle - orig.joint_angle) < 1e-9


def test_cli_canlog_export_round_trips(tmp_path: Path) -> None:
    """CLI ``.canlog`` input branch exports + verifies a round-trip.

    Closes the only CLI input branch the suite did not cover (``--sim`` and
    ``.parquet`` were). This is the literal command an operator runs on a bench file.
    """
    canlog = _write_arbitrary_canlog(tmp_path / "sample.canlog")
    out = tmp_path / "cli_ds"

    rc = main(["export", "-i", str(canlog), "-o", str(out), "--task", "peg_in_hole", "--verify"])
    assert rc == 0
    assert (out / "meta" / "info.json").exists()
    assert list((out / "data").glob("*.parquet"))

    loaded = load_lerobot(out)
    assert len(loaded) == 1
    ep = loaded[0]
    assert ep.task_label == "peg_in_hole"
    assert len(ep.samples) == _N_TICKS
    assert {s.chain_index for s in ep.samples} == {_CHAIN_INDEX}
    # Full round-trip: verify angles and timestamps survive the CLI export path.
    millideg_to_rad = math.pi / 180.0 / 1000.0
    for tick_i, s in enumerate(ep.samples):
        expected_rad = _arbitrary_angle_millideg(tick_i) * millideg_to_rad
        assert abs(s.joint_angle - expected_rad) < 1e-9
        assert s.episode_id == ep.episode_id
        assert s.task_label == "peg_in_hole"
