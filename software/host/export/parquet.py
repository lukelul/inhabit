"""Parquet :class:`Exporter` — one self-describing parquet file per episode.

This wraps the existing low-level parquet I/O (``logger.parquet_io.write_episode`` /
``read_episode``) behind the :class:`Exporter` contract. It does NOT reimplement any
serialization: it lays out a *dataset directory* of per-episode parquet files (the same
atomic, footer-stamped format the gated ``EpisodeRecorder`` writes), so the dataset stays
append-only and each episode is atomic.

Why a directory of files (and not one combined file): the parquet format here is "one
episode per file" — that is what makes each episode atomic and append-only at the dataset
level (see ``logger/parquet_io.py``). The :class:`Exporter` contract is list-in / list-out,
so this exporter maps each KEPT episode to ``<out_dir>/ep_NNNNNN.parquet`` (a zero-padded
export index, NOT the caller-controlled ``episode_id`` — that would allow path traversal and
duplicate-id clobber) and reads every ``*.parquet`` back, giving the same write -> read ->
assert-equal round-trip as lerobot. The real ``episode_id`` rides inside the parquet footer.

Data-integrity gate (preserved from #25)
----------------------------------------
The export path must not be a back door around the recorder's corruption gate. Before
writing, each episode is passed through the ONE shared policy in :mod:`export._gate`:

* per-frame: non-finite (NaN/inf) samples are dropped (the finiteness half of the recorder's
  ``frame_reject_reason``, applied to a built :class:`Episode`), and
* per-episode: the jitter gate (``logger.jitter.compute_jitter`` + ``JitterBudget``) refuses
  an episode whose timeline goes backwards or has a dropout hole — the unrecoverable cases.

A refused episode is written nowhere (recorded in ``<out_dir>/rejected.json`` so the rejection
is auditable, never silent), mirroring ``export_lerobot``'s refuse/flag policy. The gate lives
in :mod:`export._gate` so this exporter and the lerobot exporter share one policy.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path

from inhabit_can.pvt import Episode
from logger.jitter import JitterBudget, compute_jitter
from logger.parquet_io import read_episode, write_episode
from logger.recorder import CONTACT_DETECTOR_VERSION
from timing.export_meta import (
    TimingMeta,
    read_timing_sidecar,
    select_episode_timing,
    write_selected_timing_sidecar,
)

from ._gate import gate_episode, instant_order
from .base import Exporter

log = logging.getLogger("inhabit.export")

# On-disk layout version for the parquet dataset directory written here. Distinct from the
# frozen PVT_SCHEMA_VERSION (the row schema, owned by parquet_io) and from EXPORTER_ABC_VERSION.
# The C5 timing sidecar (timing.json) is ADDITIVE and OPTIONAL — absent on legacy datasets
# and invisible to load()'s ``*.parquet`` glob — so it needs no layout-version bump/migration.
PARQUET_DATASET_VERSION = 1

_REJECTED_MANIFEST = "rejected.json"

# Sidecar filename for the per-episode timing metadata, next to the episode files (the
# same dataset-root channel rejected.json already uses). One canonical document shape
# for all exporters; see timing.export_meta.
_TIMING_SIDECAR = "timing.json"


class ParquetExporter(Exporter):
    """Export episodes as a directory of atomic, footer-stamped per-episode parquet files.

    Round-trips through ``logger.parquet_io`` (no serialization reimplemented) and enforces
    the shared #25 integrity gate before writing.
    """

    name = "parquet"
    version = PARQUET_DATASET_VERSION

    def __init__(
        self,
        *,
        budget: JitterBudget | None = None,
        timing_meta: Mapping[str, TimingMeta] | None = None,
    ) -> None:
        # Same default budget the recorder and lerobot exporter use, so the three gates agree.
        self._budget = budget or JitterBudget()
        # C5: optional per-episode sync-audit metadata (episode_id -> TimingMeta), written
        # to <out_path>/timing.json by export(). ``None`` (default) keeps the pre-C5 layout
        # byte-for-byte, so the registry/conformance path is unchanged.
        self._timing_meta = timing_meta

    def export(
        self, episodes: list[Episode], out_path: str | os.PathLike[str]
    ) -> Path:
        """Write each (gated) episode to ``<out_path>/ep_NNNNNN.parquet``.

        The on-disk basename is a zero-padded, monotonically increasing export index
        (counting only KEPT episodes), NOT the caller-controlled ``episode_id``. Using the id
        as a filename let ``../`` or absolute ids escape ``out_path`` and let two episodes that
        share an id silently clobber each other (so ``load`` returned fewer episodes than were
        exported). The real ``episode_id`` still travels inside the parquet footer
        (``META_EPISODE_ID``), so it round-trips via ``read_episode`` regardless of filename.
        Zero padding keeps ``load``'s ``sorted(glob('*.parquet'))`` order lexicographically
        equal to export order.

        Refused episodes (backwards/dropout timeline, or no finite frames) are skipped and
        listed in ``<out_path>/rejected.json`` so the rejection is auditable, never silent.
        Returns the dataset root directory.
        """
        # C5 fail-fast: reject unknown timing_meta ids BEFORE creating the directory or
        # writing any episode file — metadata about an episode never offered for export
        # must never leave a partially-written dataset behind when export() raises.
        if self._timing_meta is not None:
            select_episode_timing(
                self._timing_meta,
                written_ids=set(),
                known_ids={ep.episode_id for ep in episodes},
            )

        root = Path(out_path)
        root.mkdir(parents=True, exist_ok=True)

        rejected: list[dict[str, object]] = []
        written_ids: set[str] = set()
        written_idx = 0
        for episode in episodes:
            kept, reasons = gate_episode(episode, self._budget)
            if kept is None:
                log.warning(
                    "REFUSED episode=%s from parquet export: %s",
                    episode.episode_id,
                    "; ".join(reasons),
                )
                rejected.append({"episode_id": episode.episode_id, "reasons": reasons})
                continue
            # Persist the SAME signal the gate validated: jitter on the UNIQUE instants in
            # capture order (instant_order), not the raw per-sample list. For an interleaved
            # multi-pod episode the raw list repeats each instant once per pod, which would
            # reintroduce dt=0 duplicate intervals and stamp FALSE timing provenance
            # (backwards>0, period_ns=0) onto an episode the gate already cleared. lerobot
            # infers timing on deduped instants too; keep the two exporters consistent.
            stats = compute_jitter(instant_order(kept), self._budget)
            metadata = {
                "jitter_stats": stats.as_dict(),
                "jitter_budget": {
                    "max_jitter_p99_ns": self._budget.max_jitter_p99_ns,
                    "max_gap_factor": self._budget.max_gap_factor,
                    "min_samples": self._budget.min_samples,
                },
                # Time-sync provenance so a downstream consumer can align this export's
                # timestamp_ns against CAN/video/tactile on a common clock (matches the
                # lerobot info.json "time_base"). Time sync is first-class, never implicit.
                "time_base": {
                    "timestamp_field": "timestamp_ns",
                    "clock_source": "monotonic_host",
                    "time_sync_method": "single_monotonic_host_clock",
                    "measured_jitter_ns": stats.jitter_max_ns,
                },
                "contact_detector_version": CONTACT_DETECTOR_VERSION,
                "dataset_version": PARQUET_DATASET_VERSION,
            }
            write_episode(kept, root / f"ep_{written_idx:06d}.parquet", metadata=metadata)
            written_ids.add(kept.episode_id)
            written_idx += 1

        # Always write the manifest (even when empty) so a consumer can tell a clean export
        # from one where everything was refused.
        (root / _REJECTED_MANIFEST).write_text(
            json.dumps({"rejected_episodes": rejected}, indent=2) + "\n", encoding="utf-8"
        )

        # C5: the per-episode sync-audit sidecar, next to the episode files. Only episodes
        # actually written appear; omissions are logged loudly (shared helper — the same
        # flow as the lerobot exporter, so behavior cannot drift between formats). Unknown
        # ids were already rejected fail-fast at the top of export().
        if self._timing_meta is not None:
            write_selected_timing_sidecar(
                root / _TIMING_SIDECAR,
                self._timing_meta,
                written_ids=written_ids,
                known_ids={ep.episode_id for ep in episodes},
                log=log,
                sidecar_label=_TIMING_SIDECAR,
            )
        return root

    def load(self, path: str | os.PathLike[str]) -> list[Episode]:
        """Read every ``*.parquet`` under ``path`` back into episodes (sorted by filename).

        Sorting by filename gives a deterministic, stable episode order for the round-trip
        assertion. Each file round-trips through ``read_episode`` (migration-aware via
        ``PVTSample.from_row``).
        """
        root = Path(path)
        episodes: list[Episode] = []
        for pq_file in sorted(root.glob("*.parquet")):
            episode, _meta = read_episode(pq_file)
            episodes.append(episode)
        return episodes


def load_parquet_timing_meta(
    path: str | os.PathLike[str],
) -> dict[str, TimingMeta] | None:
    """Read ``timing.json`` back as ``episode_id -> TimingMeta``; ``None`` if legacy.

    ``None`` means the dataset was written without timing metadata (pre-C5, or
    ``timing_meta`` not supplied) — such datasets MUST keep loading unchanged, so
    absence is not an error. A present-but-corrupt sidecar raises (see
    ``timing.export_meta.read_timing_sidecar``).
    """
    return read_timing_sidecar(Path(path) / _TIMING_SIDECAR)


__all__ = ["PARQUET_DATASET_VERSION", "ParquetExporter", "load_parquet_timing_meta"]
