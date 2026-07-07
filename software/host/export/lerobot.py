"""LeRobot-compatible parquet exporter and loader for PVT episodes.

Writes episodes into the lerobot v2 dataset layout:
    data/train-NNNNN-of-NNNNN.parquet   (one chunk with all episodes)
    meta/info.json                       (dataset metadata)
    meta/episodes.jsonl                  (per-episode metadata)
    meta/tasks.jsonl                     (task label registry)

Columns follow lerobot convention:
    index, episode_index, frame_index, timestamp,
    observation.chain_index (real joint identifiers for this frame),
    observation.state (joint_angle per chain_index, flattened),
    observation.velocity, ...

The loader reads the same layout back into Episode objects so the pipeline
round-trips: generate -> export -> load -> assert equal.

Dataset manifest versioning
---------------------------
``LEROBOT_DATASET_VERSION`` is the version of *this on-disk dataset layout* (the
parquet column set + info.json), NOT the frozen ``PVT_SCHEMA_VERSION`` of the
PVTSample contract. v1 reconstructed ``chain_index`` from row position, which
silently corrupts sparse / non-zero-based / partially-missing joints. v2 persists
the real ``observation.chain_index`` per frame; ``load_lerobot`` stays
migration-aware so v1 files still load (positional fallback).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from inhabit_can.pvt import Episode, PVTSample
from logger.jitter import JitterBudget, compute_jitter
from timing.export_meta import (
    TimingMeta,
    read_timing_sidecar,
    select_episode_timing,
    write_selected_timing_sidecar,
)

log = logging.getLogger("inhabit.export")

# Version of the lerobot dataset layout written by this module. Distinct from the
# frozen PVT_SCHEMA_VERSION (PVTSample). Bump only with a load-time migration.
# v2: persisted chain_index; v3: added camera_frame_id + tactile_event columns.
# The C5 timing sidecar (meta/timing.json) is ADDITIVE and OPTIONAL — absent on legacy
# datasets and ignored by load_lerobot — so it needs no layout-version bump/migration.
LEROBOT_DATASET_VERSION = 3

# Sidecar filename for the per-episode timing metadata, under meta/ next to info.json —
# the dataset's existing metadata channel. One canonical document shape for all
# exporters; see timing.export_meta.
_TIMING_SIDECAR = "timing.json"


def _group_samples_by_frame(episode: Episode) -> list[list[PVTSample]]:
    """Group samples sharing the same ``timestamp_ns`` into one frame.

    Failure mode this guards: the previous version grouped by ADJACENCY (a run of
    consecutive equal timestamps), so when pods are interleaved in the stream — e.g.
    ``[t0/pod0, t1/pod0, t0/pod1]`` from two append-only per-pod writers, or any
    non-pre-sorted multi-pod episode — a single instant got split across multiple
    "frames", scrambling the per-frame joint vector. We instead key a dict by
    ``timestamp_ns`` so every joint observed at one instant lands in the same frame
    regardless of arrival order, then emit frames in ascending time.
    """
    by_ts: dict[int, list[PVTSample]] = {}
    for s in episode.samples:
        by_ts.setdefault(s.timestamp_ns, []).append(s)
    return [by_ts[ts] for ts in sorted(by_ts)]


def _instant_order(episode: Episode) -> list[int]:
    """Unique per-frame timestamps in order of FIRST appearance in the capture stream.

    The C2 monotonicity gate must run on this, not on the grouped/sorted frames:
    grouping sorts by ``timestamp_ns`` (the C3 fix), which would hide a backward
    timeline. And it must run on UNIQUE instants, not the raw per-sample list, so a
    legitimately interleaved multi-pod stream (``[t0/podA, t1/podA, t0/podB]`` — the
    same instants repeating once per pod) is NOT mistaken for going backwards. A
    genuinely corrupt episode is one whose distinct instants first appear out of
    monotonic order (e.g. captured ``[3, 2, 1]``); ``compute_jitter`` on this list
    then reports ``backwards`` / ``dropouts`` honestly.
    """
    seen: set[int] = set()
    order: list[int] = []
    for s in episode.samples:
        if s.timestamp_ns not in seen:
            seen.add(s.timestamp_ns)
            order.append(s.timestamp_ns)
    return order


def _infer_timing(rows: list[dict[str, Any]]) -> tuple[float, int | None]:
    """Derive (fps, measured_jitter_ns) per-episode, then aggregate.

    Computes timing WITHIN each episode (by ``episode_index``) so inter-episode
    gaps are excluded — mixing separate episodes would inflate jitter and produce
    a meaningless blended fps. Returns the median fps across episodes and the
    worst (max) jitter.

    Returns ``(0.0, None)`` when there are too few frames to estimate a rate.
    """
    by_ep: dict[int, list[int]] = {}
    for r in rows:
        by_ep.setdefault(r["episode_index"], []).append(r["timestamp_ns"])

    ep_fps: list[float] = []
    ep_jitter: list[int] = []
    for ts_list in by_ep.values():
        ts = sorted(set(ts_list))
        if len(ts) < 2:
            continue
        stats = compute_jitter(ts)
        if stats.period_ns <= 0:
            continue
        ep_fps.append(1e9 / stats.period_ns)
        ep_jitter.append(stats.jitter_max_ns)

    if not ep_fps:
        return 0.0, None
    ep_fps.sort()
    fps = round(ep_fps[len(ep_fps) // 2], 6)
    jitter = max(ep_jitter)
    return fps, jitter


def export_lerobot(
    episodes: list[Episode],
    out_dir: str | os.PathLike[str],
    *,
    budget: JitterBudget | None = None,
    extra_rejected: list[dict[str, Any]] | None = None,
    extra_input_count: int = 0,
    timing_meta: Mapping[str, TimingMeta] | None = None,
) -> Path:
    """Export episodes to a lerobot-compatible dataset directory.

    ``extra_rejected`` / ``extra_input_count`` let a caller that pre-gated some episodes
    *outside* this function (e.g. the ``LeRobotExporter`` ABC adapter, which strips
    non-finite frames and may empty an episode entirely) fold those refusals into this
    dataset's audit trail so they are NOT silently lost: each record is appended to
    ``meta/info.json -> rejected_episodes`` and ``extra_input_count`` is added to
    ``total_episodes_input``. Defaults are inert, so existing callers are unaffected.

    ``timing_meta`` (C5, optional, keyed by ``episode_id``) writes the auditable
    per-episode sync summary (``timing.export_meta.TimingMeta``) to ``meta/timing.json``
    — the dataset's existing metadata channel. An id that was never offered for export
    raises (metadata about nothing is fabrication); an entry for a refused/empty episode
    is omitted from the sidecar with a WARNING (the sidecar describes only episodes that
    are actually in the dataset). ``None`` (the default) writes no sidecar — byte-for-byte
    the pre-C5 layout — and ``load_lerobot_timing_meta`` returns ``None`` for such
    datasets, so legacy round-trips are untouched.

    Time-quality gate (failure mode first)
    --------------------------------------
    A lerobot dataset is only useful if its per-frame timestamps form a trustworthy,
    monotonic timeline — downstream training resamples/aligns CAN, video and tactile
    against it. ``_infer_timing`` alone *silently* hides damage: it drops backward
    gaps (it only keeps ``b > a``) before estimating fps, so a non-monotonic or
    hole-ridden episode would still export looking clean. Before this gate,
    ``export_lerobot`` had no monotonicity check at all.

    So we measure jitter PER EPISODE on the per-frame timestamps (the same
    ``compute_jitter`` the recorder budgets against) and:

    * **Refuse** (skip, write nothing for that episode) any episode with a backward
      instant (``backwards > 0``) or a dropout (a >budget gap = a hole). A backward
      timeline is corruption, not noise; exporting it would poison alignment. Refused
      episodes are recorded under ``meta/info.json -> rejected_episodes`` with reasons
      and logged at WARNING, so the rejection is visible, never silent.
    * **Flag** (still export, mark ``quality_failed`` in ``meta/episodes.jsonl``) an
      episode whose p99 jitter exceeds budget but whose timeline is monotonic and
      hole-free. The frames are usable but the consumer is told the timing is loose.

    This is a coarser net than the recorder's gate (which QUARANTINES the whole
    episode). The gated, atomic dataset writer is ``logger.EpisodeRecorder``; this
    exporter is a convenience layer over already-built ``Episode`` objects (e.g. the
    ``tools/dataset`` CLI), so it refuses the unrecoverable cases and flags the rest
    rather than discarding data the caller may have deliberately kept.

    Returns the dataset root path.
    """
    budget = budget or JitterBudget()

    # C5 fail-fast: reject unknown timing_meta ids BEFORE creating directories or writing
    # any dataset file — metadata about an episode never offered for export must never
    # leave a partially-written dataset behind when this raises. (Known ids at this point
    # are the offered episodes plus any upstream refusals the caller passed in.)
    if timing_meta is not None:
        select_episode_timing(
            timing_meta,
            written_ids=set(),
            known_ids={ep.episode_id for ep in episodes}
            | {str(r["episode_id"]) for r in (extra_rejected or [])},
        )

    root = Path(out_dir)
    data_dir = root / "data"
    meta_dir = root / "meta"
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Build the flat table
    rows: list[dict[str, Any]] = []
    task_set: dict[str, int] = {}
    episode_meta: list[dict[str, Any]] = []
    # Seed with refusals the caller already decided upstream (e.g. episodes the ABC
    # adapter emptied by stripping non-finite frames) so they stay in the audit trail.
    rejected_episodes: list[dict[str, Any]] = list(extra_rejected or [])
    global_idx = 0

    for episode in episodes:
        frames = _group_samples_by_frame(episode)
        if not frames:
            continue

        # --- per-episode time-quality gate (see docstring) -----------------------
        # Measure jitter on the UNIQUE instants in first-appearance (capture) order
        # so (a) backwards detection still works after the C3 sort-grouping, and
        # (b) a legitimately interleaved multi-pod stream is not mistaken for going
        # backwards. See _instant_order.
        stats = compute_jitter(_instant_order(episode), budget)
        refuse_reasons: list[str] = []
        quality_reasons: list[str] = []
        if stats.backwards > 0:
            refuse_reasons.append(
                f"non-monotonic timeline: {stats.backwards} backward instant(s)"
            )
        if stats.dropouts > 0:
            refuse_reasons.append(
                f"{stats.dropouts} dropout(s): gap > {budget.max_gap_factor}x period"
            )
        if stats.jitter_p99_ns > budget.max_jitter_p99_ns:
            quality_reasons.append(
                f"jitter p99 {stats.jitter_p99_ns} ns > budget {budget.max_jitter_p99_ns} ns"
            )
        if refuse_reasons:
            log.warning(
                "REFUSED episode=%s from lerobot export: %s",
                episode.episode_id,
                "; ".join(refuse_reasons),
            )
            rejected_episodes.append({
                "episode_id": episode.episode_id,
                "reasons": refuse_reasons,
                "jitter_stats": stats.as_dict(),
            })
            continue
        if quality_reasons:
            log.warning(
                "FLAGGED episode=%s quality_failed in lerobot export: %s",
                episode.episode_id,
                "; ".join(quality_reasons),
            )

        # Dense episode_index over the EXPORTED set: refusals must not leave gaps,
        # or episodes.jsonl/parquet rows would carry sparse indices inconsistent
        # with info.json total_episodes and break consumers that assume a dense range.
        written_ep_idx = len(episode_meta)
        t0_ns = frames[0][0].timestamp_ns

        if episode.task_label and episode.task_label not in task_set:
            task_set[episode.task_label] = len(task_set)

        for frame_idx, frame in enumerate(frames):
            ts_sec = (frame[0].timestamp_ns - t0_ns) / 1e9
            # Sort by chain_index and persist the REAL identifiers so sparse /
            # non-zero-based / partially-missing joints round-trip as themselves.
            frame_sorted = sorted(frame, key=lambda s: s.chain_index)
            chain_indices = [s.chain_index for s in frame_sorted]
            angles = [s.joint_angle for s in frame_sorted]
            velocities = [s.joint_velocity for s in frame_sorted]
            currents = [s.motor_current for s in frame_sorted]
            torques = [s.estimated_torque for s in frame_sorted]
            # Future PVT streams: one camera/tactile reference per frame.
            # All samples in a frame share the same instant; verify they agree.
            cam_ids = {s.camera_frame_id for s in frame_sorted}
            tactiles = {s.tactile_event for s in frame_sorted}
            cam_id = cam_ids.pop() if len(cam_ids) == 1 else None
            tactile = tactiles.pop() if len(tactiles) == 1 else None

            rows.append({
                "index": global_idx,
                "episode_index": written_ep_idx,
                "frame_index": frame_idx,
                "timestamp": ts_sec,
                "timestamp_ns": frame[0].timestamp_ns,
                "task_index": task_set.get(episode.task_label, -1) if episode.task_label else -1,
                "observation.chain_index": chain_indices,
                "observation.state": angles,
                "observation.velocity": velocities,
                "observation.current": currents,
                "observation.torque": torques,
                "camera_frame_id": cam_id,
                "tactile_event": tactile,
                "episode_id": episode.episode_id,
                "task_label": episode.task_label,
            })
            global_idx += 1

        episode_meta.append({
            "episode_index": written_ep_idx,
            "episode_id": episode.episode_id,
            "task_label": episode.task_label,
            "length": len(frames),
            "task_index": task_set.get(episode.task_label, -1) if episode.task_label else -1,
            # Time-quality flag: True when the timeline is monotonic + hole-free but
            # exceeds the p99 jitter budget (exported with a warning; consumers can
            # filter on it). Refused episodes never reach here — see rejected_episodes.
            "quality_failed": bool(quality_reasons),
            "quality_reasons": quality_reasons,
        })

    # Write parquet
    chunk_name = "train-00000-of-00001.parquet"
    if rows:
        schema = pa.schema([
            ("index", pa.int64()),
            ("episode_index", pa.int64()),
            ("frame_index", pa.int64()),
            ("timestamp", pa.float64()),
            ("timestamp_ns", pa.int64()),
            ("task_index", pa.int64()),
            ("observation.chain_index", pa.list_(pa.int64())),
            ("observation.state", pa.list_(pa.float64())),
            ("observation.velocity", pa.list_(pa.float64())),
            ("observation.current", pa.list_(pa.float64())),
            ("observation.torque", pa.list_(pa.float64())),
            ("camera_frame_id", pa.string()),
            ("tactile_event", pa.string()),
            ("episode_id", pa.string()),
            ("task_label", pa.string()),
        ])
        arrays = {name: [r[name] for r in rows] for name in schema.names}
        table = pa.table(arrays, schema=schema)
        pq.write_table(table, data_dir / chunk_name)

    # Write meta/info.json
    n_joints_detected = max((len(r["observation.state"]) for r in rows), default=0)
    fps, jitter_ns = _infer_timing(rows)
    info = {
        "codebase_version": "v2.1",
        "robot_type": "inhabit_pvt",
        # total_episodes is the count actually WRITTEN to the dataset (== input when
        # nothing is refused). Refusals are listed separately so the gate is auditable.
        "total_episodes": len(episode_meta),
        # Include episodes the caller pre-gated and removed before delegating here, so the
        # input count reflects everything that was offered for export, not just what reached
        # this function (otherwise an all-non-finite episode would vanish from the count).
        "total_episodes_input": len(episodes) + extra_input_count,
        "rejected_episodes": rejected_episodes,
        "total_frames": len(rows),
        # fps is DERIVED from sample timestamps, never hard-coded: real episodes
        # may run at any rate, and a wrong fps misaligns this export against the
        # CAN/video/tactile streams downstream.
        "fps": fps,
        "time_base": {
            "timestamp_field": "timestamp_ns",
            "clock_source": "monotonic_host",
            "time_sync_method": "single_monotonic_host_clock",
            "measured_jitter_ns": jitter_ns,
        },
        "features": {
            "observation.state": {"dtype": "float64", "shape": [n_joints_detected]},
            "observation.velocity": {"dtype": "float64", "shape": [n_joints_detected]},
            "observation.current": {"dtype": "float64", "shape": [n_joints_detected]},
            "observation.torque": {"dtype": "float64", "shape": [n_joints_detected]},
        },
        "data_path": f"data/{chunk_name}",
        "schema_version": LEROBOT_DATASET_VERSION,
    }
    (meta_dir / "info.json").write_text(json.dumps(info, indent=2) + "\n")

    # Write meta/episodes.jsonl
    with (meta_dir / "episodes.jsonl").open("w") as f:
        for em in episode_meta:
            f.write(json.dumps(em) + "\n")

    # Write meta/tasks.jsonl
    with (meta_dir / "tasks.jsonl").open("w") as f:
        for label, idx in sorted(task_set.items(), key=lambda x: x[1]):
            f.write(json.dumps({"task_index": idx, "task_label": label}) + "\n")

    # Write meta/timing.json (C5): the per-episode sync-audit sidecar. Only episodes
    # actually written to the dataset appear; omissions are logged loudly (shared helper —
    # the same flow as the parquet exporter, so behavior cannot drift between formats).
    # Unknown ids were already rejected fail-fast before anything touched disk.
    if timing_meta is not None:
        write_selected_timing_sidecar(
            meta_dir / _TIMING_SIDECAR,
            timing_meta,
            written_ids={str(em["episode_id"]) for em in episode_meta},
            known_ids={ep.episode_id for ep in episodes}
            | {str(r["episode_id"]) for r in rejected_episodes},
            log=log,
            sidecar_label=f"meta/{_TIMING_SIDECAR}",
        )

    return root


def load_lerobot_timing_meta(
    path: str | os.PathLike[str],
) -> dict[str, TimingMeta] | None:
    """Read ``meta/timing.json`` back as ``episode_id -> TimingMeta``; ``None`` if legacy.

    ``None`` means the dataset was written without timing metadata (pre-C5, or
    ``timing_meta`` not supplied) — such datasets MUST keep loading unchanged, so
    absence is not an error. A present-but-corrupt sidecar raises (see
    ``timing.export_meta.read_timing_sidecar``).
    """
    return read_timing_sidecar(Path(path) / "meta" / _TIMING_SIDECAR)


def load_lerobot(path: str | os.PathLike[str]) -> list[Episode]:
    """Load a lerobot-format dataset back into Episode objects.

    Reconstructs PVTSample per joint per frame from the flattened observation columns.
    """
    root = Path(path)
    data_dir = root / "data"

    parquet_files = sorted(data_dir.glob("*.parquet"))
    if not parquet_files:
        return []

    tables = [pq.read_table(f) for f in parquet_files]
    table = pa.concat_tables(tables)
    rows = table.to_pylist()

    # Group rows by episode_index
    ep_map: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        ep_map.setdefault(r["episode_index"], []).append(r)

    episodes: list[Episode] = []
    for ep_idx in sorted(ep_map):
        ep_rows = sorted(ep_map[ep_idx], key=lambda r: r["frame_index"])
        eid = ep_rows[0]["episode_id"]
        task = ep_rows[0]["task_label"]
        episode = Episode(episode_id=eid, task_label=task)

        for r in ep_rows:
            states = r["observation.state"]
            velocities = r["observation.velocity"]
            currents = r["observation.current"]
            torques = r["observation.torque"]
            # Migration: v2 persists the real chain_index per frame. v1 files lack
            # the column, so fall back to positional order (the v1 behaviour) to
            # keep old datasets loadable.
            chain_indices = r.get("observation.chain_index")
            if chain_indices is None:
                chain_indices = list(range(len(states)))
            cam_id = r.get("camera_frame_id")
            tactile = r.get("tactile_event")
            for idx, chain_index in enumerate(chain_indices):
                episode.add(PVTSample(
                    timestamp_ns=r["timestamp_ns"],
                    episode_id=eid,
                    chain_index=chain_index,
                    joint_angle=states[idx],
                    joint_velocity=velocities[idx],
                    motor_current=currents[idx],
                    estimated_torque=torques[idx],
                    camera_frame_id=cam_id,
                    tactile_event=tactile,
                    task_label=task,
                ))
        episodes.append(episode)
    return episodes
