"""POST_GREEN_ROADMAP P3/P4/P5 smoke-test — committed fixture, zero hardware.

Failure mode this guards against
--------------------------------
Before this, the real-frame data path was only provable in *pieces* and not
demonstrable at all without a powered Rev-A board: there was no committed
``.canlog`` to replay, so P3 (live CAN readiness), P4 (real-frame data path +
export validation) and P5 (visualization readiness) each had a software gap that
no single artifact closed. A regression anywhere along

    .canlog (committed fixture)
      -> FileReplayTransport          [P3 transport/replay]
        -> conversion.fields_from_frame [frozen codec -> PodFields]
          -> JointPodState            [Contract B, monotonic stamp]
            -> EpisodeRecorder.ingest/finalize -> parquet -> read_episode  [P4 logger]
              -> export_lerobot / load_lerobot [P4 export validation]
    .canlog -> viz.render_stream      [P5 ASCII visualization]

would pass every per-module unit test yet silently break the demo / dataset. This
single test replays the SAME committed fixture down both the logger/export branch
AND the viz branch, asserting round-trip equality and exact rendered output.

The fixture (``tests/fixtures/sample.canlog``) is a synthetic stand-in for a real
bench capture; when a powered board produces a ``.canlog`` it can replace the
fixture and this test becomes a real-data regression guard unchanged.

Everything imports FROZEN contracts (CAN codec v1, PVTSample/PVT_SCHEMA_VERSION,
JointPodState, RobotAdapter via the modules below) and reuses existing pipeline
modules — no pipeline logic is reimplemented here.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

from export.lerobot import export_lerobot, load_lerobot
from inhabit_bridge.conversion import fields_from_frame
from inhabit_bridge.sources import CanFrame
from inhabit_can.pvt import PVT_SCHEMA_VERSION, JointPodState
from logger.parquet_io import read_episode
from logger.recorder import EpisodeRecorder
from tests.fixtures.make_sample_canlog import (
    N_TICKS,
    PODS,
    TICK_NS,
    angle_millideg_for,
    write_fixture,
)
from transport.file import FileReplayTransport
from viz.runner import render_stream

FIXTURE = Path(__file__).parent / "fixtures" / "sample.canlog"

EPISODE_ID = "postgreen_smoke_000001"
TASK = "insert_connector"

#: The pod whose clean per-node timeline drives the logger/export round-trip.
#: chain_index 0 / node_id 1 is the first pod in the chain.
LOGGED_NODE_ID, LOGGED_CHAIN_INDEX = PODS[0]

# millideg -> rad: recomputed (not imported from a private symbol) so the expected
# joint_angle is independent yet exactly matches conversion.fields_from_frame.
_MILLIDEG_TO_RAD = math.pi / 180.0 / 1000.0


def test_fixture_is_committed_and_nonempty() -> None:
    """The fixture must be committed on disk (a real bench capture replaces it later)."""
    assert FIXTURE.exists(), f"missing committed fixture {FIXTURE}"
    lines = FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(PODS) * N_TICKS  # 3 pods x N_TICKS ticks


def test_fixture_round_trips_from_generator(tmp_path: Path) -> None:
    """Regenerating the fixture is deterministic — byte-identical to the committed copy.

    Guards against the committed fixture drifting from its generator (e.g. someone
    edits one without the other), which would make the regression baseline a lie.
    """
    regenerated = write_fixture(tmp_path / "regen.canlog")
    assert regenerated.read_bytes() == FIXTURE.read_bytes()


def _pod_state_from_frame(frame: CanFrame) -> JointPodState:
    """Map a replayed CanFrame -> PodFields -> Contract B JointPodState.

    ``header_stamp_ns`` is the ONE monotonic clock value the replay transport
    stamped at recv time — the same anchor the real bridge node writes.
    """
    f = fields_from_frame(frame.data)
    return JointPodState(
        node_id=f.node_id,
        chain_index=f.chain_index,
        angle_raw_adc=f.angle_raw_adc,
        angle_millideg=f.angle_millideg,
        angle_rad=f.angle_rad,
        status_flags=f.status_flags,
        checksum_valid=f.checksum_valid,
        schema_version=f.schema_version,
        header_stamp_ns=frame.rx_monotonic_ns,
    )


def test_postgreen_data_path_and_export_round_trip(tmp_path: Path) -> None:
    """P3 + P4: replay the committed fixture -> bridge -> logger -> parquet -> lerobot.

    Drives ONE pod's clean 100 Hz timeline through the recorder so the jitter gate
    and round-trip assertions are over a uniform single-joint stream (the chain's
    other pods are still replayed and decoded — proving the whole log parses — but
    only the selected node is logged, mirroring a per-joint episode writer).
    """
    # --- P3: replay the committed fixture on ONE deterministic monotonic clock. ---
    # Advance the clock by TICK_NS only for the LOGGED pod's frames so its episode is
    # a uniform 100 Hz timeline; other pods get an interleaved (irrelevant) stamp.
    logged_tick = {"n": 0}

    def clock_for_logged() -> int:
        logged_tick["n"] += 1
        return logged_tick["n"] * TICK_NS

    rec = EpisodeRecorder(EPISODE_ID, tmp_path, task_label=TASK)
    logged_states: list[JointPodState] = []
    decoded_total = 0

    transport = FileReplayTransport(FIXTURE)
    with transport:
        while True:
            frame = transport.recv()
            if frame is None:
                break
            decoded_total += 1
            f = fields_from_frame(frame.data)
            if f.node_id != LOGGED_NODE_ID:
                continue  # full chain parses; only the selected pod is logged
            # Re-stamp the logged pod's frame on the uniform episode clock.
            stamped = CanFrame(
                can_id=frame.can_id,
                data=frame.data,
                rx_monotonic_ns=clock_for_logged(),
            )
            state = _pod_state_from_frame(stamped)
            assert state.checksum_valid  # fixture frames are all valid v1
            logged_states.append(state)
            rec.ingest(state)

    assert decoded_total == len(PODS) * N_TICKS  # whole fixture replayed + decoded
    assert len(logged_states) == N_TICKS

    # --- P4: finalize -> jitter-gated atomic parquet write. ----------------------
    result = rec.finalize()
    assert result.exported, f"episode should pass jitter budget; reasons={result.reasons}"
    assert result.path is not None and result.path.exists()
    assert result.stats.n_samples == N_TICKS
    assert result.stats.backwards == 0
    assert result.stats.dropouts == 0

    # --- P4: read back from parquet and assert exact round-trip. -----------------
    episode, meta = read_episode(result.path)
    assert episode.episode_id == EPISODE_ID
    assert episode.task_label == TASK
    assert len(episode.samples) == N_TICKS
    assert meta["dropped_checksum"] == 0  # no corrupt frames in the fixture

    for tick, sample in enumerate(episode.samples):
        src = logged_states[tick]
        expected_angle = angle_millideg_for(LOGGED_CHAIN_INDEX, tick) * _MILLIDEG_TO_RAD
        assert sample.timestamp_ns == src.header_stamp_ns
        assert sample.timestamp_ns == (tick + 1) * TICK_NS
        assert sample.chain_index == LOGGED_CHAIN_INDEX
        assert abs(sample.joint_angle - src.angle_rad) < 1e-12
        assert abs(sample.joint_angle - expected_angle) < 1e-9
        assert sample.episode_id == EPISODE_ID
        assert sample.task_label == TASK
        assert sample.schema_version == PVT_SCHEMA_VERSION

    # Timeline strictly increasing, uniformly 100 Hz (no gaps).
    stamps = [s.timestamp_ns for s in episode.samples]
    assert stamps == sorted(stamps)
    assert {stamps[j + 1] - stamps[j] for j in range(len(stamps) - 1)} == {TICK_NS}

    # --- P4: export to lerobot layout, reload, assert key fields survive. ---------
    ds_root = export_lerobot([episode], tmp_path / "lerobot_ds")
    assert (ds_root / "data").is_dir()
    assert (ds_root / "meta" / "info.json").exists()

    loaded = load_lerobot(ds_root)
    assert len(loaded) == 1
    reloaded = loaded[0]
    assert reloaded.episode_id == EPISODE_ID
    assert reloaded.task_label == TASK
    assert len(reloaded.samples) == N_TICKS

    # Full round-trip equality: every field that the lerobot exporter persists must
    # survive the export -> load cycle. Match samples by frame order (single pod =>
    # one sample per frame). Timestamps are re-derived from the parquet so we compare
    # against the original episode samples.
    for tick, sample in enumerate(reloaded.samples):
        orig = episode.samples[tick]
        assert sample.chain_index == orig.chain_index
        assert sample.episode_id == orig.episode_id
        assert sample.task_label == orig.task_label
        assert sample.timestamp_ns == orig.timestamp_ns
        assert abs(sample.joint_angle - orig.joint_angle) < 1e-9
        assert abs(sample.joint_velocity - orig.joint_velocity) < 1e-9
        assert abs(sample.motor_current - orig.motor_current) < 1e-9
        assert abs(sample.estimated_torque - orig.estimated_torque) < 1e-9


def test_postgreen_viz_renders_full_chain_from_fixture() -> None:
    """P5: render the committed fixture through the ASCII viz and assert exact output.

    The viz consumes the WHOLE chain (all 3 pods), keyed by node_id, re-rendering on
    every frame. The final snapshot is the last-known PodFields for each pod, so its
    bar columns are derived from ``angle_millideg_for(chain_index, N_TICKS - 1)`` —
    no hand-copied magic strings.
    """
    out = io.StringIO()
    transport = FileReplayTransport(FIXTURE)
    with transport:
        frames = _drain(transport)
    rendered = render_stream(frames, out=out)
    assert rendered == len(PODS) * N_TICKS

    # The output is one full-chain snapshot per frame; the LAST snapshot is the final
    # len(PODS) lines and reflects every pod at tick N_TICKS-1.
    lines = out.getvalue().rstrip("\n").split("\n")
    final_snapshot = lines[-len(PODS) :]
    assert len(final_snapshot) == len(PODS)

    # Sorted by (chain_index, node_id) inside render_frame, so line i == PODS[i].
    for i, (node_id, chain_index) in enumerate(PODS):
        line = final_snapshot[i]
        deg = angle_millideg_for(chain_index, N_TICKS - 1) / 1000.0
        assert line.startswith(f"pod {node_id:>2}:{chain_index:<2}")
        assert f"{deg:+8.2f} deg" in line
        # Exactly one bar marker '#' per line. The center mark '|' is present too,
        # unless the marker lands exactly on center and overwrites it (pod 2 here).
        bar = line[line.index("[") + 1 : line.index("]")]
        assert bar.count("#") == 1
        assert line.endswith("ok")  # status_flags == 0 -> "ok"

    # Pin the exact final snapshot so a rendering regression fails loud (this is the
    # block reproduced in host/viz/README.md "expected output").
    assert final_snapshot == [
        "pod  1:0    -10.50 deg  [------------------#-|-------------------] ok",
        "pod  2:1     +1.50 deg  [--------------------#-------------------] ok",
        "pod  3:2    +13.50 deg  [--------------------|#------------------] ok",
    ]


def _drain(transport: FileReplayTransport) -> list[CanFrame]:
    """Pull every frame from an opened replay transport into a list."""
    frames: list[CanFrame] = []
    while True:
        frame = transport.recv()
        if frame is None:
            return frames
        frames.append(frame)
