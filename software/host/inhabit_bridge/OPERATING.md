# Operating the Inhabit CAN bridge — replay & live CAN

Operator runbook for getting CAN frames flowing through the bridge, on a bench
with **no hardware** (replay) and on a **real bus** (live socketcan). Every
command here is copy-paste; every path that needs a board or a USB-CAN adapter is
marked **[HW-GATED]** with the exact check to confirm it.

This is a runbook. Architecture / QoS / time-sync rationale live in
[`README.md`](./README.md). Frozen contracts (`inhabit_can.codec`,
`RobotAdapter`, `PVTSample`, `JointPodState.msg`) are never edited.

> **Two replay paths, pick by what you have installed.**
> 1. **No ROS, no hardware** → `tools.can_replay` (pure Python, decodes through
>    the frozen codec). Use this to prove the capture + codec stack on any box.
> 2. **ROS 2 / Jazzy** → `ros2 launch ... source:=file` (publishes
>    `JointPodState` on a topic). Needs a built Jazzy workspace.

---

## 1. Replay a recording — ONE copy-paste command (no hardware, no ROS)

Run from the **repo root**. This replays the committed
`host/tests/fixtures/sample.canlog` (a deterministic 3-pod / 8-tick stand-in for
a real bench capture) and decodes each frame through the **frozen** codec:

```bash
python -m tools.can_replay replay host/tests/fixtures/sample.canlog
```

Expected output (first lines) — verified from this worktree:

```text
Replaying host/tests/fixtures/sample.canlog
  id=0x101  node=1  chain=0  angle=-14.000 deg  raw=256  flags=0x00  valid=True
  id=0x102  node=2  chain=1  angle=-2.000 deg  raw=512  flags=0x00  valid=True
  id=0x103  node=3  chain=2  angle=10.000 deg  raw=768  flags=0x00  valid=True
  ...
Done.
```

What "good" looks like:
- 24 frames (3 pods × 8 ticks), IDs cycle `0x101 0x102 0x103` (= `0x100 + node_id`).
- Every line `valid=True` (codec checksum passes).
- Ends with `Done.`

No `python-can`, no ROS, no board needed — this is the path that must always work.

**Time-sync (how the stamp is made).** Every frame's receive time comes from a
**single monotonic host clock** — `time.monotonic_ns`, read at RX. In the ROS
bridge this `rx_monotonic_ns` is split into `(sec, nanosec)` and written verbatim
into `header.stamp` (`bridge_node.stamp_from_monotonic_ns`); `conversion.py` adds
no time of its own. For *this* replay tool the same monotonic clock re-stamps each
frame inside `FileReplayTransport.recv()` (`host/transport/file.py`), so the
on-disk `t_ns` in the `.canlog` is **provenance only** — replay does not reuse it.
Decoded angles are deterministic regardless of stamping.

**Jitter.** For deterministic fixture replay, inter-sample jitter is effectively
**zero**: the fixture is synthetic (`sample.canlog` models a 3-pod chain at a
fixed 100 Hz tick — see `host/tests/fixtures/make_sample_canlog.py`) and frames
are drained back-to-back, so the stamps carry no bus timing. **Real inter-sample
jitter is a property of the live socketcan RX path and must be measured on a real
bus [HW-GATED]** (e.g. `ros2 topic hz /joint_pod_state` on a Jazzy host) — it is
not represented by replay. No jitter numbers are asserted here.

---

## 2. Replay the SAME recording through the ROS 2 bridge (needs Jazzy, no hardware)

This publishes `inhabit_msgs/JointPodState` on a ROS topic using the
`FileReplayTransport` behind `source:=file`. Requires a built ROS 2 **Jazzy**
workspace (`colcon build` of `inhabit_msgs` + `inhabit_bridge`, then
`source install/setup.bash`).

Use an **absolute** `.canlog` path (the node resolves the path from its own cwd,
which under `ros2 launch` is not your shell's cwd):

```bash
ros2 launch inhabit_bridge bridge.launch.py \
  source:=file \
  path:=/abs/path/to/repo/host/tests/fixtures/sample.canlog
```

Confirm frames are publishing (second terminal, same sourced workspace):

```bash
ros2 topic echo /joint_pod_state
```

You should see `JointPodState` messages with `node_id` 1/2/3, `chain_index`
0/1/2, `checksum_valid: true`, and a monotonic `header.stamp`. File replay is
**finite** — the node stops yielding once the log is exhausted (`stop_on_none=True`
in `transport_source.py`).

---

## 3. Live CAN — real bus **[HW-GATED]**

Requires a Linux/Jazzy host, `python-can` installed, **and** a configured CAN
interface (USB-CAN adapter or on-board controller). The bridge uses
`SocketCanTransport`, which is hardcoded to python-can's `interface="socketcan"`
(see `host/transport/socketcan.py`).

### 3a. Bring up the interface (one-time, per boot) **[HW-GATED]**

Inhabit's default bitrate is **500000** (the `SocketCanTransport` default). Match
it to the bus / firmware:

```bash
sudo ip link set can0 type can bitrate 500000
sudo ip link set up can0
```

**Confirm the link is up before launching the bridge:**

```bash
ip -details link show can0          # state should be UP, bitrate 500000
candump can0                        # raw frames; Ctrl-C to stop
```

`candump` must show frames at IDs **`0x100 + node_id`** (e.g. `101 102 103` for a
3-pod chain). If `candump` is silent, the bridge will also see nothing — fix the
bus first (see Troubleshooting).

### 3b. Launch the bridge against the live bus **[HW-GATED]**

```bash
ros2 launch inhabit_bridge bridge.launch.py source:=socketcan channel:=can0
```

Confirm it is publishing:

```bash
ros2 topic hz /joint_pod_state      # rate ≈ (pods × firmware tick rate)
ros2 topic echo /joint_pod_state    # live JointPodState messages
```

Live socketcan is **infinite**: a `recv` timeout is treated as a quiet bus, not
end-of-stream (`stop_on_none=False`), so the node keeps reading.

### Record a live capture for later headless replay **[HW-GATED]**

```bash
python -m tools.can_replay record -c can0 -b 500000 -o capture.canlog
```

Then replay it anywhere with the no-hardware command in §1:
`python -m tools.can_replay replay capture.canlog`.

### slcan — **PLANNED / not implemented**

slcan (serial-line CAN, e.g. CANable / USBtin in slcan mode) is **not supported
in code today**. `SocketCanTransport` and `SocketCanSource` both pass
`interface="socketcan"` only — there is no slcan backend or `interface` param.

To use an slcan adapter now, convert it to a socketcan interface at the OS level
first (then it is just §3 above) **[HW-GATED]**:

```bash
sudo slcand -o -c -s6 /dev/ttyACM0 can0   # -s6 = 500 kbit/s
sudo ip link set up can0
```

A native slcan transport (selectable backend on `SocketCanTransport`) is future
work and must be added behind the existing `CanTransport` interface — never by
branching on robot type in the bridge.

---

## 4. Bridge launch parameters

All sources are selected via `source:=` on `bridge.launch.py`. Decoding is always
the frozen codec, downstream — never re-implemented per source.

| Param      | Default           | Used when            | Description |
|------------|-------------------|----------------------|-------------|
| `source`   | `sim`             | always               | `sim` \| `replay` \| `file` \| `socketcan` |
| `channel`  | `can0`            | `source:=socketcan`  | socketcan channel name |
| `path`     | `""`              | `source:=file`       | path to a `.canlog` (use absolute) |
| `topic`    | `joint_pod_state` | always               | output `JointPodState` topic |
| `frame_id` | `joint_pod`       | always               | `header.frame_id` on messages |

| `source`     | Backing                                 | Hardware? | ROS? |
|--------------|-----------------------------------------|-----------|------|
| `sim`        | `SimSource` (synthetic sweeping frames) | no        | yes  |
| `replay`     | `ReplaySource` (in-memory frame list)   | no        | yes  |
| `file`       | `FileReplayTransport` (replays `.canlog`)| no       | yes  |
| `socketcan`  | `SocketCanTransport` (Linux socketcan)  | **yes**   | yes  |

Notes from the code (do not assume otherwise):
- `source:=replay` feeds an **empty** in-memory list by default
  (`_make_source` in `bridge_node.py`) — it publishes nothing unless a caller
  injects frames programmatically. **To replay a file through ROS, use
  `source:=file`, not `replay`.**
- `source:=file` with an empty `path` **raises** `ValueError` at startup
  ("source='file' requires a 'path'").
- The smallest zero-hardware sanity check that needs no recording at all:
  `ros2 launch inhabit_bridge bridge.launch.py` (defaults to `sim`).

---

## 5. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---------|--------------|-------------|
| **No frames on `/joint_pod_state`** (live) | bus quiet / no pods powered / wrong channel | `candump can0` first — if it's silent, the bridge will be too. Confirm pods powered and on the bus. |
| **No frames** (`source:=file`) | file replay is finite and already drained, or empty file | re-run; check the `.canlog` has lines: `wc -l file.canlog`. Re-record/regenerate if 0. |
| **`candump` shows frames, bridge does not** | interface vs. param mismatch, or python-can missing | confirm `channel:=` matches the up interface; `pip show python-can`. |
| **Wrong bitrate** | bus bitrate ≠ firmware/adapter | `candump` shows error frames or nothing; `ip -details link show can0` to read bitrate; re-`ip link set ... bitrate 500000` (Inhabit default). Mismatch = bus-off. |
| **Wrong / unexpected CAN IDs** | non-Inhabit traffic, or wrong node_id range | valid pod IDs are `0x100 + node_id` (`0x101+`). `SocketCanTransport.recv` drops a frame (returns `None`) only when it is non-8-byte; any 8-byte frame reaches the codec regardless of ID. Filter on the bus or verify firmware `node_id`. |
| **Empty replay / `Done.` with no rows** | `.canlog` has no records | inspect the file; regenerate the fixture: `cd host && python -m tests.fixtures.make_sample_canlog`. |
| **Missing path** (`source:=file`) | `path:=` not given | node raises `ValueError: source='file' requires a 'path'`. Pass an **absolute** `path:=`. |
| **`FileNotFoundError` on replay** | relative path resolved against node cwd | under `ros2 launch` the cwd is not your shell's; always pass an **absolute** `path:=`. |
| **Wrong interface / `can0` not found** | interface not brought up | `ip link show can0`; bring up with `sudo ip link set can0 type can bitrate 500000 && sudo ip link set up can0`. |
| **`ModuleNotFoundError: can`** | `python-can` not installed | only needed for `socketcan` / `record`; `pip install python-can`. Replay (§1) and `sim` do not need it. |
| **`malformed canlog line` on replay** | corrupt/truncated `.canlog`, or wrong schema `v` | error includes `path:lineno`; each record must be a v1 JSON object with an 8-byte hex `data` (`host/transport/file.py`). |
| **`checksum_valid=False` in messages** | bus corruption / bad firmware checksum | **expected to still publish** (fail-loud policy); investigate the bus, but Track 3 filters on this field. |

### Hardware-gated checks at a glance

| Path | Confirm it works with |
|------|-----------------------|
| Interface up | `ip -details link show can0` → state UP, bitrate 500000 |
| Live frames present | `candump can0` → frames at `0x101`/`0x102`/`0x103` |
| Bridge publishing | `ros2 topic hz /joint_pod_state` → non-zero rate |
| Capture recorded | `wc -l capture.canlog` → non-zero; then replay via §1 |

---

## 6. References (code, not docs)

- `host/transport/socketcan.py` — `SocketCanTransport` (interface=`socketcan`, default bitrate 500000)
- `host/transport/file.py` — `FileReplayTransport` / `FileRecorder` / `.canlog` format (v1 JSONL)
- `host/inhabit_bridge/bridge_node.py` — `_make_source()` source selection, params, QoS
- `host/inhabit_bridge/transport_source.py` — transport → `CanSource` adapter, `stop_on_none`
- `host/inhabit_bridge/launch/bridge.launch.py` — launch args
- `tools/can_replay/__main__.py` — `record` / `replay` CLI
- `host/tests/fixtures/sample.canlog` — committed replay fixture (regen: `host/tests/fixtures/make_sample_canlog.py`)
