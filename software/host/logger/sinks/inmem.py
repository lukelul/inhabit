"""inmem EpisodeSink — accumulate samples in RAM for tests, sim, and pipeline glue.

The simplest possible sink: it holds the ingested :class:`~inhabit_can.pvt.PVTSample`
rows in a list and hands them back on finalize as an in-memory
:class:`~inhabit_can.pvt.Episode`. No disk, no parquet, no jitter gate — its whole job is
to be a fast, dependency-free destination for tests, the simulation engine (P-B), and
in-process pipeline stages that want the episode in memory rather than on disk.

What it still guards
--------------------
Even an in-memory sink must not admit a **non-finite (NaN/inf) joint value**: a sim bug or
a bad synthetic trajectory that produces a NaN would otherwise flow downstream into an
exporter or a trainer and corrupt it just as surely as a disk write would. So the same
NaN/inf gate the durable path enforces fires here too — the gate is a property of the data
contract, not of the storage backend. (Jitter/monotonic-clock gating is intentionally
*not* applied here: this sink keeps everything for inspection, including deliberately
malformed timing a test wants to assert on. Use ``parquet-atomic`` for the gated path.)

Result
------
:meth:`finalize` always reports ``accepted=True`` (an in-memory collection cannot
half-write) with ``n_samples`` = the number of *kept* samples, and stashes the assembled
:class:`Episode` and the kept-sample list on the sink for tests to read back.
"""
from __future__ import annotations

import math

from inhabit_can.pvt import Episode, PVTSample

from .interface import EpisodeSink, SinkResult


class InMemorySink(EpisodeSink):
    """Collect PVT samples in memory; finalize hands back an :class:`Episode`.

    Parameters
    ----------
    episode_id:
        Id stamped on the assembled :class:`Episode` and the :class:`SinkResult`.
    task_label:
        Optional task label carried on the assembled :class:`Episode`.
    """

    name = "inmem"

    def __init__(self, *, episode_id: str = "inmem", task_label: str | None = None) -> None:
        super().__init__()
        self._episode_id = episode_id
        self._task_label = task_label
        self._samples: list[PVTSample] = []
        self._dropped_nonfinite = 0
        self._episode: Episode | None = None

    def open(self) -> None:
        """Reset the in-memory buffer for a fresh episode (fails loud on double-open)."""
        self._enter_open()
        self._samples = []
        self._dropped_nonfinite = 0
        self._episode = None

    def ingest(self, sample: PVTSample) -> None:
        """Append one sample, dropping a non-finite joint value (the one universal gate).

        A NaN/inf ``joint_angle`` is rejected even in memory: it would otherwise poison any
        downstream exporter or trainer that reads this buffer. Everything else is kept
        verbatim so a test/sim can inspect the exact stream it produced.
        """
        self._check_ingestable()
        if not math.isfinite(sample.joint_angle):
            self._dropped_nonfinite += 1
            return
        self._samples.append(sample)

    def finalize(self) -> SinkResult:
        """Assemble the kept samples into an :class:`Episode` and report acceptance."""
        self._enter_finalize()
        self._episode = Episode(
            episode_id=self._episode_id,
            task_label=self._task_label,
            samples=list(self._samples),
        )
        self._result = SinkResult(
            episode_id=self._episode_id,
            accepted=True,
            n_samples=len(self._samples),
            reasons=(),
            path=None,
            detail={"dropped_nonfinite": self._dropped_nonfinite},
        )
        return self._result

    # -- in-memory read-back (test/sim convenience; not part of the ABC) ----------------

    @property
    def samples(self) -> list[PVTSample]:
        """The kept samples (a copy, so a caller cannot mutate the sink's buffer)."""
        return list(self._samples)

    @property
    def episode(self) -> Episode | None:
        """The assembled :class:`Episode` after :meth:`finalize`, else ``None``."""
        return self._episode
