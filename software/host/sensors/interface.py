"""SensorSource — the abstract contract every sensor plugin implements.

A *sensor source* is the upstream end of the PVT data engine: it produces a stream of
:class:`Sample` objects, each stamped against ONE monotonic host clock. Three kinds of
source feed the Proprioceptive / Visual / Tactile triplet (see ``MASTER_PLAN.md`` and
``.claude/skills/pvt-data-logger/SKILL.md``):

* ``PROPRIO`` — joint angles / velocities / current / torque (this phase: ``sim-proprio``).
* ``VISUAL``  — camera frame references (P-B: ``sim-frames``).
* ``TACTILE`` — force / vibration / contact events (P-B: ``sim-tactile``).

Core code NEVER branches on the concrete source type; it selects a source by name from the
registry, reads its declared :attr:`SensorSource.kind`, and consumes :meth:`stream`. New
capability = a new plugin, never an ``if`` in the engine.

Time-sync contract (first-class)
---------------------------------
Every sample carries ``timestamp_ns`` read from a SINGLE MONOTONIC clock
(``time.monotonic_ns`` on the ingesting host) — NEVER wall-clock time. The clock is
*injectable* (``ClockNs``) so tests assert exact, reproducible stamps and so a future
alignment engine (P-C) can drive all sources off one shared clock. This mirrors the
contract already in ``inhabit_bridge.sources`` and ``transport.interface``.

Jitter budget. Because CAN, video, and tactile streams are aligned to this one clock,
the timestamping path's jitter is part of the contract, not an afterthought:

* The deterministic stepping clock (the default for ``sim-proprio``) has **0 ns jitter** by
  construction — stamps step by exactly ``period_ns``, so seeded sources are byte-stable and
  golden for alignment tests.
* A live source injecting ``time.monotonic_ns`` MUST measure and report its inter-sample
  jitter (deviation of observed period from nominal). The recorder
  (``host/logger/recorder.py``) holds the documented per-episode jitter budget and
  quarantines episodes that exceed it; a source's job is to stamp from the one monotonic
  clock so that measurement is meaningful. ``nominal_rate_hz`` in :class:`SensorMetadata`
  declares the expected period the jitter is measured against.

Contract versioning
-------------------
:data:`SENSOR_SOURCE_CONTRACT_VERSION` versions THIS ABC (the method/property surface a
plugin must satisfy), independently of ``PVT_SCHEMA_VERSION`` (the on-disk data schema, a
frozen contract this module references but never edits). Bump it only with a decision
record when the abstract surface changes; conformance tests assert plugins report it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum

# Version of the SensorSource ABILITY contract (method/property surface), NOT the PVT
# data schema. Independent so the abstract surface can evolve without touching the frozen
# PVTSample schema. Conformance tests pin plugins to this.
SENSOR_SOURCE_CONTRACT_VERSION = 1

# A clock returning monotonic nanoseconds. Injectable so tests assert exact stamps and a
# future alignment engine can share one clock across sources. Defaults to
# ``time.monotonic_ns`` in real sources. NEVER wall clock.
ClockNs = Callable[[], int]


class SensorKind(StrEnum):
    """Discriminator over the PVT triplet a source feeds.

    A :class:`~enum.StrEnum` so the kind serializes to a stable, human-readable token
    (``"proprio"``) in metadata and exports, and compares equal to that token without an
    ``if`` ladder. Values are part of the contract — do not rename without a version bump.
    """

    PROPRIO = "proprio"
    VISUAL = "visual"
    TACTILE = "tactile"


@dataclass(frozen=True)
class SensorMetadata:
    """Static capability/metadata a source advertises before/while streaming.

    Frozen and cheap to construct so the engine can inspect a source (kind, identity,
    declared sample rate, schema linkage) without opening it. ``contract_version`` lets a
    consumer reject a source built against an incompatible ABC revision.

    Attributes
    ----------
    kind:
        The PVT modality this source feeds (proprio/visual/tactile).
    name:
        Registry name of the plugin (e.g. ``"sim-proprio"``).
    device_id:
        Logical device identity stamped onto samples (e.g. ``"sim_joint_pod"``).
    sample_schema_version:
        The PVT schema version of the samples this source emits, so a consumer can route
        them through the right migrations. References the FROZEN ``PVT_SCHEMA_VERSION``;
        this source never edits it.
    nominal_rate_hz:
        Declared nominal sample rate (informational; ``None`` if event-driven/unknown).
    contract_version:
        The :data:`SENSOR_SOURCE_CONTRACT_VERSION` this source was built against.
    """

    kind: SensorKind
    name: str
    device_id: str
    sample_schema_version: int
    nominal_rate_hz: float | None = None
    contract_version: int = SENSOR_SOURCE_CONTRACT_VERSION


class SensorSource(ABC):
    """Abstract base for a streaming sensor source — one interface, swappable plugins.

    Lifecycle mirrors the sibling ``CanSource``/``CanTransport`` contracts so all upstream
    sources behave identically: ``open()`` acquires resources, :meth:`read` returns the
    next single sample (or ``None`` when exhausted), :meth:`stream` yields samples until
    exhausted, ``close()`` releases. Supports the context-manager protocol.

    Implementations MUST:

    * expose a constant :attr:`kind` matching ``metadata().kind`` (the kind invariant);
    * stamp every emitted sample with ``timestamp_ns`` from the injected monotonic clock;
    * be deterministic when seeded (same seed + same clock => identical sequence).
    """

    #: The PVT modality this source feeds. Class-level constant so the kind can be read
    #: without constructing/opening the source; conformance asserts it equals
    #: ``metadata().kind``.
    kind: SensorKind

    @abstractmethod
    def metadata(self) -> SensorMetadata:
        """Return this source's static capability/metadata (kind, identity, schema)."""

    @abstractmethod
    def open(self) -> None:
        """Acquire any underlying resource. No-op for pure-synthetic sources."""

    @abstractmethod
    def close(self) -> None:
        """Release any underlying resource. No-op for pure-synthetic sources."""

    @abstractmethod
    def read(self) -> object | None:
        """Return the next single sample, or ``None`` when the source is exhausted.

        The concrete sample type is declared per-source (a proprio source returns a
        ``PVTSample``); the engine reads :attr:`kind`/:meth:`metadata` to interpret it.
        """

    @abstractmethod
    def stream(self) -> Iterator[object]:
        """Yield samples until the source is exhausted or closed.

        Default consumers prefer this over :meth:`read` for batch ingestion; the two MUST
        agree (streaming is read-until-``None``).
        """

    def __enter__(self) -> SensorSource:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = [
    "SENSOR_SOURCE_CONTRACT_VERSION",
    "ClockNs",
    "SensorKind",
    "SensorMetadata",
    "SensorSource",
]
