# inhabit_bridge

CAN to ROS 2 (Jazzy) bridge for Inhabit smart joint pods. Reads CAN frames,
decodes them via the **frozen** `inhabit_can.codec`, stamps a **monotonic** host
RX time, and publishes `inhabit_msgs/JointPodState`. Runs headless with zero
hardware via a replay / sim source.

## Packages
- `inhabit_msgs` — `JointPodState.msg` (ament_cmake, rosidl). Jazzy.
- `inhabit_bridge` — this node (ament_python). Jazzy.

> **Operators:** for copy-paste replay / live-CAN runbook (incl. socketcan
> bring-up, slcan status, and a troubleshooting table), see
> [`OPERATING.md`](./OPERATING.md).

## Launch
```bash
# headless, zero hardware (synthesizes valid pod frames)
ros2 launch inhabit_bridge bridge.launch.py

# real bus on a Linux/Jazzy host
ros2 launch inhabit_bridge bridge.launch.py source:=socketcan channel:=can0

# replay a recorded .canlog through host/transport (zero hardware)
ros2 launch inhabit_bridge bridge.launch.py source:=file path:=/data/run.canlog
```

### Parameters
| Param      | Default            | Description                                  |
|------------|--------------------|----------------------------------------------|
| `source`   | `sim`              | CAN source: `sim` \| `replay` \| `file` \| `socketcan` |
| `channel`  | `can0`             | socketcan channel (only when `source:=socketcan`) |
| `path`     | `""`              | `.canlog` recording (required when `source:=file`) |
| `topic`    | `joint_pod_state`  | Output `JointPodState` topic name            |
| `frame_id` | `joint_pod`        | `header.frame_id` on published messages      |

### CAN sources
The bridge consumes anything implementing the `CanSource` interface
(`sources.py`). Two sources are backed by **host/transport** (PR #6) via the thin
`transport_source.TransportSource` adapter, so the transport layer is a
first-class bridge input without duplicating replay logic or re-implementing
decoding (decoding stays in the frozen codec):

| `source`     | Backing                                              |
|--------------|------------------------------------------------------|
| `sim`        | `sources.SimSource` (synthetic sweeping frames)      |
| `replay`     | `sources.ReplaySource` (in-memory frame list)        |
| `file`       | `transport.FileReplayTransport` (replays a `.canlog`)|
| `socketcan`  | `transport.SocketCanTransport` (Linux socketcan)     |

QoS (publisher): `KEEP_LAST` depth 10, `BEST_EFFORT`, `VOLATILE` — sensor-style
telemetry where the freshest sample wins and occasional loss is acceptable.

## Time-sync (first-class)
`header.stamp` is the time-sync anchor. It is read from a **single monotonic
clock** (`time.monotonic_ns`) at CAN-RX, the instant each frame leaves the
source — **never wall clock**. The ns value is split into `(sec, nanosec)` and
written verbatim into `header.stamp`. Consumers (incl. Track 3 PVT logging)
must treat it as a monotonic host clock, not POSIX/UTC time, and use it to align
CAN, video, and tactile streams.

Jitter: a `ReplaySource`/`SimSource` driven test shows strictly increasing
stamps; real jitter is dominated by the socketcan RX path and must be measured
on a Jazzy host with hardware (see "Needs a Jazzy env" below).

## Bad-checksum policy
A frame whose codec checksum fails is **still published**, with
`checksum_valid=False`, plus a throttled `WARN` log. Rationale: the data
pipeline must see corruption/dropouts to compute link quality and quarantine
episodes; silent drops would hide bus faults (root CLAUDE.md: "fail loud").
Downstream filters on `checksum_valid`. Frames that are not 8 bytes are dropped
with a log (they cannot be decoded by the v1 codec).

## Field mapping (Track 3 handoff)
`JointPodState` fields map 1:1 from codec `decode_state()` (`State`) plus the
header stamp and two derived fields:

| JointPodState     | Source                                            |
|-------------------|---------------------------------------------------|
| `header.stamp`    | monotonic host RX ns (`time.monotonic_ns`)        |
| `header.frame_id` | `frame_id` param                                  |
| `node_id`         | `State.node_id`                                   |
| `chain_index`     | `State.chain_index`                               |
| `angle_raw_adc`   | `State.angle_raw_adc`                             |
| `angle_millideg`  | `State.angle_millideg` (int16, ~±32.767 deg)      |
| `angle_rad`       | derived: `angle_millideg * pi / 180 / 1000`       |
| `status_flags`    | `State.status_flags`                              |
| `checksum_valid`  | `State.valid`                                      |
| `schema_version`  | `inhabit_can.codec.PROTO_VERSION` (1)             |

The ROS-independent mapping lives in `inhabit_bridge.conversion.PodFields` /
`fields_from_frame()` so it can be consumed/tested without a ROS install.

## Testing without ROS
The codec-facing logic (`conversion`, `sources`, `bridge_node.build_message`,
`stamp_from_monotonic_ns`) imports no ROS modules at top level, so
`host/tests/test_bridge.py` runs as plain Python:
```bash
cd host && python -m pytest tests/ -q
```

## Needs a real Jazzy environment to finish-verify
- `colcon build` of `inhabit_msgs` + `inhabit_bridge` and message generation.
- `ros2 launch inhabit_bridge bridge.launch.py` end-to-end (node spins,
  publishes on `joint_pod_state`, `ros2 topic echo`).
- Measured RX jitter on a real socketcan bus.
- `socketcan` source requires `python-can` and a configured `can` interface
  (imported lazily; not needed for the headless replay/sim path).
