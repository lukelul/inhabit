"""``ImpactDetector`` — the abrupt-strike label (a velocity discontinuity), P-D/D4.

An **impact** is a collision/strike: the end-effector (or a link) hits something and its
motion changes *discontinuously* — a large single-sample jump in joint velocity (a "jerk
spike"), unlike the smooth force/velocity ramp of an ordinary
:attr:`~events.interface.EventKind.CONTACT_START`. This detector names exactly that failure:
it scans a window of time-aligned :class:`~inhabit_can.pvt.PVTSample` rows for a
single-sample change in a monitored channel (default ``joint_velocity``) whose magnitude
crosses a threshold, and emits an :attr:`~events.interface.EventKind.IMPACT` at the sample
where the discontinuity lands.

Why a *discontinuity*, not a *magnitude* (impact vs contact_start / current_spike)
---------------------------------------------------------------------------------
:class:`~events.detectors.ThresholdDetector` fires on the *level* of a channel (``|value|``
crossing a band) — the electrical/force signature of a sustained contact or a hard bind. An
impact is different: what distinguishes a strike is not a high velocity but a *sudden change*
in it. So this detector thresholds the **first difference** ``value[i] - value[i-1]`` (the
jerk), computed per :attr:`~inhabit_can.pvt.PVTSample.chain_index` so an interleaved
multi-stream episode (proprio + tactile + frame rows on different chains and offset clocks)
never manufactures a phantom jump across chains. A smooth contact ramp — velocity changing
gradually, each step below ``jerk_threshold`` — yields NO impact (that is D2's
``contact_start``); only the sharp strike does.

Failure modes this leads with
-----------------------------
* **Phantom cross-stream jerk.** The merged episode round-robins one modality per instant, so
  consecutive *window* rows belong to different chains with unrelated values. Differencing
  those would fire on every row. We difference **within a chain**, so only a real same-signal
  discontinuity counts.
* **A strike double-counted as a rebound.** A physical strike rings: the velocity spikes and
  recovers, which is two discontinuities (onset + rebound) for ONE impact. An optional
  ``refractory_ns`` suppresses further impacts on a chain for a dwell after one fires, so one
  strike yields one label. Default ``0`` (disabled) keeps the base behaviour a pure jerk gate.
* **A poisoned label channel.** An unknown/typo'd channel or a non-positive threshold fails
  LOUD at construction (never mid-detection on a half-built dataset), mirroring
  :class:`~events.detectors.ThresholdDetector`.

Contract. Honours :class:`~events.interface.EventDetector` exactly: pure w.r.t. the window
(never mutated), deterministic (no randomness — same window + config ⇒ byte-identical
events), empty window ⇒ ``[]``, and every emitted :class:`~events.interface.Event` copies its
``t_monotonic_ns`` from the triggering sample (never a fresh clock) so the label stays aligned
with the one monotonic PVT timeline. Stdlib-only; reads FROZEN contracts, mutates none.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

from inhabit_can.pvt import PVTSample

from .interface import Event, EventDetector, EventKind, Window

__all__ = ["ImpactDetector"]


@dataclass(frozen=True)
class ImpactDetector(EventDetector):
    """Emit an :attr:`~events.interface.EventKind.IMPACT` at an abrupt velocity discontinuity.

    The detector walks the window in order, tracking the previous value of ``channel`` for
    each :attr:`~inhabit_can.pvt.PVTSample.chain_index` seen. When a sample's value differs
    from its chain's previous value by at least ``jerk_threshold`` in magnitude, that sample
    is a strike: an :class:`~events.interface.Event` of kind
    :attr:`~events.interface.EventKind.IMPACT` is emitted with the sample's ``t_monotonic_ns``.
    The first sample of each chain has no predecessor, so it can never be an impact (a
    discontinuity needs two points).

    Determinism: no randomness; comparison is ``>=`` so a jerk exactly *at* the threshold
    counts (boundary inclusive, documented + tested). Events come out oldest-first, in window
    order.

    Parameters
    ----------
    channel:
        Which numeric :class:`~inhabit_can.pvt.PVTSample` field to difference (default
        ``"joint_velocity"`` — the joint-rate signal a strike discontinuously changes). Only
        the proprioceptive numeric scalars are monitorable; an unknown channel fails loud at
        construction.
    jerk_threshold:
        Inclusive magnitude of the single-sample change ``|value[i] - value[i-1]|`` (same unit
        as the channel) that marks a strike. Must be ``> 0`` — a non-positive threshold would
        fire on every sample pair (``abs(delta) >= 0`` is always true) and stamp a phantom
        impact on every frame, poisoning the dataset. Rejected at construction.
    refractory_ns:
        After an impact fires on a chain, suppress further impacts on THAT chain until this
        many monotonic nanoseconds have elapsed (the strike's ring/rebound is one physical
        event, one label). ``0`` (default) disables suppression. Must be ``>= 0``.
    confidence:
        Confidence stamped on emitted events (``[0.0, 1.0]``); a fixed stub value until a
        calibrated P-D score replaces it.
    """

    channel: str = "joint_velocity"
    jerk_threshold: float = 5.0
    refractory_ns: int = 0
    confidence: float = 1.0
    name: str = "impact"

    # The PVTSample fields this detector can difference (numeric scalars only). Explicit so an
    # unknown/typo'd channel fails loudly at construction, matching ThresholdDetector.
    _NUMERIC_CHANNELS: ClassVar[tuple[str, ...]] = (
        "joint_angle",
        "joint_velocity",
        "motor_current",
        "estimated_torque",
    )

    def __post_init__(self) -> None:
        if self.channel not in self._NUMERIC_CHANNELS:
            raise ValueError(
                f"unknown channel {self.channel!r}; "
                f"monitorable channels: {', '.join(self._NUMERIC_CHANNELS)}"
            )
        # A threshold <= 0 makes ``abs(delta) >= threshold`` true for EVERY sample pair, so the
        # detector would stamp a phantom impact on every frame — fail loud at construction.
        if self.jerk_threshold <= 0.0:
            raise ValueError(f"jerk_threshold must be > 0, got {self.jerk_threshold!r}")
        if self.refractory_ns < 0:
            raise ValueError(f"refractory_ns must be >= 0, got {self.refractory_ns!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence!r}")

    def detect(self, window: Window) -> list[Event]:
        """Emit one IMPACT per abrupt per-chain velocity discontinuity, oldest-first."""
        events: list[Event] = []
        # Per-chain running state: last seen value, and the last instant we labeled (for the
        # refractory dwell). Keyed by chain_index so interleaved streams stay independent.
        prev_value: dict[int, float] = {}
        last_fired_ns: dict[int, int] = {}
        for sample in window:
            chain = sample.chain_index
            value = self._read(sample)
            previous = prev_value.get(chain)
            prev_value[chain] = value
            if previous is None:
                continue  # first sample of this chain — no predecessor, no discontinuity.
            delta = value - previous
            if not math.isfinite(delta):
                # A NaN/inf delta (sensor dropout) makes ``abs(delta) < threshold`` False,
                # which would fall through and emit a PHANTOM impact. A non-finite reading
                # is missing data, not a strike — skip it (mirrors the C3/C5 finite guards).
                continue
            if abs(delta) < self.jerk_threshold:
                continue
            if self._in_refractory(chain, sample.timestamp_ns, last_fired_ns):
                continue  # same strike's ring/rebound — one physical impact, one label.
            last_fired_ns[chain] = sample.timestamp_ns
            events.append(
                Event(
                    kind=EventKind.IMPACT,
                    t_monotonic_ns=sample.timestamp_ns,
                    confidence=self.confidence,
                    channel=self.channel,
                    detector=self.name,
                    payload={"delta": delta, "jerk_threshold": self.jerk_threshold},
                )
            )
        return events

    def _in_refractory(
        self, chain: int, timestamp_ns: int, last_fired_ns: dict[int, int]
    ) -> bool:
        """True if ``chain`` fired an impact within ``refractory_ns`` before ``timestamp_ns``."""
        if self.refractory_ns <= 0:
            return False
        fired = last_fired_ns.get(chain)
        return fired is not None and timestamp_ns - fired < self.refractory_ns

    def _read(self, sample: PVTSample) -> float:
        """Read the monitored numeric channel from a sample as a float."""
        return float(getattr(sample, self.channel))
