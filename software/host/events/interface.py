"""EventDetector contract — the typed signal that names a last-centimeter *failure*.

The wedge of the Inhabit data engine is the **last centimeter**: the moment a
gripper touches, slips off, crushes, or releases an object. Cameras get occluded
there; proprioception and tactile signals do not. An :class:`EventDetector` turns a
short window of time-aligned PVT samples into a list of **typed, timestamped
:class:`Event` records** — a *labeled signal*, not decoration. Each event names the
physical failure it represents (see :class:`EventKind`).

Why this is a versioned contract
--------------------------------
Labels must be **reproducible**: a recorded episode stores which detector (and which
detector schema) produced its events, so a relabel is auditable and diffable. We
therefore version the event schema with :data:`DETECTOR_SCHEMA_VERSION` and tag every
:class:`Event` with the ``schema_version`` of the contract that minted it. Bump it
ONLY alongside a migration story for old labels — never rename/remove an
:class:`EventKind` value or an :class:`Event` field silently.

Time-sync is first-class
------------------------
Every :class:`Event` carries ``t_monotonic_ns`` taken from the SAME single monotonic
host clock (``time.monotonic_ns``) that stamps :class:`~inhabit_can.pvt.PVTSample`.
Detectors never invent a clock; they copy the timestamp of the sample that triggered
the event so the label aligns exactly with the proprio/visual/tactile streams.

This module is the *contract* and nothing else: an enum, a frozen dataclass, and an
abstract base. Concrete detectors (and the real P-D current-spike / vibration / slip /
impact detectors) live beside it as plugins; importing this module pulls no optional
or heavy dependency.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from inhabit_can.pvt import PVTSample

__all__ = [
    "DETECTOR_SCHEMA_VERSION",
    "Event",
    "EventDetector",
    "EventKind",
    "Window",
]

# Current on-the-wire event-label schema. Bump ONLY with a migration for old labels;
# every Event records the version that produced it so relabels stay reproducible.
DETECTOR_SCHEMA_VERSION = 1

# A detector's input is a window of time-aligned PVT samples (oldest-first). We keep
# the input type as a read-only Sequence so a detector can never mutate the caller's
# buffer. ``Window`` is the named alias used throughout the package.
Window = Sequence[PVTSample]


class EventKind(StrEnum):
    """The last-centimeter failure (or recovery) an :class:`Event` labels.

    String-valued so a kind serialises to a stable, human-readable token in parquet /
    JSON exports (``EventKind.CONTACT_START.value == "contact_start"``) and round-trips
    without an integer remap. Extensible: the real P-D detectors classify into these
    kinds; add new members (never renumber/rename existing ones — that breaks recorded
    labels).
    """

    # Lead with the contact lifecycle — the core wedge signal.
    CONTACT_START = "contact_start"  # end-effector just touched: force/current rises.
    CONTACT_RELEASE = "contact_release"  # contact ended: force/current falls to free-space.
    # Failure modes detectable electrically/tactilely where the camera is occluded.
    CURRENT_SPIKE = "current_spike"  # motor current jumps: bind, jam, or hard contact.
    IMPACT = "impact"  # abrupt velocity discontinuity + vibration: a collision/strike.
    SLIP = "slip"  # grasped object slips: micro-vibration + unexpected velocity. (P-D)


@dataclass(frozen=True, slots=True)
class Event:
    """One detected last-centimeter event — a typed, reproducible label.

    ``frozen`` so a recorded label cannot be mutated after detection (labels are
    append-only evidence, like the episodes they annotate). All fields are primitive /
    immutable so an event is trivially hashable, comparable, and serialisable.

    Attributes
    ----------
    kind:
        Which physical failure/recovery this is (:class:`EventKind`).
    t_monotonic_ns:
        Monotonic host timestamp (ns) of the triggering sample — the ONE clock the PVT
        streams share, so the label aligns with proprio/visual/tactile exactly.
    confidence:
        Detector confidence in ``[0.0, 1.0]``. A stub may emit ``1.0``; trained P-D
        detectors emit a calibrated score. Validated on construction.
    channel:
        Which signal triggered the event (e.g. ``"motor_current"``), so a label is
        traceable to its evidence. Empty string = unspecified.
    detector:
        Name of the detector that produced this event (its registry name). Lets an
        episode record *who* labeled it for reproducibility.
    schema_version:
        :data:`DETECTOR_SCHEMA_VERSION` at mint time — pins the label's format.
    payload:
        Optional detector-specific detail (e.g. the crossed threshold and observed
        value). Read-only mapping; defaults to empty.
    """

    kind: EventKind
    t_monotonic_ns: int
    confidence: float = 1.0
    channel: str = ""
    detector: str = ""
    schema_version: int = DETECTOR_SCHEMA_VERSION
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Fail loud on a malformed label rather than poisoning the dataset silently.
        if not isinstance(self.kind, EventKind):
            raise TypeError(f"kind must be an EventKind, got {type(self.kind).__name__}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence!r}")


class EventDetector(ABC):
    """Turn a window of time-aligned PVT samples into typed contact-event labels.

    The single contract every detector plugin honours. Core code never branches on a
    concrete detector type; it asks the registry for one by name (see
    :func:`events.make_event_detector`) and calls :meth:`detect`.

    Contract for implementations:

    * :meth:`detect` is **pure w.r.t. its input** — it must not mutate ``window``.
    * Every returned :class:`Event` carries a ``t_monotonic_ns`` copied from a sample
      in ``window`` (never a freshly sampled clock), so labels stay aligned.
    * Detection is **deterministic** for a given window + config (seed any randomness)
      so labels are reproducible and golden fixtures stay byte-stable.
    * An empty window yields an empty list — never raise on "no data".
    """

    #: Registry name of this detector; subclasses override. Stamped onto emitted events.
    name: str = "event_detector"

    @abstractmethod
    def detect(self, window: Window) -> list[Event]:
        """Return the events present in ``window`` (oldest-first), possibly empty."""

    @property
    def schema_version(self) -> int:
        """Event-schema version this detector emits. Pinned to the package contract."""
        return DETECTOR_SCHEMA_VERSION
