"""Inhabit episode logger — time-sync, jitter gating, ML-ready PVT export.

Public surface:
- ``EpisodeRecorder``: open an episode, ingest decoded joint states, measure jitter,
  quarantine bad/half-written episodes, write a parquet file that round-trips.
- ``JitterStats`` / ``JitterBudget``: monotonic inter-sample timing measurement + gate.
- ``write_episode`` / ``read_episode``: low-level parquet I/O (used by the recorder).
- ``EpisodeSink`` + ``make_episode_sink`` / ``list_episode_sinks``: the plugin seam for
  episode destinations (``parquet-atomic`` wraps the recorder, ``inmem`` for tests/sim).
"""
from __future__ import annotations

from .jitter import JitterBudget, JitterStats, compute_jitter
from .parquet_io import read_episode, write_episode
from .recorder import (
    EpisodeRecorder,
    QuarantineError,
    RecorderResult,
    frame_reject_reason,
)
from .sinks import (
    SINK_CONTRACT_VERSION,
    EpisodeSink,
    InMemorySink,
    ParquetAtomicSink,
    SinkResult,
    list_episode_sinks,
    make_episode_sink,
)

__all__ = [
    "SINK_CONTRACT_VERSION",
    "EpisodeRecorder",
    "EpisodeSink",
    "InMemorySink",
    "JitterBudget",
    "JitterStats",
    "ParquetAtomicSink",
    "QuarantineError",
    "RecorderResult",
    "SinkResult",
    "compute_jitter",
    "frame_reject_reason",
    "list_episode_sinks",
    "make_episode_sink",
    "read_episode",
    "write_episode",
]
