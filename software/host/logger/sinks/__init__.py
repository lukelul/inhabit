"""Episode sinks — where a recorded PVT episode goes, behind ``EpisodeSink``.

Use :func:`make_episode_sink(name, **kwargs)` to get a configured sink by name instead of
importing concrete classes. The factory is built on the generic
:class:`inhabit_core.Registry`, so sinks share one registration mechanism with every other
extension point (adapters, transports, event detectors, exporters, ...).

A sink is the *destination* for one atomic episode: ``open -> ingest* -> finalize``. The
durable ``parquet-atomic`` sink wraps the EXISTING
:class:`~logger.recorder.EpisodeRecorder`, so every PR #25 data-integrity gate
(corrupt-checksum / NaN-inf frame rejection, jitter/monotonic-clock quarantine, atomic
write) keeps firing through this seam — the sink layer adds a stable contract, it does not
re-implement or weaken the recorder. Contract + version live in :mod:`logger.sinks.interface`.

Built-in plugins:
  * ``parquet-atomic`` — durable, gated parquet write (or quarantine) via EpisodeRecorder.
  * ``inmem``          — accumulate samples in memory (tests / sim / in-process pipelines).
"""
from __future__ import annotations

from typing import Any

from inhabit_core import Registry

from .inmem import InMemorySink
from .interface import (
    SINK_CONTRACT_VERSION,
    EpisodeSink,
    SinkResult,
)
from .parquet_atomic import ParquetAtomicSink

# One registry for all episode sinks. ``entry_point_group`` lets third-party packages ship
# sinks (P-M marketplace) by advertising ``inhabit.episode_sinks`` entry points; it is
# discovered lazily and degrades silently when none are installed.
_REGISTRY: Registry[EpisodeSink] = Registry(
    "episode sink", entry_point_group="inhabit.episode_sinks"
)

# Zero-extra-dependency sinks: register the classes directly. (parquet-atomic pulls pyarrow
# only when it actually writes, via EpisodeRecorder -> parquet_io; constructing the sink
# does not.)
_REGISTRY.register("parquet-atomic", ParquetAtomicSink)
_REGISTRY.register("inmem", InMemorySink)


def make_episode_sink(name: str, **kwargs: Any) -> EpisodeSink:
    """Create an :class:`EpisodeSink` by name.

    Raises ``ValueError`` listing the available names if *name* is unknown.
    """
    return _REGISTRY.make(name, **kwargs)


def list_episode_sinks() -> list[str]:
    """Sorted names of all registered episode sinks (incl. lazy entry-point plugins)."""
    return _REGISTRY.names()


__all__ = [
    "SINK_CONTRACT_VERSION",
    "EpisodeSink",
    "InMemorySink",
    "ParquetAtomicSink",
    "SinkResult",
    "list_episode_sinks",
    "make_episode_sink",
]
