"""B7 — jitter/clock property gate over scenario-driven sim episodes + CLI scenario wiring.

Two contracts are pinned here:

* **The jitter property.** Every built-in scenario, driven through the full sim stack
  (seeded+noisy ``SimRobot`` proprio + registry-built ``sim-tactile``/``sim-frames``),
  merges onto ONE monotonic timeline that ``compute_jitter`` measures as clean:
  ``backwards == 0``, ``dropouts == 0``, within the default :class:`JitterBudget` — in
  fact exactly-zero jitter, because the deterministic stepping clocks tile a uniform
  10 ms lattice by construction. The property holds across scenarios AND seeds (noise is
  proprioceptive only; the seed must never perturb ``timestamp_ns``), and the gate itself
  fails loud when the budget cannot be met — a mis-timed sim episode must never become a
  dataset.
* **The CLI wiring.** ``python -m tools.dataset export --sim --scenario X`` exports a
  lerobot dataset that round-trips through the existing ``--verify`` helper, and the
  modality payloads (FROZEN tactile tokens, monotonic frame ids) actually SURVIVE the
  round-trip — the one-modality-per-instant layout exists precisely so the exporter's
  per-frame agreement rule cannot collapse them to ``None``. Misuse fails loud:
  ``--scenario`` without ``--sim`` and unknown scenario names are argparse errors.

Headless, zero hardware, stdlib + frozen ``PVTSample`` only. NO numpy (P-B invariant).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from export.lerobot import load_lerobot
from logger.jitter import JitterBudget, compute_jitter
from sensors import list_sensor_sources
from sim.scenario import CONTACT_KINDS, EXAMPLE_SCENARIOS
from tools.dataset import scenario_episode
from tools.dataset.__main__ import main
from tools.dataset.scenario_episode import (
    LATTICE_NS,
    build_scenario_episode,
)

_SCENARIO_NAMES = sorted(EXAMPLE_SCENARIOS)


# ---------------------------------------------------------------------------
# The jitter/clock property gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_NAMES)
@pytest.mark.parametrize("seed", [0, 7, 12345])
def test_scenario_episode_timestamps_pass_the_jitter_gate(name: str, seed: int) -> None:
    """The B7 property: merged sim timestamps are monotonic, hole-free, and in budget.

    Runs the episode's own timeline back through ``compute_jitter`` (the same function the
    builder gates on and the recorder/exporter budget against) and asserts the full
    contract — not just "no reasons" but the stronger by-construction facts: strictly
    increasing unique stamps on a uniform lattice, hence exactly-zero measured jitter.
    """
    episode = build_scenario_episode(name, seed=seed)
    ts = [s.timestamp_ns for s in episode.samples]

    # One monotonic timeline: strictly increasing, no duplicate instants.
    assert ts == sorted(ts)
    assert len(set(ts)) == len(ts)

    budget = JitterBudget()
    stats = compute_jitter(ts, budget)
    assert stats.backwards == 0
    assert stats.dropouts == 0
    ok, reasons = budget.check(stats)
    assert ok, f"jitter budget violated: {reasons}"
    # Stepping clocks on a shared uniform lattice: the measured period IS the lattice and
    # the deviation is exactly zero — any drift here means the layout regressed.
    assert stats.period_ns == LATTICE_NS
    assert stats.jitter_max_ns == 0


@pytest.mark.parametrize("name", _SCENARIO_NAMES)
def test_seed_never_perturbs_the_timeline(name: str) -> None:
    """Noise is proprioceptive only: different seeds => identical timestamp sequences."""
    ts_a = [s.timestamp_ns for s in build_scenario_episode(name, seed=1).samples]
    ts_b = [s.timestamp_ns for s in build_scenario_episode(name, seed=2).samples]
    assert ts_a == ts_b


def test_gate_rejects_an_unmeetable_budget() -> None:
    """The gate is real: a budget the episode cannot satisfy raises with the reasons."""
    with pytest.raises(ValueError, match=r"failed the jitter gate.*too few samples"):
        build_scenario_episode("pick_place", budget=JitterBudget(min_samples=10**9))


def test_unknown_scenario_fails_loud() -> None:
    """Unknown names surface the fail-loud ``example_scenario`` error, listing choices."""
    with pytest.raises(ValueError, match="unknown scenario"):
        build_scenario_episode("no_such_script")


def test_builder_rejects_non_pvtsample_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry source yielding anything but PVTSample fails at the factory boundary.

    The registry types ``stream()`` as ``Iterator[object]``; the builder's isinstance
    narrowing is the load-bearing guard that a misbehaving (e.g. third-party entry-point)
    source cannot leak foreign rows into an export.
    """

    class _RogueSource:
        def __enter__(self) -> _RogueSource:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def stream(self) -> list[object]:
            return ["not-a-sample"]

    monkeypatch.setattr(
        scenario_episode, "make_sensor_source", lambda name, **kwargs: _RogueSource()
    )
    with pytest.raises(TypeError, match="expected PVTSample"):
        build_scenario_episode("pick_place")


# ---------------------------------------------------------------------------
# Episode content: the scenario script really drives the registered sources
# ---------------------------------------------------------------------------


def test_sim_sources_are_registered_and_selectable() -> None:
    """The B7 exit criterion: the sim sources the builder selects by name exist."""
    names = set(list_sensor_sources())
    assert {"sim-proprio", "sim-tactile", "sim-frames"} <= names


def test_episode_carries_all_three_modalities() -> None:
    """slip_recovery exercises every FROZEN tactile token plus frames and proprio motion."""
    episode = build_scenario_episode("slip_recovery")

    tokens = {s.tactile_event for s in episode.samples if s.tactile_event is not None}
    assert tokens == set(CONTACT_KINDS)  # slip_recovery scripts all four frozen tokens

    frame_ids = [s.camera_frame_id for s in episode.samples if s.camera_frame_id is not None]
    assert frame_ids == sorted(frame_ids) and len(set(frame_ids)) == len(frame_ids)
    assert frame_ids and frame_ids[0] == "frame_000000"

    # Proprio rows really move (noisy sine, not the scenario sources' 0.0 placeholder).
    proprio = [s for s in episode.samples if s.chain_index == 0]
    assert any(abs(s.joint_angle) > 1e-6 for s in proprio)


# ---------------------------------------------------------------------------
# CLI: --sim --scenario X exports a valid, round-tripping lerobot dataset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _SCENARIO_NAMES)
def test_cli_sim_scenario_export_roundtrips(tmp_path: Path, name: str) -> None:
    """CLI: --sim --scenario exports a lerobot dataset whose reload is sample-for-sample
    EQUAL to the deterministically rebuilt episode — the full round-trip contract, not a
    spot-check (a lossy exporter/loader could otherwise pass on surviving tokens alone)."""
    out = tmp_path / "ds"
    rc = main(["export", "--sim", "--scenario", name, "-o", str(out), "--verify"])
    assert rc == 0
    assert (out / "meta" / "info.json").exists()
    assert list((out / "data").glob("*.parquet"))

    loaded = load_lerobot(out)
    assert len(loaded) == 1
    # The CLI delegates to build_scenario_episode(name) with its default seed/task_label,
    # and the stack is deterministic — so rebuilding here yields the exact episode the CLI
    # exported. Full equality over every FROZEN column (timestamps, joint_angle,
    # chain_index, tactile_event, camera_frame_id, ...) via as_row(); the loader's
    # timestamp sort is order-preserving because the timeline is strictly increasing.
    expected = build_scenario_episode(name)
    got = loaded[0]
    assert got.episode_id == expected.episode_id
    assert got.task_label == expected.task_label
    assert len(got.samples) == len(expected.samples)
    assert [s.as_row() for s in got.samples] == [s.as_row() for s in expected.samples]


def test_cli_scenario_requires_sim(tmp_path: Path) -> None:
    """--scenario on a file input is operator error; argparse exits, nothing is written."""
    with pytest.raises(SystemExit):
        main([
            "export",
            "-i", str(tmp_path / "ep.parquet"),
            "--scenario", "pick_place",
            "-o", str(tmp_path / "ds"),
        ])
    assert not (tmp_path / "ds").exists()


def test_cli_rejects_unknown_scenario(tmp_path: Path) -> None:
    """An unknown --scenario is rejected by argparse choices (which lists valid names)."""
    with pytest.raises(SystemExit):
        main(["export", "--sim", "--scenario", "warp_core", "-o", str(tmp_path / "ds")])
