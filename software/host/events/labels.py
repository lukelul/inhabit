"""Ground-truth contact-event labels derived from a scenario's scripted timeline (P-D/D1).

No detector can be *graded* without labeled truth to grade it against. This module mints
that truth — the exact :class:`~events.interface.Event` list a
:class:`~sim.scenario.ContactScenario` **intends** — completely independently of any
:class:`~events.interface.EventDetector`. It reads the scenario's own scripted phases (the
authoritative script), never re-detecting anything from proprioceptive/tactile *signals*.

Why this is truth, not detection
--------------------------------
A :class:`~sim.scenario.ContactScenario` is a validated, ordered tile of
:class:`~sim.scenario.ContactPhase` windows. Each *contact* phase (``contact_start | slip |
impact | release``) is a scripted last-centimeter event with a known kind and a known onset
instant. The sim (``sensors.sim_scenario``) already stamps exactly those tokens onto the
FROZEN ``PVTSample.tactile_event`` field along one monotonic timeline; here we go back to the
SOURCE — ``scenario.phases`` — for the kind/order/count, and use the episode only to learn
where scenario-time ``t=0`` lands on that monotonic clock. The result is a reproducible
labeled signal: the ground truth a precision/recall scorer (``events.scoring``) penalizes
misses AND false positives against.

Failure modes this module leads with
------------------------------------
* **Fabricated events.** A scenario with no scripted contact (a free-space negative case)
  yields ``[]`` — precious for false-positive testing. We never invent a contact that the
  script does not contain.
* **A scripted phase the episode never sampled.** If a contact phase is shorter than the
  tactile sample period the episode would carry no sample for it, so the label could not be
  placed on a real monotonic instant. We fail LOUD rather than silently drop a scripted
  event — ground truth must be authoritative.
* **A clock the labels don't share.** Every emitted ``Event.t_monotonic_ns`` is the
  timestamp of a real tactile sample on the SAME single monotonic clock the PVT streams and
  a detector's events use, so truth and detection are comparable without a clock remap.

Determinism: stdlib-only (NO numpy — hard P-B/P-C invariant), no wall clock. The scenario
episode is built by the deterministic ``build_scenario_episode`` (B7), so the same
``(name, seed)`` yields byte-identical truth labels. This module reads FROZEN contracts
(``PVTSample``, ``Event``/``EventKind``) and never mutates them.
"""
from __future__ import annotations

from inhabit_can.pvt import Episode, PVTSample
from logger.jitter import JitterBudget
from sim.scenario import CONTACT_KINDS, ContactPhase, ContactScenario, example_scenario
from tools.dataset.scenario_episode import build_scenario_episode

from .interface import Event, EventKind

__all__ = [
    "GROUND_TRUTH_CHANNEL",
    "GROUND_TRUTH_DETECTOR",
    "KIND_BY_TACTILE_TOKEN",
    "ground_truth_events",
    "ground_truth_events_from_episode",
    "scripted_event_kinds",
]

#: The registry-style ``detector`` name stamped on every truth Event, so a label is
#: attributable to *the scenario script* (not a detector) when it is recorded/diffed.
GROUND_TRUTH_DETECTOR = "scenario_ground_truth"

#: The evidence channel a truth Event traces to: the FROZEN ``PVTSample.tactile_event``
#: field the sim scripted the contact token onto.
GROUND_TRUTH_CHANNEL = "tactile_event"

#: Map each FROZEN tactile token (``sim.scenario.CONTACT_KINDS``) to the FROZEN
#: :class:`~events.interface.EventKind` it labels. Explicit because the ``"release"`` token
#: maps to :attr:`EventKind.CONTACT_RELEASE` (whose *value* is ``"contact_release"``), so a
#: naive ``EventKind(token)`` would fail — the vocabularies overlap but are not identical.
KIND_BY_TACTILE_TOKEN: dict[str, EventKind] = {
    "contact_start": EventKind.CONTACT_START,
    "slip": EventKind.SLIP,
    "impact": EventKind.IMPACT,
    "release": EventKind.CONTACT_RELEASE,
}

# Fail loud NOW (import time) if the scenario vocabulary ever grows a contact token this map
# does not cover — a silent gap would drop a scripted event kind from ground truth.
_UNMAPPED = set(CONTACT_KINDS) - set(KIND_BY_TACTILE_TOKEN)
if _UNMAPPED:  # pragma: no cover - guard fires only if sim.scenario adds an unmapped token
    raise RuntimeError(
        f"KIND_BY_TACTILE_TOKEN is missing scenario contact token(s) {sorted(_UNMAPPED)}; "
        "a new tactile token needs an explicit EventKind mapping (labels would silently "
        "drop it otherwise)"
    )


def scripted_event_kinds(scenario: ContactScenario) -> list[EventKind]:
    """The ordered :class:`EventKind`\\ s this scenario scripts — pure, no episode needed.

    One entry per *contact* phase, in timeline order; the non-contact ``approach``/``settle``
    filler phases produce nothing. A free-space scenario (no contact phases) returns ``[]``.
    This is the authoritative kind/count of the scenario's ground truth, independent of any
    episode's sampling — :func:`ground_truth_events_from_episode` derives the same list and
    only adds the monotonic timestamps.
    """
    return [
        KIND_BY_TACTILE_TOKEN[phase.kind]
        for phase in scenario.phases
        if phase.is_contact()
    ]


def _tactile_anchor_and_samples(
    episode: Episode,
) -> tuple[int, list[PVTSample]]:
    """Find the tactile stream in ``episode`` and return ``(t=0 anchor ns, its samples)``.

    The tactile stream is the ONE modality that stamps ``PVTSample.tactile_event`` (the
    proprio/visual sources leave it ``None``), so it is identified by evidence — the chain
    that ever carries a token — not by a hard-coded chain index. Its earliest sample is
    scenario-time ``t=0`` (the sim anchors each stream's timeline at its first stamp), which
    is the anchor that maps a phase's scenario-local ``start_s`` back onto the monotonic
    clock. Fails loud if the episode has no single, unambiguous tactile stream.
    """
    token_chains = {
        s.chain_index for s in episode.samples if s.tactile_event is not None
    }
    if len(token_chains) != 1:
        raise ValueError(
            f"episode {episode.episode_id!r} has {len(token_chains)} tactile stream(s) "
            f"(chains carrying a tactile_event token: {sorted(token_chains)}); ground truth "
            "needs exactly one — a scenario with scripted contact must materialize its "
            "tokens on a single tactile stream"
        )
    chain = token_chains.pop()
    tactile = sorted(
        (s for s in episode.samples if s.chain_index == chain),
        key=lambda s: s.timestamp_ns,
    )
    return tactile[0].timestamp_ns, tactile


def ground_truth_events_from_episode(
    episode: Episode, scenario: ContactScenario
) -> list[Event]:
    """The scenario's scripted contact events as monotonic-stamped :class:`Event`\\ s.

    ``scenario`` is the authoritative script (kind, order, count); ``episode`` supplies the
    monotonic timeline the labels must live on. For each scripted contact phase we take its
    onset to be the EARLIEST tactile sample that falls inside that phase — decided by the
    scenario's OWN :meth:`~sim.scenario.ContactScenario.active_at` window logic (never
    re-implemented, never a token heuristic, so even two adjacent same-token phases stay
    distinct). That sample's ``timestamp_ns`` is a real instant on the shared monotonic
    clock, so a detector's event within the scorer's tolerance can match it exactly.

    A free-space scenario (no contact phases) returns ``[]`` before touching the episode —
    the negative case has no truth and needs no tactile stream. A scripted phase with no
    sample inside it raises :class:`ValueError` (see the module docstring): ground truth
    never silently drops an event the script contains.
    """
    contact_phases = [phase for phase in scenario.phases if phase.is_contact()]
    if not contact_phases:
        return []

    anchor_ns, tactile = _tactile_anchor_and_samples(episode)
    # Membership computed ONCE per sample via the scenario's own boundary logic, using the
    # exact elapsed-time formula the sim used to stamp the token (identical float => identical
    # phase), so a token-bearing sample maps back to the phase that produced it.
    membership: list[tuple[PVTSample, ContactPhase | None]] = [
        (s, scenario.active_at((s.timestamp_ns - anchor_ns) / 1e9)) for s in tactile
    ]

    events: list[Event] = []
    for phase in contact_phases:
        # `tactile` is timestamp-sorted, so the first match is the phase's onset instant.
        onset = next((s for s, ph in membership if ph is phase), None)
        if onset is None:
            raise ValueError(
                f"scenario {scenario.name!r} phase {phase.kind!r} at start_s={phase.start_s} "
                "has no tactile sample inside its window in this episode — the episode's "
                "sampling is too coarse to place this scripted event on a real monotonic "
                "instant (ground truth refuses to fabricate or drop it)"
            )
        events.append(
            Event(
                kind=KIND_BY_TACTILE_TOKEN[phase.kind],
                t_monotonic_ns=onset.timestamp_ns,
                confidence=1.0,
                channel=GROUND_TRUTH_CHANNEL,
                detector=GROUND_TRUTH_DETECTOR,
            )
        )
    return events


def ground_truth_events(
    name: str, *, seed: int = 7, budget: JitterBudget | None = None
) -> list[Event]:
    """Ground-truth events for a built-in scenario, by ``name`` + ``seed``.

    Builds the deterministic, jitter-gated scenario episode (``build_scenario_episode`` — the
    same B7 builder the CLI and the C7 bench use) and reads the scripted contact events off
    its monotonic timeline via :func:`ground_truth_events_from_episode`. ``name`` must be a
    registered scenario (``sim.scenario.EXAMPLE_SCENARIOS``); an unknown name fails loud
    through the builder. Deterministic: same ``(name, seed)`` => byte-identical labels.
    """
    episode = build_scenario_episode(name, seed=seed, budget=budget)
    scenario = example_scenario(name)
    return ground_truth_events_from_episode(episode, scenario)
