"""LeRobot :class:`Exporter` — a thin adapter over the existing lerobot module.

This wraps ``export.lerobot.export_lerobot`` / ``load_lerobot`` behind the :class:`Exporter`
contract. It reimplements NOTHING of the format: all the lerobot v3 dataset layout, the
per-frame grouping, the derived-fps timing metadata, and the per-episode time-quality gate
(refuse non-monotonic / dropout episodes, flag over-budget ones) live in ``lerobot.py`` and
are inherited unchanged.

One thing the standalone ``export_lerobot`` does NOT do is reject a non-finite (NaN/inf) joint
value per frame — in the real pipeline NaN is already dropped upstream by the recorder / CLI
canlog loader (``frame_reject_reason``) before episodes reach ``export_lerobot``. To make the
ABC-level export path enforce the #25 finiteness guard uniformly for ALL inputs (so a caller
that hands an exporter a raw, un-pre-filtered episode cannot poison the dataset with a NaN),
this adapter runs the SAME shared per-frame finiteness gate (``export._gate``) the parquet
exporter uses before delegating. The standalone function stays untouched for its existing
callers; this strengthens the plugin path without regressing anything.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from inhabit_can.pvt import Episode
from logger.jitter import JitterBudget
from timing.export_meta import TimingMeta

from ._gate import frame_is_finite
from .base import Exporter
from .lerobot import LEROBOT_DATASET_VERSION, export_lerobot, load_lerobot

log = logging.getLogger("inhabit.export")

__all__ = ["LeRobotExporter"]


def _drop_nonfinite(
    episodes: list[Episode],
) -> tuple[list[Episode], list[dict[str, Any]]]:
    """Strip non-finite frames; return (cleaned_episodes, refused_records).

    Per-episode timeline refusal (backwards/dropout) is left to ``export_lerobot``; this only
    strips NaN/inf frames so they never reach the lerobot parquet, exactly as the parquet
    exporter does via ``export._gate``.

    An episode that is EMPTY after the strip (every frame was non-finite) is NOT silently
    dropped: it is returned as a refusal record so ``export_lerobot`` can fold it into the
    dataset audit trail (``meta/info.json -> rejected_episodes``) and the input count. Losing
    it from both, as the previous version did, made an all-corrupt episode vanish without a
    trace — exactly what the #25 gate exists to prevent.
    """
    cleaned: list[Episode] = []
    refused: list[dict[str, Any]] = []
    for ep in episodes:
        kept = Episode(episode_id=ep.episode_id, task_label=ep.task_label)
        for s in ep.samples:
            if frame_is_finite(s):
                kept.add(s)
        if kept.samples:
            cleaned.append(kept)
        else:
            log.warning(
                "REFUSED episode=%s from lerobot export: %s",
                ep.episode_id,
                "no finite frames remain after the integrity gate",
            )
            refused.append({
                "episode_id": ep.episode_id,
                "reasons": ["no finite frames remain after the integrity gate"],
            })
    return cleaned, refused


class LeRobotExporter(Exporter):
    """Export episodes to a lerobot-compatible dataset directory.

    The per-episode time-quality gate (refuse non-monotonic / dropout; flag over-budget) is
    enforced inside ``export_lerobot``; the per-frame finiteness gate is applied here. Neither
    is weakened.
    """

    name = "lerobot"
    version = LEROBOT_DATASET_VERSION

    def __init__(
        self,
        *,
        budget: JitterBudget | None = None,
        timing_meta: Mapping[str, TimingMeta] | None = None,
    ) -> None:
        # ``None`` lets export_lerobot apply its documented default budget.
        self._budget = budget
        # C5: optional per-episode sync-audit metadata (episode_id -> TimingMeta), written
        # to meta/timing.json by export_lerobot. ``None`` (default) keeps the pre-C5
        # layout byte-for-byte, so the registry/conformance path is unchanged.
        self._timing_meta = timing_meta

    def export(
        self, episodes: list[Episode], out_path: str | os.PathLike[str]
    ) -> Path:
        """Strip non-finite frames, then delegate to ``export_lerobot`` (timeline gate included).

        Episodes emptied by the finiteness strip are threaded into ``export_lerobot``'s audit
        trail (and input count) as refusals rather than silently discarded — which also keeps
        their ids KNOWN to the timing-sidecar gate (timing meta for a refused episode is
        omitted with a warning, never written and never a crash).
        """
        cleaned, refused = _drop_nonfinite(episodes)
        return export_lerobot(
            cleaned,
            out_path,
            budget=self._budget,
            extra_rejected=refused,
            extra_input_count=len(refused),
            timing_meta=self._timing_meta,
        )

    def load(self, path: str | os.PathLike[str]) -> list[Episode]:
        """Delegate to ``load_lerobot`` (migration-aware v1->v3 layout reader)."""
        return load_lerobot(path)
