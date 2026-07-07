# REVIEW GUIDE — understand the codebase + the robotics behind it

Read in this order. Each file is small on purpose.

## 1. The "why" and the rules
- `README.md`, `.claude/CLAUDE.md` — what Inhabit is, the contracts, the house rules.
- `AGENTS.md` — the short shared contract every agent obeys.

## 2. The contract (read the code)
- `host/inhabit_can/codec.py` + `firmware/inc/can_frame.h` — the SAME CAN frame in Python and C.
  Read both; confirm to yourself they pack identical bytes. This is the spine of the system.
- `host/inhabit_can/adapter.py` — the `RobotAdapter` pattern (why no robot-specific code leaks
  into the core).
- `host/inhabit_can/pvt.py` — the dataset unit (the actual product).

## 3. The flow
- `host/` bridge node — CAN bytes → decoded ROS 2 `JointPodState`.
- `RUNBOOK.md` / `ORCHESTRATION.md` — how the agents build it in parallel.

## Robotics / embedded concepts to learn (and where they appear)
- **CAN bus** — differential 2-wire bus, 11-bit IDs, little-endian payloads, checksum. → `codec.py`/`can_frame.h`.
- **ISR vs main loop** — interrupts set flags; logic runs in the loop (deterministic, no blocking). → `firmware/src/main.c`.
- **ADC + filtering** — reading the MT6701 analog angle, denoising. → encoder TODO in `main.c`.
- **SPI** — how the STM32 talks to the MCP2515 CAN controller. → `mcp2515.c`.
- **ROS 2 pub/sub + QoS** — nodes publish messages; QoS picks reliability vs latency. → bridge node.
- **Monotonic time-sync** — one steady clock stamps every sample so streams align. → bridge + `pvt.py`.
- **PVT triplet** — proprioceptive + visual + tactile; the data robots actually need. → `pvt.py`.
- **Imitation learning / world models** — why contact-rich demo data is the business. → CLAUDE.md vision.

## Good external references
- ROS 2 Jazzy docs (concepts: nodes, topics, QoS, launch).
- MCP2515 datasheet (CNF1/2/3 bit timing for a 16 MHz crystal) + your schematic for the /INT net.
- A short "intro to CAN bus" primer.
