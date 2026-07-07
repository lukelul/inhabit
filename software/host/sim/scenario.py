"""Contact scenario spec — scripted last-centimeter contact timelines (Phase P-B/B4).

The wedge of the whole dataset is the **last centimeter**: contact, slip, impact,
release. B5 (``sim-tactile`` / ``sim-frames`` sources) needs to know, deterministically,
*when* each contact event fires and *over what window*, so it can stamp the already-FROZEN
``PVTSample.tactile_event`` / ``camera_frame_id`` fields onto a monotonic timeline. This
module is that script — a small, validated, serializable value; NOT a physics engine and
NOT a rules engine (PONYTAIL). Force curves, friction models, and per-sample synthesis are
deliberately out of scope; they land in later tasks.

Contract alignment (do not drift):

* ``ContactPhase.kind`` for a *contact* phase is one of the FROZEN tactile tokens carried by
  ``inhabit_can.pvt.PVTSample.tactile_event`` — ``contact_start | slip | impact | release``
  — plus two *non-contact* filler kinds (``approach``, ``settle``) for the gaps where no
  tactile event fires. No new tokens are invented here; B5 aligns on exactly this set.
* Stdlib-only, deterministic, **NO numpy** (hard P-B invariant): serialization is plain
  :mod:`json`, so committed golden scenarios stay byte-stable across machines and CI.
* :class:`ContactScenario` is a value (dataclass ``eq``) so ``from_dict(to_dict(s)) == s``
  and JSON round-trip equality are *meaningful* — the byte-stability guarantee the golden
  fixture rests on.

Validation is fail-loud (mirrors ``tools.dataset.sim_adapter.SimConfig.validate``): a
physically-nonsensical or ambiguous script raises :class:`ValueError` at spec time, not
silently later while B5 is stamping samples.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CONTACT_KINDS",
    "EXAMPLE_SCENARIOS",
    "NONCONTACT_KINDS",
    "PHASE_KINDS",
    "PICK_PLACE",
    "SLIP_RECOVERY",
    "ContactPhase",
    "ContactScenario",
    "example_scenario",
]

#: The FROZEN tactile tokens — must match ``PVTSample.tactile_event``'s vocabulary
#: exactly (``contact_start | slip | impact | release``). A contact phase's ``kind`` is
#: emitted verbatim into ``tactile_event`` by B5, so these are the ONLY contact kinds.
CONTACT_KINDS: tuple[str, ...] = ("contact_start", "slip", "impact", "release")

#: Non-contact filler kinds for the gaps (free-space motion before touch, and the
#: post-release settle). These never become a ``tactile_event`` token — a sample inside an
#: ``approach``/``settle`` window carries ``tactile_event=None``.
NONCONTACT_KINDS: tuple[str, ...] = ("approach", "settle")

#: Every legal ``ContactPhase.kind``. Anything else is rejected by :meth:`ContactScenario.validate`.
PHASE_KINDS: tuple[str, ...] = CONTACT_KINDS + NONCONTACT_KINDS

# Float comparison epsilon for phase-boundary contiguity/overlap checks. Serialized times
# are JSON floats; a tolerance keeps the "phase B starts exactly where A ended" check robust
# to representation without loosening the overlap rejection to anything meaningful.
_EPS = 1e-9


@dataclass(frozen=True)
class ContactPhase:
    """One phase of a contact script: a ``kind`` active over ``[start_s, start_s+duration_s)``.

    Frozen (immutable value) so a :class:`ContactScenario` built from phases has meaningful
    dataclass equality and round-trips exactly. The window is half-open ``[start, end)`` so
    adjacent phases sharing a boundary do NOT both claim the boundary instant — the
    "active event at time t" query stays unambiguous (see :meth:`ContactScenario.active_at`).

    ``kind`` is one of :data:`PHASE_KINDS`. For a *contact* kind the token is what B5 writes
    into ``PVTSample.tactile_event`` for samples inside this window; a non-contact kind
    (``approach``/``settle``) maps to ``tactile_event=None``.
    """

    kind: str
    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        """Exclusive end of the phase window (``start_s + duration_s``)."""
        return self.start_s + self.duration_s

    def is_contact(self) -> bool:
        """True if this phase emits a tactile token (i.e. ``kind`` is a contact kind)."""
        return self.kind in CONTACT_KINDS

    def to_dict(self) -> dict[str, Any]:
        """Plain-``dict`` form for JSON. Floats stay floats so round-trip is exact."""
        return {"kind": self.kind, "start_s": self.start_s, "duration_s": self.duration_s}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ContactPhase:
        """Rebuild from :meth:`to_dict` output.

        Failure mode guarded: a truncated/foreign dict missing a required key would raise an
        opaque ``KeyError`` deep in deserialization. Fail loud with the offending phase and
        the exact missing keys instead, so a bad golden/scenario file is obvious at load.
        """
        missing = {"kind", "start_s", "duration_s"} - set(d)
        if missing:
            raise ValueError(f"phase dict missing keys {sorted(missing)}: {dict(d)!r}")
        # Coerce times to float so an int in JSON (e.g. ``0``) compares/round-trips as the
        # same value a Python literal ``0.0`` would produce — keeps eq stable across sources.
        return cls(
            kind=str(d["kind"]),
            start_s=float(d["start_s"]),
            duration_s=float(d["duration_s"]),
        )


@dataclass(frozen=True)
class ContactScenario:
    """An ordered, validated, serializable last-centimeter contact script.

    A scenario is an ordered list of contiguous :class:`ContactPhase` windows that tile a
    ``[0, total_duration_s)`` timeline. It answers exactly the question B5 asks: *which
    tactile token (if any) is active at time t?* — no more. It is a frozen value so
    ``from_dict(to_dict(s)) == s`` and the JSON round-trips byte-for-byte, which is what the
    committed golden fixture asserts.

    Build via the module constants / :func:`example_scenario`, or construct directly and call
    :meth:`validate` (constructors do NOT auto-validate, mirroring ``SimConfig`` — validation
    is an explicit fail-loud gate so callers choose when to pay for it).
    """

    name: str
    phases: tuple[ContactPhase, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Accept a plain list at construction (ergonomic + what from_dict builds) but store a
        # tuple so the value is hashable/immutable and equality is order-sensitive and stable.
        if not isinstance(self.phases, tuple):
            object.__setattr__(self, "phases", tuple(self.phases))

    @property
    def total_duration_s(self) -> float:
        """End of the last phase (``0.0`` for an empty scenario). The scripted timeline length."""
        if not self.phases:
            return 0.0
        return self.phases[-1].end_s

    def validate(self) -> None:
        """Reject a physically-nonsensical or ambiguous script before B5 drives it.

        Fail-loud (mirrors ``SimConfig.validate``): every check below leads with the failure
        mode it prevents, so a bad scenario blows up at spec time with a clear message instead
        of silently mislabeling samples downstream. Guards, in order:

        * **Empty name** — an unnamed scenario can't be referenced by the CLI/golden, and an
          empty ``name`` breaks round-trip identity. Reject it.
        * **Empty phase list** — an empty script has no timeline for B5 to stamp; almost
          always a construction bug. Reject rather than silently emit zero events.
        * **Unknown ``kind``** — a typo'd or invented token would (for a contact kind) leak a
          non-frozen value into ``PVTSample.tactile_event`` and corrupt the labeled signal.
          Only :data:`PHASE_KINDS` are allowed.
        * **Non-positive / negative-time window** — ``duration_s <= 0`` is a zero/negative
          window that can't host a sample; ``start_s < 0`` predates the timeline origin.
        * **First phase not at 0.0** — the timeline must start at the origin so ``active_at``
          and B5's sample stamping share one zero; a gap before the first phase is ambiguous.
        * **Out-of-order / overlapping / non-contiguous phases** — phases must be sorted and
          *tile* the timeline (each starts exactly where the previous ended). An overlap makes
          "which event at t" ambiguous; a gap leaves an unlabeled hole. Both are rejected so
          the timeline is a clean partition.
        * **``contact_start`` never released** — a script that grabs and never lets go is
          physically nonsensical (the gripper is stuck closed forever). Every ``contact_start``
          must be followed (later in time) by a ``release``. This is the one cross-phase
          semantic check B4 owns; it keeps scripted episodes physically coherent.
        """
        if not self.name:
            raise ValueError("scenario name must be a non-empty string")
        if not self.phases:
            raise ValueError(f"scenario {self.name!r} must have at least one phase")

        cursor = 0.0
        for i, ph in enumerate(self.phases):
            if ph.kind not in PHASE_KINDS:
                raise ValueError(
                    f"scenario {self.name!r} phase {i} has unknown kind {ph.kind!r}; "
                    f"allowed: {sorted(PHASE_KINDS)}"
                )
            if ph.duration_s <= 0:
                raise ValueError(
                    f"scenario {self.name!r} phase {i} ({ph.kind!r}) has non-positive "
                    f"duration_s={ph.duration_s!r} (must be > 0)"
                )
            if ph.start_s < 0:
                raise ValueError(
                    f"scenario {self.name!r} phase {i} ({ph.kind!r}) has negative "
                    f"start_s={ph.start_s!r}"
                )
            if abs(ph.start_s - cursor) > _EPS:
                # Distinguish the two failure directions in the message for a fast diagnosis.
                if ph.start_s > cursor:
                    raise ValueError(
                        f"scenario {self.name!r} has a gap before phase {i} ({ph.kind!r}): "
                        f"expected start_s={cursor!r}, got {ph.start_s!r}"
                    )
                raise ValueError(
                    f"scenario {self.name!r} phase {i} ({ph.kind!r}) overlaps/precedes the "
                    f"previous phase: expected start_s={cursor!r}, got {ph.start_s!r}"
                )
            cursor = ph.end_s

        self._validate_grasp_balance()

    def _validate_grasp_balance(self) -> None:
        """Reject a ``contact_start`` with no later ``release`` (grasp that never lets go).

        Failure mode: a scripted episode that grabs an object and holds it forever is not a
        last-centimeter *interaction* — it never produces the release signal detectors and
        datasets care about. We require the counts/ordering to make sense: every
        ``contact_start`` is matched by a subsequent ``release``. ``slip``/``impact`` are
        mid-contact events, so they are only valid *inside* an open grasp (a slip or impact
        with nothing gripped is physically nonsensical); a bare ``release`` with no preceding
        open grasp is likewise rejected as it implies letting go of nothing.
        """
        open_grasps = 0
        for i, ph in enumerate(self.phases):
            if ph.kind == "contact_start":
                open_grasps += 1
            elif ph.kind == "release":
                if open_grasps == 0:
                    raise ValueError(
                        f"scenario {self.name!r} phase {i} is a 'release' with no open "
                        f"'contact_start' before it"
                    )
                open_grasps -= 1
            elif ph.kind in ("slip", "impact"):
                if open_grasps == 0:
                    raise ValueError(
                        f"scenario {self.name!r} phase {i} ({ph.kind!r}) occurs with no open "
                        f"grasp — mid-contact events require an active 'contact_start'"
                    )
        if open_grasps > 0:
            raise ValueError(
                f"scenario {self.name!r} has {open_grasps} 'contact_start' phase(s) with no "
                f"matching later 'release' (a grasp that never lets go)"
            )

    def active_at(self, t_s: float) -> ContactPhase | None:
        """Return the phase whose half-open window ``[start, end)`` contains ``t_s``.

        ``None`` if ``t_s`` is outside the scenario timeline (before ``0`` or at/after
        ``total_duration_s``). Half-open windows mean a boundary instant belongs to the phase
        that *starts* there, never the one that ends there, so the answer is unambiguous even
        when phases abut. This is the primitive B5 calls once per sample timestamp.
        """
        for ph in self.phases:
            if ph.start_s - _EPS <= t_s < ph.end_s - _EPS:
                return ph
        return None

    def tactile_event_at(self, t_s: float) -> str | None:
        """The FROZEN tactile token active at ``t_s``, or ``None``.

        This is the direct B5 hook: it returns exactly what belongs in
        ``PVTSample.tactile_event`` for a sample at ``t_s`` — a contact token
        (``contact_start | slip | impact | release``) inside a contact window, or ``None``
        inside an ``approach``/``settle`` window or outside the timeline. B5 never has to know
        the phase kinds; it just copies this value.
        """
        ph = self.active_at(t_s)
        if ph is None or not ph.is_contact():
            return None
        return ph.kind

    # -- serialization (stdlib json only; round-trippable value) ----------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain-``dict`` form: ``{"name", "phases": [phase dicts]}``. JSON-ready, no numpy."""
        return {"name": self.name, "phases": [ph.to_dict() for ph in self.phases]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ContactScenario:
        """Rebuild from :meth:`to_dict` output such that ``from_dict(to_dict(s)) == s``.

        Failure mode guarded: a malformed dict (missing ``name``/``phases``, or ``phases`` not
        a list) would otherwise raise an opaque ``KeyError``/``TypeError`` mid-parse. Fail loud
        with the offending value. Does NOT auto-validate — call :meth:`validate` explicitly.
        """
        missing = {"name", "phases"} - set(d)
        if missing:
            raise ValueError(f"scenario dict missing keys {sorted(missing)}: {dict(d)!r}")
        raw_phases = d["phases"]
        if not isinstance(raw_phases, list):
            raise ValueError(f"scenario 'phases' must be a list, got {type(raw_phases).__name__}")
        return cls(
            name=str(d["name"]),
            phases=tuple(ContactPhase.from_dict(p) for p in raw_phases),
        )

    def dumps(self, *, indent: int | None = 2) -> str:
        """Serialize to a JSON string (stdlib :mod:`json`).

        ``indent=2`` and ``sort_keys=False`` (insertion order) are pinned so the committed
        golden fixture is stable and human-diffable; a trailing newline is NOT added here (the
        fixture writer owns the on-disk EOL, mirroring ``make_sample_canlog``).
        """
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    @classmethod
    def loads(cls, s: str) -> ContactScenario:
        """Parse a JSON string produced by :meth:`dumps` back into a value (no validation)."""
        return cls.from_dict(json.loads(s))


# -- built-in example scenarios --------------------------------------------------------------
# Realistic inputs for B5 and the test suite. Times are seconds on the scenario-local
# timeline; phases tile [0, total) contiguously so every one passes ``validate()``. Kept
# short and hand-checkable — these are scripts, not captures.

#: A clean pick-and-place: free-space approach, grasp, hold (contact_start's window IS the
#: sustained grasp until release), then release and settle. The canonical happy path.
PICK_PLACE: ContactScenario = ContactScenario(
    name="pick_place",
    phases=(
        ContactPhase(kind="approach", start_s=0.0, duration_s=0.50),
        ContactPhase(kind="contact_start", start_s=0.50, duration_s=0.80),
        ContactPhase(kind="release", start_s=1.30, duration_s=0.20),
        ContactPhase(kind="settle", start_s=1.50, duration_s=0.30),
    ),
)

#: A richer last-centimeter interaction: approach, grasp, a mid-grasp slip and a re-seating
#: impact (the failure/recovery signal that is the wedge), then release and settle.
SLIP_RECOVERY: ContactScenario = ContactScenario(
    name="slip_recovery",
    phases=(
        ContactPhase(kind="approach", start_s=0.0, duration_s=0.40),
        ContactPhase(kind="contact_start", start_s=0.40, duration_s=0.30),
        ContactPhase(kind="slip", start_s=0.70, duration_s=0.15),
        ContactPhase(kind="impact", start_s=0.85, duration_s=0.10),
        ContactPhase(kind="release", start_s=0.95, duration_s=0.20),
        ContactPhase(kind="settle", start_s=1.15, duration_s=0.25),
    ),
)

#: Registry of built-in scenarios by name — the set the CLI (B7) and tests select from.
EXAMPLE_SCENARIOS: dict[str, ContactScenario] = {
    PICK_PLACE.name: PICK_PLACE,
    SLIP_RECOVERY.name: SLIP_RECOVERY,
}


def example_scenario(name: str) -> ContactScenario:
    """Look up a built-in scenario by name (fail-loud on unknown, listing what's available).

    Mirrors the plugin-registry ``make(name)`` ergonomics: an unknown name is a caller bug,
    so raise :class:`ValueError` with the valid choices rather than returning ``None``.
    """
    try:
        return EXAMPLE_SCENARIOS[name]
    except KeyError:
        raise ValueError(
            f"unknown scenario {name!r}; available: {sorted(EXAMPLE_SCENARIOS)}"
        ) from None
