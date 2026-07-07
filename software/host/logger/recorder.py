"""EpisodeRecorder — open an episode, ingest decoded joint states, measure monotonic
jitter, and either EXPORT a round-trippable parquet file or QUARANTINE the episode.

Lifecycle (atomic, append-only)
-------------------------------
    rec = EpisodeRecorder(episode_id="demo_000421", out_dir=..., task_label="insert")
    for state in stream:            # JointPodState (or dict) from Track 2
        rec.ingest(state)
    result = rec.finalize()         # measures jitter, gates, writes OR quarantines

- During ingest we only append to an in-memory Episode (append-only).
- ``finalize`` measures jitter ONCE over the full episode, checks the budget, and:
    * PASS  -> atomic write to ``<out_dir>/<episode_id>.parquet`` (via parquet_io,
              which writes ``.part`` then renames, so it is crash-safe too).
    * FAIL  -> NOTHING is written to the dataset dir; the episode is recorded as
              quarantined (a sidecar JSON in ``<out_dir>/quarantine/`` documents why),
              and ``RecorderResult.exported`` is False.
- A half-written episode (process crashes before/at finalize) leaves at most a
  ``.parquet.part`` temp from parquet_io — never a readable episode. The dataset
  only ever contains complete, in-budget episodes.

Jitter is always MEASURED and LOGGED (Python ``logging``) regardless of pass/fail,
so timing quality is observable even for accepted episodes.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from inhabit_can.pvt import (
    Episode,
    JointPodState,
    PVTSample,
    sample_from_pod_state,
)

from .jitter import JitterBudget, JitterStats, compute_jitter
from .parquet_io import write_episode

log = logging.getLogger("inhabit.logger")

# Bump this when the contact-event detector changes so labels stay reproducible.
# Proprioceptive-only iteration: no contact detection runs yet.
CONTACT_DETECTOR_VERSION = "none-0"


class QuarantineError(RuntimeError):
    """Raised by ``finalize(strict=True)`` when an episode fails the budget."""

    def __init__(self, episode_id: str, reasons: list[str]) -> None:
        self.episode_id = episode_id
        self.reasons = reasons
        super().__init__(f"episode {episode_id!r} quarantined: {'; '.join(reasons)}")


@dataclass
class RecorderResult:
    """Outcome of ``finalize``."""

    episode_id: str
    exported: bool
    stats: JitterStats
    reasons: list[str]
    path: Path | None  # the parquet path if exported, else the quarantine sidecar


def _coerce(state: JointPodState | Mapping[str, Any]) -> JointPodState:
    """Accept either a JointPodState or a plain dict with the same fields.

    The ROS subscriber adapter (integration) will hand us real JointPodState
    objects; tests and other producers can hand dicts. Either way we normalize to
    the typed contract before mapping.
    """
    if isinstance(state, JointPodState):
        return state
    return JointPodState(
        node_id=int(state["node_id"]),
        chain_index=int(state["chain_index"]),
        angle_raw_adc=int(state["angle_raw_adc"]),
        angle_millideg=int(state["angle_millideg"]),
        angle_rad=float(state["angle_rad"]),
        status_flags=int(state["status_flags"]),
        checksum_valid=bool(state["checksum_valid"]),
        schema_version=int(state["schema_version"]),
        header_stamp_ns=int(state.get("header_stamp_ns", state.get("header_stamp", 0))),
    )


def frame_reject_reason(state: JointPodState) -> str | None:
    """The single drop policy for a decoded frame. Returns a reason, or None to keep.

    Failure modes guarded (and why a bad frame must never reach parquet/lerobot):

    * **Corrupt checksum** (``checksum_valid is False``) — the bus flipped a bit. The
      decoded angle is garbage; admitting it poisons the numerical timeline. Drop it
      (the resulting time hole is honestly surfaced by the jitter dropout gate).
    * **Non-finite angle/velocity** (``NaN``/``inf``) — a railed ADC, a divide-by-zero
      in a future derivation, or a corrupted float would otherwise serialize straight
      into the dataset and silently break any model that trains on it. ``math.isfinite``
      rejects it at the door.

    This is the ONE place the policy lives so the gated recorder and the
    ``tools/dataset`` CLI exporter cannot drift apart (the CLI bug was that it carried
    ``checksum_valid`` but never checked it).
    """
    if not state.checksum_valid:
        return "checksum_invalid"
    if not math.isfinite(state.angle_rad):
        return f"non_finite_angle_rad:{state.angle_rad!r}"
    return None


class EpisodeRecorder:
    """Ingest decoded joint states into one atomic, jitter-gated PVT episode."""

    def __init__(
        self,
        episode_id: str,
        out_dir: str | os.PathLike[str],
        *,
        task_label: str | None = None,
        budget: JitterBudget | None = None,
        drop_invalid_checksum: bool = True,
    ) -> None:
        self.episode = Episode(episode_id=episode_id, task_label=task_label)
        self.out_dir = Path(out_dir)
        self.task_label = task_label
        self.budget = budget or JitterBudget()
        self.drop_invalid_checksum = drop_invalid_checksum
        self._dropped_checksum = 0
        self._dropped_nonfinite = 0
        self._finalized = False

    def ingest(self, state: JointPodState | Mapping[str, Any]) -> None:
        """Append one decoded joint state to the episode (append-only).

        Bad frames are dropped here so they never reach the timeline: corrupt
        checksum (when ``drop_invalid_checksum``) and non-finite (NaN/inf) joint
        values (always). See :func:`frame_reject_reason` for the shared policy.
        """
        if self._finalized:
            raise RuntimeError("recorder already finalized; open a new episode")
        s = _coerce(state)
        # Delegate the drop decision to the SHARED policy so the recorder and the
        # tools/dataset CLI can never disagree on what a bad frame is. The
        # ``drop_invalid_checksum`` opt-out (for raw captures) keeps corrupt frames
        # but the NaN/inf guard is unconditional — a garbage joint value must NEVER
        # reach parquet/lerobot regardless of that flag.
        reason = frame_reject_reason(s)
        if reason == "checksum_invalid":
            if self.drop_invalid_checksum:
                self._dropped_checksum += 1
                return
            # Corrupt frame kept (opt-out): the finiteness guard still applies, so a
            # bad-checksum frame whose angle is also NaN/inf does not slip through.
            if not math.isfinite(s.angle_rad):
                self._dropped_nonfinite += 1
                return
        elif reason is not None:  # non-finite joint value (always rejected)
            self._dropped_nonfinite += 1
            return
        sample = sample_from_pod_state(
            s, episode_id=self.episode.episode_id, task_label=self.task_label
        )
        self.episode.add(sample)

    def ingest_sample(self, sample: PVTSample) -> None:
        """Append an already-mapped :class:`PVTSample` (append-only), NaN/inf-gated.

        The ``ingest`` path above takes the upstream ``JointPodState`` (raw decoded CAN)
        and maps it to a ``PVTSample`` internally. This sibling path accepts a sample that
        is *already* a ``PVTSample`` — the aligned row that downstream sinks share — so the
        :class:`~logger.sinks.parquet_atomic.ParquetAtomicSink` can wrap the recorder
        without re-deriving the mapping or reaching into private state.

        Provenance is re-bound, not trusted. This recorder is the single authority for an
        episode's ``episode_id`` and ``task_label``: the :meth:`ingest` path *always* stamps
        them from the recorder (``sample_from_pod_state(..., episode_id=self.episode.episode_id,
        task_label=self.task_label)``), so the two entry points must not disagree. A caller
        that hands a sample carrying a foreign ``episode_id``/``task_label`` (a mis-wired
        stream, a reused row from another episode) would otherwise persist rows whose
        provenance does not match the file they land in — silent dataset corruption. We
        therefore re-stamp a copy of the sample (via :func:`dataclasses.replace`, never
        mutating the caller's object) to THIS recorder's metadata before appending, exactly
        mirroring how ``ingest`` stamps. The clean common case (already-matching metadata)
        appends the sample untouched, so there is no needless copy on the hot path.

        The unconditional NaN/inf gate still fires: a non-finite ``joint_angle`` (a railed
        ADC, a future divide-by-zero, a corrupted float) would otherwise serialize straight
        into parquet/lerobot and silently break any model that trains on it. We reject it at
        the door and count it, exactly as :meth:`ingest` does for ``angle_rad`` — the
        finiteness policy must not differ between the two entry points. (Checksum validity
        is a ``JointPodState`` concept that no longer exists once a sample is a
        ``PVTSample``; it is enforced upstream, on the raw-frame path.)
        """
        if self._finalized:
            raise RuntimeError("recorder already finalized; open a new episode")
        if not math.isfinite(sample.joint_angle):
            self._dropped_nonfinite += 1
            return
        if sample.episode_id != self.episode.episode_id or sample.task_label != self.task_label:
            # Re-bind foreign provenance to this recorder (the authority), mirroring how
            # ``ingest`` stamps every sample. Copy, don't mutate the caller's object.
            sample = replace(
                sample, episode_id=self.episode.episode_id, task_label=self.task_label
            )
        self.episode.add(sample)

    @property
    def drop_counts(self) -> dict[str, int]:
        """How many frames were rejected, by reason — read-only provenance.

        ``dropped_checksum`` (corrupt-checksum frames) and ``dropped_nonfinite`` (NaN/inf
        joint values) are the data-integrity gate's tally. The recorder already stamps
        these into the parquet footer and the quarantine sidecar; this view lets a wrapper
        (e.g. the parquet sink) surface them without re-reading the file or touching
        private state.
        """
        return {
            "dropped_checksum": self._dropped_checksum,
            "dropped_nonfinite": self._dropped_nonfinite,
        }

    def measure(self) -> JitterStats:
        ts = [s.timestamp_ns for s in self.episode.samples]
        return compute_jitter(ts, self.budget)

    def finalize(self, *, strict: bool = False) -> RecorderResult:
        """Measure jitter, gate on budget, and export or quarantine.

        ``strict=True`` raises :class:`QuarantineError` on failure instead of
        returning a non-exported result (useful for batch jobs that should fail loud).
        """
        if self._finalized:
            raise RuntimeError("recorder already finalized")
        self._finalized = True

        stats = self.measure()
        ok, reasons = self.budget.check(stats)

        log.info(
            "episode=%s samples=%d period_ns=%d jitter_p99_ns=%d jitter_max_ns=%d "
            "dropouts=%d backwards=%d dropped_checksum=%d dropped_nonfinite=%d -> %s",
            self.episode.episode_id,
            stats.n_samples,
            stats.period_ns,
            stats.jitter_p99_ns,
            stats.jitter_max_ns,
            stats.dropouts,
            stats.backwards,
            self._dropped_checksum,
            self._dropped_nonfinite,
            "EXPORT" if ok else "QUARANTINE",
        )

        if not ok:
            path = self._quarantine(stats, reasons)
            if strict:
                raise QuarantineError(self.episode.episode_id, reasons)
            return RecorderResult(
                episode_id=self.episode.episode_id,
                exported=False,
                stats=stats,
                reasons=reasons,
                path=path,
            )

        metadata = {
            "jitter_stats": stats.as_dict(),
            "jitter_budget": {
                "max_jitter_p99_ns": self.budget.max_jitter_p99_ns,
                "max_gap_factor": self.budget.max_gap_factor,
                "min_samples": self.budget.min_samples,
            },
            "contact_detector_version": CONTACT_DETECTOR_VERSION,
            "dropped_checksum": self._dropped_checksum,
            "dropped_nonfinite": self._dropped_nonfinite,
        }
        out = self.out_dir / f"{self.episode.episode_id}.parquet"
        path = write_episode(self.episode, out, metadata=metadata)
        return RecorderResult(
            episode_id=self.episode.episode_id,
            exported=True,
            stats=stats,
            reasons=[],
            path=path,
        )

    def _quarantine(self, stats: JitterStats, reasons: list[str]) -> Path:
        """Record WHY an episode was rejected. No episode parquet is written."""
        qdir = self.out_dir / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        sidecar = qdir / f"{self.episode.episode_id}.quarantine.json"
        payload = {
            "episode_id": self.episode.episode_id,
            "task_label": self.task_label,
            "n_samples": len(self.episode),
            "dropped_checksum": self._dropped_checksum,
            "dropped_nonfinite": self._dropped_nonfinite,
            "reasons": reasons,
            "jitter_stats": stats.as_dict(),
            "contact_detector_version": CONTACT_DETECTOR_VERSION,
        }
        tmp = sidecar.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, sidecar)
        log.warning("quarantined episode=%s reasons=%s", self.episode.episode_id, reasons)
        return sidecar
