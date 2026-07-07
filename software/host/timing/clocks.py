"""Deterministic simulated clocks — reusable ``ClockNs``-compatible time sources (C1).

Failure modes these clocks exist to prevent (lead-with-the-failure-mode):

* **Wall time in tests/sim => non-reproducible fixtures.** Any clock here is a pure
  function of its construction arguments — no ``time`` calls anywhere — so two identically
  constructed clocks emit byte-identical sequences on any machine (the P-B/P-C determinism
  bar the golden fixtures depend on).
* **Silently repeated/clamped stamps => forged duplicate time.** A scripted clock that
  "helpfully" repeats its last stamp when exhausted manufactures duplicate timestamps that
  alignment cannot distinguish from a real stalled clock. :class:`ScriptedClock` raises
  :class:`ClockExhausted` instead — loud, typed, catchable by the C4 chaos bench.
* **Int64 overflow => unrepresentable stamps.** A lattice ticks forever; past ``2**63-1``
  its stamps could no longer round-trip through on-disk encodings. :class:`LatticeClock`
  refuses to emit past the ceiling rather than hand out a stamp the dataset cannot hold.

Both clocks satisfy the existing ``sensors.interface.ClockNs`` seam (a plain
``Callable[[], int]`` returning monotonic nanoseconds) — this module deliberately does NOT
import that ABC's module; compatibility is structural and pinned by tests. They generalize
the two patterns already in the tree: ``SimRobot``'s ``start_ns + i*period_ns`` lattice and
``sensors.sim_proprio._SteppingClock``. Both are :data:`~timing.stamp.ClockDomain.MONOTONIC`
by construction (strictly increasing, never zero) and expose ``domain`` saying so.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from timing.stamp import MAX_STAMP_NS, ClockDomain, validate_stamp_ns

__all__ = [
    "ClockExhausted",
    "LatticeClock",
    "ScriptedClock",
]


class ClockExhausted(RuntimeError):
    """A simulated clock was asked for a stamp it cannot honestly emit.

    Two cases: a :class:`ScriptedClock` past the end of its script, and a
    :class:`LatticeClock` whose next tick would exceed the int64 stamp ceiling. Raised
    instead of repeating, clamping or wrapping — silent time reuse/truncation would forge
    duplicate/backwards stamps and poison alignment undetectably. Typed (not a bare
    ``RuntimeError`` string-match) so the C4 chaos bench can assert exhaustion explicitly.
    """


class LatticeClock:
    """Strictly-increasing fixed-lattice clock: call ``i`` returns ``start_ns + i*period_ns``.

    The reusable form of the ``SimRobot`` / ``_SteppingClock`` stepping pattern: a
    deterministic, zero-jitter monotonic clock for seeded sources and golden fixtures.
    Satisfies the ``ClockNs`` seam (a plain callable returning int nanoseconds).

    ``start_ns`` must be a valid stamp (``>= 1`` — the first call must never emit the
    zero "never stamped" sentinel) and ``period_ns >= 1`` (strict monotonicity, the
    time-sync contract). A call whose stamp would exceed ``2**63-1`` raises instead of
    emitting a value on-disk encodings cannot hold.
    """

    __slots__ = ("_index", "_period_ns", "_start_ns")

    #: The domain of every stamp this clock emits — strictly increasing by construction.
    domain: ClassVar[ClockDomain] = ClockDomain.MONOTONIC

    def __init__(self, start_ns: int, period_ns: int) -> None:
        # Fail loud at construction (never mid-stream) on any value that would break the
        # monotonic contract: zero/negative start, zero/negative period, bool, non-int.
        self._start_ns = validate_stamp_ns(start_ns, name="start_ns")
        self._period_ns = validate_stamp_ns(period_ns, name="period_ns")
        self._index = 0

    def __call__(self) -> int:
        """Return the next lattice stamp (first call returns ``start_ns`` exactly)."""
        value = self._start_ns + self._index * self._period_ns
        if value > MAX_STAMP_NS:
            raise ClockExhausted(
                f"LatticeClock overflow at tick {self._index}: stamp {value} exceeds "
                f"2**63-1 — refusing to emit a stamp int64 encodings cannot hold"
            )
        self._index += 1
        return value


class ScriptedClock:
    """Plays back a validated strictly-increasing stamp script, then fails loud.

    The chaos-bench (C4) clock: a test scripts the exact stamps (including jitter, gaps —
    anything strictly increasing) and every consumer sees precisely that timeline,
    reproducibly. Satisfies the ``ClockNs`` seam (a plain callable returning int ns).

    The script is validated at construction — every stamp a valid nanosecond value
    (:func:`~timing.stamp.validate_stamp_ns`), strictly increasing, non-empty — so a
    backwards or duplicate scripted timeline is a loud constructor error, not a silent
    poisoned fixture. Once exhausted, calling raises :class:`ClockExhausted` (never
    repeats or clamps).
    """

    __slots__ = ("_index", "_stamps")

    #: The domain of every stamp this clock emits — strict increase is enforced up front.
    domain: ClassVar[ClockDomain] = ClockDomain.MONOTONIC

    def __init__(self, stamps: Sequence[int]) -> None:
        validated = tuple(
            validate_stamp_ns(s, name=f"stamps[{i}]") for i, s in enumerate(stamps)
        )
        if not validated:
            raise ValueError(
                "ScriptedClock needs at least one stamp — an empty script is a clock "
                "that can never tick (caller bug, not a timeline)"
            )
        for i in range(1, len(validated)):
            if validated[i] <= validated[i - 1]:
                raise ValueError(
                    f"ScriptedClock script must be strictly increasing: stamps[{i}]="
                    f"{validated[i]} <= stamps[{i - 1}]={validated[i - 1]} — a repeating/"
                    "backwards script would replay non-monotonic time"
                )
        self._stamps = validated
        self._index = 0

    def __call__(self) -> int:
        """Return the next scripted stamp; :class:`ClockExhausted` past the end."""
        if self._index >= len(self._stamps):
            raise ClockExhausted(
                f"ScriptedClock exhausted after {len(self._stamps)} stamp(s) — refusing "
                "to repeat or clamp (silent reuse would forge duplicate timestamps)"
            )
        value = self._stamps[self._index]
        self._index += 1
        return value
