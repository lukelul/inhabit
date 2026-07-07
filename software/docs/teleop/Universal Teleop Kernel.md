# Universal Teleop Kernel

## What It Means

A **universal teleoperation kernel** is a modular hardware+software platform that:
1. Attaches to any robot kinematic chain
2. Records human control demonstrations
3. Produces ML-ready training data
4. Works across robot protocols (CAN, ROS 2, UR RTDE, KUKA, Franka, sim)

The kernel is "universal" because the robot-specific protocol is an adapter plugin, not hardwired into the core.

---

## Why Hardware Is an Actuated Data-Node

Traditional approach: build a robot controller, add data logging as an afterthought.

Inhabit approach: the hardware IS a data acquisition endpoint. Every joint angle, every fault flag, every contact event is a training signal. The motor driver exists to enable demonstrations, but the primary output is the dataset.

### Smart Joint Pod Architecture
- Self-contained module: encoder + CAN + ENUM + (future) motor + contact sensor
- Plugs into any kinematic chain via daisy-chain connector
- Automatically discovers its position (ENUM protocol)
- Reports telemetry at ~1 kHz over CAN
- Future: accepts motor commands for active demonstration

### Why Modular Teleop Matters
- One pod design serves arms, grippers, legs, humanoid joints
- Manufacturing scales: same board, different magnet/motor config
- Kinematic chain length is software-defined (ENUM handles ordering)
- Failure of one pod doesn't kill the chain (fault isolation via status flags)

---

## Why Protocol-Agnostic Robot Translation Matters

The `RobotAdapter` interface abstracts away robot-specific protocols:

```python
class RobotAdapter(ABC):
    def connect() -> None
    def read_state() -> RobotState
    def send_command(cmd: RobotCommand) -> None
    def capabilities() -> Capabilities
```

This means:
- The data pipeline works the same for every robot
- Training data from a UR arm and a custom hand share the same schema
- Adding a new robot = one adapter file, not a rewrite
- Core code never branches on robot type

---

## How the Software Layer Becomes the Business

1. Hardware captures demonstrations (proprioceptive data from day one)
2. Video sync adds visual context (future)
3. Contact sensors add tactile ground truth (future)
4. PVT episodes are ML-ready (parquet, lerobot-compatible)
5. Jitter-gated quality ensures training data actually aligns
6. Schema versioning + migrations ensure old data stays useful
7. The dataset grows with every demonstration session

The **data moat** is: synchronized, jitter-gated, contact-labeled PVT episodes that no one else is collecting. The hardware is how you collect it. The pipeline is how you make it useful.

---

## Roadmap

### Hardware
- Rev-A: Sensor node (encoder + CAN) -- current
- Rev-B: Bare MCU, digital encoder -- planned
- Rev-C: Motor driver, current sensing -- planned
- Rev-D: MEMS mic, contact sensor array -- future

### Software
- CAN bridge + PVT logger (proprioceptive only) -- current
- Video sync (camera timestamp alignment) -- planned
- Contact event detection (current spikes, vibration) -- planned
- Multi-robot adapter library (UR, Franka, KUKA, sim) -- planned
- lerobot-compatible export pipeline -- planned
- Dashboard / visualization -- TBD

### Data
- Proprioceptive-only episodes -- current
- PV (proprioceptive + visual) episodes -- planned
- PVT (full triplet) episodes -- future
- Contact-labeled demonstrations -- future
- Cross-robot transfer datasets -- future

---

## Failure Modes and Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Schema drift between firmware and host | Data corruption | Frozen contracts, version field in every frame |
| Timestamp misalignment between streams | Unusable training data | Single monotonic clock, jitter budget gate |
| Contact sensor noise | False positive labels | Calibration, threshold tuning, multi-modal consensus |
| Adapter interface too narrow | Can't support some robots | Capabilities field allows feature detection |
| Manufacturing variability | Pod-to-pod calibration drift | Per-pod calibration + telemetry |
| Data volume scaling | Storage/processing bottleneck | Parquet columnar format, incremental export |
