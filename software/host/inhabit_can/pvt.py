"""PVT sample — proprioceptive + visual + tactile, time-aligned. Schema is versioned.

Time-sync is first-class: ONE monotonic host clock. Every sample carries
``timestamp_ns`` taken from that clock (``time.monotonic_ns()`` on the host that
ingests the stream). The recorder measures inter-sample jitter against that clock
and quarantines episodes whose jitter exceeds a documented budget (see
``host/logger/recorder.py``).

This module is the *schema* and nothing else: dataclasses + versioning +
migrations + the upstream input contract. All I/O (parquet/HDF5/lerobot) and the
jitter/quarantine logic live in ``host/logger`` so the schema stays dependency-free
and trivially testable.

Schema versioning
-----------------
``PVT_SCHEMA_VERSION`` is the *current* on-disk schema. Bump it ONLY together with
a migration registered in ``MIGRATIONS`` so old episodes keep round-tripping. Never
rename/remove a field silently — add a migration.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any

PVT_SCHEMA_VERSION = 1

# Ordered, typed column layout for the proprioceptive-only iteration. The writer
# uses this as the single source of truth for the parquet schema so the file is
# self-describing and round-trips exactly. Adding a column => new schema version +
# migration.
SAMPLE_COLUMNS: tuple[str, ...] = (
    "timestamp_ns",
    "episode_id",
    "chain_index",
    "joint_angle",
    "joint_velocity",
    "motor_current",
    "estimated_torque",
    "camera_frame_id",
    "tactile_event",
    "task_label",
    "schema_version",
)


@dataclass
class PVTSample:
    """One time-aligned PVT row. ``timestamp_ns`` is a monotonic host timestamp."""

    timestamp_ns: int
    episode_id: str
    chain_index: int
    joint_angle: float
    joint_velocity: float = 0.0
    motor_current: float = 0.0
    estimated_torque: float = 0.0
    camera_frame_id: str | None = None
    tactile_event: str | None = None  # contact_start | slip | impact | release | None
    task_label: str | None = None
    schema_version: int = PVT_SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def as_row(self) -> dict[str, Any]:
        """Column-name -> value, in :data:`SAMPLE_COLUMNS` order."""
        d = asdict(self)
        return {c: d[c] for c in SAMPLE_COLUMNS}

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PVTSample:
        """Rebuild from a column mapping (parquet read-back). Runs migrations."""
        row = migrate_row(dict(row))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in row.items() if k in known})


@dataclass
class JointPodState:
    """Upstream contract (Track 2). The thin ROS subscriber adapter fills this from
    a ``JointPodState`` message; here it is a plain dataclass so the writer is pure,
    testable Python with no ROS dependency.

    ``header_stamp_ns`` is the monotonic RX time (ns) — the ONE clock we sync on.
    """

    node_id: int
    chain_index: int
    angle_raw_adc: int
    angle_millideg: int
    angle_rad: float
    status_flags: int
    checksum_valid: bool
    schema_version: int
    header_stamp_ns: int  # monotonic RX timestamp (header.stamp)


def sample_from_pod_state(
    state: JointPodState,
    *,
    episode_id: str,
    task_label: str | None = None,
) -> PVTSample:
    """Map a decoded :class:`JointPodState` to a :class:`PVTSample`.

    Proprioceptive-only this iteration: ``joint_angle`` from ``angle_rad`` (radians),
    timestamp from the monotonic ``header_stamp_ns``. Velocity/current/torque/camera/
    tactile stay at defaults until those streams are wired in.
    """
    return PVTSample(
        timestamp_ns=state.header_stamp_ns,
        episode_id=episode_id,
        chain_index=state.chain_index,
        joint_angle=state.angle_rad,
        task_label=task_label,
    )


# --- migrations ------------------------------------------------------------
# Map a row at version N to version N+1. Keyed by the source version. The reader
# walks these in order until the row reaches PVT_SCHEMA_VERSION, so a v1 file still
# loads after we ship v2. Today the chain is empty (v1 is current); the machinery
# is in place so a future bump cannot silently break old data.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a single row to :data:`PVT_SCHEMA_VERSION` via :data:`MIGRATIONS`."""
    v = int(row.get("schema_version", PVT_SCHEMA_VERSION))
    while v < PVT_SCHEMA_VERSION:
        if v not in MIGRATIONS:
            raise ValueError(f"no migration from schema v{v} to v{v + 1}")
        row = MIGRATIONS[v](row)
        v = int(row["schema_version"])
    if v > PVT_SCHEMA_VERSION:
        raise ValueError(
            f"episode schema v{v} is newer than reader v{PVT_SCHEMA_VERSION}; upgrade the reader"
        )
    return row


@dataclass
class Episode:
    """Atomic, append-only collection of samples for one demonstration.

    A half-written episode is quarantined, not exported. Writing / jitter checks /
    quarantine live in ``host.logger.recorder.EpisodeRecorder`` — this stays a plain
    container so it is cheap to construct and assert against in tests.
    """

    episode_id: str
    task_label: str | None = None
    samples: list[PVTSample] = field(default_factory=list)

    def add(self, s: PVTSample) -> None:
        self.samples.append(s)

    def __len__(self) -> int:
        return len(self.samples)
