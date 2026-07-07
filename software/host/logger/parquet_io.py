"""Parquet read/write for PVT episodes — the ML-ready export format.

Why parquet (primary format)
----------------------------
- Columnar + typed schema embedded in the file => self-describing and round-trips
  exactly (write -> read -> assert-equal), unlike ad-hoc CSV which loses dtypes and
  null/None distinctions.
- Native, zero-glue ingestion by the training stack: HuggingFace ``datasets`` and
  ``lerobot`` both read parquet directly; pandas/polars/Arrow/Spark all do too.
- Per-file key/value metadata: we stamp episode_id, schema_version, jitter stats,
  the jitter budget, and the contact-detector version into the footer so labels and
  timing provenance travel WITH the data and stay reproducible.
- One file per episode keeps episodes atomic and append-only at the dataset level:
  write to a ``.part`` temp, fsync the data, atomic rename, then fsync the parent
  dir on POSIX so the rename itself is durable. A crashed write leaves at most the
  ``.part`` (quarantined), never a half-valid episode in the dataset.

HDF5 is a fine secondary target for raw high-rate sensor blobs (audio/video features)
later; parquet is the right primary for the tabular PVT rows here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from inhabit_can.pvt import (
    PVT_SCHEMA_VERSION,
    SAMPLE_COLUMNS,
    Episode,
    PVTSample,
)

# Footer metadata keys (bytes in parquet; we encode/decode as utf-8 JSON).
META_EPISODE_ID = b"inhabit.episode_id"
META_SCHEMA_VERSION = b"inhabit.schema_version"
META_TASK_LABEL = b"inhabit.task_label"
META_JITTER_STATS = b"inhabit.jitter_stats"
META_JITTER_BUDGET = b"inhabit.jitter_budget"
META_DETECTOR_VERSION = b"inhabit.contact_detector_version"

# Explicit Arrow schema mirroring SAMPLE_COLUMNS. Pinned dtypes => exact round-trip.
_ARROW_SCHEMA = pa.schema(
    [
        ("timestamp_ns", pa.int64()),
        ("episode_id", pa.string()),
        ("chain_index", pa.int32()),
        ("joint_angle", pa.float64()),
        ("joint_velocity", pa.float64()),
        ("motor_current", pa.float64()),
        ("estimated_torque", pa.float64()),
        ("camera_frame_id", pa.string()),
        ("tactile_event", pa.string()),
        ("task_label", pa.string()),
        ("schema_version", pa.int32()),
    ]
)
assert tuple(_ARROW_SCHEMA.names) == SAMPLE_COLUMNS  # schema/columns must agree


def _episode_table(episode: Episode) -> pa.Table:
    cols: dict[str, list[Any]] = {c: [] for c in SAMPLE_COLUMNS}
    for s in episode.samples:
        for c, v in s.as_row().items():
            cols[c].append(v)
    arrays = [pa.array(cols[name], type=_ARROW_SCHEMA.field(name).type) for name in SAMPLE_COLUMNS]
    return pa.table(arrays, schema=_ARROW_SCHEMA)


def write_episode(
    episode: Episode,
    path: str | os.PathLike[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Atomically write ``episode`` to a parquet file at ``path``.

    Writes ``<path>.part`` then ``os.replace`` to the final name so a crash mid-write
    never produces a readable-but-incomplete episode. ``metadata`` (jitter stats,
    budget, detector version, ...) is merged into the parquet footer.

    Returns the final path. NOTE: callers (the recorder) are responsible for the
    quarantine decision; this function just writes durably and atomically.
    """
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_suffix(final.suffix + ".part")

    table = _episode_table(episode)

    footer: dict[bytes, bytes] = {
        META_EPISODE_ID: episode.episode_id.encode("utf-8"),
        META_SCHEMA_VERSION: str(PVT_SCHEMA_VERSION).encode("utf-8"),
        META_TASK_LABEL: json.dumps(episode.task_label).encode("utf-8"),
    }
    for k, v in (metadata or {}).items():
        footer[f"inhabit.{k}".encode()] = json.dumps(v, sort_keys=True).encode("utf-8")

    table = table.replace_schema_metadata(
        {**(table.schema.metadata or {}), **footer}
    )

    with pq.ParquetWriter(part, table.schema) as w:
        w.write_table(table)

    # durability: fsync the data, then atomically rename into place. Open for
    # read+write (not O_RDONLY) so os.fsync works on Windows, which rejects fsync
    # on a read-only handle (EBADF).
    fd = os.open(part, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(part, final)

    # On POSIX, fsync the parent dir so the rename (the dir entry) is durable too.
    # Windows has no dir fd / O_DIRECTORY; the rename is atomic there regardless.
    if hasattr(os, "O_DIRECTORY"):
        dir_fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    return final


def read_episode(path: str | os.PathLike[str]) -> tuple[Episode, dict[str, Any]]:
    """Read a parquet episode back. Returns (Episode, footer_metadata).

    Rows are migrated to the current schema via ``PVTSample.from_row`` so old-version
    files keep loading. Footer values written as JSON are decoded back to objects.
    """
    table = pq.read_table(path)
    rows = table.to_pylist()
    samples = [PVTSample.from_row(r) for r in rows]

    raw_meta = table.schema.metadata or {}
    episode_id = raw_meta.get(META_EPISODE_ID, b"").decode("utf-8")
    raw_task = raw_meta.get(META_TASK_LABEL)
    task_label = json.loads(raw_task.decode("utf-8")) if raw_task is not None else None
    # fall back to row-level episode id if footer somehow missing
    if not episode_id and samples:
        episode_id = samples[0].episode_id

    episode = Episode(episode_id=episode_id, task_label=task_label, samples=samples)

    meta: dict[str, Any] = {}
    for k, v in raw_meta.items():
        key = k.decode("utf-8")
        if not key.startswith("inhabit."):
            continue
        short = key[len("inhabit.") :]
        text = v.decode("utf-8")
        if short in {"episode_id", "schema_version"}:
            meta[short] = text
            continue
        try:
            meta[short] = json.loads(text)
        except json.JSONDecodeError:
            meta[short] = text
    return episode, meta
