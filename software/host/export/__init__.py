"""Inhabit dataset export — ML-ready exporters behind one versioned ``Exporter`` contract.

Pick an exporter by name through the registry::

    from export import make_exporter, list_exporters
    exporter = make_exporter("lerobot")        # or "parquet"
    root = exporter.export(episodes, out_dir)
    episodes_back = exporter.load(root)        # round-trips

The standalone ``export_lerobot`` / ``load_lerobot`` functions remain public so existing
callers (the ``tools/dataset`` CLI, the round-trip tests) keep working unchanged — the
registry wraps them, it does not replace them.
"""
from .base import EXPORTER_ABC_VERSION, Exporter
from .lerobot import export_lerobot, load_lerobot, load_lerobot_timing_meta
from .lerobot_exporter import LeRobotExporter
from .parquet import ParquetExporter, load_parquet_timing_meta
from .registry import list_exporters, make_exporter

__all__ = [
    "EXPORTER_ABC_VERSION",
    "Exporter",
    "LeRobotExporter",
    "ParquetExporter",
    "export_lerobot",
    "list_exporters",
    "load_lerobot",
    "load_lerobot_timing_meta",
    "load_parquet_timing_meta",
    "make_exporter",
]
