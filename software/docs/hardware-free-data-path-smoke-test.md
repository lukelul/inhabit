# Hardware-free data-path smoke-test (POST_GREEN P3 / P4 / P5)

Closes the software side of `POST_GREEN_ROADMAP.md` P3 (live CAN readiness),
P4 (real-frame data path + export validation) and P5 (visualization readiness)
with **one** committed artifact: a tiny replayable CAN log plus a smoke-test that
drives the whole real-frame path with **zero hardware**.

## The committed fixture

`host/tests/fixtures/sample.canlog` — a deterministic, hand-checkable `.canlog`
(schema-v1 frames written via the real `transport.file.FileRecorder`). It models a
3-pod daisy chain (`chain_index` 0,1,2 / `node_id` 1,2,3) streaming 8 ticks at
100 Hz (24 frames).

It is a **synthetic stand-in for a real bench capture**. When a powered Rev-A board
produces a `.canlog` (P3/P4 hardware items), drop it in to replace the fixture and
the smoke-test below becomes a real-data regression guard, unchanged.

Regenerate it deterministically (byte-identical):

```bash
cd host
python -m tests.fixtures.make_sample_canlog
```

A test asserts the committed copy stays byte-identical to its generator, so the two
can never silently drift.

## The smoke-test (run this)

One pytest exercises both branches of the data path off the same fixture:
`replay -> bridge conversion -> JointPodState -> EpisodeRecorder -> parquet ->
read_episode -> lerobot export/load` **and** `replay -> ASCII viz`.

```bash
# from the repo root
python -m pytest host/tests/test_postgreen_smoke.py -q

# or the whole suite
python -m pytest host -q
```

## Copy-paste demo commands (no board)

All paths are relative to the **repo root**; the CAN schema v1 codec, `RobotAdapter`,
`PVTSample`/`PVT_SCHEMA_VERSION` and `JointPodState` are frozen contracts (consumed,
never edited).

### P3 — transport/replay smoke-test

Replay the fixture through the frozen codec and print decoded pod state:

```bash
python -m tools.can_replay replay host/tests/fixtures/sample.canlog
```

Expected (first lines): one decoded row per frame, all `valid=True`:

```text
Replaying host/tests/fixtures/sample.canlog
  id=0x101  node=1  chain=0  angle=-14.000 deg  raw=256  flags=0x00  valid=True
  id=0x102  node=2  chain=1  angle=-2.000 deg  raw=512  flags=0x00  valid=True
  id=0x103  node=3  chain=2  angle=10.000 deg  raw=768  flags=0x00  valid=True
  ...
Done.
```

### P4 — export validation (fixture -> bridge -> logger -> lerobot, round-trip)

`tools.dataset` imports the host packages directly, so put `host/` on `PYTHONPATH`:

```bash
PYTHONPATH=host python -m tools.dataset export \
    -i host/tests/fixtures/sample.canlog \
    -o /tmp/inhabit_lerobot_ds \
    --task insert_connector --verify
```

Expected tail (the `--verify` flag reloads the written dataset and asserts it
round-trips):

```text
Exported 1 episode(s), 24 sample(s) -> /tmp/inhabit_lerobot_ds
OK: round-trip verified - 1 episode(s), 24 sample(s)
```

The authoritative round-trip equality check (timestamps on one monotonic clock,
`chain_index`, `joint_angle`, episode/task identity, `schema_version`) lives in
`host/tests/test_postgreen_smoke.py::test_postgreen_data_path_and_export_round_trip`.

### P5 — live/replay ASCII visualization

See `host/viz/README.md` for the viz command, its expected output, and failure
cases. In short, from `host/`:

```bash
python -m viz tests/fixtures/sample.canlog
```

## What this prevents

Before this artifact, the real-frame path was only provable **in pieces** (per-module
unit tests) and was **not demonstrable at all without a powered board** — there was no
committed `.canlog` to replay. A regression at any seam (the `.canlog` wire format, the
replay re-stamp, the codec->fields mapping, the `JointPodState` contract, the parquet
schema, the lerobot export, or the viz rendering) could pass every per-module test yet
silently break the demo or corrupt the dataset. This fixture + smoke-test closes that
gap and is the regression baseline a real bench capture later inherits.

## Still hardware-blocked (not failures)

Per `POST_GREEN_ROADMAP.md` P3/P4/P6, the remaining items need the physical board:
live `socketcan`/`slcan` capture (`candump can0` showing `0x100+node_id` frames), a
real `.canlog` from a powered board replacing this fixture, two-board ENUM ordering,
and measured live-bus jitter. Each names its bench evidence in the roadmap.
