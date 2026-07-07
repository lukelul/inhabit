"""Exporter registry — swappable ML-ready dataset writers behind one name->factory map.

Use ``make_exporter(name, **kwargs)`` to get a configured :class:`Exporter` by name instead
of importing concrete classes. Built on the generic :class:`inhabit_core.Registry`, so
exporters share one registration mechanism with every other extension point (adapters,
transports, ...). Mirrors the ``host/adapters`` reference pattern: register first-party
plugins directly, expose ``make_exporter`` + ``list_exporters`` (the latter delegating to
``Registry.names()`` — the Registry intentionally has no ``__iter__``).

Third-party packages (the P-M marketplace) can ship exporters via the ``inhabit.exporters``
entry-point group; discovery is lazy and degrades silently when none are installed.
"""
from __future__ import annotations

from typing import Any

from inhabit_core import Registry

from .base import Exporter
from .lerobot_exporter import LeRobotExporter
from .parquet import ParquetExporter

# One registry for all exporters. ``entry_point_group`` lets third-party packages contribute
# exporters by advertising ``inhabit.exporters`` entry points; it is discovered lazily and
# degrades silently when none are installed.
_REGISTRY: Registry[Exporter] = Registry("exporter", entry_point_group="inhabit.exporters")

# First-party exporters are zero-extra-dependency (both only need pyarrow, already required),
# so register the classes directly — same as the sim/replay adapters.
_REGISTRY.register("lerobot", LeRobotExporter)
_REGISTRY.register("parquet", ParquetExporter)


def list_exporters() -> list[str]:
    """Return sorted names of all registered exporters.

    Delegates to ``Registry.names()`` (which returns a sorted list and runs entry-point
    discovery once), since ``Registry`` exposes no ``__iter__``.
    """
    return _REGISTRY.names()


def make_exporter(name: str, **kwargs: Any) -> Exporter:
    """Create an :class:`Exporter` by name.

    Raises ``ValueError`` listing the available names if *name* is unknown.
    """
    return _REGISTRY.make(name, **kwargs)


__all__ = ["list_exporters", "make_exporter"]
