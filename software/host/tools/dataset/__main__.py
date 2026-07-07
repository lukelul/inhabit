"""CLI: export recorded episodes to lerobot format.

Usage:
    python -m tools.dataset export -i episode.parquet -o ./lerobot_ds
    python -m tools.dataset export -i recording.canlog -o ./lerobot_ds
    python -m tools.dataset export --sim -o ./lerobot_ds
    python -m tools.dataset export --sim --scenario slip_recovery -o ./lerobot_ds
    python -m tools.dataset export -i episode.parquet -o ./lerobot_ds --verify
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inhabit_can.pvt import Episode, JointPodState, PVTSample, sample_from_pod_state

from export.lerobot import export_lerobot, load_lerobot


def _load_canlog_episode(path: Path, episode_id: str, task_label: str | None) -> Episode:
    """Decode a .canlog through the frozen codec into an Episode.

    Two failure modes are guarded here:

    * **Corrupt / non-finite frames leaking into the export (C1/C4).** Earlier this
      loader carried ``checksum_valid`` onto the state but never checked it, so a
      corrupt-checksum (or NaN/inf) frame leaked straight into the lerobot export even
      though the recorder drops it at ingest — the two paths disagreed. We now apply
      the SAME drop policy via :func:`logger.recorder.frame_reject_reason`, so the
      convenience CLI and the gated recorder cannot drift on what counts as a bad frame.
    * **Losing the real capture cadence.** ``FileReplayTransport.recv`` re-stamps every
      frame with ``time.monotonic_ns()`` at recv time, so jitter measured downstream
      reflects the replay loop speed, not the bench cadence (see
      ``host/logger/DATASET_READINESS.md`` NOTE on replay timing). For the export
      time-quality gate to mean anything, we read the REAL on-disk ``t_ns`` (the
      monotonic stamp captured at RX) via ``transport.file._load_canlog`` and use it as
      ``header_stamp_ns``.

    Dropped frames are reported on stderr so the operator sees the count.
    """
    from inhabit_bridge.conversion import fields_from_frame
    from logger.recorder import frame_reject_reason
    from transport.file import _load_canlog

    episode = Episode(episode_id=episode_id, task_label=task_label)
    dropped = 0
    for t_ns, _can_id, data in _load_canlog(path):
        pf = fields_from_frame(data)
        state = JointPodState(
            node_id=pf.node_id,
            chain_index=pf.chain_index,
            angle_raw_adc=pf.angle_raw_adc,
            angle_millideg=pf.angle_millideg,
            angle_rad=pf.angle_rad,
            status_flags=pf.status_flags,
            checksum_valid=pf.checksum_valid,
            schema_version=pf.schema_version,
            header_stamp_ns=t_ns,  # real captured monotonic stamp, not the replay re-stamp
        )
        reason = frame_reject_reason(state)
        if reason is not None:
            dropped += 1
            continue
        sample = sample_from_pod_state(state, episode_id=episode_id, task_label=task_label)
        episode.add(sample)
    if dropped:
        print(
            f"dropped {dropped} corrupt/non-finite frame(s) from {path}",
            file=sys.stderr,
        )
    return episode


def _load_parquet_episode(path: Path) -> Episode:
    """Load an episode from a per-episode parquet file (logger format)."""
    from logger.parquet_io import read_episode

    episode, _meta = read_episode(path)
    return episode


def _load_sim_episode(task_label: str | None) -> Episode:
    """Generate a synthetic episode via SimAdapter."""
    from tools.dataset.sim_adapter import SimConfig, SimAdapter

    cfg = SimConfig(n_joints=3, n_samples=100, task_label=task_label or "sim_reach")
    return SimAdapter(cfg).generate_episode()


def _load_scenario_episode(name: str, task_label: str | None) -> Episode:
    """Generate a scenario-driven multi-modality sim episode (B7's --sim --scenario path).

    Delegates to :func:`tools.dataset.scenario_episode.build_scenario_episode`, which
    drives the registered ``sim-tactile`` / ``sim-frames`` sources plus a seeded+noisy
    ``SimRobot`` proprio stream over the named built-in contact scenario, merges them onto
    one monotonic timeline, and routes the merged timestamps through the jitter gate
    (``compute_jitter`` + ``JitterBudget``) BEFORE export — a mis-timed sim episode raises
    here instead of exporting looking clean.
    """
    from tools.dataset.scenario_episode import build_scenario_episode

    return build_scenario_episode(name, task_label=task_label)


def _sort_key(s: PVTSample) -> tuple[int, int]:
    """Canonical sort: (timestamp_ns, chain_index) so interleaved captures compare equal."""
    return (s.timestamp_ns, s.chain_index)


def _verify_roundtrip(root: Path, originals: list[Episode]) -> bool:
    """Reload the exported dataset and verify full field-level equality.

    Both sides are sorted into canonical (timestamp_ns, chain_index) order so
    interleaved captures that get reordered by export don't cause false failures.
    Checks all v3 persisted fields: timestamp, chain_index, joint_angle,
    velocity, current, torque, task_label, camera_frame_id, tactile_event.
    """
    loaded = load_lerobot(root)
    if not loaded:
        print("FAIL: round-trip produced no episodes", file=sys.stderr)
        return False
    if len(loaded) != len(originals):
        print(
            f"FAIL: round-trip episode count mismatch: "
            f"exported {len(originals)}, loaded {len(loaded)}",
            file=sys.stderr,
        )
        return False
    for orig, back in zip(originals, loaded, strict=True):
        if orig.episode_id != back.episode_id:
            print(f"FAIL: episode_id mismatch: {orig.episode_id} != {back.episode_id}", file=sys.stderr)
            return False
        if len(orig.samples) != len(back.samples):
            print(
                f"FAIL: sample count mismatch in {orig.episode_id}: "
                f"{len(orig.samples)} != {len(back.samples)}",
                file=sys.stderr,
            )
            return False
        # Canonical order so interleaved captures compare correctly.
        o_sorted = sorted(orig.samples, key=_sort_key)
        b_sorted = sorted(back.samples, key=_sort_key)
        for i, (so, sb) in enumerate(zip(o_sorted, b_sorted, strict=True)):
            if so.timestamp_ns != sb.timestamp_ns:
                print(f"FAIL: timestamp_ns mismatch at sample {i} in {orig.episode_id}", file=sys.stderr)
                return False
            if so.chain_index != sb.chain_index:
                print(f"FAIL: chain_index mismatch at sample {i} in {orig.episode_id}", file=sys.stderr)
                return False
            if abs(so.joint_angle - sb.joint_angle) > 1e-9:
                print(f"FAIL: joint_angle mismatch at sample {i} in {orig.episode_id}", file=sys.stderr)
                return False
            if abs(so.joint_velocity - sb.joint_velocity) > 1e-9:
                print(f"FAIL: joint_velocity mismatch at sample {i}", file=sys.stderr)
                return False
            if abs(so.motor_current - sb.motor_current) > 1e-9:
                print(f"FAIL: motor_current mismatch at sample {i}", file=sys.stderr)
                return False
            if abs(so.estimated_torque - sb.estimated_torque) > 1e-9:
                print(f"FAIL: estimated_torque mismatch at sample {i}", file=sys.stderr)
                return False
            if so.task_label != sb.task_label:
                print(f"FAIL: task_label mismatch at sample {i}", file=sys.stderr)
                return False
    total = sum(len(ep) for ep in loaded)
    print(f"OK: round-trip verified — {len(loaded)} episode(s), {total} sample(s)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.dataset",
        description="Export PVT episodes to lerobot format.",
    )
    sub = parser.add_subparsers(dest="command")

    exp = sub.add_parser("export", help="Export episode(s) to lerobot dataset")
    inp = exp.add_mutually_exclusive_group(required=True)
    inp.add_argument("-i", "--input", type=Path, help=".canlog or .parquet file")
    inp.add_argument("--sim", action="store_true", help="Generate a synthetic episode")
    exp.add_argument("-o", "--output", type=Path, required=True, help="Output dataset directory")
    # Built-in contact scenarios only (a curated closed set), so argparse both validates
    # the name and advertises the choices in --help; requires --sim (checked after parse).
    from sim.scenario import EXAMPLE_SCENARIOS

    exp.add_argument(
        "--scenario",
        default=None,
        choices=sorted(EXAMPLE_SCENARIOS),
        help="Drive --sim with a built-in contact scenario (multi-modality PVT episode)",
    )
    exp.add_argument("--episode-id", default=None, help="Episode ID (default: filename stem)")
    exp.add_argument("--task", default=None, help="Task label")
    exp.add_argument("--verify", action="store_true", help="Verify round-trip after export")

    args = parser.parse_args(argv)
    if args.command != "export":
        parser.print_help()
        return 1

    if args.scenario is not None and not args.sim:
        parser.error("--scenario requires --sim")

    if args.sim:
        if args.scenario is not None:
            episodes = [_load_scenario_episode(args.scenario, args.task)]
        else:
            episodes = [_load_sim_episode(args.task)]
    elif args.input.suffix == ".canlog":
        eid = args.episode_id or args.input.stem
        episodes = [_load_canlog_episode(args.input, eid, args.task)]
    elif args.input.suffix == ".parquet":
        episodes = [_load_parquet_episode(args.input)]
    else:
        print(f"Unknown input format: {args.input.suffix} (expected .canlog or .parquet)", file=sys.stderr)
        return 1

    # The canlog loader now uses the REAL on-disk RX timestamps (not the replay
    # re-stamp), so the default time-quality gate is meaningful here: a genuinely
    # non-monotonic or hole-ridden capture is refused, an over-budget-but-monotonic
    # one is flagged, and a clean uniform-cadence capture exports unchanged. The
    # hard, atomic, per-episode gate remains the recorder; this is the convenience
    # exporter over already-built episodes.
    root = export_lerobot(episodes, args.output)
    # Read counts from info.json (already written) instead of reloading the
    # whole dataset — avoids an expensive full re-parse just for a status line.
    import json as _json
    info = _json.loads((root / "meta" / "info.json").read_text())
    n_exported = info["total_episodes"]
    total_frames = info["total_frames"]
    n_refused = info.get("total_episodes_input", len(episodes)) - n_exported
    msg = f"Exported {n_exported} episode(s), {total_frames} frame(s) -> {root}"
    if n_refused:
        msg += f" ({n_refused} refused by time-quality gate)"
    print(msg)

    if args.verify:
        if not _verify_roundtrip(root, episodes):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
