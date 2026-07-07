# viz — live ASCII joint-angle visualizer

Renders Inhabit pod telemetry (`JointPodState`-like frames) as a compact terminal
display so an operator can watch joint angles in real time.

- `ascii_viz.py` — rendering (`render_frame`, `format_pod`, `_bar`). No deps beyond stdlib.
- `runner.py` — thin wiring: feeds CAN frames into `render_frame`. No new rendering logic.
- `__main__.py` — CLI entry point (`python -m viz`).

The viz only **consumes**. The CAN codec, `JointPodState.msg`, `RobotAdapter`, and
`PVTSample` are frozen contracts: imported, never edited.

## Operator demo & runbook

For a full no-hardware demo checklist (copy-paste replay commands, the exact
expected ASCII output from `tests/fixtures/sample.canlog`, a symptom -> cause ->
fix troubleshooting table, and the HARDWARE-GATED live-bus path), see
[`DEMO.md`](./DEMO.md).

## Run it

Invoke from the `host/` directory (matches `pyproject.toml` `pythonpath = ["."]`,
the same convention the test suite uses):

```bash
cd host

# Replay a recorded .canlog episode
python -m viz path/to/episode.canlog

# Or pipe decoded canlog frames (JSONL) on stdin
cat path/to/episode.canlog | python -m viz -

# Animated full-screen terminal view (ANSI clear between snapshots)
python -m viz path/to/episode.canlog --clear
```

## Data path (all reused, no re-implementation)

```
.canlog file / stdin (JSONL)
  -> CanFrame                       (transport.file.FileReplayTransport)
    -> fields_from_frame()          (frozen codec -> inhabit_bridge.conversion.PodFields)
      -> render_frame()             (viz.ascii_viz)
```

Each incoming CAN frame updates one pod (keyed by `node_id`) and re-renders the
whole chain — exactly how a live telemetry display behaves.

## Failure mode this closes

The visualizer was **orphaned**: `ascii_viz.render_frame` existed but nothing fed
it real frames, so an operator could not actually see live joint angles
(BENCHMARKS item 8 — no orphaned modules). `runner.py` + `__main__.py` are the
missing wiring.

A malformed input line fails loud (`ValueError` with `path:lineno` / `stdin:lineno`
context) instead of silently dropping telemetry; an empty source exits non-zero
with `viz: no frames to display`.

## Smoke-test against the committed fixture (P5, no hardware)

A tiny committed CAN log, `host/tests/fixtures/sample.canlog` (a 3-pod chain at
100 Hz — see `docs/hardware-free-data-path-smoke-test.md`), lets you render the viz
with zero hardware. The replay transport re-stamps each frame on the host's
monotonic clock at `recv()` time (`time.monotonic_ns`), so rendered timestamps
reflect replay-time, not the fixture's recorded provenance `t_ns`. Jitter
measurement and the time-sync method (`single_monotonic_host_clock`) are
documented in `host/logger/jitter.py` and `host/export/lerobot.py`
(`time_base.time_sync_method`). From `host/`:

```bash
python -m viz tests/fixtures/sample.canlog
```

### Expected output (final chain snapshot)

The runner re-renders the whole chain on every frame, keyed by `node_id`. The last
snapshot printed is the three pods at the final tick (this exact block is pinned by
`tests/test_postgreen_smoke.py::test_postgreen_viz_renders_full_chain_from_fixture`,
so a rendering regression fails loud):

```text
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.50 deg  [--------------------#-------------------] ok
pod  3:2    +13.50 deg  [--------------------|#------------------] ok
```

`|` is the 0-rad center mark; `#` is the joint position. Pod 2 sits at +1.50 deg, so
its `#` lands on the center column and overwrites the `|` — expected, not a bug.

### Failure cases (all exit non-zero, fail loud)

```bash
# Empty source -> nothing to show
printf '' | python -m viz -
# stderr: viz: no frames to display          (exit 1)

# Missing file -> surfaced, not a stack trace
python -m viz does_not_exist.canlog
# stderr: viz: [Errno 2] No such file or directory: 'does_not_exist.canlog'   (exit 1)

# Malformed canlog line -> path:lineno context, telemetry never silently dropped
printf 'not json\n' | python -m viz -
# stderr: viz: stdin:1: malformed canlog line: Expecting value: ...           (exit 1)
```

For the full P3 (replay) and P4 (lerobot export round-trip) commands against the
same fixture, see `docs/hardware-free-data-path-smoke-test.md`.
