"""Sensor sources — swappable upstream plugins behind :class:`SensorSource`.

A sensor source produces a stream of time-stamped samples for one modality of the PVT
triplet (proprio / visual / tactile). Use ``make_sensor_source(name, **kwargs)`` to get a
configured source by name instead of importing concrete classes; the factory is built on
the generic :class:`inhabit_core.Registry`, so sensor sources share one registration
mechanism with every other extension point (adapters, transports, exporters, ...).

Four zero-dependency plugins ship built-in: ``sim-proprio`` (seeded, deterministic
synthetic proprioceptive samples), ``replay`` (deterministic playback of a recorded
``PVTSample`` sequence — the sensor-source analogue of ``ReplayAdapter``), and the P-B
scenario-driven pair ``sim-tactile`` (tactile events from a ``ContactScenario`` script) and
``sim-frames`` (visual frame references on the same timeline). Third-party packages can
contribute sources via the ``inhabit.sensor_sources`` entry-point group, discovered lazily
and degrading silently when none are installed.

Frozen contracts: this package IMPORTS ``PVTSample``/``PVT_SCHEMA_VERSION`` to shape its
output but never edits them.
"""
from __future__ import annotations

from typing import Any

from inhabit_core import Registry

from .interface import (
    SENSOR_SOURCE_CONTRACT_VERSION,
    ClockNs,
    SensorKind,
    SensorMetadata,
    SensorSource,
)
from .replay import ReplaySource
from .sim_proprio import SimProprioSource
from .sim_scenario import SimFramesSource, SimTactileSource

# One registry for all sensor sources. ``entry_point_group`` lets third-party packages ship
# sources (P-M marketplace) by advertising ``inhabit.sensor_sources`` entry points; it is
# discovered lazily and degrades silently when none are installed.
_REGISTRY: Registry[SensorSource] = Registry(
    "sensor source", entry_point_group="inhabit.sensor_sources"
)

# Zero-dependency sources: register the classes directly (matches the sim/replay adapters).
# Two built-ins satisfy the P-A "≥2 plugins each pass conformance" exit criterion.
_REGISTRY.register("sim-proprio", SimProprioSource)
_REGISTRY.register("replay", ReplaySource)
_REGISTRY.register("sim-tactile", SimTactileSource)
_REGISTRY.register("sim-frames", SimFramesSource)


def list_sensor_sources() -> list[str]:
    """Return sorted names of all registered sensor sources.

    Delegates to ``Registry.names()`` (which runs entry-point discovery once and returns a
    sorted list); ``Registry`` exposes no ``__iter__``, so introspection goes through the
    public ``names()`` API.
    """
    return _REGISTRY.names()


def make_sensor_source(name: str, **kwargs: Any) -> SensorSource:
    """Create a :class:`SensorSource` by name.

    Raises ``ValueError`` listing the available names if *name* is unknown, or if the
    constructed source advertises a :data:`SENSOR_SOURCE_CONTRACT_VERSION` other than the
    one this host implements. Rejecting an incompatible (e.g. third-party entry-point)
    plugin HERE keeps the failure localized to the factory boundary instead of surfacing
    deep in core ingestion after the source is already wired in.
    """
    source = _REGISTRY.make(name, **kwargs)
    contract = source.metadata().contract_version
    if contract != SENSOR_SOURCE_CONTRACT_VERSION:
        raise ValueError(
            f"{name!r} implements sensor-source contract {contract}, "
            f"expected {SENSOR_SOURCE_CONTRACT_VERSION}"
        )
    return source


__all__ = [
    "SENSOR_SOURCE_CONTRACT_VERSION",
    "ClockNs",
    "ReplaySource",
    "SensorKind",
    "SensorMetadata",
    "SensorSource",
    "SimFramesSource",
    "SimProprioSource",
    "SimTactileSource",
    "list_sensor_sources",
    "make_sensor_source",
]
