"""``Exporter`` — the frozen contract every ML-ready dataset writer plugs into.

An exporter turns a list of in-memory :class:`~inhabit_can.pvt.Episode` objects into an
on-disk dataset (a directory) and reads that dataset back into episodes. Core code never
branches on the concrete format; it asks the registry for an ``Exporter`` by name (``lerobot``,
``parquet``, later ``hdf5``) and uses this two-method surface.

The round-trip contract (why this is the whole point)
-----------------------------------------------------
A dataset format is only trustworthy if it round-trips: ``load(export(episodes, out))`` must
reproduce the episodes the training stack will read, field-for-field within tolerance. Every
registered exporter is exercised by the same round-trip conformance test, so a format that
silently loses a column, a dtype, or a chain identifier fails CI rather than poisoning a model.

The contract deliberately does NOT promise byte-identical *input* preservation, because the
data-integrity gate (see below) may legitimately *drop* corrupt frames or *refuse* a corrupt
episode. What it promises is: whatever an exporter writes, its own ``load`` reads back equal.

Data-integrity gate (preserved from the #25 corruption-gate work)
-----------------------------------------------------------------
The PVT dataset is the business; a single corrupt frame poisons the numerical timeline every
downstream model trains on. So an exporter MUST NOT widen the door that the gated recorder
closed. Concretely, on the export path:

* a corrupt-checksum or non-finite (NaN/inf) frame must be dropped, and
* a non-monotonic or hole-ridden (dropout) episode must be refused (written nowhere),

reusing the ONE shared policy (``logger.recorder.frame_reject_reason`` + the jitter gate) so
the exporters and the recorder can never drift on what "corrupt" means. The ``lerobot`` exporter
inherits this through ``export_lerobot``; the ``parquet`` exporter applies it explicitly. Both
are proven by a regression test that a corrupt frame is still rejected.

Contract surface
----------------
``export(episodes, out_path) -> Path``  — write all episodes under ``out_path`` (a directory),
    applying the integrity gate; return the dataset root.
``load(path) -> list[Episode]``         — read a dataset written by this exporter back into
    episodes (migration-aware where the format versions its layout).

Versioning
----------
``EXPORTER_ABC_VERSION`` versions THIS contract (the two-method shape + the gate guarantee),
NOT any on-disk layout. Each concrete exporter additionally exposes its own ``version`` (the
format/layout version) so a dataset's provenance is reproducible. Bump ``EXPORTER_ABC_VERSION``
only with a ``docs/decisions`` record, like any other frozen contract.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from inhabit_can.pvt import Episode

# Version of the Exporter ABC (the method contract + the round-trip/integrity guarantees),
# distinct from each concrete exporter's on-disk layout version and from the frozen
# PVT_SCHEMA_VERSION of PVTSample.
EXPORTER_ABC_VERSION = 1

__all__ = ["EXPORTER_ABC_VERSION", "Exporter"]


class Exporter(ABC):
    """Abstract base for an ML-ready dataset exporter (one per output format).

    Subclasses implement :meth:`export` and :meth:`load` such that
    ``load(export(eps, out))`` reproduces ``eps`` (modulo frames/episodes the integrity
    gate legitimately drops/refuses) — the round-trip contract the conformance suite
    enforces on every registered exporter.
    """

    #: Human-readable format name (also the registry key). Subclasses set this.
    name: str = "exporter"
    #: On-disk layout version for this exporter, distinct from EXPORTER_ABC_VERSION and
    #: from the frozen PVT_SCHEMA_VERSION. Bump with a load-time migration.
    version: int = 0

    @abstractmethod
    def export(
        self, episodes: list[Episode], out_path: str | os.PathLike[str]
    ) -> os.PathLike[str]:
        """Write ``episodes`` to a dataset directory at ``out_path``; return its root.

        MUST apply the shared data-integrity gate (drop corrupt/non-finite frames; refuse
        non-monotonic/dropout episodes) so the export path never widens the recorder's gate.
        """

    @abstractmethod
    def load(self, path: str | os.PathLike[str]) -> list[Episode]:
        """Read a dataset previously written by this exporter back into episodes."""
