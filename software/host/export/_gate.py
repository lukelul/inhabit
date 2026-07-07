"""Shared data-integrity gate for the export path (the #25 corruption guards, in ONE place).

Both the ``lerobot`` and ``parquet`` exporters route every episode through this module before
writing, so neither can become a back door around the gate the recorder enforces at ingest,
and the two exporters can never drift on what "corrupt" means.

Two guards, matching the recorder's policy (``logger.recorder.frame_reject_reason``):

* **per-frame finiteness** — a NaN/inf joint value must NEVER reach parquet/lerobot; it would
  serialize straight into the dataset and silently break any model trained on it. The recorder
  rejects ``JointPodState.angle_rad`` at ingest; here we apply the same unconditional finiteness
  check to the derived float fields carried on an already-built :class:`PVTSample`. (Checksum
  validity is not carried on a built sample — it lives on ``JointPodState`` upstream — so the
  per-frame half that applies to an ``Episode`` is the finiteness guard.)
* **per-episode timeline** — a non-monotonic (backwards) or hole-ridden (dropout) timeline is
  unrecoverable corruption: exporting it would poison alignment. We refuse the whole episode,
  measuring on the UNIQUE instants in capture order (via :func:`instant_order`) with the same
  ``compute_jitter`` the recorder budgets against, so a legitimately interleaved multi-pod
  stream is not mistaken for going backwards.
"""
from __future__ import annotations

import math

from inhabit_can.pvt import Episode, PVTSample
from logger.jitter import JitterBudget, compute_jitter

__all__ = ["frame_is_finite", "gate_episode", "instant_order"]


def frame_is_finite(s: PVTSample) -> bool:
    """True iff every numeric field of the sample is finite (NaN/inf => reject).

    Mirrors the finiteness half of ``logger.recorder.frame_reject_reason``, applied to the
    derived float fields carried on a built :class:`PVTSample`.
    """
    return all(
        math.isfinite(v)
        for v in (s.joint_angle, s.joint_velocity, s.motor_current, s.estimated_torque)
    )


def instant_order(episode: Episode) -> list[int]:
    """Unique per-frame timestamps in first-appearance (capture) order.

    The monotonicity gate must run on UNIQUE instants in capture order — not the raw
    per-sample list — so a legitimately interleaved multi-pod stream (the same instants
    repeating once per pod) is not mistaken for going backwards. This is the same signal
    ``export.lerobot._instant_order`` gates on, kept identical here on purpose.
    """
    seen: set[int] = set()
    order: list[int] = []
    for s in episode.samples:
        if s.timestamp_ns not in seen:
            seen.add(s.timestamp_ns)
            order.append(s.timestamp_ns)
    return order


def gate_episode(
    episode: Episode, budget: JitterBudget
) -> tuple[Episode | None, list[str]]:
    """Apply the shared integrity gate; return (kept_episode_or_None, refuse_reasons).

    Drops non-finite frames per-frame, then refuses the whole episode if its timeline is
    backwards or holed. A refused episode (``None``) must be written nowhere; the caller is
    responsible for recording the reasons so the rejection is auditable.
    """
    kept = Episode(episode_id=episode.episode_id, task_label=episode.task_label)
    for s in episode.samples:
        if frame_is_finite(s):
            kept.add(s)

    if not kept.samples:
        return None, ["no finite frames remain after the integrity gate"]

    stats = compute_jitter(instant_order(kept), budget)
    reasons: list[str] = []
    if stats.backwards > 0:
        reasons.append(f"non-monotonic timeline: {stats.backwards} backward instant(s)")
    if stats.dropouts > 0:
        reasons.append(f"{stats.dropouts} dropout(s): gap > {budget.max_gap_factor}x period")
    if reasons:
        return None, reasons
    return kept, []
