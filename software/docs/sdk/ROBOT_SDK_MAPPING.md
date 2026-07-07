# Robot SDK Mapping — vendor SDKs onto the frozen `RobotAdapter`

> Release/adapter planning doc for **P-G — Multi-robot adapter ecosystem** (MASTER_PLAN.md).
> This is the contract that lets UR / Franka / KUKA / generic-ROS2 / custom-CAN / future
> vendors become Inhabit adapters **without a single core change**. Docs-only; no code here.

**Failure mode this document exists to prevent:** the moment core code grows an
`if robot == "ur"` branch, every new robot becomes a merge conflict in the kernel and a new
class of clock-skew / e-stop / unit bug hides in a vendor special-case. The architecture law
below makes that branch impossible: robots are plugins, the kernel only ever calls four
methods, and the contract is frozen.

---

## 1. Architecture law & frozen-contract policy

Inhabit is **plugin-everything behind stable, versioned contracts** (MASTER_PLAN.md
"Architecture law"). For robots specifically:

1. **Core never branches on vendor type.** The kernel imports `RobotAdapter` and calls
   `connect / read_state / send_command / capabilities`. It does not know UR from Franka.
   (ADR-0006, FROZEN.)
2. **A new robot = a new plugin**, never a kernel edit. Each plugin is:
   - a **typed contract** implementation — a subclass of `RobotAdapter`;
   - **conformance-tested** — must pass the RobotAdapter conformance suite (P-A/A3, the gate);
   - **capability-negotiated** — advertises what it can do via `Capabilities`, never lies;
   - **sim/mock-backed** — exercisable with no hardware, proven by a sim integration test;
   - **lazy-imported** — its vendor SDK is imported only when an instance is built, never at
     package-import time;
   - **optional-dep-guarded** — the vendor SDK is an optional dependency; importing
     `host/adapters` and running the test suite must work with none of them installed.
3. **The `RobotAdapter` contract is FROZEN.** Adapters map *onto* it; they never change it.
   The contract changes only via a new versioned decision record (a successor to ADR-0006)
   plus orchestrator approval — never to make one vendor fit. If a vendor cannot be expressed
   through the current contract, that is a gap to record and escalate, **not** a reason to edit
   `adapter.py`. (MASTER_PLAN.md "Frozen contracts".)

### How the plugin wiring actually works today (`host/adapters/__init__.py`)

- One `inhabit_core.Registry[RobotAdapter]` named `"adapter"` holds every adapter, keyed by a
  short **registry name** (the string passed to `make_adapter`).
- The registry is constructed with `entry_point_group="inhabit.adapters"`, so third-party
  packages can ship adapters (the P-M marketplace path) by advertising that entry point; it is
  discovered lazily and degrades silently when none are installed.
- **Zero-dependency adapters (`sim`, `replay`) register the class directly.**
- **Heavyweight adapters (`ros2`, `ur`) register behind a factory function** that imports the
  concrete module only inside the factory — so importing `host/adapters` pulls **no** rclpy and
  no vendor SDK. This is the exact pattern every future heavyweight adapter must reuse.
- Public API: `make_adapter(name, **kwargs) -> RobotAdapter` (raises `ValueError` listing the
  available names on an unknown key) and `list_adapters() -> list[str]` (sorted).

> Reality check (do not over-claim): `set(list_adapters()) == {"replay", "ros2", "sim", "ur"}`
> today, and `make_adapter("kuka")` / `make_adapter("franka")` raise `ValueError` — they are
> **planned**, not registered. (Verified in `host/tests/test_adapters.py::TestMakeAdapter`.)

---

## 2. The `RobotAdapter` contract — as actually implemented

Source of truth: **`host/inhabit_can/adapter.py`** (FROZEN). The ABC has exactly four abstract
methods, and three plain dataclasses carry the data. Quoted signatures below are the real ones.

### Methods (`class RobotAdapter(ABC)`)

| Method | Real signature | Returns | Contract |
|---|---|---|---|
| `connect` | `connect(self) -> None` | `None` | Acquire the link / node / socket. Must be **idempotent** (a second call is a no-op once connected — see `ROS2Adapter.connect`). May raise if the robot is unreachable; stubs raise `NotImplementedError`. |
| `read_state` | `read_state(self) -> RobotState` | `RobotState` | Latest joint state. Must return an **independent copy** so a caller mutating `joint_angles` cannot corrupt internal state (`ROS2Adapter`/`ReplayAdapter` both copy). Must carry a valid monotonic `timestamp_ns` even before the first vendor frame. |
| `send_command` | `send_command(self, cmd: RobotCommand) -> None` | `None` | Push a joint-target command. Read-only adapters (`replay`) implement it as a no-op; the kernel never special-cases that. |
| `capabilities` | `capabilities(self) -> Capabilities` | `Capabilities` | Static-ish description used for **capability negotiation**. Must be truthful: `dof` is the real joint count downstream buffers are sized from; `has_force_feedback` must be `False` until force data is actually wired. |

### Data carriers (dataclasses)

| Type | Fields (real) | Units / meaning |
|---|---|---|
| `RobotState` | `joint_angles: list[float]` (default `[]`), `timestamp_ns: int` (default `0`) | `joint_angles` in **radians** (SI; the host stack works in rad — e.g. ROS `JointState.position`). `timestamp_ns` = host monotonic clock in **nanoseconds**. |
| `RobotCommand` | `joint_targets: list[float]` (default `[]`) | Target joint positions in **radians**, same ordering as `joint_angles`. |
| `Capabilities` | `dof: int` (default `0`), `has_force_feedback: bool` (default `False`) | Degrees of freedom; whether force/torque feedback is available. This is the **entire** capability vocabulary today — richer fields (control modes, force read, torque cmd) are a future versioned extension, not assumed. |

### Timestamp / clock-sync expectation (first-class, non-negotiable)

`timestamp_ns` is a **single monotonic host clock** (`time.monotonic_ns()`), set by the adapter
**at receive**, never wall-clock, and never the robot's own clock unless that clock has been
disciplined to host monotonic time. This matches the host time-sync guideline
(`host/CLAUDE.md`: "All samples carry a monotonic host timestamp; align CAN, video, and tactile
to a common clock") and the bridge rule (`docs/architecture/System Architecture.md`: host RX
stamp = `time.monotonic_ns()`, NEVER wall clock).

Concrete proof in the existing code:
- `ROS2Adapter` seeds `_last_state` with `time.monotonic_ns()` so the very first `read_state()`
  before any callback still honours the contract — **no zero-timestamp sample ever leaves**.
- `ReplayAdapter` rejects non-positive and non-monotonic `timestamp_ns` at construction, because
  a zero/backwards host timestamp silently corrupts downstream jitter math and episode alignment.

**Failure mode — clock skew:** if an adapter passes through a vendor's own clock, two robots in
one session drift apart and the episode aligner silently mis-pairs PVT rows. Every adapter MUST
stamp on the host monotonic clock and document, per family below, how the vendor clock is mapped
(disciplined, offset-estimated, or ignored in favour of RX time).

> **Per-SDK clock evidence:** `docs/sdk/SDK_TIMEBASE_MAP.md` (P-C/C6) audits what timestamp
> guarantees each vendor SDK *actually documents* — C1 clock-domain classification, cited
> sources, and the required C2 normalization — deepening the "Timestamp source" rows below.

---

## 3. Status legend

| Symbol | Meaning |
|---|---|
| ✅ implemented | Registered, functional, conformance-coverable today with no hardware. |
| 🟡 partial | Registered and importable, but core methods incomplete (stub / not yet RTDE-/SDK-backed). |
| 📋 planned | Not registered yet; `make_adapter(name)` raises `ValueError`. Spec only. |
| 🔒 hardware-blocked | Design is clear, but closing it requires the physical robot/board on a bench. |

A family can be both "software-✅/🟡/📋" **and** carry a 🔒 on the *hardware-needed evidence*
row — the software lane closes in sim; the bench row closes only with the real device.

### Family status at a glance

| Family | Registry name | Software status | Closes on hardware? |
|---|---|---|---|
| Replay / recorded | `replay` | ✅ implemented | No (file-only) |
| Simulation (data engine) | `sim_robot` | ✅ implemented — P-B/B2 `sim.SimRobotAdapter`: configurable DOF + pluggable trajectory, **monotonic non-zero timestamps + independent-copy reads**; passes the RobotAdapter conformance suite | No (zero-hardware by design) |
| Simulation (reference stub) | `sim` | 🟡 partial — the original reference stub (`inhabit_can.adapter.SimAdapter`); `read_state` returns internal state **by reference** and `timestamp_ns=0`. Kept for back-compat; **use `sim_robot` for the data path** (it is the non-stub sim that closed the gap) | No (zero-hardware by design) |
| Generic ROS 2 | `ros2` | 🟡 partial (functional vs live topics; rclpy required at runtime, unverified against a real arm) | 🔒 against a real ROS 2 arm |
| Universal Robots (UR) | `ur` | 🟡 partial — **stub**; only `capabilities()` works, the rest raise `NotImplementedError` | 🔒 against a real UR controller (RTDE) |
| Franka | `franka` | 📋 planned (not registered) | 🔒 against a real Panda/FR3 (FCI) |
| KUKA iiwa | `kuka` | 📋 planned (not registered) | 🔒 against a real iiwa (FRI) |
| Custom-CAN / Inhabit Rev-A | `custom_can` | 🟡 partial — `adapters.custom_can_adapter.CustomCanAdapter` registered; wraps a `CanSource` (SimSource by default) behind the frozen contract, decoding schema v1 by `chain_index`. Optionally sized/ordered from a CAD-derived `inhabit_description.ArmConfig` (see the `cad-import` skill) instead of a bare `dof` integer | 🔒 against the Rev-A board |
| Generic vendor SDK | *(template)* | 📋 template / pattern | depends on vendor |

---

## 4. Per-family mapping

Every section below carries the same fields so the matrix is uniform and reviewable. "Design
budget" numbers are **targets, not measurements** — no real latency/rate has been benchmarked
against hardware. They are labelled as budgets, never claimed as results.

### 4.1 Generic ROS 2 robot — `ros2` 🟡

| Field | Mapping |
|---|---|
| SDK / vendor | ROS 2 **Jazzy** (`rclpy`, `sensor_msgs/JointState`). Source: `host/adapters/ros2_adapter.py`. |
| Registry name | `ros2` (registered behind a lazy factory in `host/adapters/__init__.py`). |
| Control mode support | Position only — publishes `JointState.position`. No velocity/effort/Cartesian today. |
| State-read mapping | Subscribe `joint_state_topic` (default `/joint_states`); `msg.position[:dof]` (padded to `dof`) → `RobotState.joint_angles`; `timestamp_ns = time.monotonic_ns()` at callback. Non-finite positions are dropped (last good state held). |
| Command-write mapping | `RobotCommand.joint_targets` → `JointState.position` published on `joint_command_topic` (default `/joint_commands`). |
| Joint naming / ordering | Positional, by index, capped/padded to `dof`. **Does not** currently reorder by `msg.name` — caller must ensure publisher order matches expected DOF order. (Gap to close per-robot.) |
| Units & conversion | radians in, radians out — pass-through (ROS `JointState.position` is already rad/SI). |
| Timestamp source | Host `time.monotonic_ns()` at RX. `msg.header.stamp` is intentionally **not** trusted (avoids importing the publisher's clock skew). |
| Clock-sync assumptions | Single host monotonic clock; publisher clock ignored. |
| Transport | DDS / ROS 2 middleware. **QoS chosen deliberately:** subscription uses `qos_profile_sensor_data` (BEST_EFFORT, compatible with both reliable and best-effort publishers — the common sensor case); command publisher uses RELIABLE depth-10 (commands must not be silently dropped). |
| Safety / e-stop | Delegated to the ROS 2 graph / robot driver. The adapter has no e-stop primitive; an upstream controller or hardware e-stop is assumed. **Failure mode:** no command ack — a dropped/late command is invisible to the adapter; mitigated only by RELIABLE QoS. |
| Rate limits | Bounded by `spin_once` polling in `read_state` and publisher throughput; **design budget** ≤ 1 kHz read poll. |
| Latency budget | **Design budget** DDS round-trip target < 5 ms LAN; unmeasured. |
| Simulated / mock | ✅ via the ROS 2 graph itself (e.g. a sim publisher on `/joint_states`); module is importable without rclpy (lazy import), so unit tests run with no ROS install. |
| Required optional dep | `rclpy` + `sensor_msgs` — **lazy-imported inside `connect()`/callbacks**, never at module import, never required by the test suite. (`TYPE_CHECKING`-only import for types.) |
| Conformance tests | `host/tests/test_adapters.py::TestROS2Adapter` today; must additionally pass the P-A/A3 RobotAdapter conformance suite once it lands. |
| Capability flags | `Capabilities(dof=<configured>, has_force_feedback=False)`. |
| Unsupported | velocity/effort/Cartesian control; force feedback; name-based joint reordering; trajectory actions. |
| Hardware-needed evidence 🔒 | On a real ROS 2 arm: subscribe `/joint_states`, command a small move on `/joint_commands`, capture a rosbag, and show host-monotonic timestamp jitter within the host jitter budget (p99 < 2 ms) across ≥ N seconds. |

### 4.2 Universal Robots (UR) — `ur` 🟡 (stub)

| Field | Mapping |
|---|---|
| SDK / vendor | Universal Robots **RTDE** (Real-Time Data Exchange, controller port 30004), plus URScript `servoj` for commands. Source: `host/adapters/ur_adapter.py` (stub). Arms: UR3/5/10/16/20/30 (6-DOF). |
| Registry name | `ur` (lazy factory). |
| Control mode support | Planned: RTDE read + `servoj` position streaming. **Today: none — `connect`/`read_state`/`send_command` raise `NotImplementedError`.** |
| State-read mapping | Planned: RTDE `actual_q` (6 joints, rad) → `RobotState.joint_angles`; RTDE timestamp re-stamped to host monotonic at RX → `timestamp_ns`. |
| Command-write mapping | Planned: `RobotCommand.joint_targets` (rad) → `servoj(q, ...)` URScript / RTDE input registers. |
| Joint naming / ordering | UR base→wrist3 order (`base, shoulder, elbow, wrist1, wrist2, wrist3`), 6 entries. |
| Units & conversion | radians (UR RTDE `actual_q` is already rad) — pass-through. |
| Timestamp source | Planned host `time.monotonic_ns()` at RTDE RX. |
| Clock-sync assumptions | RTDE runs at 125/500 Hz; re-stamp on host clock, do not trust controller clock for cross-modal alignment. |
| Transport | TCP to controller IP (default `192.168.1.2`), RTDE port 30004. |
| Safety / e-stop | UR safety system is authoritative (protective stop, emergency stop). **Failure mode:** on a protective stop the controller stops accepting `servoj` — the adapter must surface that as a fault, not silently buffer commands. (To be designed; not in the stub.) |
| Rate limits | RTDE 125 Hz (CB-series) / up to 500 Hz (e-Series). `servoj` lookahead/gain budget per UR docs. |
| Latency budget | **Design budget** < 8 ms control loop on LAN; unmeasured. |
| Simulated / mock | Planned: URSim (Docker) for a no-hardware integration test; the stub keeps the registry aware of UR now. |
| Required optional dep | `ur-rtde` (or equivalent RTDE client) — **must be lazy-imported in the factory/`connect()`**, optional, never required by the test suite. |
| Conformance tests | Today `host/tests/test_adapters.py::TestURAdapter` asserts the stub contract (methods raise, `capabilities()` honest). When RTDE-backed: P-A/A3 conformance + a URSim integration test. |
| Capability flags | `Capabilities(dof=6, has_force_feedback=False)` — force feedback stays `False` until RTDE force/torque is actually wired (the stub deliberately does not over-advertise). |
| Unsupported | everything except `capabilities()` until RTDE lands; force/torque; Cartesian/freedrive. |
| Hardware-needed evidence 🔒 | On a real UR: RTDE read of `actual_q`, a `servoj` move, protective-stop handling demo, and host-monotonic jitter within budget. |

### 4.3 Franka — `franka` 📋 planned

| Field | Mapping |
|---|---|
| SDK / vendor | Franka **FCI** via `libfranka` (C++), or the `franky` / `panda-py` Python bindings, or `franka_ros2`. Panda / FR3, 7-DOF. **Not registered.** |
| Registry name | `franka` (planned; `make_adapter("franka")` raises `ValueError` today). |
| Control mode support | Planned: joint-position / joint-velocity / torque + Cartesian via FCI. Initial adapter target = joint-position read + command only. |
| State-read mapping | `franka::RobotState.q` (7 joints, rad) → `RobotState.joint_angles`; FCI is 1 kHz; re-stamp host monotonic → `timestamp_ns`. Force/torque (`O_F_ext_hat_K`, `tau_J`) available → enables `has_force_feedback=True` later. |
| Command-write mapping | `RobotCommand.joint_targets` (rad) → FCI joint-position motion-generator callback. |
| Joint naming / ordering | `panda_joint1..7` base→flange order, 7 entries. |
| Units & conversion | radians (FCI `q` is rad) — pass-through. |
| Timestamp source | Planned host `time.monotonic_ns()` at the 1 kHz FCI callback RX. |
| Clock-sync assumptions | FCI requires a 1 kHz real-time loop; re-stamp on host clock. **Failure mode:** missing the 1 kHz deadline triggers an FCI `communication_constraints_violation` and the robot stops — the adapter must treat a missed deadline as a hard fault. |
| Transport | UDP FCI to the robot IP on a real-time-capable host (`PREEMPT_RT` kernel recommended). |
| Safety / e-stop | Franka has hardware e-stop + reflex system; a reflex error locks the robot until `automatic_error_recovery`. Adapter must surface reflex/e-stop as a fault and not auto-recover silently. |
| Rate limits | 1 kHz control loop (hard requirement). |
| Latency budget | **Design budget** 1 ms control period (FCI requirement); unmeasured. |
| Simulated / mock | Planned: a `franka`-flavoured `SimAdapter`/mock backend (no `libfranka`) for the sim integration test; later a Gazebo/`franka_ros2` sim. |
| Required optional dep | `libfranka` bindings (`franky` / `panda-py`) or `franka_ros2` — **lazy-imported in the factory**, optional, never required by the test suite. |
| Conformance tests | P-A/A3 RobotAdapter conformance + a mock/sim integration test before "ready". |
| Capability flags | Start `Capabilities(dof=7, has_force_feedback=False)`; flip force feedback to `True` only once `O_F_ext_hat_K`/`tau_J` is actually surfaced. |
| Unsupported (initial) | Cartesian/impedance control; collision-behaviour config; force feedback in v1. |
| Hardware-needed evidence 🔒 | On a real Panda/FR3: FCI 1 kHz read of `q`, a joint-position move, reflex/e-stop fault surfaced, 1 kHz deadline held, host-monotonic jitter within budget. |

### 4.4 KUKA iiwa — `kuka` 📋 planned

| Field | Mapping |
|---|---|
| SDK / vendor | KUKA **FRI** (Fast Robot Interface) to the iiwa / Sunrise cabinet, or `iiwa_ros2` / `iiwa_stack`. LBR iiwa 7/14, 7-DOF. **Not registered.** |
| Registry name | `kuka` (planned; `make_adapter("kuka")` raises `ValueError` today — see `TestMakeAdapter::test_unknown_raises`). |
| Control mode support | Planned: FRI joint-position (and torque-overlay) modes; initial adapter = joint-position read + command. |
| State-read mapping | FRI `getMeasuredJointPosition()` (7 joints, rad) → `RobotState.joint_angles`; re-stamp host monotonic → `timestamp_ns`. Measured torque available → future `has_force_feedback`. |
| Command-write mapping | `RobotCommand.joint_targets` (rad) → FRI `setJointPosition()` within the FRI command window. |
| Joint naming / ordering | `iiwa_joint_1..7` base→flange, 7 entries. |
| Units & conversion | radians (FRI joint positions are rad) — pass-through. |
| Timestamp source | Planned host `time.monotonic_ns()` at FRI sample RX. |
| Clock-sync assumptions | FRI runs at a fixed cycle (1–10 ms, configured on the cabinet); re-stamp on host clock. **Failure mode:** dropped FRI packets / late command → the cabinet leaves `COMMANDING_ACTIVE` and falls back to monitoring; the adapter must detect the FRI session-state transition and fault, not keep streaming. |
| Transport | UDP FRI to the cabinet; the Sunrise-side FRI application must be running and in the right session state. |
| Safety / e-stop | KUKA SafetyController is authoritative; FRI session-state machine (`IDLE→MONITORING_*→COMMANDING_*`) gates commanding. Adapter mirrors session state as a capability/fault. |
| Rate limits | FRI cycle 1–10 ms (cabinet-configured). |
| Latency budget | **Design budget** ≤ FRI cycle time (target ≤ 5 ms); unmeasured. |
| Simulated / mock | Planned: a `kuka`-flavoured mock backend (no FRI cabinet) for the sim integration test. |
| Required optional dep | FRI client bindings (`pyFRI` / vendor lib) or `iiwa_ros2` — **lazy-imported in the factory**, optional, never required by the test suite. |
| Conformance tests | P-A/A3 RobotAdapter conformance + a mock/sim integration test before "ready". |
| Capability flags | Start `Capabilities(dof=7, has_force_feedback=False)`; force feedback only once FRI measured torque is surfaced. |
| Unsupported (initial) | torque-overlay / impedance; Cartesian; redundancy (e1) control in v1. |
| Hardware-needed evidence 🔒 | On a real iiwa: FRI read of measured joint position, a position move within the command window, FRI session-state transition handled as a fault, host-monotonic jitter within budget. |

### 4.5 Custom-CAN / Inhabit Rev-A — `custom_can` 🟡 partial (🔒 on hardware)

| Field | Mapping |
|---|---|
| SDK / vendor | **Inhabit's own** CAN schema v1 (`host/inhabit_can/codec.py`, FROZEN) over the Rev-A daisy-chained pods. The host data path lives in `host/inhabit_bridge/` + `host/transport/`; `adapters.custom_can_adapter.CustomCanAdapter` is the `RobotAdapter` wrapper presenting the chain as one robot. |
| Registry name | `custom_can` (registered behind a lazy factory in `host/adapters/__init__.py`). |
| Control mode support | Read-only today (Rev-A is a **sensor** node, no actuation — root CLAUDE.md). `send_command` is a documented no-op (like `replay`) until actuated pods exist. |
| State-read mapping | Decoded `State.angle_millideg` per pod → radians → `RobotState.joint_angles`, ordered by `chain_index` (the ENUM order); `timestamp_ns` from the CAN RX monotonic stamp (`CanFrame.rx_monotonic_ns`). A bad-checksum or out-of-range `chain_index` frame is dropped rather than corrupting a joint slot. |
| Command-write mapping | No-op in Rev-A (sensor node). Future actuated pods: new CAN ID block (never break v1). |
| Joint naming / ordering | By `chain_index` from the ENUM enumeration protocol (host seeds index 0; pods claim the next free index down the chain). Can be sourced from a CAD-derived `inhabit_description.ArmConfig` (`cad-import` skill) instead of a bare `dof` integer — `chain_index`/`node_id`/limits then come from the SolidWorks/URDF export rather than being assumed. |
| Units & conversion | `angle_millideg` (int16, milli-degrees) → degrees → radians. Conversion lives in the adapter; the codec stays frozen. |
| Timestamp source | Host monotonic RX stamp on the CAN frame (`time.monotonic_ns()` at the bridge), NEVER wall clock — same rule as the bridge node. |
| Clock-sync assumptions | Single host monotonic clock; per-pod firmware has no synced clock, so host-RX time is authoritative (a known limitation for sub-ms cross-pod alignment — measured jitter must be reported). |
| Transport | SocketCAN / USB-CAN via `host/transport/` (`SocketCanTransport`, lazy `python-can`) or `.canlog` file replay (`FileReplayTransport`) for the headless path. `CustomCanAdapter` defaults to a zero-hardware `SimSource` when no `source=` is given. |
| Safety / e-stop | Sensor node — no actuation to stop. `status_flags` carries `ST_ADC_FAULT`/`ST_SPI_FAULT`/`ST_CAN_FAULT`/`ST_MAGNET_OOB`; bad-checksum frames are dropped by the adapter, "fail loud" rather than corrupting a joint reading. |
| Rate limits | Firmware TX ~1 kHz (`tick_1khz`). |
| Latency budget | **Design budget** bus + USB-CAN < 2 ms to host; jitter budget p99 < 2 ms (host jitter gate). |
| Simulated / mock | ✅ `CustomCanAdapter()` with no arguments runs end to end against the default `SimSource` — zero hardware, zero configuration. `ReplaySource`/`FileReplayTransport` cover the recorded-frame path. |
| Required optional dep | `python-can` for live SocketCAN — **lazy-imported** (already is, in `SocketCanSource`/`SocketCanTransport`); the replay/sim path needs no optional dep and stays in the test suite. |
| Conformance tests | `host/tests/conformance/test_adapter_conformance.py` (auto-discovered as `custom_can`, command-reflection test skipped — read-only by design, same as `replay`) + `host/tests/test_custom_can_adapter.py` (decode-by-chain-index, corrupt-frame handling, ArmConfig sizing). |
| Capability flags | `Capabilities(dof=<chain length>, has_force_feedback=False)`. |
| Unsupported | actuation / commands (Rev-A is sensor-only); force feedback; any field outside CAN schema v1 (future telemetry = new CAN ID, never a v1 break); CAD-sourced per-joint limit *enforcement* (`ArmConfig` limits are carried but not yet clamped/validated against live readings). |
| Hardware-needed evidence 🔒 | On the Rev-A board(s): a 2+ pod daisy chain enumerates in ENUM order, the adapter reports DOF = chain length, `joint_angles` track real shaft angle, `status_flags` faults surface, and host-RX jitter is within the p99 < 2 ms budget. |

### 4.6 Replay adapter — `replay` ✅

| Field | Mapping |
|---|---|
| SDK / vendor | None — plays back a pre-recorded `list[RobotState]`. Source: `host/adapters/replay_adapter.py`. |
| Registry name | `replay` (zero-dep, registered directly). |
| Control mode support | Read-only; `send_command` is a documented no-op. |
| State-read mapping | Returns recorded states in order; once exhausted, holds the last state forever. Deep-copies on read so callers can't corrupt the recording. |
| Command-write mapping | No-op (read-only). |
| Joint naming / ordering | As recorded; all states must share one joint count (enforced). |
| Units & conversion | As recorded (radians by convention); no conversion. |
| Timestamp source | The recorded `timestamp_ns`, validated **positive and monotonic** at construction (the host time-sync contract). |
| Clock-sync assumptions | Recording must already be on a single monotonic clock; non-positive / backwards / NaN are rejected up front. |
| Transport | In-memory list (and, by extension, anything that produced the recording). |
| Safety / e-stop | N/A (offline playback). |
| Rate limits | Caller-driven (as fast as `read_state` is called). |
| Latency budget | N/A (deterministic, offline). |
| Simulated / mock | ✅ it **is** the mock/offline path. |
| Required optional dep | None. Pure stdlib. Always in the test suite. |
| Conformance tests | `host/tests/test_adapters.py::TestReplayAdapter` (extensive: empty/mixed-DOF/zero/negative/backwards/NaN/inf all rejected; determinism; no input mutation). Will also run under P-A/A3. |
| Capability flags | `Capabilities(dof=<recorded joint count>, has_force_feedback=False)`; a `dof` override that disagrees with the recording is rejected so `capabilities()` can never lie. |
| Unsupported | commanding; force feedback; live data. |
| Hardware-needed evidence | None — file-only by design. |

### 4.7 Simulation adapter — `sim` 🟡 (reference stub)

| Field | Mapping |
|---|---|
| SDK / vendor | None — the zero-hardware reference adapter that ships in `host/inhabit_can/adapter.py` (`SimAdapter`). |
| Registry name | `sim` (zero-dep, registered directly). |
| Control mode support | Position: `send_command` sets internal state, which `read_state` returns. |
| State-read mapping | Returns the current internal `RobotState` **by reference** (not a copy — callers must not mutate; P-B `SimRobot` will return independent copies like `ROS2Adapter`). |
| Command-write mapping | `RobotCommand.joint_targets` → internal `RobotState.joint_angles`. |
| Joint naming / ordering | Positional, `dof` entries (default 6), all start at 0.0. |
| Units & conversion | radians by convention; pass-through. |
| Timestamp source | ⚠️ **Known gap (this stub):** `SimAdapter` returns `timestamp_ns=0` (the `RobotState` default) — not contract-complete for data-engine use. **Closed by P-B/B2:** the `sim_robot` adapter (`sim.SimRobotAdapter`, §4.7b) supplies seeded monotonic timestamps + independent-copy reads. `SimAdapter` remains the minimal reference stub; for the ML data path use `sim_robot` (or `ReplayAdapter` with timestamped states). |
| Clock-sync assumptions | Single host clock once the P-B `SimRobot` supplies timestamps. |
| Transport | In-process. |
| Safety / e-stop | N/A. |
| Rate limits | Caller-driven. |
| Latency budget | N/A. |
| Simulated / mock | ✅ it **is** the simulator (the canonical "pipeline runs end-to-end before any robot exists" adapter). |
| Required optional dep | None. Always in the test suite. |
| Conformance tests | `host/tests/test_adapters.py::TestSimAdapter` + `test_codec.py::test_sim_adapter` + `test_dataset_roundtrip.py::test_sim_adapter_deterministic`. Will also run under P-A/A3. |
| Capability flags | `Capabilities(dof=<configured>, has_force_feedback=False)`. |
| Unsupported | force feedback; realistic dynamics (P-B `SimRobot` adds kinematics/noise/scenarios). |
| Hardware-needed evidence | None — zero-hardware by design. |

### 4.7b Simulation data-engine adapter — `sim_robot` ✅ (P-B/B2)

The non-stub sim adapter that closes the two `sim`-stub gaps for the data path. Wraps
`sim.SimRobot` (the configurable, seeded synthetic joint robot) behind the FROZEN
`RobotAdapter` — the contract is *implemented*, never edited.

| Field | Mapping |
|---|---|
| SDK / vendor | None — `sim.SimRobotAdapter` over `sim.SimRobot`. Source: `host/sim/robot.py`. |
| Registry name | `sim_robot` (registered behind a lazy factory in `host/adapters/__init__.py`; importing `host/adapters` pulls `sim` only when an instance is built). |
| Control mode support | Position. `send_command` records targets; `read_state` reflects them (on a fresh, freshly-stamped state) until the next command; with no command outstanding it free-runs the configured trajectory. |
| State-read mapping | Advances one tick and returns a **new** `RobotState` (new list) with every joint's angle for that tick and `timestamp_ns = start_ns + i*period_ns` (**> 0, strictly increasing**). Independent-copy by construction. |
| Command-write mapping | `RobotCommand.joint_targets` **copied** into an internal override; reflected by `read_state` (copy on the write path too, so a later `cmd` mutation can't reach internal state). |
| Trajectory models | Pluggable `Trajectory` callables (a `(t, joint, params) -> angle` seam, not a class tree): built-ins `sine` (matches the legacy sweep), `ramp` (triangle reach/retract), `hold` (static). Any bespoke `Callable` is accepted. Configurable DOF, amplitude, frequency, seed, clock (start/period). |
| Joint naming / ordering | Positional, `dof` entries, `chain_index = joint_index`. |
| Units & conversion | radians by convention; pass-through. |
| Timestamp source | Deterministic monotonic clock `start_ns + i*period_ns` (default 100 Hz, `start_ns > 0`). Not wall-clock; byte-stable. Passes `compute_jitter` with `backwards==0`/`dropouts==0` within the default `JitterBudget`. |
| Clock-sync assumptions | Single monotonic timeline; strictly increasing across reads/reconnects (the time-sync invariant). |
| Determinism | Randomness flows through ONE `sim.rng.SeededRng` (stdlib, **no numpy**); trajectories are deterministic today so same config => byte-identical output. The RNG seam is threaded through for B3's per-channel noise. |
| Simulated / mock | ✅ it **is** the simulator (zero hardware). |
| Required optional dep | None. Always in the test suite. |
| Conformance tests | ✅ passes the **RobotAdapter conformance suite** (`host/tests/conformance/test_adapter_conformance.py`, auto-discovered as `sim_robot`, no skips) + `host/tests/test_sim_robot.py` (property/contract). |
| Capability flags | `Capabilities(dof=<configured>, has_force_feedback=False)` — truthful DOF (matches state length); force feedback stays `False`. |
| Unsupported | force feedback; realistic dynamics/noise (B3), contact scenarios (B4/B5). |
| Hardware-needed evidence | None — zero-hardware by design. |

### 4.8 Generic vendor SDK template (for any future robot) 📋

Use this checklist to add a new vendor without touching core. Copy the field set above and fill
it in; the adapter is "ready" only when every row is answered and the conformance + sim gates pass.

| Field | What to specify |
|---|---|
| SDK / vendor | Exact SDK name, version, transport protocol, supported arm models & DOF. |
| Registry name | Short stable key for `make_adapter(name)`; register behind a **lazy factory** in `host/adapters/__init__.py`. |
| Control mode support | Which modes the adapter exposes (position is the v1 baseline; the frozen contract only carries joint targets today). |
| State-read mapping | Vendor state field → `RobotState.joint_angles` (radians); how `timestamp_ns` is set (host monotonic at RX). |
| Command-write mapping | `RobotCommand.joint_targets` (radians) → vendor command call. No-op if read-only. |
| Joint naming / ordering | Canonical joint order and count; document any name↔index mapping. |
| Units & conversion | State the vendor's native unit and the exact conversion to radians; put conversion **in the adapter**, never in a frozen module. |
| Timestamp source | Host `time.monotonic_ns()` at RX (default). If the vendor clock is used, document how it's disciplined to host time. |
| Clock-sync assumptions | Single monotonic host clock; name the cross-modal-alignment failure mode for this vendor. |
| Transport | TCP/UDP/DDS/serial/CAN, ports, host requirements (e.g. RT kernel). |
| Safety / e-stop | Where authority lives; how the adapter surfaces a stop/reflex/protective-stop as a **fault**, never a silent buffer. |
| Rate limits | Native loop rate (hard requirements like Franka's 1 kHz get a callout). |
| Latency budget | A **design budget**, labelled as such — no fabricated measurements. |
| Simulated / mock | The no-hardware backend (vendor sim, Docker sim, or a mock) used for the integration test. |
| Required optional dep | The SDK package; must be **lazy-imported in the factory**, optional, and absent from the test-suite requirements. |
| Conformance tests | Must pass P-A/A3 RobotAdapter conformance + a sim/mock integration test. |
| Capability flags | Fill `Capabilities.dof` truthfully; `has_force_feedback` stays `False` until force data is real. |
| Unsupported features | List explicitly so callers can capability-gate. |
| Hardware-needed evidence 🔒 | The exact bench demo that closes the family on the real device. |

---

## 5. Cross-reference — the conformance + sim gate

An adapter is **not considered ready** until both gates pass (MASTER_PLAN.md P-A and P-G):

1. **RobotAdapter conformance suite (P-A / task A3).** A reusable, parametrized suite under
   `host/tests/conformance/` that auto-discovers every registered adapter and asserts the
   contract invariants (`connect`/`read_state`/`send_command`/`capabilities`: idempotent connect,
   independent-copy reads, truthful `capabilities`, monotonic positive `timestamp_ns`, no-op
   commands tolerated). **Status: landing in task A3** — the harness lives at
   `host/tests/conformance/` (branch `feat/p-a/conformance-harness`). Per-adapter tests in
   `host/tests/test_adapters.py` remain the direct contract check and are **additive to**, not
   replaced by, the conformance harness.
2. **Sim / mock integration test (P-G).** Each adapter must run end-to-end against its
   sim/mock backend with no hardware, proving the data path (`connect → read_state → send_command`)
   works and feeds the PVT engine.

P-G exit criterion (MASTER_PLAN.md): *"every adapter passes conformance + sim e2e; capability
matrix documented; coverage ≥ 90%."* This document is the capability matrix; the conformance
harness (A3) and the per-family sim tests are the executable gates that close P-G.

---

## Related files

- `host/inhabit_can/adapter.py` — FROZEN `RobotAdapter` ABC + `RobotState`/`RobotCommand`/`Capabilities`/`SimAdapter`.
- `host/adapters/__init__.py` — registry + `make_adapter`/`list_adapters`; lazy `ros2`/`ur` factories.
- `host/adapters/replay_adapter.py`, `host/adapters/ros2_adapter.py`, `host/adapters/ur_adapter.py` — implemented/stub adapters.
- `host/inhabit_core/__init__.py` / `registry.py` — generic `Registry[T]` the adapter registry is built on.
- `host/tests/test_adapters.py` — current adapter contract tests (interim conformance).
- `docs/decisions/0006-RobotAdapter-Frozen-Contract.md` — the frozen-contract ADR.
- `docs/host/Host Software Architecture.md`, `docs/architecture/System Architecture.md` — module map, timing assumptions, frozen-contract table.
- `MASTER_PLAN.md` (P-A, P-G, architecture law) · `MASTER_TASK_QUEUE.md` (A3 conformance harness).
