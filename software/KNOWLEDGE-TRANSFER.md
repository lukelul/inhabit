# KNOWLEDGE TRANSFER -- Inhabit Project Snapshot

> **One sentence:** Inhabit is a universal teleoperation kernel -- modular smart joint pods and an ML-native data pipeline that turns human robot control into synchronized proprioceptive-visual-tactile (PVT) training data.

---

## Product Vision

### Universal Teleop Kernel

The hardware is an **actuated data-node**, not just a controller. Each smart joint pod is a modular sensor/actuator unit that slots into any kinematic chain. The software layer ingests teleoperation sessions and produces ML-ready datasets. The "last centimeter" -- contact, occlusion, force, friction, recovery -- is the data moat that current robot foundation models lack.

### Smart Joint Pod Concept

A self-contained joint module containing:
- Absolute magnetic encoder (angle sensing)
- CAN bus communication (daisy-chain topology)
- Physical enumeration (automatic chain ordering)
- Status/fault reporting
- Future: motor driver, MEMS contact sensor, current sensing

### Actuated Data-Node

The pod is not just hardware -- it is a data acquisition endpoint. Every joint angle reading, every fault flag, every contact event is a training signal. The business is the data pipeline, not the robot.

---

## Current State: Rev-A Smart Joint Sensor Node

A **validation board**, not the final actuated pod. Proves:
- Cheap absolute angle sensing (MT6701 magnetic encoder, analog output)
- Daisy-chained CAN telemetry (MCP2515 SPI CAN controller)
- Physical enumeration via ENUM line
- Repeatable modular manufacturing

### Hardware Stack

| Component | Part | Role |
|-----------|------|------|
| Encoder | MT6701 | Magnetic absolute angle, analog out to STM32 ADC |
| MCU | STM32C011F6P6 | Dev module (hand-soldered); bare chip in Rev-B |
| CAN controller | MCP2515 | SPI CAN (16 MHz crystal), 500 kbps |
| CAN transceiver | SN65HVD230 | CANH/CANL physical bus driver |
| TVS protection | SM24CANB-02HTG | ESD/transient on CAN bus |
| Bus | 5-wire daisy chain | 5V5, GND, CANH, CANL, ENUM |

### Canonical Pin Map (Rev-A)

| Signal | STM32 Pin | Notes |
|--------|-----------|-------|
| ENC_ADC | PA0 | MT6701 analog OUT |
| ENUM_IN | PA1 | From previous pod |
| ENUM_OUT | PA2 | To next pod |
| MCP2515 /INT | PB6 | Active-low, EXTI line 6, falling edge (CONFIRMED) |
| MCP2515_CS | PA4 | SPI chip select |
| SPI_SCK | PA5 | SPI clock |
| SPI_MISO | PA6 | SPI data in |
| SPI_MOSI | PA7 | SPI data out |
| Power in | 5V5 | Board input |
| Logic rail | VCC_BUS / 3V3 | Regulated |

---

## Firmware Stack

**Language:** C (STM32 HAL/LL). **Target:** STM32C011F6P6.

### Modules

| File | Purpose |
|------|---------|
| `firmware/src/main.c` | Main loop skeleton, ISR handlers, board init |
| `firmware/src/can_frame.c` | CAN schema v1 pack/unpack (frozen contract) |
| `firmware/src/calib.c` | ADC-to-millideg linear calibration, calibration telemetry |
| `firmware/src/can_health.c` | Uniform fault-bit policy (non-sticky clear on healthy round-trip) |
| `firmware/src/enum.c` | ENUM state machine (WAIT->DEBOUNCE->ASSIGNED->DONE) |
| `firmware/drivers/mcp2515.c` | MCP2515 SPI driver (reset, read/write/bitmod, TX, RX) |
| `firmware/inc/can_frame.h` | CAN schema v1 header (frozen contract) |
| `firmware/inc/mcp2515.h` | MCP2515 register map, constants, API |
| `firmware/inc/enum.h` | ENUM protocol contract, state types |
| `firmware/inc/calib.h` | Calibration types and API |
| `firmware/inc/can_health.h` | Health policy API |

### Firmware Rules
- No heap after init (static allocation only)
- No blocking in ISRs (ISRs set flags, main loop acts)
- Filter encoder ADC (oversample + median/IIR)
- Every CAN frame follows schema v1 with XOR checksum
- Faults set `status_flags` bits, never hang
- MCP2515 /INT confirmed on PB6 (EXTI line 6, falling edge)

### Tests
- `firmware/test/test_can_frame.c` -- pack/unpack round-trip, checksum
- `firmware/test/test_calib.c` -- calibration fit and telemetry
- `firmware/test/test_mcp2515.c` -- SPI mock, loopback, register read/write
- `firmware/test/test_can_health.c` -- fault-bit policy transitions
- `firmware/test/test_enum.c` -- ENUM state machine

---

## Host Software Stack

**Language:** Python 3.11+, type-hinted. **Framework:** ROS 2 Jazzy.

### Modules

| Path | Purpose |
|------|---------|
| `host/inhabit_can/codec.py` | CAN schema v1 decode/encode (frozen, mirrors `can_frame.h`) |
| `host/inhabit_can/adapter.py` | `RobotAdapter` ABC + `SimAdapter` (frozen contract) |
| `host/inhabit_can/pvt.py` | `PVTSample`, `Episode`, `JointPodState`, migrations (frozen contract) |
| `host/inhabit_bridge/bridge_node.py` | ROS 2 CAN-to-JointPodState bridge node |
| `host/inhabit_bridge/sources.py` | `CanSource` ABC: `ReplaySource`, `SimSource`, `SocketCanSource` |
| `host/inhabit_bridge/conversion.py` | Raw CAN frame -> `PodFields` (ROS-independent) |
| `host/transport/interface.py` | `CanTransport` ABC (bidirectional send+recv) |
| `host/transport/file.py` | `.canlog` file recorder + replay transport |
| `host/transport/socketcan.py` | SocketCAN transport (Linux python-can) |
| `host/logger/recorder.py` | `EpisodeRecorder` -- ingest, jitter gate, export/quarantine |
| `host/logger/parquet_io.py` | Atomic parquet write/read with provenance footer |
| `host/logger/jitter.py` | Monotonic jitter measurement + budget gate |
| `host/adapters/replay_adapter.py` | `ReplayAdapter` (offline testing) |
| `host/adapters/ros2_adapter.py` | ROS 2 adapter (TBD implementation details) |
| `host/adapters/ur_adapter.py` | UR robot stub (future RTDE) |
| `host/viz/` | Visualization (TBD) |
| `host/export/` | Dataset export utilities (TBD) |

### Host Rules
- One adapter interface (`RobotAdapter`). Never branch on robot type.
- Time sync is first-class. All samples carry monotonic host timestamp.
- Schema versioning with migrations (never silent field changes).
- Type hints everywhere. ruff + mypy clean. ROS 2 = Jazzy.
- Exports ML-ready (parquet, lerobot-style).

---

## CAN Schema v1 (FROZEN)

```
ID: 0x100 + node_id
Payload (8 bytes, little-endian):
  [0:1] angle_raw_adc   uint16 LE
  [2:3] angle_millideg   int16 LE
  [4]   node_id          uint8
  [5]   chain_index      uint8
  [6]   status_flags     uint8
  [7]   checksum         uint8 (XOR of bytes 0..6)
```

**Status flags:**
- Bit 0: `ST_ADC_FAULT`
- Bit 1: `ST_SPI_FAULT`
- Bit 2: `ST_CAN_FAULT`
- Bit 3: `ST_MAGNET_OOB`
- Bit 4: `ST_NOT_ENUMERATED`
- Bit 5: `ST_CALIB_INVALID`

New telemetry uses new CAN ID blocks. Bytes in v1 are never repurposed.

---

## ENUM Protocol

1. All pods power on un-indexed (`ST_NOT_ENUMERATED` set)
2. Pod with ENUM_IN asserted (HIGH) claims `chain_index = max(peer CAN indexes) + 1` (or 0 if none)
3. Debounce: 10 consecutive ticks of stable ENUM_IN
4. After assignment, delay 5 ticks, then assert ENUM_OUT -> wakes next pod
5. Chain overflow (index > 0xFE) -> fault, stays un-enumerated
6. Once ENUM_DONE, post-enumeration peer traffic is ignored (guard against late/duplicate)

---

## Calibration Telemetry

- `inhabit_calib_adc_to_millideg()` -- linear fit: `raw_adc * slope + intercept`
- `inhabit_calib_fit_linear()` -- least-squares from calibration samples
- Separate CAN ID block (`0x200 + node_id`), 8-byte payload mirroring v1 layout
- Test: `test_calib.c`

---

## PVT Data Model (FROZEN)

```python
PVTSample:
    timestamp_ns: int       # monotonic host timestamp
    episode_id: str
    chain_index: int
    joint_angle: float      # radians (from angle_rad)
    joint_velocity: float   # 0.0 (future)
    motor_current: float    # 0.0 (future)
    estimated_torque: float # 0.0 (future)
    camera_frame_id: str    # None (future)
    tactile_event: str      # None (future: contact_start|slip|impact|release)
    task_label: str
    schema_version: int     # 1
```

- **Episode:** atomic, append-only collection of samples
- **Jitter gate:** episodes exceeding timing budget are quarantined (not exported)
- **Schema migrations:** `MIGRATIONS` dict walks old versions forward
- **Export:** Parquet (primary), with Arrow schema and provenance footer metadata

---

## Robot Adapters (FROZEN interface)

```python
class RobotAdapter(ABC):
    def connect() -> None
    def read_state() -> RobotState
    def send_command(cmd: RobotCommand) -> None
    def capabilities() -> Capabilities
```

Implementations: `SimAdapter`, `ReplayAdapter`, `URAdapter` (stub), `ROS2Adapter` (TBD).
Core code never branches on robot type.

---

## Dataset / Export Pipeline

- **Primary format:** Parquet (one file per episode)
- **Atomic writes:** `.part` temp + `os.replace` + fsync
- **Footer metadata:** episode_id, schema_version, task_label, jitter_stats, jitter_budget, contact_detector_version
- **Quarantine:** failed episodes get a `.quarantine.json` sidecar, no parquet written
- **Round-trip:** write -> read -> assert equal (tested)
- **Future:** HDF5 for high-rate sensor blobs (audio/video features), lerobot-style episode directories

---

## Visualization / Debug Layer

- `host/viz/` -- TBD (live joint-angle display, virtual-arm rendering)
- `.canlog` file format: JSONL (`{"v":1, "t_ns":..., "id":..., "data":"hex..."}`)
- `tools/can_replay/` -- CAN log replay utilities
- `tools/calibrate.py` -- calibration helper
- `tools/dataset/` -- dataset inspection utilities

---

## Agent Workflow

### Agents
| Agent | Lane | Owns |
|-------|------|------|
| `firmware-engineer` | Firmware | `firmware/` |
| `ros2-integrator` | Host/ROS2 | `host/` (ROS2 parts) |
| `data-pipeline-engineer` | Data | `host/logger/`, `dataset/` |
| `hardware-bringup` | Hardware | Physical board, bench work |
| `embedded-reviewer` | Review | Gates every merge |
| `research-scout` | Research | Papers, datasheets |

### Git Model
- One worktree per track (`git worktree add`)
- Branches: `feat/fw-*`, `feat/host-*`, `feat/data-*`
- PRs merge in dependency order (schema-defining track first)
- Squash merge + delete branch

### GitNexus Role
Code intelligence MCP: indexes the repo as a knowledge graph. Provides `impact`, `context`, `query`, `detect_changes`, `rename`, `explain` tools. Must run `impact` before editing any symbol, `detect_changes` before committing.

### CodeRabbit Role
Automated PR review on GitHub. Configured via `.coderabbit.yaml`. No unresolved Major comments before merge.

### CI / Verify Role
- `scripts/verify.ps1` / `scripts/verify.sh` -- C firmware tests + Python pytest
- `.github/workflows/ci.yml` -- Ubuntu CI: pytest, ruff (blocking), mypy (blocking)

### Obsidian Role
This documentation vault provides the operating manual, SOPs, architecture references, and onboarding for humans and future agents.

---

## Benchmarks Status

Per BENCHMARKS.md, an agent's work is done when:
1. `scripts/verify.ps1` passes (C + Python tests)
2. New subsystem ships with >= 1 test
3. New files only in track's own directory; frozen contracts untouched
4. CodeRabbit PR review has no unresolved blocking comments
5. `embedded-reviewer` returns OK

System-level (green light for ultracode):
6. End-to-end: replayed CAN -> bridge -> episode writer -> round-trip assert
7. GitHub Actions `verify` green on `main`
8. GitNexus re-index shows no orphaned modules

Hardware-gated (deferred): colcon build on Jazzy, live CAN bus jitter, MCP2515 /INT on verified pin.

---

## Known Risks

See [[docs/risks/Risk Register]] for the full register. Key risks:
- Wrong PCBA rotation (bottom-side orientation UNVERIFIED)
- MCP2515 oscillator mismatch
- CAN bus termination missing
- Encoder magnet misalignment
- Noisy ENC_ADC
- ENUM race conditions
- Schema drift
- Timestamp drift
- Agent modifying frozen contracts

---

## Next Milestones

**Immediate (Rev-A bring-up):**
1. Assemble + power Rev-A board
2. Flash STM32
3. Verify encoder ADC
4. MCP2515 SPI bring-up (loopback first)
5. First CAN frame
6. Two-board daisy chain
7. ENUM ordering
8. Host logging

**Then:**
- Passive master arm (3-7 pods)
- ML data logger + video sync
- Last-centimeter sensors (MEMS mic, current/vibration contact detection)

---

## What Not to Touch

- `host/inhabit_can/codec.py` -- CAN schema v1 (frozen)
- `firmware/inc/can_frame.h` / `firmware/src/can_frame.c` -- CAN schema v1 (frozen)
- `host/inhabit_can/adapter.py` -- RobotAdapter interface (frozen)
- `host/inhabit_can/pvt.py` -- PVTSample, JointPodState, Episode (frozen)
- `host/inhabit_msgs/` -- JointPodState.msg (frozen)

---

## What Must Be Tested on Real Hardware

- ADC readings from MT6701 (magnet alignment, noise floor)
- MCP2515 SPI communication (clock/wiring, register read-back)
- CAN bus TX/RX (loopback first, then live bus)
- ENUM_IN/ENUM_OUT physical GPIO (debounce, propagation)
- Two-board daisy chain (ordering, CAN collision)
- 5V5/VCC_BUS power distribution
- CAN transceiver signal integrity (scope CANH/CANL)
- Inter-sample jitter under real USB-CAN conditions
