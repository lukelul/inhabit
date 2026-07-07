# Inhabit — Project Brain (CLAUDE.md)

> Root memory for the Inhabit codebase. Keep it **lean**. Details live in
> `.claude/skills/*` and per-directory `CLAUDE.md` files. If a fact is only needed for
> one task, put it in a skill, not here. Bloated context makes agents *worse* — prune ruthlessly.

## What Inhabit is
A **universal teleoperation kernel**: modular smart joint pods (hardware) + an ML-native
data ingestion layer (software) that turns human robot control into synchronized
**Proprioceptive–Visual–Tactile (PVT)** training data.

- The joint pod is the physical API. The data engine is the business.
  **The "last centimeter" (contact, occlusion, force, friction, recovery) is the wedge.**
- We are NOT building "a controller." We build the data pipeline robot foundation models lack.

## Where we are now (Rev-A)
A **smart joint *sensor* node** — validation board, not the final actuated pod. It proves:
cheap absolute angle sensing, daisy-chained CAN telemetry, physical enumeration, repeatable
modular manufacturing.

Hardware stack:
- **Encoder:** MT6701 magnetic, **analog out → STM32 ADC** (analog in Rev-A to avoid early I2C/SSI/ABZ complexity).
- **MCU:** STM32C011F6P6 (hand-soldered dev module now; bare chip in Rev-B).
- **CAN controller:** MCP2515 over SPI (16 MHz crystal).
- **CAN transceiver:** SN65HVD230 → physical CANH/CANL.
- **Protection:** SM24CANB-02HTG TVS on the bus.
- **Bus:** 5-wire daisy chain — 5V5, GND, CANH, CANL, ENUM.

### Canonical pin map (Rev-A) — single source of truth
| Signal      | STM32 pin | Notes |
|-------------|-----------|-------|
| ENC_ADC     | A0        | MT6701 analog OUT |
| ENUM_IN     | A1        | from previous pod |
| ENUM_OUT    | A2        | to next pod |
| MCP2515 INT | B6        | active-low /INT; confirmed against schematic (EXTI line 6, falling edge) |
| MCP2515_CS  | PA4       | SPI chip select |
| SPI_SCK     | PA5       | |
| SPI_MISO    | PA6       | |
| SPI_MOSI    | PA7       | |
| Power in    | 5V5       | board input |
| Logic rail  | VCC_BUS / 3V3 | regulated |

> WARNING: bottom-side PCBA orientation is **unverified**. Confirm from
> schematic/Gerbers before writing register code that depends on it.
> (MCP2515 /INT is confirmed on B6 — see pin map above.)

## CAN message schema (v1)
```
ID: 0x100 + node_id
Payload (8 bytes):
  byte 0-1: angle_raw_adc   (uint16, little-endian)
  byte 2-3: angle_millideg  (int16)
  byte 4:   node_id
  byte 5:   chain_index
  byte 6:   status_flags
  byte 7:   checksum/reserved
```
Future fields (separate IDs, do NOT break v1): velocity, calibration state, tactile event,
motor current, error state, temperature, timestamp fragment.

## Enumeration protocol
Identical boards become an ordered kinematic chain via the ENUM line:
1. All pods power on, un-indexed.
2. A pod with ENUM_IN asserted claims the next free chain_index (host seeds index 0).
3. It asserts ENUM_OUT, waking the next pod. Repeat down the chain.

## PVT data contract (software side)
Each episode records the triplet, time-aligned:
- **Proprioceptive:** joint angles/velocities, motor current, torque est, gripper, link config.
- **Visual:** wrist/scene/depth/stereo/egocentric frames (referenced by camera_frame_id).
- **Tactile/contact:** force, vibration, current spikes, strain, MEMS contact audio, slip/impact.

Reference packet shape: `.claude/skills/pvt-data-logger/SKILL.md`. Timestamp synchronization
is the hardest part — treat it as first-class, never an afterthought.

## Tech baseline & conventions
- **ROS 2 distro:** target **Jazzy Jalisco** (LTS → May 2029, Ubuntu 24.04) for production.
  Lyrical Luth (May 2026 LTS, Ubuntu 26.04) is newer — adopt only once CI is green. Pin the
  distro in every package and CI job; never assume "latest."
- **Firmware:** C, STM32 HAL/LL. Deterministic; no dynamic allocation in the hot path; no
  blocking I/O in ISRs. Filter encoder ADC noise. Fail loud via status_flags.
- **Host/data:** Python 3.11+, type-hinted. ROS 2 rclpy nodes. ML-ready exports
  (parquet/HDF5/lerobot-style). Version the schema from day one.
- **Adapters are plugins:** robot protocol support (custom CAN, ROS 2, UR, KUKA, Franka,
  humanoid, sim) must be swappable behind one interface. Never hardwire one robot.

## Operating rules for agents
1. **Verify hardware claims against the schematic before generating register-level code.**
   When unsure of a pin/peripheral, say so and ask — do not guess silicon.
2. **Lead with the failure mode.** ESD, noise, timing, occlusion, slip. For any feature, name
   how it fails and how we detect it (status_flags, contact events).
3. **Schema is sacred.** Don't silently change the CAN layout or PVT packet. Version it.
4. **Keep context lean.** Use /clear between unrelated tasks. Pull detail from skills on demand.
5. **Small, reviewable diffs.** Embedded bugs hide in big diffs.
6. **Cite the source** (datasheet section, schematic net, ROS doc) for non-obvious claims.

## Roadmap
P1 board bring-up → P2 CAN bring-up → P3 modular 2+ board chain → P4 passive master arm
(3–7 pods) → P5 ML data logger + video sync → P6 last-centimeter sensors (MEMS mic,
current/vibration contact detection).

P4 CAD ingestion: a SolidWorks 6/7-DOF arm assembly becomes a real kinematic chain via
SW2URDF export → `host/inhabit_description` → `ArmConfig` → `adapters.custom_can_adapter`
(see `.claude/skills/cad-import/SKILL.md`).

Immediate: assemble & power Rev-A → flash STM32 → verify encoder ADC → MCP2515 SPI bring-up
→ first CAN frame → two-board daisy chain → ENUM ordering → host logging.
