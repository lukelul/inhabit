"""parquet-atomic EpisodeSink — the durable, gated destination, wrapping EpisodeRecorder.

This sink is a thin adapter over the EXISTING :class:`~logger.recorder.EpisodeRecorder`.
It does NOT reimplement recording, jitter measurement, atomic writes, or quarantine — it
delegates every one of those to the recorder so the hard-won PR #25 data-integrity gates
keep firing through the new sink seam:

* **corrupt-checksum / NaN-inf frames** are dropped by the recorder's shared
  :func:`~logger.recorder.frame_reject_reason` policy (a garbage joint value must never
  reach parquet/lerobot and silently break a trainer);
* **inter-sample jitter** is measured against the ONE monotonic clock and an episode that
  blows the budget (p99 jitter, a dropout, a backwards/non-monotonic clock, too few
  samples) is **quarantined** — written nowhere in the dataset dir, only a sidecar saying
  why (a clock jump silently misaligns the PVT streams);
* the parquet write itself is **atomic** (``.part`` then ``os.replace``, fsync), so a
  crash never leaves a readable-but-incomplete episode.

Because all of that lives in the recorder, this file is deliberately tiny: open binds a
recorder, ingest forwards a sample through the recorder's NaN/inf-gated public
:meth:`~logger.recorder.EpisodeRecorder.ingest_sample`, and finalize delegates and
re-expresses the recorder's ``RecorderResult`` as the plugin-agnostic :class:`SinkResult`.

Input-type note
---------------
A sink, by contract, ingests :class:`~inhabit_can.pvt.PVTSample` (the aligned episode row
every sink shares). The recorder's other entry point ingests the upstream
``JointPodState`` (raw decoded CAN) where the *checksum* gate lives. Checksum validity is
a ``JointPodState`` concept that no longer exists once data is a ``PVTSample``; it is
enforced upstream, before a sample is built. This sink therefore upholds the NaN/inf and
jitter/monotonic gates on its ``PVTSample`` input, and the conformance/quarantine tests
also exercise the recorder's full checksum gate behind this sink via the JointPodState
path to prove no gate was weakened.
"""
from __future__ import annotations

import os
from pathlib import Path

from inhabit_can.pvt import PVTSample

from ..jitter import JitterBudget
from ..recorder import EpisodeRecorder
from .interface import EpisodeSink, SinkResult


class ParquetAtomicSink(EpisodeSink):
    """Durable PVT episode sink: atomic parquet write or quarantine, gates intact.

    Wraps one :class:`~logger.recorder.EpisodeRecorder` per episode. All gating,
    jitter measurement, atomic write, and quarantine behaviour is the recorder's; this
    class only adapts the lifecycle and the result shape.

    Parameters
    ----------
    out_dir:
        Dataset directory. Accepted episodes land at ``<out_dir>/<episode_id>.parquet``;
        rejected ones leave a ``<out_dir>/quarantine/<episode_id>.quarantine.json`` sidecar.
    episode_id:
        Stable id for this episode (one sink instance == one episode).
    task_label:
        Optional human task label stamped into every sample + the footer.
    budget:
        Optional :class:`~logger.jitter.JitterBudget`; defaults to the documented ~100 Hz
        budget. Recorded into the parquet footer so the dataset is reproducible.
    strict:
        When ``True``, :meth:`finalize` raises
        :class:`~logger.recorder.QuarantineError` on a budget failure instead of returning
        a rejected :class:`SinkResult` (for batch jobs that should fail loud).
    """

    name = "parquet-atomic"

    def __init__(
        self,
        *,
        out_dir: str | os.PathLike[str],
        episode_id: str,
        task_label: str | None = None,
        budget: JitterBudget | None = None,
        strict: bool = False,
    ) -> None:
        super().__init__()
        self._out_dir = out_dir
        self._episode_id = episode_id
        self._task_label = task_label
        self._budget = budget
        self._strict = strict
        self._recorder: EpisodeRecorder | None = None

    def open(self) -> None:
        """Bind a fresh recorder for this episode (fails loud on a double-open)."""
        self._enter_open()
        self._recorder = EpisodeRecorder(
            episode_id=self._episode_id,
            out_dir=self._out_dir,
            task_label=self._task_label,
            budget=self._budget,
        )

    def ingest(self, sample: PVTSample) -> None:
        """Append one PVT sample via the recorder's NaN/inf-gated public seam.

        Forwards to :meth:`~logger.recorder.EpisodeRecorder.ingest_sample`, which applies
        the unconditional non-finite (NaN/inf) joint-value gate before the sample reaches
        the timeline — a railed/garbage joint value would otherwise serialize into parquet
        and silently break any model that trains on the dataset. No gate is duplicated or
        weakened here; the recorder owns the policy.
        """
        self._check_ingestable()
        assert self._recorder is not None  # set in open(); guarded by _check_ingestable
        self._recorder.ingest_sample(sample)

    def finalize(self) -> SinkResult:
        """Delegate to the recorder (measure jitter, gate, atomic-write or quarantine)."""
        self._enter_finalize()
        assert self._recorder is not None
        rec_result = self._recorder.finalize(strict=self._strict)
        # Drop counts (corrupt-checksum / non-finite) are provenance the recorder already
        # stamps into the parquet footer and the quarantine sidecar; we surface the public
        # ``drop_counts`` view here so a caller can gate on it without re-reading the file.
        self._result = SinkResult(
            episode_id=rec_result.episode_id,
            accepted=rec_result.exported,
            n_samples=rec_result.stats.n_samples,
            reasons=tuple(rec_result.reasons),
            path=Path(rec_result.path) if rec_result.path is not None else None,
            detail={
                "jitter_stats": rec_result.stats.as_dict(),
                **self._recorder.drop_counts,
            },
        )
        return self._result
