# Rev-A Bench Evidence Templates (blank fill-in + thresholds)

> **HARDWARE-BLOCKED.** Every measured value below is a blank `___` to be filled at the bench
> with a real Rev-A board on instruments. This file pre-stages the *templates* and the
> *pass/fail thresholds* (numeric where a datasheet or the frozen code/contract fixes them;
> `TBD-needs-board` where the number can only come from silicon). Filling a blank requires a
> scope / logic-analyzer / DMM / CAN-sniffer capture — **do not** write a number you did not
> measure.
>
> Companion docs (read first): `firmware/BENCH_TESTS.md` §6 (bring-up order),
> `docs/bench/firmware-bench-evidence.md` (golden 3-pod frames), `.claude/skills/pcb-bringup/SKILL.md`
> (phase-by-phase procedure + failure tree). Pin map / schema / ENUM protocol live in
> root `.claude/CLAUDE.md` (single source of truth) — **frozen, never edited here.**
>
> **Bring up ONE stage at a time. Do not advance until the current stage's gate is met on
> instruments.** Log the outcome of each filled template into `docs/bringup-log.md`.

## How to use a template line

Each row gives three things:
- **Capture** — the artifact that constitutes evidence (DMM reading, scope screenshot,
  LA decode, CSV, candump log). A blank with no artifact is not evidence.
- **Gate** — the pass/fail window. Numeric where fixed by a datasheet or by the frozen
  code/contract (cited). `TBD-needs-board` where only silicon can set it.
- **Actual** — the `___` blank you fill at the bench, plus the artifact filename/photo ref.

Cross-references to firmware are by-name only (pin map, status bits, CNF constants, ENUM
ticks); the firmware code and the 4 frozen contracts (CAN schema v1, RobotAdapter, PVTSample,
JointPodState.msg) are **not** modified by this doc.

---

## E1 — First power (`pcb-bringup` Phase 1)

**Stage gate to advance:** rails in window, idle current below hard-stop, bus ~60 Ω.
**Pre-power (mandatory, before any supply is connected):** DMM continuity 5V5 / VCC_BUS / 3V3
to GND must read **open** (no short). Inspect bottom-side PCBA orientation (root `CLAUDE.md`
flags this as the unverified risk). Power via bench supply with current limit set to **~100 mA**
to start (per `pcb-bringup` Phase 1).

| # | What to capture | Gate (pass window) | Actual |
|---|-----------------|--------------------|--------|
| E1.0 | DMM continuity 5V5↔GND, VCC_BUS↔GND, 3V3↔GND, **unpowered** | OPEN (no short) before applying power | 5V5↔GND = `___` · VCC_BUS↔GND = `___` · 3V3↔GND = `___` (photo: `___`) |
| E1.1 | DMM on **5V5** input rail, powered | nominal **5.5 V**; pass window **TBD-needs-board** (set from regulator/supply spec once the BOM regulator part is confirmed) | 5V5 = `___` V |
| E1.2 | DMM on **3V3** logic rail (STM32C011 VDD), powered | **3.3 V** nominal; STM32C011 operating range **2.0–3.6 V** (STM32C011 datasheet, Operating conditions) → fail if outside **2.0–3.6 V**; target **3.3 V ±5% = 3.135–3.465 V** | 3V3 = `___` V |
| E1.3 | Bench-supply current readout at idle (post-inrush, firmware idle/heartbeat) | hard-stop **TBD-needs-board** (set from measured-clean baseline + margin; start the supply limit at **100 mA** per `pcb-bringup` Phase 1). Any sustained pin at the supply's current limit ⇒ short / backwards part — power off, reinspect | idle = `___` mA (supply limit set = `___` mA; inrush peak = `___` mA) |
| E1.4 | Scope ripple on 3V3 rail (AC-couple) | **TBD-needs-board** (set p-p ripple budget from regulator spec); record value for the record either way | 3V3 ripple p-p = `___` mV (scope: `___`) |
| E1.5 | DMM CANH↔CANL, **unpowered**, both boards' termination present | **~60 Ω** expected (two 120 Ω terminators in parallel; root `CLAUDE.md` bus = 5-wire daisy chain). One terminator only ⇒ ~120 Ω; none ⇒ open | CANH-CANL = `___` Ω |

**Failure tree (name most-likely first):** high current at the supply limit ⇒ **short or a
backwards-installed part** (most common at first power) — power off, reinspect orientation,
thermal-cam (`pcb-bringup` Phase 1). 3V3 out of the 2.0–3.6 V STM32 range ⇒ regulator wrong
value / not enabled / wrong rail order (wrong order can latch up the STM32 — `BENCH_TESTS.md`
§6.1). CANH-CANL ≠ ~60 Ω ⇒ **missing or extra 120 Ω termination** (see E4/E6 bus-error tree).

---

## E2 — MT6701 ADC sweep (`pcb-bringup` Phase 2; `BENCH_TESTS.md` §2.2)

**Stage gate to advance:** clean monotonic A0 ramp across a full rotation (no flat spots),
raw_adc span covers most of the 12-bit range, and the `ST_MAGNET_OOB` window has been *defined*.
Probe MT6701 analog OUT → STM32 **A0** (root pin map). ADC is **12-bit (0–4095)**; firmware
oversamples + filters per house rule (`firmware/CLAUDE.md`). Rotate the joint against a printed
protractor / index jig to known mechanical angles.

| # | What to capture | Gate (pass window) | Actual |
|---|-----------------|--------------------|--------|
| E2.1 | Scope A0 across a full **0–360°** mechanical rotation | clean, **monotonic** ramp, no flat spots/clipping (flat = magnet off-center/out of range, `BENCH_TESTS.md` §2.2) | A0 V_min = `___` V @ `___`° · A0 V_max = `___` V @ `___`° (scope: `___`) |
| E2.2 | `angle_raw_adc` (CAN byte[0:1], LE) logged at mechanical **0°** | 12-bit reading 0–4095; specific value **TBD-needs-board** (depends on magnet/jig zero offset) | raw_adc @ 0° = `___` (0–4095) |
| E2.3 | `angle_raw_adc` at mechanical **180°** | distinct from 0° by roughly half the usable span; value **TBD-needs-board** | raw_adc @ 180° = `___` |
| E2.4 | Raw span = (max raw over rotation) − (min raw over rotation) | target: span covers **most of 0–4095** (large fraction of full scale = good analog gain/headroom); exact min span **TBD-needs-board** (depends on MT6701 analog OUT V-range vs 3V3 ADC ref) | span = `___` counts (min `___` … max `___`) |
| E2.5 | Defined `ST_MAGNET_OOB` (bit 3, `0x08`, `can_frame.h`) raw window `[low, high]` | **TBD-needs-board** — there is currently **no ADC-window constant in firmware** (only the `ST_MAGNET_OOB` *bit* exists in `can_frame.h`; the numeric window is the `encoder_read_raw` TODO in `main.c`). Set `[low, high]` from the measured clean-rotation min/max with margin, then back-annotate firmware in a separate change | OOB window = `[ ___ , ___ ]` raw counts; chosen margin = `___` |
| E2.6 | 2–3 known-angle calib points + readback (cross-check `test_calib` math) | a swept angle reads back within tolerance after fit; tolerance **TBD-needs-board** | (angle→raw) pairs: `___` ; readback err = `___` mdeg (CSV: `___`) |

**Failure tree (name most-likely first):** flat / noisy / clipped ADC ramp ⇒ **magnet alignment
/ distance** (off-center or too far), then MT6701 MODE-pin / analog-out config, then wrong ADC
channel (`pcb-bringup` Phase 2). Out-of-window raw ⇒ firmware sets **`ST_MAGNET_OOB`**; a failed
ADC read ⇒ **`ST_ADC_FAULT`** (`BENCH_TESTS.md` §2.2). Both surface in CAN byte[6].

---

## E3 — /INT loopback (`pcb-bringup` Phase 3; `BENCH_TESTS.md` §2.3, §6.7)

**Stage gate to advance:** in `MCP_MODE_LOOPBACK`, a TX on TXB0 pulls **/INT (PB6) low**, and it
returns high after `can_rx_service()` clears RX0IF — proving the SPI↔CAN↔EXTI chain with **no
transceiver and no second board**. /INT is **active-low, open-drain**, on **PB6**, EXTI line 6,
falling-edge (root pin map + `main.c`). LA on PA4–PA7 (SPI) and PB6 (/INT).

> Pre-gate (the single most important MCP2515 check, `BENCH_TESTS.md` §2.3): a `READ CANSTAT`
> after `RESET` must return **`0x80`** (Config mode). If not, the MCP2515 isn't talking
> (wrong CS, no 16 MHz crystal, swapped MISO/MOSI) — do not proceed to E3 timing.

| # | What to capture | Gate (pass window) | Actual |
|---|-----------------|--------------------|--------|
| E3.0 | LA decode: `READ CANSTAT` after `RESET` (`0x0E`→) | returns **`0x80`** (Config). LOOPBACK confirmed = CANSTAT **`0x40`** (`BENCH_TESTS.md` §2.3) | CANSTAT after reset = `___` ; after loopback = `___` (LA: `___`) |
| E3.1 | Scope PB6 idle (no pending RX) | idle **HIGH ≈ 3.3 V** (pull-up; /INT de-asserted). Logic-high V_IH per STM32C011 ≥ ~0.7·VDD | PB6 idle = `___` V |
| E3.2 | Scope PB6 asserted (after TX loopback raises RX0IF) | **LOW ≤ 0.4 V** (open-drain pulled low; STM32 V_IL ~0.3·VDD ⇒ ≤ ~0.99 V at 3V3, use **≤ 0.4 V** as the clean-assert gate) | PB6 low = `___` V |
| E3.3 | Scope/LA: PB6 falling edge → /INT serviced (back HIGH after `can_rx_service` clears RX0IF) | /INT returns high after service; **TX→service low-duration** budget **TBD-needs-board** (bounded by SPI clock + poll budget = 1; record the measured µs) | /INT low duration = `___` µs (scope: `___`) |
| E3.4 | LA: CS-framed SPI init sequence (`BENCH_TESTS.md` §2.3) | `0xC0` RESET, `READ 0x0E`→`0x80`, CNF writes `0x2A←0x00`,`0x29←0xB1`,`0x28←0x05`, `CANINTE 0x2B←0x03`, BIT_MODIFY CANCTRL→`0x40` | CNF bytes seen = `___` (LA: `___`) |

**Failure tree (name most-likely first):** CANSTAT-after-reset ≠ `0x80` ⇒ **MCP2515 not talking**:
wrong CS (PA4), **16 MHz crystal not oscillating** (scope OSC1 — dead crystal = garbage reads),
or swapped MISO/MOSI (`pcb-bringup` Phase 3, `BENCH_TESTS.md` §2.3). /INT never falls in loopback
⇒ CANINTE not set (`0x2B←0x03`) or EXTI/PB6 not configured. Any SPI timeout ⇒ firmware
**`ST_SPI_FAULT`**; mode not confirmed ⇒ **`ST_CAN_FAULT`**.

---

## E4 — Per-pod frame rate / bus load (`pcb-bringup` Phase 3 live; `firmware-bench-evidence.md`)

**Stage gate to advance:** each pod's CAN ID appears at the expected steady rate and the
measured bus load is well under capacity. Bus bitrate is **500 kbit/s** (CNF `0x00/0xB1/0x05`,
`BENCH_TESTS.md` §7). Firmware TX is driven off the **1 kHz tick** (`main.c` `tick_1khz`;
`firmware-bench-evidence.md` "~1 kHz per pod"). Capture with `candump can0` (after
`ip link set can0 up type can bitrate 500000`) or PCAN-View over a fixed 10 s window.

| # | What to capture | Gate (pass window) | Actual |
|---|-----------------|--------------------|--------|
| E4.1 | Per-ID frame rate over **10 s** (`candump`, count frames for each `0x100+node_id`, ÷10) | target ~**1000 fps** per pod (1 kHz tick); acceptable floor **TBD-needs-board** (set after measuring real loop/TX timing) | per-ID rate = `___` fps (10 s count = `___`; ID = `___`; log: `___`) |
| E4.2 | Inter-frame interval distribution per ID | ≈ **1 ms** mean at 1 kHz; jitter budget **TBD-needs-board** | mean Δt = `___` ms · p99 Δt = `___` ms |
| E4.3 | Bus load = (total bus bits/s) ÷ 500 000 | well under capacity; a single ~135-bit 8-byte std frame @ 1 kHz ≈ **27% of 500 kbit/s** per pod (~135 kbit/s incl. stuffing/overhead) — record measured % | bus load = `___` % of 500 kbit/s (N pods = `___`) |
| E4.4 | Error/overload frame count over the 10 s window | **0** error frames expected on a healthy terminated bus | error frames = `___` |

**Failure tree (name most-likely first):** no frames / error frames ⇒ **bitrate or oscillator
mismatch** (most common: CNF computed for the wrong crystal), then **missing 120 Ω termination**
(E1.5 must read ~60 Ω), then TX/RX swapped to the SN65HVD230, then ground offset between boards
(`pcb-bringup` Phase 3). Rate far below 1 kHz ⇒ loop stalls / SPI retries raising
**`ST_SPI_FAULT`** in byte[6].

---

## E5 — Per-pod capture fill-in block (`firmware-bench-evidence.md` §"How to capture")

**One block per pod.** Decode one captured schema-v1 frame and record every field; compare
against the golden frames in `docs/bench/firmware-bench-evidence.md` §4 / `BENCH_TESTS.md` §4.
Schema v1 (root `CLAUDE.md`, **frozen**): `[0:1] raw_adc u16 LE`, `[2:3] millideg i16 LE`,
`[4] node_id`, `[5] chain_index`, `[6] status_flags`, `[7] checksum = XOR(bytes 0..6)`.

```text
Pod ____ capture
  captured CAN ID .......... 0x____      gate: == 0x100 + node_id  (root CLAUDE.md schema v1)
  DLC ...................... ____          gate: == 8 (INHABIT_DLC)
  payload byte[0:1] raw_adc  0x__ 0x__    -> ____ (LE u16, 0..4095)   [E2 cross-check]
  payload byte[2:3] millideg 0x__ 0x__    -> ____ (LE i16)
  payload byte[4] node_id .. 0x__         gate: matches assigned node_id
  payload byte[5] chain_index 0x__        gate: matches physical chain position (E6)
  payload byte[6] status_flags 0x__       gate: ST_NOT_ENUMERATED (0x10) CLEAR post-enumerate
  payload byte[7] checksum . 0x__         gate: == XOR(byte0..byte6)  (recompute & confirm)
  source file / log ........ ____________________
  capture timestamp (UTC) .. ____________________
  scope / LA / candump ref . ____________________
```

**Failure tree (name most-likely first):** byte[7] ≠ XOR(0..6) ⇒ **bus corruption** (EMI /
termination) — `inhabit_unpack()` drops it, so persistent bad checksums show as **zero valid
frames** at the host (`BENCH_TESTS.md` §2.1). byte[5] differs from physical position ⇒ ENUM
problem (E6). ID ≠ `0x100+node_id` ⇒ node_id/codec mismatch.

---

## E6 — ENUM edge tolerances + full-chain-log acceptance (`pcb-bringup` Phase 4; `BENCH_TESTS.md` §2.6, §6.9)

**Stage gate (final):** in physical order, pod 0 advertises `chain_index 0`, pod 1 `chain_index 1`,
… (byte[5]), all with **`ST_NOT_ENUMERATED` (0x10) CLEAR**; reversing the cable order re-orders
the indices (`BENCH_TESTS.md` §2.6). Scope ENUM_OUT=**PA2** and ENUM_IN=**PA1** (root pin map).
ENUM timing from `enum.h`: `ENUM_DEBOUNCE_TICKS=10` (10 ms @ 1 kHz), `ENUM_OUT_DELAY_TICKS=5`
(5 ms), per-pod ~15 ms, 3-pod ~45 ms (`firmware-bench-evidence.md`).

| # | What to capture | Gate (pass window) | Actual |
|---|-----------------|--------------------|--------|
| E6.1 | Scope PA1 rising edge → debounce accept | stable HIGH ≥ **10 ms** (`ENUM_DEBOUNCE_TICKS=10` @ 1 kHz) before accept; glitches < that filtered | debounce observed = `___` ms |
| E6.2 | Scope: this pod's index assigned → **PA2 (ENUM_OUT) rising edge** | ~**5 ms** after assign (`ENUM_OUT_DELAY_TICKS=5`); record measured | assign→ENUM_OUT = `___` ms |
| E6.3 | Scope: pod N PA2 rising edge → pod N+1 claims next index | **ENUM_OUT→next-index** latency; budget ~per-pod **~15 ms** (debounce+delay); exact edge tolerance **TBD-needs-board** | ENUM_OUT→next index = `___` ms |
| E6.4 | Full-chain CAN log, **N pods @ ~1 kHz over T seconds** | expected frames ≈ **N × 1000 × T**; record captured vs expected | N = `___` · T = `___` s · expected = `___` · captured = `___` |
| E6.5 | Dropped-frame fraction over the window | **dropped ≤ TBD-needs-board %** (set acceptance from a clean baseline; corrupt frames are dropped by checksum, E5) | dropped = `___` % |
| E6.6 | Inter-frame jitter p99 across the chain log | **jitter_p99 ≤ 2 ms** (acceptance target) | jitter_p99 = `___` ms |
| E6.7 | Count frames with `status_flags & 0x10` (ST_NOT_ENUMERATED) **after** enumeration completes | **0** frames (every enumerated pod must clear the bit; `firmware-bench-evidence.md` "must be CLEAR") | count = `___` |
| E6.8 | Reverse cable order, re-capture chain_index sequence | indices follow **physical** order, not node_ids (`BENCH_TESTS.md` §2.6) | reversed indices = `___` (log: `___`) |

**Failure tree (name most-likely first):** all pods report `chain_index 0` / `ST_NOT_ENUMERATED`
never clears ⇒ **ENUM_IN not seen** — broken/floating ENUM wire (PA1 pull-down means a
disconnected first pod reads de-asserted and never enumerates), or the FSM not ticked
(`pcb-bringup` Phase 4, `BENCH_TESTS.md` §2.6). Both pods claim index 0 ⇒ ENUM_IN wiring or a
state-machine race — add a settle delay and re-read. chain_index gap (0, 2, no 1) ⇒ pod 1 not
hearing pod 0 on CAN ⇒ **termination / transceiver** (back to E1.5 / E4).

---

## Stage-gate summary (do not advance until each is met on instruments)

| Stage | Advance only when | Most-likely failure if it fails |
|-------|-------------------|---------------------------------|
| E1 power | rails in window, idle < hard-stop, CANH-CANL ~60 Ω | short / backwards part (high current at limit) |
| E2 encoder | clean monotonic A0 ramp, span ~full scale, OOB window defined | magnet alignment / distance |
| E3 /INT loopback | CANSTAT=0x80 after reset; PB6 falls on TX, returns high | SPI wiring / 16 MHz crystal not oscillating |
| E4 live CAN | per-ID ~1 kHz, bus load sane, 0 error frames | bitrate/osc mismatch, then missing 120 Ω termination |
| E5 capture | every field decodes; byte[7]==XOR(0..6) | bus corruption (EMI / termination) |
| E6 chain/ENUM | indices follow physical order; 0x10 clear; jitter_p99 ≤ 2 ms | ENUM wiring (ENUM_IN not seen) |

All measured values above are **HARDWARE-BLOCKED** until a Rev-A board is on the bench. After
filling any template, append the result + artifact reference to `docs/bringup-log.md`
(`pcb-bringup` skill: "a bring-up you didn't log is a bring-up you'll redo").
