"""Exporter ABC + registry: registration, factory, round-trip, and integrity gate.

Covers A4 (P-A): the ``Exporter`` contract and its registry.

* Registry: ``list_exporters`` is sorted and contains both built-ins; ``make_exporter``
  builds the right concrete type; an unknown name raises ``ValueError``.
* Round-trip: for BOTH ``lerobot`` and ``parquet``, a seeded in-memory episode set exports
  and loads back field-for-field equal (the round-trip contract every exporter must pass).
* Integrity gate (preserved from #25): a corrupt (non-finite) frame and a non-monotonic /
  dropout episode are still rejected on the export path for both exporters.

The episodes are built deterministically (seeded) so the assertions are reproducible.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pytest

from export import (
    EXPORTER_ABC_VERSION,
    Exporter,
    LeRobotExporter,
    ParquetExporter,
    list_exporters,
    make_exporter,
)
from inhabit_can.pvt import Episode, PVTSample
from logger.jitter import JitterBudget
from logger.parquet_io import read_episode

# Exporters whose round-trip / gate behaviour must hold identically. Parametrize so a new
# exporter is one line away from being held to the same contract.
_EXPORTER_NAMES = ["lerobot", "parquet"]


def _seeded_episodes(*, n_episodes: int = 2, n_frames: int = 8, n_joints: int = 3) -> list[Episode]:
    """Build a deterministic set of clean, monotonic episodes (no RNG => reproducible).

    Uniform 10 ms cadence keeps every episode comfortably inside the default jitter budget,
    so the round-trip tests exercise the happy path (the gate is tested separately).
    """
    episodes: list[Episode] = []
    for e in range(n_episodes):
        ep = Episode(episode_id=f"seed_ep_{e:03d}", task_label=f"task_{e}")
        for f in range(n_frames):
            ts = f * 10_000_000  # 100 Hz, monotonic
            for j in range(n_joints):
                ep.add(
                    PVTSample(
                        timestamp_ns=ts,
                        episode_id=ep.episode_id,
                        chain_index=j,
                        joint_angle=round(0.1 * e + 0.01 * f + 0.001 * j, 6),
                        joint_velocity=round(0.002 * f, 6),
                        motor_current=round(0.03 * j, 6),
                        estimated_torque=round(0.04 * j, 6),
                        task_label=ep.task_label,
                    )
                )
        episodes.append(ep)
    return episodes


def _sort_key(s: PVTSample) -> tuple[int, int]:
    """Canonical (timestamp_ns, chain_index) order so interleaved exports compare equal."""
    return (s.timestamp_ns, s.chain_index)


# --- registry ---------------------------------------------------------------------


def test_list_exporters_is_sorted_and_contains_builtins() -> None:
    names = list_exporters()
    assert names == sorted(names)  # sorted contract
    assert "lerobot" in names
    assert "parquet" in names


def test_make_exporter_returns_correct_concrete_type() -> None:
    lerobot = make_exporter("lerobot")
    parquet = make_exporter("parquet")
    assert isinstance(lerobot, LeRobotExporter)
    assert isinstance(parquet, ParquetExporter)
    # Both honour the ABC surface.
    assert isinstance(lerobot, Exporter)
    assert isinstance(parquet, Exporter)
    assert lerobot.name == "lerobot"
    assert parquet.name == "parquet"


def test_make_exporter_unknown_name_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="Unknown exporter 'hdf5'"):
        make_exporter("hdf5")
    # The error lists the available names so the failure is actionable.
    with pytest.raises(ValueError, match="lerobot"):
        make_exporter("nope")


def test_exporter_abc_version_is_pinned() -> None:
    """The contract version is a stable int (bumped only via a decision record)."""
    assert isinstance(EXPORTER_ABC_VERSION, int)
    assert EXPORTER_ABC_VERSION >= 1


# --- round-trip (both exporters) --------------------------------------------------


@pytest.mark.parametrize("name", _EXPORTER_NAMES)
def test_roundtrip_via_abc(name: str, tmp_path: Path) -> None:
    """export -> load reproduces the seeded episodes field-for-field (the round-trip contract)."""
    exporter = make_exporter(name)
    episodes = _seeded_episodes()

    root = exporter.export(episodes, tmp_path / f"{name}_ds")
    loaded = exporter.load(root)

    assert len(loaded) == len(episodes)
    # Match episodes by id (file/dir ordering differs per exporter); both build the same set.
    orig_by_id = {ep.episode_id: ep for ep in episodes}
    for back in loaded:
        orig = orig_by_id[back.episode_id]
        assert back.task_label == orig.task_label
        assert len(back.samples) == len(orig.samples)
        o_sorted = sorted(orig.samples, key=_sort_key)
        b_sorted = sorted(back.samples, key=_sort_key)
        for so, sb in zip(o_sorted, b_sorted, strict=True):
            assert so.timestamp_ns == sb.timestamp_ns
            assert so.chain_index == sb.chain_index
            assert so.joint_angle == pytest.approx(sb.joint_angle)
            assert so.joint_velocity == pytest.approx(sb.joint_velocity)
            assert so.motor_current == pytest.approx(sb.motor_current)
            assert so.estimated_torque == pytest.approx(sb.estimated_torque)
            assert so.task_label == sb.task_label


@pytest.mark.parametrize("name", _EXPORTER_NAMES)
def test_empty_export_roundtrips(name: str, tmp_path: Path) -> None:
    """Exporting nothing yields a loadable, empty dataset (no crash)."""
    exporter = make_exporter(name)
    root = exporter.export([], tmp_path / f"{name}_empty")
    assert exporter.load(root) == []


# --- integrity gate preserved (#25) -----------------------------------------------


@pytest.mark.parametrize("name", _EXPORTER_NAMES)
def test_corrupt_nonfinite_frame_still_rejected(
    name: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A NaN joint value must never reach disk via either exporter (the #25 finiteness gate).

    lerobot: a single-frame NaN episode collapses to an unusable/empty export. parquet:
    the non-finite frame is dropped before write. Either way, no NaN survives the round-trip.
    """
    exporter = make_exporter(name)
    ep = Episode(episode_id="nan_ep", task_label="t")
    # Two clean instants + one NaN sample at a clean instant.
    ep.add(PVTSample(timestamp_ns=0, episode_id="nan_ep", chain_index=0, joint_angle=0.1))
    ep.add(
        PVTSample(
            timestamp_ns=10_000_000, episode_id="nan_ep", chain_index=0, joint_angle=float("nan")
        )
    )
    ep.add(
        PVTSample(timestamp_ns=20_000_000, episode_id="nan_ep", chain_index=0, joint_angle=0.3)
    )

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        root = exporter.export([ep], tmp_path / f"{name}_nan")
    loaded = exporter.load(root)

    # No NaN ever round-trips back, whatever the format chose to do with the episode.
    for back in loaded:
        for s in back.samples:
            assert math.isfinite(s.joint_angle)


def test_lerobot_drops_nonfinite_keeps_finite(tmp_path: Path) -> None:
    """lerobot exporter strips the NaN frame and keeps the two finite instants.

    Regression for the #25 finiteness guard at the ABC export path: the standalone
    ``export_lerobot`` has no per-frame NaN gate (NaN is dropped upstream in the real
    pipeline), so the ``LeRobotExporter`` applies the shared gate before delegating. A NaN
    must never round-trip back out of a lerobot dataset.
    """
    exporter = make_exporter("lerobot")
    ep = Episode(episode_id="mixed_lr", task_label="t")
    ep.add(PVTSample(timestamp_ns=0, episode_id="mixed_lr", chain_index=0, joint_angle=0.1))
    ep.add(
        PVTSample(
            timestamp_ns=10_000_000, episode_id="mixed_lr", chain_index=0, joint_angle=float("nan")
        )
    )
    ep.add(
        PVTSample(timestamp_ns=20_000_000, episode_id="mixed_lr", chain_index=0, joint_angle=0.3)
    )

    root = exporter.export([ep], tmp_path / "ds")
    loaded = exporter.load(root)
    assert len(loaded) == 1
    kept = sorted(s.timestamp_ns for s in loaded[0].samples)
    assert kept == [0, 20_000_000]  # the NaN frame is gone
    for s in loaded[0].samples:
        assert math.isfinite(s.joint_angle)


def test_parquet_drops_nonfinite_keeps_finite(tmp_path: Path) -> None:
    """parquet exporter drops only the NaN frame and keeps the two finite instants."""
    exporter = make_exporter("parquet")
    ep = Episode(episode_id="mixed", task_label="t")
    ep.add(PVTSample(timestamp_ns=0, episode_id="mixed", chain_index=0, joint_angle=0.1))
    ep.add(
        PVTSample(
            timestamp_ns=10_000_000, episode_id="mixed", chain_index=0, joint_angle=float("inf")
        )
    )
    ep.add(PVTSample(timestamp_ns=20_000_000, episode_id="mixed", chain_index=0, joint_angle=0.3))

    root = exporter.export([ep], tmp_path / "ds")
    loaded = exporter.load(root)
    assert len(loaded) == 1
    kept = sorted(s.timestamp_ns for s in loaded[0].samples)
    assert kept == [0, 20_000_000]  # the inf frame is gone


def test_parquet_all_nonfinite_episode_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An episode whose every frame is non-finite is refused (no husk written)."""
    exporter = make_exporter("parquet")
    ep = Episode(episode_id="all_nan", task_label="t")
    nan = float("nan")
    for ts in (0, 10_000_000):
        ep.add(PVTSample(timestamp_ns=ts, episode_id="all_nan", chain_index=0, joint_angle=nan))

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        root = exporter.export([ep], tmp_path / "ds")

    assert any("REFUSED" in r.message for r in caplog.records)
    assert exporter.load(root) == []
    manifest = json.loads((Path(root) / "rejected.json").read_text())
    assert manifest["rejected_episodes"][0]["episode_id"] == "all_nan"
    assert "no finite frames" in manifest["rejected_episodes"][0]["reasons"][0]


@pytest.mark.parametrize("name", _EXPORTER_NAMES)
def test_backwards_timeline_refused(
    name: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-monotonic episode is refused (written nowhere) by both exporters."""
    exporter = make_exporter(name)
    ep = Episode(episode_id="backwards", task_label="t")
    for ts in (3_000_000, 2_000_000, 1_000_000):  # distinct instants captured backwards
        ep.add(PVTSample(timestamp_ns=ts, episode_id="backwards", chain_index=0, joint_angle=0.1))

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        root = exporter.export([ep], tmp_path / f"{name}_back")

    assert any("REFUSED" in r.message for r in caplog.records)
    assert exporter.load(root) == []  # not in the dataset


@pytest.mark.parametrize("name", _EXPORTER_NAMES)
def test_dropout_timeline_refused(
    name: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A hole in the timeline (> max_gap_factor x period) refuses the episode in both."""
    exporter = make_exporter(name)
    ep = Episode(episode_id="dropout", task_label="t")
    # 10 ms cadence then a 50 ms jump = a missed-frame hole (> 2.5x period).
    for ts in (0, 10_000_000, 20_000_000, 70_000_000, 80_000_000):
        ep.add(PVTSample(timestamp_ns=ts, episode_id="dropout", chain_index=0, joint_angle=0.1))

    with caplog.at_level(logging.WARNING, logger="inhabit.export"):
        root = exporter.export([ep], tmp_path / f"{name}_drop")

    assert any("REFUSED" in r.message and "dropout" in r.message for r in caplog.records)
    assert exporter.load(root) == []


def test_parquet_refusal_listed_in_manifest(tmp_path: Path) -> None:
    """parquet refusal is auditable: the refused episode_id lands in rejected.json."""
    exporter = make_exporter("parquet")
    bad = Episode(episode_id="bad", task_label="t")
    for ts in (3_000_000, 2_000_000, 1_000_000):
        bad.add(PVTSample(timestamp_ns=ts, episode_id="bad", chain_index=0, joint_angle=0.1))
    good = Episode(episode_id="good", task_label="t")
    for i in range(4):
        good.add(
            PVTSample(
                timestamp_ns=i * 10_000_000,
                episode_id="good",
                chain_index=0,
                joint_angle=float(i),
            )
        )

    root = exporter.export([bad, good], tmp_path / "ds")
    manifest = json.loads((Path(root) / "rejected.json").read_text())
    assert [r["episode_id"] for r in manifest["rejected_episodes"]] == ["bad"]

    loaded = exporter.load(root)
    assert [ep.episode_id for ep in loaded] == ["good"]


def test_make_exporter_forwards_kwargs() -> None:
    """make_exporter forwards constructor kwargs (e.g. a custom jitter budget)."""
    tight = JitterBudget(max_jitter_p99_ns=1, max_gap_factor=1.1, min_samples=2)
    exporter = make_exporter("parquet", budget=tight)
    assert isinstance(exporter, ParquetExporter)
    assert exporter._budget is tight


# --- parquet filename safety (path traversal + duplicate-id clobber) ---------------


def _clean_episode(eid: str, *, n_frames: int = 4) -> Episode:
    """A small monotonic 100 Hz episode that passes the gate, with episode_id ``eid``."""
    ep = Episode(episode_id=eid, task_label="t")
    for f in range(n_frames):
        ep.add(
            PVTSample(
                timestamp_ns=f * 10_000_000,
                episode_id=eid,
                chain_index=0,
                joint_angle=float(f),
            )
        )
    return ep


def test_parquet_episode_id_does_not_escape_out_path(tmp_path: Path) -> None:
    """A ``../`` episode_id must NOT write a file outside out_path (path-traversal guard).

    Regression: the basename was once ``f"{episode_id}.parquet"``, so an id of ``../escaped``
    wrote ``escaped.parquet`` in the PARENT of out_path (write_episode mkdir's the parent).
    The on-disk name is now a zero-padded export index, so nothing escapes the dataset root.
    """
    exporter = make_exporter("parquet")
    out = tmp_path / "ds"
    sentinel = tmp_path / "escaped.parquet"

    root = exporter.export([_clean_episode("../escaped")], out)

    # Nothing wrote outside the dataset root: no sibling file, only ep_*.parquet inside.
    assert not sentinel.exists()
    written = sorted(p.name for p in Path(root).glob("*.parquet"))
    assert written == ["ep_000000.parquet"]
    # Every written parquet lives under out (no traversal).
    for p in Path(root).glob("*.parquet"):
        assert out.resolve() in p.resolve().parents
    # episode_id still round-trips out of the footer, traversal chars and all.
    loaded = exporter.load(root)
    assert [ep.episode_id for ep in loaded] == ["../escaped"]


def test_parquet_absolute_episode_id_does_not_escape(tmp_path: Path) -> None:
    """An absolute-path episode_id must not create files anywhere on disk."""
    exporter = make_exporter("parquet")
    out = tmp_path / "ds"
    abs_id = str(tmp_path / "pwned")

    root = exporter.export([_clean_episode(abs_id)], out)

    assert not (tmp_path / "pwned.parquet").exists()
    written = sorted(p.name for p in Path(root).glob("*.parquet"))
    assert written == ["ep_000000.parquet"]
    loaded = exporter.load(root)
    assert [ep.episode_id for ep in loaded] == [abs_id]


def test_parquet_duplicate_episode_id_both_persist(tmp_path: Path) -> None:
    """Two episodes sharing an episode_id must BOTH persist (no silent clobber).

    Regression: filename ``f"{episode_id}.parquet"`` made the second write overwrite the
    first, so ``len(load(...)) < len(exported)``. Distinct export-index basenames keep both,
    and each round-trips its own samples; the round-trip len invariant holds.
    """
    exporter = make_exporter("parquet")
    a = _clean_episode("dup", n_frames=3)
    b = _clean_episode("dup", n_frames=5)

    root = exporter.export([a, b], tmp_path / "ds")
    loaded = exporter.load(root)

    assert len(loaded) == 2  # len preserved: nothing clobbered
    assert [ep.episode_id for ep in loaded] == ["dup", "dup"]
    # Both distinct payloads survived: lengths sorted == the two inputs sorted.
    assert sorted(len(ep.samples) for ep in loaded) == [3, 5]
    # Two physical files on disk, deterministically ordered by zero-padded index.
    files = sorted(p.name for p in Path(root).glob("*.parquet"))
    assert files == ["ep_000000.parquet", "ep_000001.parquet"]


# --- parquet footer timing provenance (MUST be the gated signal) -------------------


def test_parquet_interleaved_footer_jitter_is_deduped(tmp_path: Path) -> None:
    """Footer jitter of an interleaved multi-pod episode reports backwards==0 + non-zero period.

    Regression: the footer once persisted compute_jitter over the RAW per-sample list. For an
    interleaved multi-pod episode (the same instant repeats once per pod) that reintroduces the
    dt=0 duplicate intervals instant_order() removes, stamping FALSE provenance (backwards>0,
    period_ns=0) onto an episode the GATE already cleared on instant_order. The footer must
    carry the SAME deduped signal the gate validated.
    """
    exporter = make_exporter("parquet")
    ep = Episode(episode_id="interleaved", task_label="t")
    # Interleaved capture order: each instant appears once per pod (3 pods), instants
    # themselves are monotonic 10 ms apart. Raw list has dt=0 repeats; deduped does not.
    for f in range(5):
        ts = f * 10_000_000
        for pod in range(3):
            ep.add(
                PVTSample(
                    timestamp_ns=ts,
                    episode_id="interleaved",
                    chain_index=pod,
                    joint_angle=0.1 * pod,
                )
            )

    root = exporter.export([ep], tmp_path / "ds")
    files = sorted(Path(root).glob("*.parquet"))
    assert len(files) == 1
    _episode, meta = read_episode(files[0])

    js = meta["jitter_stats"]
    assert js["backwards"] == 0  # not poisoned by dt=0 duplicates
    assert js["period_ns"] == 10_000_000  # real 10 ms period recovered, not 0
    assert js["dropouts"] == 0


def test_parquet_footer_records_time_sync_method(tmp_path: Path) -> None:
    """Parquet footer records the clock source + time-sync method (timing provenance)."""
    exporter = make_exporter("parquet")
    root = exporter.export([_clean_episode("prov")], tmp_path / "ds")
    files = sorted(Path(root).glob("*.parquet"))
    _episode, meta = read_episode(files[0])

    tb = meta["time_base"]
    assert tb["clock_source"] == "monotonic_host"
    assert tb["time_sync_method"] == "single_monotonic_host_clock"
    assert tb["timestamp_field"] == "timestamp_ns"


# --- lerobot: empty-after-strip episodes stay in the audit trail (CodeRabbit) ------


def test_lerobot_all_nonfinite_episode_is_audited(tmp_path: Path) -> None:
    """An all-non-finite episode is NOT silently dropped: it is counted + listed as refused.

    Regression for the finiteness strip emptying an episode: it must still appear in
    ``meta/info.json -> rejected_episodes`` and in ``total_episodes_input`` so the corrupt
    episode leaves a trace, instead of vanishing from both the count and the audit trail.
    """
    exporter = make_exporter("lerobot")
    nan = float("nan")
    bad = Episode(episode_id="all_nan_lr", task_label="t")
    for ts in (0, 10_000_000):
        bad.add(PVTSample(timestamp_ns=ts, episode_id="all_nan_lr", chain_index=0, joint_angle=nan))
    good = _clean_episode("good_lr")

    root = exporter.export([bad, good], tmp_path / "ds")
    info = json.loads((Path(root) / "meta" / "info.json").read_text())

    assert info["total_episodes_input"] == 2  # both offered episodes counted
    assert info["total_episodes"] == 1  # only the good one written
    rejected_ids = [r["episode_id"] for r in info["rejected_episodes"]]
    assert "all_nan_lr" in rejected_ids
    # The good episode still round-trips; no NaN survives.
    loaded = exporter.load(root)
    assert [ep.episode_id for ep in loaded] == ["good_lr"]
    for s in loaded[0].samples:
        assert math.isfinite(s.joint_angle)
