"""Scenario-driven sim episode builder with the jitter/clock property gate (Phase P-B/B7).

The dataset CLI's ``--sim --scenario X`` path needs a hardware-free episode that exercises
the FULL deterministic sim stack B2-B5 built — seeded+noisy ``SimRobot`` proprio plus the
scenario-driven ``sim-tactile`` / ``sim-frames`` sources — and that provably honours the
one-clock timing contract before it is ever exported. This module is that builder: it
merges the three modality streams onto ONE monotonic timeline, routes the merged
timestamps through the SAME :func:`logger.jitter.compute_jitter` the recorder and the
lerobot exporter budget against, and fails loud if the episode is not clean (backwards
intervals, dropouts, or over-budget jitter). A sim episode that cannot pass its own
timing gate must never become a dataset.

Registry, not imports (the B7 "registered/selectable" criterion)
----------------------------------------------------------------
The tactile and frame streams are built via :func:`sensors.make_sensor_source` — the same
name-based factory the engine uses — NOT by importing the concrete B5 classes. This keeps
the CLI on the plugin path (new capability = a new registered source, never an ``if``
here) and makes the factory wiring itself part of what the B7 tests cover. Because the
registry types streams as ``object``, each yielded sample is isinstance-narrowed to the
FROZEN :class:`~inhabit_can.pvt.PVTSample` and anything else is rejected loudly — a
misbehaving (e.g. third-party entry-point) source must fail at the factory boundary, not
corrupt an export.

One modality per instant (why the streams are phase-offset)
-----------------------------------------------------------
The lerobot exporter groups co-stamped samples into one frame and keeps a per-frame
``camera_frame_id`` / ``tactile_event`` only when every sample in the frame AGREES; a
frame mixing a tactile token with a proprio ``None`` would collapse to ``None`` and
silently drop the very last-centimeter signal the scenario scripts. So the three streams
share one period (:data:`STREAM_PERIOD_NS`) but are offset by one lattice step
(:data:`LATTICE_NS`) each — proprio at ``t0``, tactile at ``t0+10ms``, frames at
``t0+20ms`` — a round-robin over a uniform 10 ms lattice. Every instant carries exactly
one modality (the exporter's agreement invariant holds trivially, so tokens and frame ids
round-trip), and the merged timeline is perfectly uniform, so the jitter gate measures
0 ns jitter by construction. The gate also enforces the design: a timestamp collision
would produce a zero interval, which ``compute_jitter`` counts as ``backwards`` and the
gate rejects.

Determinism: stdlib-only (NO numpy — hard P-B invariant), no wall clock. Proprio noise is
small but non-zero (mirroring the B6 golden fixture) so the seeded-noise path is really
exercised; the seed NEVER perturbs ``timestamp_ns`` (noise is proprioceptive only), which
the B7 property test pins across seeds.
"""
from __future__ import annotations

from inhabit_can.pvt import Episode, PVTSample
from logger.jitter import JitterBudget, compute_jitter
from sensors import make_sensor_source
from sim.robot import NoiseSpec, SimRobot
from sim.scenario import ContactScenario, example_scenario

__all__ = ["LATTICE_NS", "STREAM_PERIOD_NS", "build_scenario_episode"]

#: The uniform merged-timeline step. One modality fires every lattice step, so the merged
#: inter-sample interval is exactly this — the "period" the jitter gate measures.
LATTICE_NS = 10_000_000  # 10 ms => 100 Hz merged, the recorder's nominal budget rate

#: Per-stream sample period: three modalities round-robin the lattice, so each individual
#: stream ticks every third lattice step.
STREAM_PERIOD_NS = 3 * LATTICE_NS

#: Shared epoch (> 0 — never a zero timestamp; mirrors the B6 golden fixture).
_START_NS = 1_000_000_000

#: Chain identities: proprio owns joint 0 (``SimRobot(dof=1)``, matching the golden
#: fixture); tactile and frames take the next indices so every (timestamp, chain) key in
#: the episode is unique and the round-trip verifier's canonical sort is unambiguous.
_TACTILE_CHAIN = 1
_FRAMES_CHAIN = 2

#: Small, non-zero per-channel proprio noise (the B6 golden fixture values) so the seeded
#: B3 noise path is exercised — all-zero noise would silently stop covering it.
_NOISE = NoiseSpec(
    joint_angle_sigma=0.01,
    joint_velocity_sigma=0.02,
    motor_current_sigma=0.005,
    estimated_torque_sigma=0.004,
)


def _collect_registry_stream(
    source_name: str,
    *,
    scenario: ContactScenario,
    seed: int,
    episode_id: str,
    chain_index: int,
    task_label: str | None,
    start_ns: int,
) -> list[PVTSample]:
    """Drain one registry-built scenario source into a list of FROZEN ``PVTSample`` rows.

    Goes through :func:`make_sensor_source` (name-based selection — the plugin path) and
    isinstance-narrows every yielded object: the registry's ``stream()`` is typed
    ``Iterator[object]``, and a source emitting anything but a ``PVTSample`` must fail
    HERE, loudly, before a single row reaches the exporter.
    """
    source = make_sensor_source(
        source_name,
        scenario=scenario,
        seed=seed,
        episode_id=episode_id,
        chain_index=chain_index,
        task_label=task_label,
        start_ns=start_ns,
        period_ns=STREAM_PERIOD_NS,
    )
    samples: list[PVTSample] = []
    with source:
        for obj in source.stream():
            if not isinstance(obj, PVTSample):
                raise TypeError(
                    f"sensor source {source_name!r} yielded {type(obj).__name__}, "
                    "expected PVTSample"
                )
            samples.append(obj)
    return samples


def build_scenario_episode(
    name: str,
    *,
    seed: int = 7,
    task_label: str | None = None,
    budget: JitterBudget | None = None,
) -> Episode:
    """Build one gated, scenario-driven multi-modality sim :class:`Episode` by name.

    ``name`` selects a built-in :data:`sim.scenario.EXAMPLE_SCENARIOS` script (fail-loud
    ``ValueError`` on an unknown name, listing what's available). The returned episode
    interleaves proprio / tactile / frame rows in canonical ``(timestamp_ns, chain_index)``
    order — the same order the round-trip verifier sorts into.

    The jitter/clock property gate (the B7 contract): the merged timestamp sequence is
    routed through :func:`compute_jitter` and checked against ``budget`` (default
    :class:`JitterBudget`). ``backwards == 0``, ``dropouts == 0`` and within-budget p99
    jitter are all enforced by :meth:`JitterBudget.check`; any violation raises
    :class:`ValueError` with the budget's reasons, so a mis-timed sim episode can never
    be exported looking clean.
    """
    scenario = example_scenario(name)
    episode_id = f"sim_{scenario.name}"
    label = task_label or scenario.name

    # Proprio covers the same [0, total_duration) window the scenario sources self-exhaust
    # at: ceil(total/period) ticks, so the last proprio stamp stays one lattice step ahead
    # of the last tactile stamp and the merged lattice stays uniform to the very end.
    total_ns = round(scenario.total_duration_s * 1e9)
    n_ticks = -(-total_ns // STREAM_PERIOD_NS)  # ceil division on ints
    robot = SimRobot(
        dof=1,  # one joint => one row per tick => unique (timestamp, chain) keys
        trajectory="sine",
        seed=seed,
        noise=_NOISE,
        start_ns=_START_NS,
        period_ns=STREAM_PERIOD_NS,
        episode_id=episode_id,
        task_label=label,
    )
    proprio = robot.generate(n_ticks)
    tactile = _collect_registry_stream(
        "sim-tactile",
        scenario=scenario,
        seed=seed,
        episode_id=episode_id,
        chain_index=_TACTILE_CHAIN,
        task_label=label,
        start_ns=_START_NS + LATTICE_NS,
    )
    frames = _collect_registry_stream(
        "sim-frames",
        scenario=scenario,
        seed=seed,
        episode_id=episode_id,
        chain_index=_FRAMES_CHAIN,
        task_label=label,
        start_ns=_START_NS + 2 * LATTICE_NS,
    )

    # ONE timeline: merge in (timestamp_ns, chain_index) order — canonical, deterministic,
    # and by construction collision-free (one modality per lattice instant).
    rows = sorted(proprio + tactile + frames, key=lambda s: (s.timestamp_ns, s.chain_index))

    # The property gate. Runs over ALL merged stamps (not de-duplicated instants), so an
    # accidental cross-stream collision shows up as a zero interval => `backwards` => reject.
    gate = budget or JitterBudget()
    stats = compute_jitter([s.timestamp_ns for s in rows], gate)
    ok, reasons = gate.check(stats)
    if not ok:
        raise ValueError(
            f"scenario episode {name!r} failed the jitter gate: " + "; ".join(reasons)
        )

    episode = Episode(episode_id=episode_id, task_label=label)
    for sample in rows:
        episode.add(sample)
    return episode
