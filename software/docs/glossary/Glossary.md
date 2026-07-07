# Glossary

## Project

| Term | Definition |
|------|------------|
| **Inhabit** | The project: a universal teleoperation kernel -- modular smart joint pods + ML-native data ingestion |
| **Universal Teleop Kernel** | The concept: hardware+software platform that works across robots and produces ML-ready training data |
| **Actuated Data-Node** | The pod philosophy: hardware is primarily a data acquisition endpoint, not just a controller |
| **Smart Joint Pod** | Self-contained joint module with encoder, CAN, ENUM, and (future) motor/sensors |
| **Rev-A Smart Joint Sensor Node** | Current validation board (sensor only, no motor) |

## Hardware

| Term | Definition |
|------|------------|
| **MT6701** | Magnetic absolute angle encoder IC by MagnTek. Analog output in Rev-A. |
| **STM32C011** | STMicroelectronics Cortex-M0+ MCU (STM32C011F6P6). Core processor. |
| **MCP2515** | Microchip stand-alone CAN 2.0B controller with SPI interface. 16 MHz crystal. |
| **SN65HVD230** | Texas Instruments CAN bus transceiver (3.3V logic to CANH/CANL). |
| **CANH/CANL** | Differential CAN bus signal lines (CAN High, CAN Low). |
| **ENUM** | Enumeration protocol: GPIO-based chain ordering of identical pods |
| **VCC_BUS** | 3.3V regulated logic rail on the pod board |
| **5V5** | 5.5V bus power input to the pod (before regulation) |

## Protocol

| Term | Definition |
|------|------------|
| **CAN schema v1** | Frozen CAN frame format: ID=0x100+node_id, 8 bytes, XOR checksum. See `can_frame.h`/`codec.py`. |
| **JointPodState** | ROS 2 message type published by the bridge node. Contains decoded CAN telemetry + monotonic timestamp. |
| **RobotAdapter** | Abstract interface every robot speaks through: `connect`, `read_state`, `send_command`, `capabilities`. Frozen. |
| **PVTSample** | One time-aligned proprioceptive-visual-tactile data row. Schema-versioned. Frozen. |

## Data

| Term | Definition |
|------|------------|
| **PVT** | Proprioceptive-Visual-Tactile: the three data streams needed for contact-rich robot learning |
| **Last Centimeter** | The contact/occlusion phase where robots fail and existing datasets are weakest |
| **Active-Tactile Synchronization** | Recording tactile data during active human demonstrations, synchronized to a common clock |
| **MEMS microphone contact sensing** | Hypothesis: cheap MEMS mic near contact surface detects acoustic signatures of manipulation events |
| **Episode** | Atomic, append-only collection of PVT samples from one demonstration |

## Tooling

| Term | Definition |
|------|------------|
| **GitNexus** | Code intelligence MCP that indexes the repo as a knowledge graph. Provides impact analysis, context, query tools. |
| **CodeRabbit** | Automated PR review bot on GitHub. Configured via `.coderabbit.yaml`. |
| **Ponytail** | Coding philosophy: laziest solution that works. YAGNI, stdlib over deps, one line over fifty. |
| **Orchestrator** | Human manager who directs parallel Claude agents via `/orchestrate` |
| **Worker** | Specialized Claude agent working in an isolated worktree on a specific track |
| **Frozen contract** | Code artifact that must not be edited: CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg |
| **Worktree** | Git worktree: isolated checkout for parallel agent work (`git worktree add`) |
| **Verification gate** | `scripts/verify.ps1` -- all C and Python tests must pass before merge |
