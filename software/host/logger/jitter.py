"""Monotonic inter-sample jitter measurement and the budget gate.

ONE clock, measured jitter, reject out-of-budget episodes.

We sample joint telemetry at a nominal rate. The CAN node emits at a fixed period;
the host stamps each frame with ``time.monotonic_ns()`` at RX. The *delta* between
consecutive monotonic timestamps should be ~constant. Anything that perturbs that —
USB-CAN buffering, dropped frames, scheduler stalls, the host going to sleep — shows
up as jitter and corrupts time alignment between PVT streams. So we measure it and
quarantine episodes that exceed budget.

Definitions
-----------
Given monotonic timestamps t[0..N-1], the inter-sample intervals are
``dt[i] = t[i+1] - t[i]`` (ns). We report:
- ``period_ns``      : median dt (robust nominal rate estimate)
- ``jitter_p99_ns``  : 99th-percentile absolute deviation |dt - period|
- ``jitter_max_ns``  : worst absolute deviation
- ``dropouts``       : intervals exceeding ``max_gap_factor * period`` (a missed frame)
- ``backwards``      : intervals <= 0 (monotonic clock must never go backwards)

Why deviation-from-median and not std-dev: a few large dropouts would inflate std
and hide the typical timing quality. p99 of |deviation| is what training-time
alignment actually cares about, and it is robust to the rate not being known a priori.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class JitterStats:
    """Measured timing quality for one episode (all times in nanoseconds)."""

    n_samples: int
    n_intervals: int
    period_ns: int
    jitter_p99_ns: int
    jitter_max_ns: int
    dropouts: int
    backwards: int

    def as_dict(self) -> dict[str, int]:
        return {
            "n_samples": self.n_samples,
            "n_intervals": self.n_intervals,
            "period_ns": self.period_ns,
            "jitter_p99_ns": self.jitter_p99_ns,
            "jitter_max_ns": self.jitter_max_ns,
            "dropouts": self.dropouts,
            "backwards": self.backwards,
        }


@dataclass(frozen=True)
class JitterBudget:
    """The documented timing budget. An episode passes only if ALL hold.

    Defaults target a ~100 Hz (10 ms) telemetry stream with the CAN-over-USB jitter
    we expect on a desktop host:
      * ``max_jitter_p99_ns = 2 ms`` — 99% of intervals within 2 ms of the median
        period. At 10 ms nominal that is +/-20%, generous enough for a non-RT host
        yet tight enough that frames still align to a 30/60 fps video timeline.
      * ``max_gap_factor = 2.5`` — an interval > 2.5x the period means a frame was
        dropped; the window has a hole and is not exported.
      * ``min_samples = 2`` — need at least one interval to have any timing signal.
    These are deliberately conservative starting values; tune per deployment and
    record the budget alongside the dataset (the recorder stamps it into metadata).
    """

    max_jitter_p99_ns: int = 2_000_000  # 2 ms
    max_gap_factor: float = 2.5
    min_samples: int = 2

    def check(self, stats: JitterStats) -> tuple[bool, list[str]]:
        """Return (ok, reasons). ``reasons`` is empty iff ok."""
        reasons: list[str] = []
        if stats.n_samples < self.min_samples:
            reasons.append(
                f"too few samples: {stats.n_samples} < min {self.min_samples}"
            )
        if stats.backwards > 0:
            reasons.append(
                f"monotonic clock went backwards on {stats.backwards} interval(s)"
            )
        if stats.dropouts > 0:
            reasons.append(
                f"{stats.dropouts} dropout(s): interval > {self.max_gap_factor}x period"
            )
        if stats.jitter_p99_ns > self.max_jitter_p99_ns:
            reasons.append(
                f"jitter p99 {stats.jitter_p99_ns} ns > budget {self.max_jitter_p99_ns} ns"
            )
        return (len(reasons) == 0, reasons)


def _percentile_sorted(sorted_vals: Sequence[int], pct: float) -> int:
    """Nearest-rank percentile on an already-sorted, non-empty sequence."""
    if not sorted_vals:
        return 0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # nearest-rank: rank in [1, n]
    rank = max(1, min(len(sorted_vals), round(pct / 100.0 * len(sorted_vals))))
    return sorted_vals[rank - 1]


def _median_sorted(sorted_vals: Sequence[int]) -> int:
    n = len(sorted_vals)
    if n == 0:
        return 0
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) // 2


def compute_jitter(
    timestamps_ns: Sequence[int],
    budget: JitterBudget | None = None,
) -> JitterStats:
    """Measure jitter from a sequence of monotonic timestamps.

    No external deps (pure stdlib) so this is cheap to call on the hot path and in
    tests. ``budget`` is only needed for the dropout factor; if omitted, defaults.
    """
    budget = budget or JitterBudget()
    n = len(timestamps_ns)
    if n < 2:
        return JitterStats(
            n_samples=n,
            n_intervals=0,
            period_ns=0,
            jitter_p99_ns=0,
            jitter_max_ns=0,
            dropouts=0,
            backwards=0,
        )

    intervals = [
        timestamps_ns[i + 1] - timestamps_ns[i] for i in range(n - 1)
    ]
    backwards = sum(1 for dt in intervals if dt <= 0)

    sorted_dt = sorted(intervals)
    period = _median_sorted(sorted_dt)

    deviations = sorted(abs(dt - period) for dt in intervals)
    jitter_p99 = _percentile_sorted(deviations, 99.0)
    jitter_max = deviations[-1] if deviations else 0

    gap_threshold = period * budget.max_gap_factor
    dropouts = sum(1 for dt in intervals if period > 0 and dt > gap_threshold)

    return JitterStats(
        n_samples=n,
        n_intervals=len(intervals),
        period_ns=period,
        jitter_p99_ns=jitter_p99,
        jitter_max_ns=jitter_max,
        dropouts=dropouts,
        backwards=backwards,
    )
