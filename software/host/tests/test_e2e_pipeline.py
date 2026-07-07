"""End-to-end PVT pipeline test (BENCHMARKS #6) — pure Python, no ROS, no hardware.

Failure mode this guards against
--------------------------------
The PVT chain is unit-tested in pieces (codec, transport, bridge conversion,
recorder, parquet round-trip), but nothing exercises the WHOLE seam in one flow.
A regression at any boundary — the .canlog wire format, the replay re-stamp, the
codec->fields mapping, the JointPodState contract, or the parquet schema — would
pass every per-module test yet silently corrupt the dataset. This proves a frame
the firmware would emit flows all the way to a round-trippable ML episode:

    encode_state                  -> raw 8-byte CAN frame (frozen codec)
    FileRecorder                  -> .canlog on disk (versioned wire format)
    FileReplayTransport           -> CanFrame stream, re-stamped on ONE monotonic clock
    conversion.fields_from_frame  -> PodFields (the single codec->msg mapping)
    JointPodState                 -> Contract B (+ monotonic header_stamp_ns)
    EpisodeRecorder.ingest        -> append-only episode (drops corrupt-checksum frames)
    finalize                      -> jitter-gated atomic parquet write
    read_episode                  -> assert PVTSamples equal the inputs

A frame with a deliberately corrupted checksum is recorded into the .canlog and
must be dropped from the exported timeline (kept off the dataset, not poisoning it).

Everything below imports the FROZEN contracts (codec, PVTSample, JointPodState)
and reuses the existing modules — no pipeline logic is reimplemented here.
"""
from __future__ import annotations

import math
from pathlib import Path

from inhabit_bridge.conversion import fields_from_frame
from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from inhabit_can.pvt import JointPodState
from logger.parquet_io import read_episode
from logger.recorder import EpisodeRecorder
from transport.file import FileRecorder, FileReplayTransport

PERIOD_NS = 10_000_000  # 100 Hz — comfortably inside the default jitter budget
N_GOOD = 40
NODE_ID = 3
CHAIN_INDEX = 1
EPISODE_ID = "e2e_000001"
TASK = "insert_connector"

# millideg -> rad, identical to the constant conversion.fields_from_frame uses to
# derive angle_rad. Recomputing it here (rather than importing a private symbol)
# keeps the expected joint_angle independent yet exactly matched.
_MILLIDEG_TO_RAD = math.pi / 180.0 / 1000.0


def _good_millideg(i: int) -> int:
    """The angle_millideg encoded into good frame ``i`` (single source of truth)."""
    return (i * 100) - 2000  # spans negative + positive, well within int16


def _good_frame(i: int) -> bytes:
    """One valid v1 CAN payload whose decoded angle varies with ``i``."""
    _can_id, data = encode_state(
        State(
            angle_raw_adc=(i * 37) & 0xFFFF,
            angle_millideg=_good_millideg(i),
            node_id=NODE_ID,
            chain_index=CHAIN_INDEX,
            status_flags=0,
        )
    )
    return data


def _corrupt_frame() -> bytes:
    """A valid frame with its checksum byte flipped — decodes, but invalid."""
    _can_id, good = encode_state(
        State(99, 1234, node_id=NODE_ID, chain_index=CHAIN_INDEX, status_flags=0)
    )
    bad = bytearray(good)
    bad[7] ^= 0xFF  # corrupt only the checksum; payload bytes stay decodable
    return bytes(bad)


def _pod_state_from_frame(frame: CanFrame) -> JointPodState:
    """Map a replayed CanFrame -> bridge PodFields -> Contract B JointPodState.

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


def test_e2e_replay_bridge_state_writer_round_trip(tmp_path: Path) -> None:
    logfile = tmp_path / "pipeline.canlog"

    # --- 1. Record frames to a .canlog via the transport FileRecorder. ---------
    # The corrupt frame is the FIRST record so we prove a bad frame at the head of
    # the stream is dropped without shifting the surviving timeline. Write-time
    # t_ns is intentionally irrelevant: replay re-stamps on its own clock.
    corrupt = _corrupt_frame()
    good_frames = [_good_frame(i) for i in range(N_GOOD)]

    with FileRecorder(logfile) as fr:
        fr.write(CanFrame(can_id=0x100 + NODE_ID, data=corrupt, rx_monotonic_ns=0))
        for i, data in enumerate(good_frames):
            fr.write(
                CanFrame(can_id=0x100 + NODE_ID, data=data, rx_monotonic_ns=(i + 1) * PERIOD_NS)
            )

    # Sanity: corrupt + N_GOOD frames are all on disk — the timeline filter lives
    # downstream in the recorder, NOT at the wire layer.
    assert len(logfile.read_text(encoding="utf-8").strip().splitlines()) == N_GOOD + 1

    # --- 2. Replay through the file transport on ONE deterministic monotonic clock.
    # The clock advances by exactly PERIOD_NS per recv, including the corrupt frame.
    # Because the corrupt frame is dropped, surviving samples land on ticks
    # 2..N_GOOD+1 -> still a uniform 100 Hz timeline with no gap.
    tick = {"n": 0}

    def fake_clock() -> int:
        tick["n"] += 1
        return tick["n"] * PERIOD_NS

    rec = EpisodeRecorder(EPISODE_ID, tmp_path, task_label=TASK)

    replayed_good_states: list[JointPodState] = []
    transport = FileReplayTransport(logfile, clock_ns=fake_clock)
    with transport:
        while True:
            frame = transport.recv()
            if frame is None:
                break
            state = _pod_state_from_frame(frame)
            if state.checksum_valid:
                replayed_good_states.append(state)
            # Hand EVERY frame (corrupt included) to the recorder; it owns the drop
            # decision so the corrupt frame stays off the dataset timeline.
            rec.ingest(state)

    # The corrupt frame decoded but was flagged invalid; only good frames survive.
    assert len(replayed_good_states) == N_GOOD

    # --- 3. Finalize: jitter-gated atomic parquet write. -----------------------
    result = rec.finalize()
    assert result.exported, f"episode should pass jitter budget; reasons={result.reasons}"
    assert result.path is not None and result.path.exists()
    assert result.stats.n_samples == N_GOOD  # corrupt frame excluded
    assert result.stats.backwards == 0
    assert result.stats.dropouts == 0

    # --- 4. Read back from parquet and assert exact round-trip. ----------------
    episode, meta = read_episode(result.path)
    assert episode.episode_id == EPISODE_ID
    assert episode.task_label == TASK
    assert len(episode.samples) == N_GOOD
    # Provenance: the recorder records exactly one dropped corrupt frame.
    assert meta["dropped_checksum"] == 1

    # Each round-tripped PVTSample must equal the corresponding replayed input:
    # timestamp (exact monotonic anchor), chain_index (exact), joint_angle (within
    # float tolerance), plus episode/task identity.
    for i, sample in enumerate(episode.samples):
        src = replayed_good_states[i]
        expected_angle = _good_millideg(i) * _MILLIDEG_TO_RAD

        assert sample.timestamp_ns == src.header_stamp_ns
        assert sample.timestamp_ns == (i + 2) * PERIOD_NS  # ticks 2..N_GOOD+1
        assert sample.chain_index == CHAIN_INDEX
        assert sample.chain_index == src.chain_index
        assert abs(sample.joint_angle - src.angle_rad) < 1e-12
        assert abs(sample.joint_angle - expected_angle) < 1e-9
        assert sample.episode_id == EPISODE_ID
        assert sample.task_label == TASK

    # Timeline is strictly increasing and uniformly spaced (no gap from the drop).
    stamps = [s.timestamp_ns for s in episode.samples]
    assert stamps == sorted(stamps)
    intervals = {stamps[j + 1] - stamps[j] for j in range(len(stamps) - 1)}
    assert intervals == {PERIOD_NS}
