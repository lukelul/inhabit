"""Concrete EventDetector stubs — the seed for the P-D contact-detection suite.

Two deterministic, dependency-free detectors so the registry has >=2 plugins for
conformance from day one:

* :class:`NoopDetector` — the null label channel: a window with no detectable
  last-centimeter failure produces no events. Proves "no data / no contact => no
  label", which a real detector must also honour (no phantom contacts).
* :class:`ThresholdDetector` — the simplest real signal: a monitored channel crossing
  a configured magnitude. Surfaces the **current-spike / hard-contact** failure (motor
  current jumps when the end-effector binds or strikes) and the **contact lifecycle**
  (force/current rising above free-space). The trained P-D detectors replace the fixed
  threshold with calibrated logic, but keep this exact contract.

Both are seeded/deterministic: same window + config => byte-identical events.
"""
from __future__ import annotations

from dataclasses import dataclass

from inhabit_can.pvt import PVTSample

from .interface import Event, EventDetector, EventKind, Window

__all__ = ["NoopDetector", "ThresholdDetector"]


class NoopDetector(EventDetector):
    """Detect nothing — the calibration baseline for "free space => no label".

    The failure it guards against is the *false positive*: a detector that hallucinates
    contacts pollutes the dataset worse than one that misses them. ``noop`` is the
    reference for a clean channel; every conformance run asserts it never invents an
    event regardless of input.
    """

    name = "noop"

    def detect(self, window: Window) -> list[Event]:
        """Always return an empty list (no contact, no label)."""
        return []


@dataclass(frozen=True)
class ThresholdDetector(EventDetector):
    """Emit an event when a windowed channel crosses a magnitude threshold.

    The failure this surfaces: a **current spike / hard contact** — motor current (or
    another monitored channel) jumping above its free-space band is the electrical
    signature of the end-effector binding, jamming, or striking something the camera
    cannot see. This stub uses a fixed threshold; the P-D detector swaps in calibrated,
    per-channel logic but keeps this contract (one typed :class:`Event` per crossing
    sample, timestamp copied from that sample).

    Determinism: no randomness — the same window and config always yield the same
    events, in window order. Comparison is ``>=`` so a sample exactly *at* the
    threshold counts as a crossing (boundary is inclusive; documented + tested).

    Parameters
    ----------
    channel:
        Which :class:`~inhabit_can.pvt.PVTSample` numeric field to monitor
        (default ``"motor_current"``). Unknown channel => ``ValueError`` at construct
        time (fail loud, not at detection time on a poisoned dataset).
    threshold:
        Inclusive magnitude (compared against ``abs(value)``) that triggers an event.
    kind:
        Which :class:`EventKind` to label a crossing with (default
        :attr:`EventKind.CURRENT_SPIKE`).
    confidence:
        Confidence stamped on emitted events (``[0.0, 1.0]``); a fixed stub value.
    """

    channel: str = "motor_current"
    threshold: float = 1.0
    kind: EventKind = EventKind.CURRENT_SPIKE
    confidence: float = 1.0
    name: str = "threshold"

    # The set of PVTSample fields this stub can monitor (numeric scalars only). Kept
    # explicit so an unknown/typo'd channel fails loudly at construction.
    _NUMERIC_CHANNELS = ("joint_angle", "joint_velocity", "motor_current", "estimated_torque")

    def __post_init__(self) -> None:
        if self.channel not in self._NUMERIC_CHANNELS:
            raise ValueError(
                f"unknown channel {self.channel!r}; "
                f"monitorable channels: {', '.join(self._NUMERIC_CHANNELS)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence!r}")
        # A threshold <= 0 makes `abs(value) >= threshold` true for EVERY sample, so the
        # detector would stamp a phantom contact event on every frame — silently poisoning
        # the last-centimeter dataset. Fail loud at construction (not at detection time),
        # matching the channel/confidence guards above.
        if self.threshold <= 0.0:
            raise ValueError(f"threshold must be > 0, got {self.threshold!r}")

    def detect(self, window: Window) -> list[Event]:
        """Emit one event per sample whose ``abs(channel)`` is at/above ``threshold``."""
        events: list[Event] = []
        for sample in window:
            value = self._read(sample)
            if abs(value) >= self.threshold:
                events.append(
                    Event(
                        kind=self.kind,
                        t_monotonic_ns=sample.timestamp_ns,
                        confidence=self.confidence,
                        channel=self.channel,
                        detector=self.name,
                        payload={"value": value, "threshold": self.threshold},
                    )
                )
        return events

    def _read(self, sample: PVTSample) -> float:
        """Read the monitored numeric channel from a sample as a float."""
        return float(getattr(sample, self.channel))
