"""Event detectors — last-centimeter contact labels behind ``EventDetector``.

Use :func:`make_event_detector(name, **kwargs)` to get a configured detector by name
instead of importing concrete classes. The factory is built on the generic
:class:`inhabit_core.Registry`, so detectors share one registration mechanism with
every other extension point (adapters, transports, exporters, ...).

The detector is a *labeled signal* for the wedge of the data engine — the moment a
gripper touches, slips, strikes, or releases. Each :class:`Event` is typed, timestamped
on the single monotonic clock, and tagged with the detector + schema version that
produced it, so labels are reproducible. Contract and version live in
:mod:`events.interface`.

Built-in plugins (sim/stub for P-A; real P-D detectors land later as new plugins):
  * ``noop``      — emits nothing (the free-space / no-false-positive baseline).
  * ``threshold`` — emits a typed event when a monitored channel crosses a magnitude.
"""
from __future__ import annotations

from typing import Any

from inhabit_core import Registry

from .contact import ContactDetector
from .detectors import NoopDetector, ThresholdDetector
from .impact import ImpactDetector
from .interface import (
    DETECTOR_SCHEMA_VERSION,
    Event,
    EventDetector,
    EventKind,
    Window,
)

# One registry for all event detectors. ``entry_point_group`` lets third-party packages
# ship detectors (P-M marketplace) by advertising ``inhabit.event_detectors`` entry
# points; it is discovered lazily and degrades silently when none are installed.
_REGISTRY: Registry[EventDetector] = Registry(
    "event detector", entry_point_group="inhabit.event_detectors"
)

# Zero-dependency stubs: register the classes directly.
_REGISTRY.register("noop", NoopDetector)
_REGISTRY.register("threshold", ThresholdDetector)
_REGISTRY.register("contact", ContactDetector)
_REGISTRY.register("impact", ImpactDetector)


def make_event_detector(name: str, **kwargs: Any) -> EventDetector:
    """Create an :class:`EventDetector` by name.

    Raises ``ValueError`` listing the available names if *name* is unknown.
    """
    return _REGISTRY.make(name, **kwargs)


def list_event_detectors() -> list[str]:
    """Sorted names of all registered event detectors (incl. lazy entry-point plugins)."""
    return _REGISTRY.names()


__all__ = [
    "DETECTOR_SCHEMA_VERSION",
    "ContactDetector",
    "Event",
    "EventDetector",
    "EventKind",
    "ImpactDetector",
    "NoopDetector",
    "ThresholdDetector",
    "Window",
    "list_event_detectors",
    "make_event_detector",
]
