# viz — operator demo & runbook

Goal: make Inhabit pod telemetry **observable with no hardware**. This is the
copy-paste checklist for a replay demo off the committed fixture, the exact ASCII
output you should see, a troubleshooting table, and the **hardware-gated** live path.

The viz only **consumes** frozen contracts (CAN codec, `JointPodState.msg`,
`RobotAdapter`, `PVTSample`). Nothing here edits them.

---

## 0. The pipeline you are observing

```
.canlog file / stdin (JSONL)
  -> CanFrame                       transport.file.FileReplayTransport  (replay)
    -> fields_from_frame()          inhabit_bridge.conversion (frozen codec -> PodFields)
      -> render_frame()             viz.ascii_viz
```

- One incoming CAN frame updates exactly one pod, keyed by `node_id`.
- The runner re-renders the **whole chain** on every frame — the same behavior a
  live telemetry display has.
- Pods are printed sorted by `(chain_index, node_id)`, so chain order is visible.
- Replay re-stamps each frame on the host's monotonic clock at `recv()` time. The
  on-disk `t_ns` is provenance only; it does not change the rendered angles.

Code map: `viz/ascii_viz.py` (rendering), `viz/runner.py` (wiring), `viz/__main__.py`
(CLI), `inhabit_bridge/conversion.py` (`fields_from_frame` -> `PodFields`).

---

## 1. Replay demo (NO HARDWARE) — copy-paste

All commands run from `host/` (matches `pyproject.toml` `pythonpath = ["."]`, the
same convention the test suite uses).

### Step 1 — go to host/

```bash
cd host
```

### Step 2 — replay the committed fixture

The fixture `tests/fixtures/sample.canlog` is a 3-pod daisy chain (`chain_index`
0/1/2, `node_id` 1/2/3) streaming 8 ticks at 100 Hz (24 frames total).

```bash
python -m viz tests/fixtures/sample.canlog
```

This prints one chain snapshot per frame (24 snapshots). The chain grows from 1
pod (only pod 1 seen) to all 3 as more `node_id`s arrive, then ramps. The **final
snapshot** (the bottom 3 lines) is the steady-state you verify against:

```text
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.50 deg  [--------------------#-------------------] ok
pod  3:2    +13.50 deg  [--------------------|#------------------] ok
```

> **Host timestamp note:** the angles above carry no timestamp in the ASCII line,
> but the frames behind them do. On replay, each frame is re-stamped with
> `time.monotonic_ns()` at `FileReplayTransport.recv()` time — a single monotonic
> host RX clock, never wall-clock. The fixture's on-disk `t_ns` (0, 2_500_000,
> 5_000_000, … = `make_sample_canlog.PER_RECORD_NS` apart) is **provenance only**:
> it is not read at render time and does not affect the rendered angles. For
> time-sync alignment of replay/video/tactile traces, use the host-stamped
> `rx_monotonic_ns` on each `CanFrame` (the same clock the bridge writes into
> `header.stamp` via `bridge_node.stamp_from_monotonic_ns`).

Read the bar: `|` is the 0-rad center mark; `#` is the joint position within
`[-pi, +pi]`. Pod 2 is at +1.50 deg, so its `#` lands on the center column and
**overwrites** the `|` — expected, not a bug. `ok` means `status_flags == 0` and
the checksum is valid.

### Step 3 — animated full-screen view (optional)

```bash
python -m viz tests/fixtures/sample.canlog --clear
```

`--clear` emits an ANSI clear-screen before each snapshot so the bars animate in
place. Omit it whenever you want plain, captureable output (logging, piping, CI).

### Step 4 — stdin / pipe path (same result)

Useful for chaining tools or replaying a log you produce elsewhere. `-` reads
canlog JSONL (one record per line) from stdin:

```bash
cat tests/fixtures/sample.canlog | python -m viz -
```

Final 3 lines are identical to Step 2 (same host-monotonic re-stamping applies):

```text
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.50 deg  [--------------------#-------------------] ok
pod  3:2    +13.50 deg  [--------------------|#------------------] ok
```

---

## 2. Full expected output (fixture replay)

This is the **real** rendered output of `python -m viz tests/fixtures/sample.canlog`
(captured, not hand-written). The chain fills in over the first 3 frames, then all
3 pods ramp together for the remaining ticks. The last block matches Step 2.

```text
pod  1:0    -14.00 deg  [------------------#-|-------------------] ok
pod  1:0    -14.00 deg  [------------------#-|-------------------] ok
pod  2:1     -2.00 deg  [-------------------#|-------------------] ok
pod  1:0    -14.00 deg  [------------------#-|-------------------] ok
pod  2:1     -2.00 deg  [-------------------#|-------------------] ok
pod  3:2    +10.00 deg  [--------------------|#------------------] ok
pod  1:0    -13.50 deg  [------------------#-|-------------------] ok
pod  2:1     -2.00 deg  [-------------------#|-------------------] ok
pod  3:2    +10.00 deg  [--------------------|#------------------] ok
pod  1:0    -13.50 deg  [------------------#-|-------------------] ok
pod  2:1     -1.50 deg  [-------------------#|-------------------] ok
pod  3:2    +10.00 deg  [--------------------|#------------------] ok
pod  1:0    -13.50 deg  [------------------#-|-------------------] ok
pod  2:1     -1.50 deg  [-------------------#|-------------------] ok
pod  3:2    +10.50 deg  [--------------------|#------------------] ok
pod  1:0    -13.00 deg  [------------------#-|-------------------] ok
pod  2:1     -1.50 deg  [-------------------#|-------------------] ok
pod  3:2    +10.50 deg  [--------------------|#------------------] ok
pod  1:0    -13.00 deg  [------------------#-|-------------------] ok
pod  2:1     -1.00 deg  [-------------------#|-------------------] ok
pod  3:2    +10.50 deg  [--------------------|#------------------] ok
pod  1:0    -13.00 deg  [------------------#-|-------------------] ok
pod  2:1     -1.00 deg  [-------------------#|-------------------] ok
pod  3:2    +11.00 deg  [--------------------|#------------------] ok
pod  1:0    -12.50 deg  [------------------#-|-------------------] ok
pod  2:1     -1.00 deg  [-------------------#|-------------------] ok
pod  3:2    +11.00 deg  [--------------------|#------------------] ok
pod  1:0    -12.50 deg  [------------------#-|-------------------] ok
pod  2:1     -0.50 deg  [-------------------#|-------------------] ok
pod  3:2    +11.00 deg  [--------------------|#------------------] ok
pod  1:0    -12.50 deg  [------------------#-|-------------------] ok
pod  2:1     -0.50 deg  [-------------------#|-------------------] ok
pod  3:2    +11.50 deg  [--------------------|#------------------] ok
pod  1:0    -12.00 deg  [------------------#-|-------------------] ok
pod  2:1     -0.50 deg  [-------------------#|-------------------] ok
pod  3:2    +11.50 deg  [--------------------|#------------------] ok
pod  1:0    -12.00 deg  [------------------#-|-------------------] ok
pod  2:1     +0.00 deg  [--------------------#-------------------] ok
pod  3:2    +11.50 deg  [--------------------|#------------------] ok
pod  1:0    -12.00 deg  [------------------#-|-------------------] ok
pod  2:1     +0.00 deg  [--------------------#-------------------] ok
pod  3:2    +12.00 deg  [--------------------|#------------------] ok
pod  1:0    -11.50 deg  [------------------#-|-------------------] ok
pod  2:1     +0.00 deg  [--------------------#-------------------] ok
pod  3:2    +12.00 deg  [--------------------|#------------------] ok
pod  1:0    -11.50 deg  [------------------#-|-------------------] ok
pod  2:1     +0.50 deg  [--------------------#-------------------] ok
pod  3:2    +12.00 deg  [--------------------|#------------------] ok
pod  1:0    -11.50 deg  [------------------#-|-------------------] ok
pod  2:1     +0.50 deg  [--------------------#-------------------] ok
pod  3:2    +12.50 deg  [--------------------|#------------------] ok
pod  1:0    -11.00 deg  [------------------#-|-------------------] ok
pod  2:1     +0.50 deg  [--------------------#-------------------] ok
pod  3:2    +12.50 deg  [--------------------|#------------------] ok
pod  1:0    -11.00 deg  [------------------#-|-------------------] ok
pod  2:1     +1.00 deg  [--------------------#-------------------] ok
pod  3:2    +12.50 deg  [--------------------|#------------------] ok
pod  1:0    -11.00 deg  [------------------#-|-------------------] ok
pod  2:1     +1.00 deg  [--------------------#-------------------] ok
pod  3:2    +13.00 deg  [--------------------|#------------------] ok
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.00 deg  [--------------------#-------------------] ok
pod  3:2    +13.00 deg  [--------------------|#------------------] ok
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.50 deg  [--------------------#-------------------] ok
pod  3:2    +13.00 deg  [--------------------|#------------------] ok
pod  1:0    -10.50 deg  [------------------#-|-------------------] ok
pod  2:1     +1.50 deg  [--------------------#-------------------] ok
pod  3:2    +13.50 deg  [--------------------|#------------------] ok
```

What "correct" looks like at a glance:

- **3 distinct pods**, lines sorted `pod 1:0`, `pod 2:1`, `pod 3:2`.
- Each pod's `#` sits in a **different column** — pod 1 left of center, pod 2 on
  center, pod 3 right of center.
- The `#` **drifts smoothly** over time (the ramp) with no stuck rows.
- Every line ends in `ok` — no `0x..` status flags, no `CK!`.

> The final-block lines are pinned by
> `tests/test_postgreen_smoke.py::test_postgreen_viz_renders_full_chain_from_fixture`,
> so a rendering regression fails CI loud.

---

## 3. Troubleshooting

Each row maps a symptom in the ASCII display to a cause and a fix, keyed to the
code that produces (or would produce) it.

| Symptom in viz | Likely cause | Fix / where to look |
|---|---|---|
| **No pods at all** — `viz: no frames to display` (exit 1) | Source was empty, or every line was blank. `render_stream` rendered 0 frames, so `__main__.main` returns 1. | Confirm the file is non-empty and is real canlog JSONL. Re-run Step 2. For a live bus, this means **zero frames arrived** — go to the live-path checklist (bus down, no pods powered, wrong channel). |
| **Fewer pods than expected** (e.g. only `pod 1:0` shows) | Pods are keyed by `node_id` in `runner.render_stream`; a pod only appears once its **first** frame is decoded. Early snapshots legitimately show a partial chain (see section 2). If it never fills in, that `node_id` never transmitted. | Watch the **last** snapshot, not the first. If a pod is still missing at the end: bad/duplicate `node_id`, unenumerated pod, or a dead board. Check enumeration (root CLAUDE.md ENUM protocol) and `node_id`/`chain_index` bytes 4/5 of the v1 payload. |
| **Wrong pod order** (chain looks shuffled) | Lines are sorted by `(chain_index, node_id)` in `ascii_viz.render_frame`. Wrong order means the **`chain_index` byte is wrong on the wire**, not a viz bug. | Fix enumeration on the chain (ENUM line / host seeds index 0). The viz faithfully shows whatever `chain_index` the pod reported — do not "fix" it in viz. |
| **Frozen values** (a pod's `#` and degrees never change) | That `node_id` stopped sending new frames; `runner` keeps showing the **last known** `PodFields` for it. On a real bus: stuck encoder ADC, hung MCU, or a wedged board still on the bus. | For replay: confirm the log actually varies that pod. For live: check the pod's encoder (A0 ADC) and that its frames are still arriving (`candump`). |
| **Jitter** (`#` jumps around erratically, degrees noisy) | Encoder ADC noise upstream (analog MT6701 out on A0). The viz shows raw decoded `angle_millideg`; it does no filtering. | Filtering is a firmware concern (root CLAUDE.md: "Filter encoder ADC noise"), not viz. Inspect `angle_raw_adc` (bytes 0-1) vs `angle_millideg` (bytes 2-3) to separate sensor noise from a decode issue. |
| **Missing frames / gaps** (chain count dips, or live stream stalls) | BEST_EFFORT QoS on the bridge (`bridge_node`) and a high-rate CAN stream mean occasional loss is acceptable by design. The viz never blocks waiting for a frame. | Expected under load; the freshest sample wins. If loss is heavy on a live bus: check termination, bitrate (`SocketCanTransport` defaults 500 kbit/s), and bus errors. |
| **`CK!` at end of a line** | Codec checksum failed for that frame. `conversion.fields_from_frame` decodes it anyway with `checksum_valid=False`; viz appends `CK!` so corruption is **visible, never silently dropped** (root CLAUDE.md: "fail loud"). | Treat as a bus-integrity signal: noise/ESD, bad termination, or a firmware checksum bug (byte 7 of the v1 payload). Quarantine the episode for PVT logging. |
| **`0x..` instead of `ok`** | `status_flags` (byte 6) is non-zero. The pod is reporting a fault. | Decode the flag bits against the firmware `status_flags` definition; the pod is signaling a hardware/firmware condition (fail-loud by design). |
| **`viz: ...: malformed canlog line: ...` (exit 1)** | A line is not valid canlog JSONL (bad JSON, missing `id`/`data`, odd-length hex). `runner.frames_from_stdin` / `frames_from_replay` raise `ValueError` with `path:lineno` context. | Fix the offending line (the error names the line number). Telemetry is never silently dropped — this is intentional. |
| **Timestamp confusion** (on-disk `t_ns` doesn't match what you expect) | Replay **re-stamps** each frame on the host monotonic clock at `recv()` time. The fixture's `t_ns` is **provenance only** and does not affect rendered angles. | Don't read meaning into the fixture `t_ns`. For real time-sync, the bridge writes `header.stamp` from a single monotonic host RX clock (`bridge_node.stamp_from_monotonic_ns`); see `host/CLAUDE.md` time-sync rule. |

### Verified failure-mode outputs (real captures)

```bash
# Empty source -> nothing to show
printf '' | python -m viz -
# stderr: viz: no frames to display                                           (exit 1)

# Missing file -> surfaced cleanly, not a stack trace
python -m viz does_not_exist.canlog
# stderr: viz: [Errno 2] No such file or directory: 'does_not_exist.canlog'   (exit 1)

# Malformed canlog line -> path:lineno context
printf 'not json\n' | python -m viz -
# stderr: viz: stdin:1: malformed canlog line: Expecting value: line 1 column 1 (char 0)   (exit 1)

# Bad checksum byte (byte 7 corrupted) -> still rendered, marked CK!
printf '{"v":1,"t_ns":0,"id":257,"data":"000150c9010000FF"}\n' | python -m viz -
# stdout: pod  1:0    -14.00 deg  [------------------#-|-------------------] ok CK!
```

---

## 4. Live demo path (from a real bus) — HARDWARE-GATED

> **HARDWARE-GATED.** Everything below requires a powered Rev-A chain on a Linux
> host with ROS 2 Jazzy and socketcan. It is **not** part of the no-hardware exit
> criteria and is **unverified** until the evidence checklist is filled in.

### Topology

```
Rev-A pod chain (CANH/CANL/ENUM)
  -> USB-CAN / socketcan (can0)
    -> inhabit_bridge bridge_node (source:=socketcan)  -> /joint_pod_state (JointPodState)
    -> (parallel) candump can0 > live.canlog            -> python -m viz live.canlog
```

Two ways to watch live angles:

1. **Bridge -> ROS topic** (the production path): the bridge publishes
   `JointPodState` on `/joint_pod_state`. Confirm with `ros2 topic echo`.
2. **Capture -> viz** (operator glance): tee bus frames into a `.canlog` and feed
   the same replay viz. The viz itself stays hardware-free.

### Bring-up (Linux + Jazzy only)

```bash
# 1. Bring up the CAN interface (matches SocketCanTransport default 500 kbit/s)
sudo ip link set can0 type can bitrate 500000
sudo ip link set up can0

# 2. Confirm raw frames arrive at all (IDs should be 0x100 + node_id = 0x101.. )
candump can0

# 3. Launch the bridge on the live bus
ros2 launch inhabit_bridge bridge.launch.py source:=socketcan channel:=can0

# 4a. Verify the published telemetry
ros2 topic echo /joint_pod_state

# 4b. OR capture to a canlog and watch the ASCII bars live
candump -L can0 | <your canlog adapter> > live.canlog   # tee a JSONL .canlog
python -m viz live.canlog --clear
```

> Note: `candump -L` is the native SocketCAN log format, **not** the Inhabit
> `.canlog` JSONL the viz/transport consume (`{"v":1,"t_ns":..,"id":..,"data":"<hex>"}`).
> A small adapter is needed to convert, or record directly through
> `transport.file.FileRecorder`. The viz contract is the JSONL format only.

### Evidence required to mark the live path VERIFIED

This path stays HARDWARE-GATED until **all** of the following are captured on a
powered chain and attached to the bench report:

- [ ] `candump can0` output showing frames with IDs `0x101`, `0x102`, `0x103`
      (= `0x100 + node_id` for a 3-pod chain).
- [ ] `ros2 topic echo /joint_pod_state` showing distinct `node_id` /
      `chain_index` and a monotonic, increasing `header.stamp`.
- [ ] `python -m viz` (live capture) screenshot/paste showing 3 pods in chain
      order with `#` bars that **move** as the operator moves the arm.
- [ ] At least one `CK!` or `0x..` event observed and explained (proves fail-loud
      works on real noise), or an explicit note that none occurred over N minutes.
- [ ] Measured inter-sample jitter on the live bus. Jitter is a **live-bus
      property**, so this item is HARDWARE-GATED — the replay demo cannot stand in
      for it. The synthetic fixture is deterministic (`make_sample_canlog.py` spaces
      every record by a fixed `PER_RECORD_NS`), so its inter-sample jitter is
      effectively zero by construction; it proves the render path, not bus timing.
      On a real chain, measure with `ros2 topic hz /joint_pod_state` (publish rate /
      stddev) and/or run the captured `rx_monotonic_ns` stream through
      `host/logger/jitter.py` (`compute_jitter`). Record the measured `jitter_p99_ns`
      and the clock source (host `time.monotonic_ns` via
      `bridge_node.stamp_from_monotonic_ns`), and report whether it passes the
      logger's documented budget (`JitterBudget`: default `max_jitter_p99_ns` 2 ms,
      `max_gap_factor` 2.5). **No number is asserted here — fill it in from the
      measurement.**

Until that checklist is complete, the **replay demo (sections 1-2) is the
authoritative no-hardware demo**.

---

## 5. Exit-criteria self-check

```bash
# from repo root
python -m pytest host -q

# from host/
ruff check .
mypy .
```

- No-hardware replay demo runs (section 1). [verified]
- Expected ASCII documented from real output (section 2). [verified]
- Live path marked HARDWARE-GATED with explicit evidence checklist (section 4).
- Frozen contracts untouched — viz only consumes.
