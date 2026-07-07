# SDK Timebase Map — evidence-cited clock-domain audit (P-C/C6)

> What timestamp guarantees each robot SDK **actually** provides, backed by fetched official
> documentation — and exactly how each clock maps onto our timing vocabulary. This deepens the
> per-family "Timestamp source" rows of `docs/sdk/ROBOT_SDK_MAPPING.md`; it does not replace
> that document. Docs-only; no code here.

**Failure mode this document exists to prevent:** an adapter author reads a vendor field named
`timestamp`, assumes it is comparable to our host clock, and wires it straight into
`RobotState.timestamp_ns`. Two robots (or a robot and a camera) then live on different
timelines, the episode aligner silently mis-pairs PVT rows, and the resulting training data is
poisoned *undetectably*. The defense is knowing — with a citation, not a vibe — which clock
every SDK stamp comes from, and refusing to guess where the docs are silent.

**Audit rules (how this document was built):**

1. Every non-obvious claim carries a URL to the page that was actually fetched and read.
2. Where official docs are silent or ambiguous, the row says so plainly (`cannot-claim`, or a
   "verified by absence" note) — **no guessed guarantees**, ever.
3. Clock classifications use the C1 `ClockDomain` tokens exactly (`host/timing/stamp.py`):
   `MONOTONIC` / `WALL` / `SOURCE`.
4. Normalization prescriptions use the C2 `Normalizer` treatments exactly
   (`host/timing/normalize.py`): **identity** (MONOTONIC), **SOURCE + offset_ns** (skew
   recorded; out-of-range results flagged `SKEW_OUT_OF_RANGE`, never clamped), **flag
   `UNKNOWN_SKEW`** (SOURCE without a measured offset — never guessed), and **WALL rejected**
   (wall time is episode provenance, never a normalizable timeline).

---

## 1. How to read this map

### C1 clock domains (`host/timing/stamp.py` — the vocabulary)

| Token | Meaning | Alignment-grade? |
|---|---|---|
| `MONOTONIC` | The ONE canonical host clock (`time.monotonic_ns()` on the ingesting host). What `PVTSample.timestamp_ns` and `CanFrame.rx_monotonic_ns` carry. | Yes — the only domain accepted where alignment-grade time is required (`require_monotonic`). |
| `WALL` | Wall-clock time (`time.time_ns()`, epoch-based). NTP steps, DST and manual adjustment make it jump both directions. | Never. Provenance only; C2's `Normalizer` rejects it at construction. |
| `SOURCE` | A device/SDK-local clock (robot controller tick, camera hardware stamp). Meaningful only within that source. | Only after C2 normalization with a **measured** `offset_ns`; without one, every record is flagged `UNKNOWN_SKEW`. |

### C2 treatments (`host/timing/normalize.py` — what "normalize" means per domain)

| Input domain | Treatment | Never |
|---|---|---|
| `MONOTONIC` | **identity** (`normalized_ns == raw`); backwards stamps flagged `BACKWARDS_IN_SOURCE` | reordered / clamped / dropped |
| `SOURCE` + known `offset_ns` | `normalized_ns = raw + offset`, `skew_ns` recorded; out-of-range flagged `SKEW_OUT_OF_RANGE` | clamped |
| `SOURCE`, no offset | every record flagged `UNKNOWN_SKEW`, `normalized_ns=None` | guessed |
| `WALL` | rejected at `Normalizer` construction — wall→monotonic mapping is always a guess | normalized |

### Status vocabulary (strict — no other tokens are used)

| Status | Meaning |
|---|---|
| `simulation-proven` | The claimed behavior is exercised by our test suite **today** (named test cited). |
| `SDK-doc-audited` | Official docs were fetched, read, and cited; **no code of ours exercises it yet**. |
| `bench-pending` | The claim can only be closed by a measurement on physical hardware; the exact bench evidence is named. |
| `cannot-claim` | Docs unavailable/ambiguous — the row states exactly what is missing. Not a failure; an honest boundary. |

**Never used:** "hardware-ready", "validated", or any completion language without bench logs.
A row may carry two statuses when different claims in it have different evidence (e.g. the
clock semantics are `SDK-doc-audited` while the skew magnitude is `bench-pending`).

---

## 2. At-a-glance summary

| SDK / path | Timestamp field | Clock domain (C1) | Source type | Documented rate | Drift/skew risk | What can be trusted | C2 treatment required | Status |
|---|---|---|---|---|---|---|---|---|
| UR — RTDE | output field `timestamp` (DOUBLE) | `SOURCE` | controller uptime, seconds | up to 500 Hz (e-/ur-Series, current guide); manuals cite 125 Hz (CB-era legacy) | controller clock free-runs vs host; no documented sync; under load cycles are *skipped*, never queued | intra-controller ordering & cycle spacing; gap detection via `timestamp` | host-RX `MONOTONIC` stamp (identity); vendor stamp = SOURCE + measured offset, else flag `UNKNOWN_SKEW` | `SDK-doc-audited` (semantics) · `bench-pending` (skew) |
| Franka — libfranka FCI | `franka::RobotState::time` (`franka::Duration`, ms) | `SOURCE` | controller uptime, integer milliseconds | 1 kHz (hard requirement) | free-runs vs host; 1 ms quantization; no documented sync | strict per-controller monotonicity (documented); cycle counting | host-RX `MONOTONIC` stamp (identity); vendor stamp = SOURCE + measured offset, else flag `UNKNOWN_SKEW` | `SDK-doc-audited` (semantics) · `bench-pending` (skew) |
| KUKA — iiwa FRI | monitor-message timestamp (third-party doc: cabinet epoch time, µs; official semantics not publicly documented) | `SOURCE` (cabinet clock — epoch-based per third-party doc, treat as WALL-like: never alignment-grade) | Sunrise-cabinet clock | FRI send period 1–100 ms (community/mirror figure — no official public page) | cabinet clock free-runs vs host; epoch-based ⇒ NTP-steppable; no public sync guarantees | liveness (stamp advancing = cabinet app running — third-party doc) | host-RX `MONOTONIC` stamp (identity); vendor stamp = SOURCE, flag `UNKNOWN_SKEW` until offset measured (and re-measured per session — epoch clock can step) | **`cannot-claim`** (official semantics — FRI manual is proprietary) · `bench-pending` (skew) |
| ROS 2 (Jazzy) — `header.stamp` | `std_msgs/Header.stamp` (`builtin_interfaces/Time`) | `WALL` by default (publisher-set); `SOURCE` under sim time | publisher's node clock (`RCL_ROS_TIME` → system/wall unless sim `/clock`) | topic-dependent | NTP steps / publisher skew; stamp set at publish, not reception; zero stamps if `use_sim_time` with no `/clock` | nothing, for alignment — by C2 rule WALL is never normalized | **ignore for alignment**; host-RX `MONOTONIC` stamp (identity) — what `ROS2Adapter` already does; keep `header.stamp` as provenance | `SDK-doc-audited` (semantics) · `simulation-proven` (our RX stamping) |
| Custom CAN — Inhabit Rev-A | `CanFrame.rx_monotonic_ns` (ours, at host RX) | `MONOTONIC` | host-RX-monotonic (`time.monotonic_ns()`) | firmware TX ~1 kHz (design, unbenched) | none on host stamp; bus+driver latency folded into stamp (unmeasured) | monotonicity, non-zero, single-host comparability | **identity** | `simulation-proven` (stamping contract) · `bench-pending` (real-bus latency/jitter) |
| Generic SDK template | *(rule, not a claim)* | declared per adapter | — | — | — | — | host-RX `MONOTONIC` default; SOURCE requires measured offset; WALL never | n/a — the rule statuses apply per implementation |

---

## 3. Per-family audit

### 3.1 Universal Robots — RTDE

| Field | Finding | Evidence |
|---|---|---|
| Timestamp field | RTDE output field `timestamp`, type `DOUBLE`, documented verbatim as **"Time elapsed since the controller was started [s]"** — controller uptime in seconds, stated officially including the unit. | UR RTDE Guide (canonical, current), output-field table: <https://docs.universal-robots.com/tutorials/communication-protocol-tutorials/rtde-guide.html>; identical row in the official PolyScope manuals: <https://www.universal-robots.com/manuals/EN/HTML/SW10_10/Content/Prod-RTDE/Real_Time_Data_Exchange_RTDE.htm> and <https://www.universal-robots.com/manuals/EN/HTML/SW5_23/Content/Prod-RTDE/Real_Time_Data_Exchange_RTDE.htm> |
| Clock domain (C1) | `SOURCE` — a controller-local uptime clock. Not host `MONOTONIC`, not `WALL`, not referenced to any external epoch. | classification per `host/timing/stamp.py` `ClockDomain.SOURCE` ("a robot controller's tick counter") |
| Documented rate | Current guide: output at up to the real-time control-loop frequency — **"500 Hz on e-Series and ur-Series robots"**; client-requested frequency 1–500 Hz, actual rate `floor(500 / frequency)`. The manuals instead say "The RTDE generally generates output messages on 125 Hz" (SW10, protocol v2: 1–125 Hz, `floor(125 / frequency)`). **Ambiguity stated, not smoothed:** no fetched official page pairs "125 Hz" with "CB-Series" in one sentence — that attribution is a reasonable inference (CB3 control loop era), and the e-Series SW5.23 manual still carries the legacy 125 Hz sentence while the current guide says 500 Hz. Trust the current guide per series; treat manual "125 Hz" text as CB-era legacy. | guide + both manual pages above |
| Transport / pacing | **TCP port 30004** (stated in the manuals; the current tutorials page does not name the port — verified by explicit search). Standard TCP/IP; packet emission tied to controller cycles. **Skip-don't-queue:** "if the controller lacks computational resources it will skip a number of output packages... The skipped packages will not be sent later, the controller will always send the most recent data" — under load you get **gaps, not latency buildup**, and the `timestamp` field is how skipped cycles are detected. Episode loggers must tolerate and record dropped controller cycles, never assume a gapless stream. | manuals above (port + skip behavior); guide (TCP, pacing); corroborating official client README: <https://github.com/UniversalRobots/RTDE_Python_Client_Library> |
| Host sync | **No documented host-sync mechanism found** (verified by absence): the official RTDE Guide, the SW5/SW10 manual RTDE pages, the official UR Client Library architecture docs (<https://docs.universal-robots.com/Universal_Robots_ROS2_Documentation/doc/ur_client_library/doc/architecture/rtde_client.html>), and the official RTDE Python Client README mention no NTP/PTP/host-time handshake anywhere in the RTDE path. A UR forum thread *requesting* time sync as a feature (<https://forum.universal-robots.com/t/feature-request-time-sync/15811>) is consistent with the absence — but is community material, not official documentation. | absence stated, not guessed |
| Resolution / jitter | **Not officially documented.** No official statement on timestamp resolution, precision, or delivery jitter. Labeled inference (UNVERIFIED, not documented): since packets are emitted on control cycles, `timestamp` should advance in cycle quanta (2 ms at 500 Hz, 8 ms at 125 Hz); TCP delivery jitter is unspecified. | absence stated |
| Drift/skew risk | Controller clock free-runs relative to the host. Offset is unknown at connect and drifts; TCP delivery adds variable latency on top; under load, skipped cycles produce gaps. | consequence of the above |
| What can be trusted | Ordering and spacing of samples *within* one controller session, and **gap detection** (a `timestamp` jump > one cycle = skipped packages). Cross-source comparability: **nothing**, until an offset is measured. | — |
| What must be normalized (C2) | Adapter default: stamp at RX with host `time.monotonic_ns()` → `MONOTONIC`, treatment **identity** (this is what `docs/sdk/ROBOT_SDK_MAPPING.md` §4.2 already plans). If the vendor `timestamp` is additionally recorded (recommended, for latency diagnostics), it is `SOURCE`: alignment-grade use requires a **measured** `offset_ns` (SOURCE + offset), otherwise every record is flagged `UNKNOWN_SKEW` — never guessed. | `host/timing/normalize.py` |
| Status | **`SDK-doc-audited`** for the field semantics/rates (docs fetched and cited; our `URAdapter` is still a stub — `host/adapters/ur_adapter.py` raises `NotImplementedError`, so nothing is simulation-proven). **`bench-pending`** for the actual controller↔host offset/drift magnitude and RTDE delivery jitter: requires a live UR controller (see §4). | — |

### 3.2 Franka — libfranka (FCI)

| Field | Finding | Evidence |
|---|---|---|
| Timestamp field | `franka::RobotState::time`, type `franka::Duration`, documented as **"Strictly monotonically increasing timestamp since robot start."** | libfranka 0.15.0 Doxygen, `RobotState`: <https://frankarobotics.github.io/libfranka/0.15.0/structfranka_1_1RobotState.html> (older host `frankaemika.github.io` mirrors the docs post-rebrand) |
| Resolution | `franka::Duration` "Represents a duration with **millisecond resolution**" — integer milliseconds (`Duration(uint64_t milliseconds)`, `toMSec()`, `toSec()`). So `RobotState::time` quantizes to 1 ms, exactly one FCI cycle. | <https://frankarobotics.github.io/libfranka/0.15.0/classfranka_1_1Duration.html> |
| Clock domain (C1) | `SOURCE` — controller-local uptime. Documented strictly monotonic **within the controller**, which is more than UR documents — but still not comparable to host time without an offset. | classification per `host/timing/stamp.py` |
| Documented rate | **1 kHz** bidirectional state/command exchange — a hard requirement, not a target. | FCI docs: <https://frankaemika.github.io/docs/overview.html>, <https://frankaemika.github.io/docs/libfranka.html> |
| Transport / RT | State/command exchange over **UDP**; a **PREEMPT_RT real-time kernel is a requirement** on the workstation. Missing the 1 kHz deadline aborts motion with the documented error `communication_constraints_violation`. | <https://frankaemika.github.io/docs/libfranka.html>; RT kernel: <https://frankaemika.github.io/docs/installation_linux.html#setting-up-the-real-time-kernel>; deadline error: <https://frankaemika.github.io/docs/troubleshooting.html#motion-stopped-due-to-discontinuities-or-communication-constraints-violation> |
| Host sync | **No documented host-sync mechanism found** (verified by absence): libfranka Doxygen (`RobotState`, `Duration`, `Robot`) and the FCI docs describe `time` only as time since robot start; no API or procedure relates it to the workstation clock. | absence stated after reading the pages above |
| Drift/skew risk | Controller clock free-runs vs host; 1 ms quantization floor; robot-sample→UDP-arrival latency is **nowhere bounded in the docs** — do not claim a bound. | absence stated |
| What can be trusted | Strict per-controller monotonicity (documented — the strongest vendor guarantee in this audit) and cycle counting (each tick = 1 ms). Cross-source comparability: nothing without a measured offset. | RobotState doc above |
| What must be normalized (C2) | Adapter default: host `time.monotonic_ns()` at the 1 kHz callback RX → `MONOTONIC`, **identity** (per `ROBOT_SDK_MAPPING.md` §4.3 plan). Vendor `time` recorded alongside = `SOURCE`: **SOURCE + measured offset_ns** for alignment-grade use, else flag `UNKNOWN_SKEW`. | `host/timing/normalize.py` |
| Status | **`SDK-doc-audited`** (docs fetched/cited; the `franka` adapter is not even registered — `make_adapter("franka")` raises `ValueError` today). **`bench-pending`** for offset/drift magnitude and sample→arrival latency: requires a real Panda/FR3 (see §4). | — |

### 3.3 KUKA — iiwa FRI

**The honest headline: `cannot-claim` for official timestamp semantics.** KUKA's FRI
documentation ships with the proprietary Sunrise.OS *Connectivity* package and is not publicly
fetchable — so unlike UR and Franka, no official page could be read and cited. What is missing,
exactly: the official Sunrise.OS FRI manual section defining the monitor-message timestamp's
clock source, epoch, resolution, and any host-sync behavior. Until someone with a Sunrise
license supplies that section (or a bench measurement exists), every semantic claim below is
labeled third-party or community evidence.

| Field | Finding | Evidence |
|---|---|---|
| Timestamp field | The FRI monitor message carries a cabinet timestamp; public **community mirrors** of the proprietary FRI Client SDK exist (not KUKA-official, internals not asserted here). | mirrors: <https://github.com/cmower/FRI-Client-SDK_Cpp>, <https://github.com/lbr-stack/fri> — cited as existence evidence only |
| Timestamp semantics (third-party) | A professional third-party integration doc (Quanser QUARC, fetched and read): **"Timestamp indicates, in microseconds (us), the robot application current timestamp value in epoch Unix time, as determined by the Sunrise cabinet"**, and "As long as the timestamp value changes and is being updated, the FRI cabinet application is running and connected" (a liveness indicator, not a sync guarantee). | <https://docs.quanser.com/quarc/documentation/kuka_lbr_fri_timebase_block.html> |
| Clock domain (C1) | `SOURCE` — a cabinet-local clock. Per the third-party doc it is *epoch-based* (Unix time), i.e. WALL-like in behavior: adjustable/steppable on the cabinet. That makes it **doubly** unsuitable for alignment: it is a foreign clock AND it may not even be monotonic. | classification per `host/timing/stamp.py`; semantics per the Quanser page above |
| Documented rate | FRI send period is configured on the Sunrise side (community/mirror figure: 1–100 ms). **No official public page** states this; treat as unconfirmed. | community/mirror material — labeled |
| Host sync | No public sync guarantees of any kind. | absence — and the official docs themselves are not public |
| What can be trusted | Only liveness (per the third-party doc): an advancing stamp means the cabinet app is running. Nothing about it is alignment-grade. | Quanser page above |
| What must be normalized (C2) | Adapter default (unchanged by the documentation gap): host `time.monotonic_ns()` at RX → `MONOTONIC`, **identity** (per `ROBOT_SDK_MAPPING.md` §4.4 plan). If the cabinet stamp is recorded: `SOURCE`, flag `UNKNOWN_SKEW` until a **measured** offset exists — and because the cabinet clock is epoch-based, any measured offset must be treated as per-session and re-measured (an NTP step on the cabinet invalidates it mid-episode; the C4 `SKEWED_CLOCK`/step shapes model exactly this). | `host/timing/normalize.py` |
| Status | **`cannot-claim`** (official semantics — proprietary docs; exact missing artifact named above) · **`bench-pending`** (offset/drift/step behavior: requires a real iiwa + Sunrise license, see §4). | — |

### 3.4 ROS 2 (Jazzy) — `header.stamp` and DDS timestamps

| Field | Finding | Evidence |
|---|---|---|
| Timestamp field | `std_msgs/Header.stamp` (`builtin_interfaces/Time`, sec+nanosec) is **ordinary message payload set by the publisher** — the canonical pattern is `t.header.stamp = self.get_clock().now().to_msg()` ("the current time used by the Node"). The middleware does not write it at reception (labeled inference: no single official sentence says "middleware never touches stamp", but reception-time metadata lives in a separate structure, `rmw_message_info_t`, and `stamp` is serialized payload). | Header definition: <https://github.com/ros2/common_interfaces/blob/jazzy/std_msgs/msg/Header.msg>; official tf2 tutorial: <https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Tf2/Writing-A-Tf2-Broadcaster-Py.html>; <https://github.com/ros2/rclcpp/blob/jazzy/rclcpp/include/rclcpp/message_info.hpp> |
| Default clock chain | Node default clock is `RCL_ROS_TIME` (rclcpp `node_options.hpp`: `clock_type_ {RCL_ROS_TIME}`; rclpy `Node` uses `ROSClock`). Per `rcl/time.h`: "RCL_ROS_TIME will report ... or if a ROS time source is not active it reports the same as RCL_SYSTEM_TIME", and "RCL_SYSTEM_TIME reports the same value as the system clock". Per `rcutils/time.h`, system time ≈ `std::chrono::system_clock::now()` — **epoch-based, adjustable wall time** (that `system_clock` is non-monotonic Unix time is a C++ standard fact). **Bottom line, the critical claim: with `use_sim_time` off (the default), `header.stamp` is effectively WALL — NTP-adjustable and able to step backwards.** `RCL_STEADY_TIME` (monotonic) exists as a separate clock type but is never the node default, so it is not what goes into `header.stamp` unless explicitly requested. | <https://github.com/ros2/rclcpp/blob/jazzy/rclcpp/include/rclcpp/node_options.hpp>; <https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/node.py> + <https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/clock.py>; <https://github.com/ros2/rcl/blob/jazzy/rcl/include/rcl/time.h>; <https://github.com/ros2/rcutils/blob/jazzy/include/rcutils/time.h>; design article: <https://design.ros2.org/articles/clock_and_time.html> |
| Clock domain (C1) | `WALL` by default (publisher's system clock). With `use_sim_time=true`, the node clock follows `/clock` — the stamp becomes `SOURCE` (the sim timeline). Either way it is **never** host `MONOTONIC`. | classification per `host/timing/stamp.py` |
| Sim time | "If `/clock` is being published, calls to the ROS time abstraction will return the latest time received ... **If time has not been set it will return zero if nothing has been received.**" — i.e. `use_sim_time=true` with no `/clock` publisher yields **zero stamps**, exactly the "never stamped" sentinel C1 rejects loudly. A real failure mode for any logger trusting `header.stamp`. | <https://design.ros2.org/articles/clock_and_time.html>; <https://github.com/ros2/rclcpp/blob/jazzy/rclcpp/include/rclcpp/time_source.hpp> |
| DDS-level timestamps | `rmw_message_info_t` carries `source_timestamp` (publish time) and `received_timestamp` (reception time), with the officially vague caveat "The exact point at which the timestamp is taken is not specified". rclcpp exposes them via `MessageInfo` callbacks; **rclpy (Jazzy) does NOT expose `MessageInfo` in `create_subscription`** — which matters here, since our host stack is rclpy. Per-rmw reality (from official rmw source, not documentation — no per-rmw feature matrix exists): Fast DDS (the Jazzy default rmw) populates both from DDS SampleInfo; **Cyclone DDS fakes `received_timestamp` at take() with `system_clock::now()`** (an in-source `TODO`), so under Cyclone it is processing time, not wire-arrival time. | <https://github.com/ros2/rmw/blob/jazzy/rmw/include/rmw/types.h>; <https://github.com/ros2/rclcpp/blob/jazzy/rclcpp/include/rclcpp/any_subscription_callback.hpp>; <https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/node.py>; <https://github.com/ros2/rmw_fastrtps/blob/jazzy/rmw_fastrtps_shared_cpp/src/rmw_take.cpp>; <https://github.com/ros2/rmw_cyclonedds/blob/jazzy/rmw_cyclonedds_cpp/src/rmw_node.cpp>; default rmw: <https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Different-Middleware-Vendors.html> |
| Multi-machine sync | **Essentially absent from core docs**: no docs.ros.org (Jazzy) page requires NTP/PTP/chrony for cross-machine `header.stamp` consistency. Closest official statement (design article): external time sources like GPS should integrate "using standard NTP integrations with the system clock". Community/vendor guidance (labeled as such — Clearpath, ROS Answers, etc.) converges on chrony. | design article above; community e.g. <https://docs.clearpathrobotics.com/docs/ros/networking/ntp/> |
| Drift/skew risk | Publisher wall clock can be stepped by NTP mid-episode (backwards included); stamp is set at publish, so DDS transit latency is invisible; different publishers on different machines are aligned only as well as their chrony setup — which core ROS 2 never mandates. | consequence of the above |
| What can be trusted | For alignment: **nothing** — by the C2 rule, WALL is never normalized (any wall→monotonic mapping is a guess). `header.stamp` remains useful as *provenance* ("what the publisher's clock read at publish") and for intra-publisher diagnostics. | `host/timing/normalize.py` (WALL rejected at `Normalizer` construction) |
| What must be normalized (C2) | **Ignore `header.stamp` for alignment; host-RX `MONOTONIC` stamp, treatment identity.** This is exactly what `ROS2Adapter` already does: `timestamp_ns = time.monotonic_ns()` in the subscription callback, `header.stamp` deliberately not trusted. Under `use_sim_time` the stamp could be treated as `SOURCE` with a measured offset, but the default posture stands: RX-stamp on the host. | `host/adapters/ros2_adapter.py` (`_on_joint_state`) |
| Status | **`SDK-doc-audited`** for the `header.stamp`/clock-chain/DDS semantics (official sources fetched and cited above). **`simulation-proven`** for our side of the contract: `host/tests/test_adapters.py::TestROS2Adapter` exercises the host-RX stamping fallback (`test_fallback_state_has_timestamp` asserts `timestamp_ns > 0` before any callback) and non-finite frame rejection without needing rclpy. The live-graph path (real `/joint_states` publisher → callback RX-stamp) is skipped in CI (no rclpy) — closing it needs a ROS 2 environment, and controller-grade timing numbers stay **`bench-pending`** (real arm, see §4). | test file cited |

### 3.5 Custom CAN — Inhabit Rev-A (our own contract)

This is the one family where *we* are the vendor, so the guarantees are ours to state plainly.

| Field | Finding | Evidence |
|---|---|---|
| Timestamp field | `CanFrame.rx_monotonic_ns` — the host receive time, read from `time.monotonic_ns()` at the moment the frame is pulled off the bus. Set by every `CanSource` (`ReplaySource`, `SimSource`, `SocketCanSource`). | `host/inhabit_bridge/sources.py` (module docstring "Time-sync contract" + `CanFrame`) |
| Firmware clock | **CAN schema v1 carries no clock.** The 8-byte payload is `angle_raw_adc / angle_millideg / node_id / chain_index / status_flags / checksum` — no timestamp field of any kind. The pods have no synchronized clock; host-RX time is the *only* timebase. Stated plainly: sub-millisecond cross-pod ordering is not recoverable from the frames themselves. | root `CLAUDE.md` "CAN message schema (v1)"; `host/inhabit_can/codec.py` (FROZEN) |
| Clock domain (C1) | `MONOTONIC` — this is the canonical domain, by construction. Never wall clock (explicit contract in the module docstring and `docs/architecture/System Architecture.md`). | `host/inhabit_bridge/sources.py` |
| Documented rate | Firmware TX ~1 kHz (`tick_1khz`) — a **design figure, not a benched measurement** (no Rev-A board has been on a bench yet). | root `CLAUDE.md` roadmap; `ROBOT_SDK_MAPPING.md` §4.5 |
| Drift/skew risk | None on the stamp itself (single host clock). The real risk is **latency folded into the stamp**: bus arbitration + USB-CAN/SocketCAN driver buffering happens *before* `monotonic_ns()` is read, so the stamp is "when the host saw it", not "when the encoder sampled". That gap is unmeasured (`bench-pending`). | design analysis; budget (p99 < 2 ms) in `ROBOT_SDK_MAPPING.md` §4.5 — labelled a budget, not a result |
| What can be trusted | Monotonicity, non-zero-ness, and single-host comparability of `rx_monotonic_ns` across all sources on one host — the exact invariants C1 validates. | `host/timing/stamp.py` |
| What must be normalized (C2) | **identity** — already in the canonical domain. Backwards stamps (should be impossible from one host clock) would be flagged `BACKWARDS_IN_SOURCE`, never repaired. | `host/timing/normalize.py` |
| Status | **`simulation-proven`** for the stamping contract: exercised today by `host/tests/test_bridge.py` (frames carry increasing `rx_monotonic_ns`), `host/tests/conformance/test_transport_conformance.py` (RX-stamp monotonicity asserted), and `host/tests/test_calibration_helper.py` (injected-clock stamping). **`bench-pending`** for real-bus latency/jitter: requires the Rev-A board (see §4 — this is the exact first bench milestone). | test files cited |

### 3.6 Generic SDK adapter template — the rule every future adapter follows

Not a claim about any vendor; the contract each new adapter must declare **before** it is
trusted with timestamps. Extends the template row set of `ROBOT_SDK_MAPPING.md` §4.8.

1. **Declare the domain.** Every timestamp the adapter touches is classified with a C1
   `ClockDomain` token (`MONOTONIC` / `WALL` / `SOURCE`) in the adapter's mapping-doc row
   *before* implementation. An unclassified stamp is a review blocker.
2. **Host-RX stamp is the default.** `RobotState.timestamp_ns` is host `time.monotonic_ns()`
   at receive — the frozen-contract expectation (`ROBOT_SDK_MAPPING.md` §2). This is treatment
   **identity** in C2 and requires no vendor cooperation.
3. **Vendor SOURCE clocks are quarantined until measured.** A vendor stamp may be *recorded*
   freely (it is useful provenance and latency-diagnostic data), but alignment-grade use
   requires a **measured** source→monotonic `offset_ns` (C2: SOURCE + offset). Without one,
   records are flagged `UNKNOWN_SKEW` — the pipeline never guesses an offset.
4. **WALL never enters the timeline.** Wall-clock values (including ROS `header.stamp` under
   the default clock) are episode provenance only; C2's `Normalizer` rejects them by
   construction.
5. **Claims follow the status vocabulary.** A new adapter's timing row starts at
   `SDK-doc-audited` (cite the vendor page) or `cannot-claim` (say what's missing); it becomes
   `simulation-proven` only when a test in our suite exercises it, and its skew/latency numbers
   stay `bench-pending` until a physical measurement exists.

---

## 4. Hardware smoke-test plan (future, non-blocking)

None of this blocks P-C — the software lane closes on sim/replay. Each step names the exact
evidence that would upgrade a row above. Statuses only ever move forward on **captured logs**,
never on a successful compile or an optimistic afternoon.

| # | Bench step | Evidence produced | Row upgraded |
|---|---|---|---|
| 1 | **Two-node CAN breadboard** (Rev-A pods, 5-wire chain): power both pods, verify enumeration order, capture ≥60 s of frames on the host via `SocketCanSource`. | `.canlog` capture with `rx_monotonic_ns` for every frame; inter-frame interval histogram per pod. | §3.5 rate: "~1 kHz design" → measured TX rate; `bench-pending` → `simulation-proven`-equivalent bench claim for live stamping. |
| 2 | **Encoder→CAN→host latency probe**: toggle a known mechanical reference (or inject a step via the encoder magnet), measure encoder-edge→frame-RX delta with a scope on CANH vs host stamp. | Measured bus+driver latency distribution (p50/p99) to compare against the p99 < 2 ms budget. | §3.5 drift/skew row: latency-folded-into-stamp becomes a measured number. |
| 3 | **Camera frame timestamp capture**: run a camera alongside step 1, stamping frames with the same host `time.monotonic_ns()` at frame arrival; record both streams. | Paired CAN/video capture on one monotonic timeline. | Enables the first cross-modal alignment check on real data (P5/P6 roadmap); no row claims until measured. |
| 4 | **Measured skew report** (per vendor SDK, when hardware exists): for UR/Franka/KUKA, log (vendor stamp, host RX stamp) pairs for ≥10 min; fit offset + drift rate. | `offset_ns` (+ drift) per controller session — the exact input C2's SOURCE+offset treatment needs. | §3.1/§3.2/§3.3 skew rows: `bench-pending` → measured; vendor stamps become alignable (`UNKNOWN_SKEW` flag no longer forced). |
| 5 | **First hardware-in-loop replay dataset**: record a real two-pod episode end-to-end (CAN + camera), export via the existing exporters, reload, and replay through `ReplaySource`/`ReplayAdapter`. | A committed, reloadable dataset whose timing metadata (C5) audits clean. | The whole map gains its first end-to-end hardware evidence; any status language stronger than `bench-pending` for hardware paths becomes justified *only here*. |

---

## 5. Related files

- `docs/sdk/ROBOT_SDK_MAPPING.md` — per-family adapter map this audit deepens (esp. §2 timestamp contract, §4.x "Timestamp source" rows).
- `host/timing/stamp.py` — C1 `ClockDomain` / `Stamp` / `require_monotonic` (the vocabulary used here).
- `host/timing/normalize.py` — C2 `Normalizer` / `TimingRecord` / `NormalizationFlag` (the treatments prescribed here).
- `host/adapters/ros2_adapter.py` — host-RX `MONOTONIC` stamping in practice (`header.stamp` deliberately not trusted).
- `host/inhabit_bridge/sources.py` — `CanFrame.rx_monotonic_ns` contract for custom CAN.
- `host/inhabit_can/codec.py` — FROZEN CAN schema v1 (no clock field).
- `MASTER_TASK_QUEUE.md` §P-C (C6) — the task this document closes.
