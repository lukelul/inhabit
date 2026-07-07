"""Deterministic generator for the committed ``sample.canlog`` regression fixture.

This emits a TINY, hand-checkable ``.canlog`` (schema-v1 frames written via the
real :class:`~transport.file.FileRecorder`, so the on-disk wire format is the one
the pipeline actually consumes) that stands in for a real bench capture until a
powered Rev-A board produces one. Regenerate with::

    cd host
    python -m tests.fixtures.make_sample_canlog

The fixture models a 3-pod daisy chain (``chain_index`` 0,1,2 / ``node_id`` 1,2,3)
streaming for ``N_TICKS`` ticks at 100 Hz. Each tick every pod emits one v1 frame;
records are written in pod order within a tick, and the recorded ``t_ns`` advances
by ``PER_RECORD_NS`` per record so the log is strictly monotonic on disk.

Replay re-stamps on its own monotonic clock, so the on-disk ``t_ns`` is provenance
only; the numbers below are chosen so the generator and the smoke-test agree on the
decoded angles WITHOUT importing any private constant — see ``angle_millideg_for``.

Frozen contracts (CAN codec v1) are imported and reused; nothing is reimplemented.
"""
from __future__ import annotations

from pathlib import Path

from inhabit_bridge.sources import CanFrame
from inhabit_can.codec import State, encode_state
from transport.file import FileRecorder

#: Pods in the chain: (node_id, chain_index). A 3-pod chain is the smallest set
#: that proves multi-pod ordering in the viz output.
PODS: tuple[tuple[int, int], ...] = ((1, 0), (2, 1), (3, 2))

#: Number of 100 Hz ticks captured. Small on purpose — the fixture is committed.
N_TICKS = 8

#: 100 Hz tick period; comfortably inside the recorder's default jitter budget.
TICK_NS = 10_000_000

#: Spacing between consecutive records on disk so ``t_ns`` is strictly increasing
#: even within a tick (3 records per tick). Provenance only — replay re-stamps.
PER_RECORD_NS = TICK_NS // (len(PODS) + 1)

FIXTURE_PATH = Path(__file__).with_name("sample.canlog")


def angle_millideg_for(chain_index: int, tick: int) -> int:
    """The ``angle_millideg`` encoded for one pod at one tick (single source of truth).

    A per-pod offset plus a per-tick ramp keeps every pod's angle distinct and
    monotonically advancing, while staying inside the int16 millideg range
    (+/- 32.767 deg) and the ASCII viz's +/- pi window. The pods are spread far
    enough apart that their ASCII bars land on visibly different columns. Both the
    generator and the smoke-test call this so expected values are derived, never
    hand-copied.
    """
    return (chain_index * 12000) + (tick * 500) - 14000


def build_frames() -> list[CanFrame]:
    """Build the full ordered list of :class:`CanFrame` records for the fixture."""
    frames: list[CanFrame] = []
    record = 0
    for tick in range(N_TICKS):
        for node_id, chain_index in PODS:
            cid, data = encode_state(
                State(
                    angle_raw_adc=(node_id << 8 | tick) & 0xFFFF,
                    angle_millideg=angle_millideg_for(chain_index, tick),
                    node_id=node_id,
                    chain_index=chain_index,
                    status_flags=0,
                )
            )
            frames.append(
                CanFrame(
                    can_id=cid,
                    data=data,
                    rx_monotonic_ns=record * PER_RECORD_NS,
                )
            )
            record += 1
    return frames


def write_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Write the deterministic fixture to ``path`` via the real FileRecorder.

    The committed fixture is a byte-exact regression baseline. ``FileRecorder``
    opens in text mode, so on Windows the line terminator would be CRLF and on
    POSIX LF — making the committed bytes platform-dependent. We normalize to LF
    after writing so the file (and the byte-identical round-trip test) is stable on
    every platform; ``.gitattributes`` pins ``*.canlog`` to ``eol=lf`` to match.
    """
    if path.exists():
        path.unlink()  # FileRecorder appends; regenerate from scratch.
    with FileRecorder(path) as fr:
        for frame in build_frames():
            fr.write(frame)
    # Normalize CRLF -> LF deterministically across platforms.
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    path.write_bytes(raw)
    return path


if __name__ == "__main__":
    out = write_fixture()
    print(f"wrote {out} ({len(build_frames())} frames, {len(PODS)} pods x {N_TICKS} ticks)")
