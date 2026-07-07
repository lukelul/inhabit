"""host.timing — clock domains, domain-labeled stamps, deterministic clocks (Phase P-C).

The timebase vocabulary the rest of P-C builds on. Failure modes it exists to prevent:
**wall-clock leakage** (a wall/device stamp standing in for host-monotonic time =>
cross-modal misalignment), **zero/negative/backwards stamps** (poisoned datasets), and
**cross-domain comparison** (ordering two unrelated clocks is noise). See ``timing.stamp``
for the full failure-mode ledger.

C1 ships the vocabulary (PONYTAIL): :class:`ClockDomain` + :class:`Stamp` +
:func:`require_monotonic` (the type-level monotonic gate) and two deterministic
``ClockNs``-compatible clocks, :class:`LatticeClock` and :class:`ScriptedClock`.
C2 adds normalization on top — :class:`Normalizer` turning raw source stamps into
:class:`TimingRecord` values that are either cleanly normalized or FLAGGED with a
:class:`NormalizationFlag` reason token (never silently repaired). C3 adds the
multi-modal alignment engine — :func:`align`/:func:`align_modalities` producing
quality-annotated :class:`AlignmentResult` values within an explicit
:class:`AlignmentBudget` (misses flagged, stale reuse banned, events never
interpolated — see ``timing.align``). C5 adds the exported timing metadata —
:class:`TimingMeta` (built from real records/results via ``TimingMeta.from_run``,
never defaulted) plus the sidecar read/write helpers, so a dataset's synchronization
can be AUDITED from the exported artifact alone (see ``timing.export_meta``).

Stdlib only, no numpy (the P-C invariant). The FROZEN ``PVTSample`` / ``SensorSource`` ABC
surfaces are referenced by contract, never edited.
"""
from __future__ import annotations

from timing.align import (
    AlignmentBudget,
    AlignmentMethod,
    AlignmentQuality,
    AlignmentResult,
    align,
    align_modalities,
    interpolate_proprio,
    timeline_from_records,
)
from timing.clocks import ClockExhausted, LatticeClock, ScriptedClock
from timing.export_meta import (
    TIMING_META_VERSION,
    ModalityTiming,
    SyncVerdict,
    TimingMeta,
    read_timing_sidecar,
    select_episode_timing,
    write_timing_sidecar,
)
from timing.normalize import NormalizationFlag, Normalizer, TimingRecord
from timing.stamp import (
    MAX_STAMP_NS,
    MIN_STAMP_NS,
    ClockDomain,
    Stamp,
    require_monotonic,
    validate_stamp_ns,
)

__all__ = [
    "MAX_STAMP_NS",
    "MIN_STAMP_NS",
    "TIMING_META_VERSION",
    "AlignmentBudget",
    "AlignmentMethod",
    "AlignmentQuality",
    "AlignmentResult",
    "ClockDomain",
    "ClockExhausted",
    "LatticeClock",
    "ModalityTiming",
    "NormalizationFlag",
    "Normalizer",
    "ScriptedClock",
    "Stamp",
    "SyncVerdict",
    "TimingMeta",
    "TimingRecord",
    "align",
    "align_modalities",
    "interpolate_proprio",
    "read_timing_sidecar",
    "require_monotonic",
    "select_episode_timing",
    "timeline_from_records",
    "validate_stamp_ns",
    "write_timing_sidecar",
]
