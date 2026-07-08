"""``contact`` — the contact_start / contact_release lifecycle detector (P-D/D2).

The core last-centimeter wedge: name *when the gripper first touches* and *when it lets
go*. This detector turns a window of time-aligned :class:`~inhabit_can.pvt.PVTSample` rows
into a stream of :class:`~events.interface.Event`\\ s of exactly two kinds —
:attr:`~events.interface.EventKind.CONTACT_START` on the rising edge into contact and
:attr:`~events.interface.EventKind.CONTACT_RELEASE` on the falling edge back to free space.
The mid-contact failure modes (``slip`` / ``impact`` / ``current_spike``) are OWNED BY
SEPARATE detectors; this one is the lifecycle spine they hang off.

Which channel is the contact signal?
------------------------------------
A detector can only label what the data actually drives. In the deterministic sim the ONE
signal that tracks contact is the FROZEN ``PVTSample.tactile_event`` token: the
scenario-driven tactile stream stamps ``contact_start | slip | impact | release`` inside a
contact phase and ``None`` in the free-space ``approach`` / ``settle`` gaps, while the
proprioceptive channels (``motor_current`` etc.) are an independent seeded sine + noise and
do NOT correlate with contact. So the DEFAULT monitored channel is ``"tactile_event"``,
mapped to a scalar *contact level*:

* an active-grasp token (``contact_start`` / ``slip`` / ``impact``) -> ``1.0`` (in contact),
* the ``release`` token -> ``0.0`` (contact ended: force falls to free space),
* ``None`` (or any unknown token) -> *not a contact reading*: the sample is skipped, so
  proprio / frame rows interleaved into the same episode window never disturb the state.

The same detector also works on a real analog contact channel (``motor_current`` /
``estimated_torque`` — Phase 6 force/current contact sensing): pass ``channel="..."`` and the
level is ``abs(value)``. That path is what the hysteresis test exercises with a noisy analog
signal; the frozen sim proves the tactile path against D1 ground truth.

Hysteresis (no chatter)
-----------------------
A single threshold on a noisy signal chatters: every up-crossing re-fires ``contact_start``.
This is a Schmitt trigger — two thresholds with a deadband. Contact turns ON only when the
level rises to ``onset_threshold`` and turns OFF only when it falls to ``release_threshold``
(``release_threshold <= onset_threshold``); oscillations that stay inside the deadband do
NOT re-fire. For the clean binary tactile signal the default symmetric ``0.5 / 0.5`` pair is
enough; for a noisy analog channel choose ``onset_threshold > release_threshold`` to size the
deadband above the noise.

Contract
--------
:meth:`detect` is pure w.r.t. its input, deterministic (no RNG), stamps every event with the
triggering sample's own ``t_monotonic_ns`` (never a fresh clock), and returns ``[]`` on an
empty window. A ``contact_start`` always precedes its ``contact_release`` by construction
(the state machine strictly alternates). Config is via constructor kwargs; the detector is a
frozen value so it cannot drift between calls. Reads FROZEN contracts (``Event`` /
``EventKind`` / ``PVTSample``) and mutates none of them; ``schema_version`` is pinned to the
package :data:`~events.interface.DETECTOR_SCHEMA_VERSION`.
"""
from __future__ import annotations

from dataclasses import dataclass

from inhabit_can.pvt import PVTSample

from .interface import Event, EventDetector, EventKind, Window

__all__ = ["ContactDetector"]

#: The special non-numeric channel: the FROZEN ``PVTSample.tactile_event`` token stream.
_TACTILE_CHANNEL = "tactile_event"

#: Numeric ``PVTSample`` fields usable as an analog contact signal (monitored as ``abs``).
_NUMERIC_CHANNELS: tuple[str, ...] = (
    "joint_angle",
    "joint_velocity",
    "motor_current",
    "estimated_torque",
)

#: Every channel this detector can monitor: the numeric fields plus the tactile token.
_MONITORABLE_CHANNELS: tuple[str, ...] = (*_NUMERIC_CHANNELS, _TACTILE_CHANNEL)

#: FROZEN tactile tokens (``PVTSample.tactile_event`` vocabulary) that mean the gripper is
#: actively in contact — the grasp is held. ``release`` is deliberately NOT here: it is the
#: explicit contact-ENDED marker and maps to level 0.0 so it triggers the falling edge.
_CONTACT_ACTIVE_TOKENS = frozenset({"contact_start", "slip", "impact"})

#: The token that explicitly ends a contact (force falls to free space) -> level 0.0.
_CONTACT_ENDED_TOKENS = frozenset({"release"})


@dataclass(frozen=True)
class ContactDetector(EventDetector):
    """Emit ``contact_start`` / ``contact_release`` on the contact channel's rising/falling edge.

    Walks the window once, tracking a boolean *in-contact* state through a two-threshold
    Schmitt trigger. The state flips (and one typed :class:`Event` is emitted at the
    triggering sample's timestamp) only on a real edge:

    * free -> contact when the contact level rises to :attr:`onset_threshold`
      (emit :attr:`~events.interface.EventKind.CONTACT_START`),
    * contact -> free when it falls to :attr:`release_threshold`
      (emit :attr:`~events.interface.EventKind.CONTACT_RELEASE`).

    Between the two thresholds the state is held, so a signal wobbling inside the deadband
    emits ONE start, not a chatter of them.

    Parameters
    ----------
    channel:
        Which :class:`~inhabit_can.pvt.PVTSample` field carries the contact signal. Default
        ``"tactile_event"`` (the scenario-driven contact token — see the module docstring);
        or a numeric field (``motor_current`` / ``estimated_torque`` / ...) monitored as
        ``abs(value)``. Unknown channel => ``ValueError`` at construction (fail loud, never
        at detect time on a poisoned dataset).
    onset_threshold:
        Contact level (inclusive) that turns contact ON. Must be ``> 0`` — a non-positive
        onset would fire on the first sample of every episode (``abs`` level is ``>= 0``),
        stamping a phantom contact and poisoning the last-centimeter dataset.
    release_threshold:
        Contact level (inclusive) that turns contact OFF. Must satisfy
        ``0 <= release_threshold <= onset_threshold`` — the deadband between the two is the
        hysteresis; an inverted pair is a config bug and is rejected loud.
    confidence:
        Confidence stamped on emitted events (``[0.0, 1.0]``); a fixed stub value until the
        trained P-D detector emits a calibrated score.
    """

    channel: str = _TACTILE_CHANNEL
    onset_threshold: float = 0.5
    release_threshold: float = 0.5
    confidence: float = 1.0
    name: str = "contact"

    def __post_init__(self) -> None:
        if self.channel not in _MONITORABLE_CHANNELS:
            raise ValueError(
                f"unknown channel {self.channel!r}; "
                f"monitorable channels: {', '.join(_MONITORABLE_CHANNELS)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence!r}")
        # A non-positive onset fires on every sample (level is >= 0), so contact would be
        # asserted on the first frame of any episode — a phantom label. Reject at construction.
        if self.onset_threshold <= 0.0:
            raise ValueError(f"onset_threshold must be > 0, got {self.onset_threshold!r}")
        if self.release_threshold < 0.0:
            raise ValueError(
                f"release_threshold must be >= 0, got {self.release_threshold!r}"
            )
        # Hysteresis requires the release threshold at or below the onset threshold; an
        # inverted deadband (release > onset) has no stable state and is a config bug.
        if self.release_threshold > self.onset_threshold:
            raise ValueError(
                f"release_threshold ({self.release_threshold!r}) must be <= onset_threshold "
                f"({self.onset_threshold!r}); an inverted hysteresis band is nonsensical"
            )

    def detect(self, window: Window) -> list[Event]:
        """Return the contact-lifecycle events in ``window`` (oldest-first), possibly empty.

        Iterates the window in its given (oldest-first) order — never re-sorts or samples a
        clock — so timestamps come straight from the triggering samples and the result is
        byte-identical for a given window + config.
        """
        events: list[Event] = []
        in_contact = False
        for sample in window:
            level = self._contact_level(sample)
            if level is None:
                # Not a reading on the monitored contact channel (e.g. a proprio/frame row's
                # tactile_event=None interleaved into the episode) — leave the state untouched.
                continue
            if not in_contact and level >= self.onset_threshold:
                in_contact = True
                events.append(self._event(EventKind.CONTACT_START, sample, level))
            elif in_contact and level <= self.release_threshold:
                in_contact = False
                events.append(self._event(EventKind.CONTACT_RELEASE, sample, level))
        return events

    def _contact_level(self, sample: PVTSample) -> float | None:
        """Scalar contact level for a sample, or ``None`` if it carries no contact reading.

        For the tactile channel a ``None``/unknown token means "no reading here" (skip); for a
        numeric channel every sample is a reading, monitored as ``abs(value)``.
        """
        if self.channel == _TACTILE_CHANNEL:
            token = sample.tactile_event
            if token in _CONTACT_ACTIVE_TOKENS:
                return 1.0
            if token in _CONTACT_ENDED_TOKENS:
                return 0.0
            return None  # None or an unrecognized token: not a contact reading -> skip.
        return abs(float(getattr(sample, self.channel)))

    def _event(self, kind: EventKind, sample: PVTSample, level: float) -> Event:
        """Mint a typed event at the triggering sample's own monotonic timestamp."""
        return Event(
            kind=kind,
            t_monotonic_ns=sample.timestamp_ns,
            confidence=self.confidence,
            channel=self.channel,
            detector=self.name,
            payload={
                "level": level,
                "onset_threshold": self.onset_threshold,
                "release_threshold": self.release_threshold,
            },
        )
