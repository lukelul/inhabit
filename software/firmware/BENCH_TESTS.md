# Inhabit Rev-A — Firmware Bench Test Guide

> Purpose: make the firmware **instantly validatable** the moment the Rev-A PCB arrives.
> Every host-buildable test below proves something in *software*; this guide maps each one
> to the **physical board evidence** (scope / logic analyzer / serial / CAN sniffer) that
> confirms the same thing on the bench. Lead with the failure mode; name how each stage
> fails and how the firmware detects it (`status_flags`).
>
> Frozen contracts referenced here (`can_frame.h`/`.c` schema v1) are **used, never edited**.
> All expected CAN bytes in this doc were **derived with the frozen codec**, not hand-computed
> (see [§4](#4-golden-frames-3-pod-chain-derived-from-the-frozen-codec)).

---

## 0. TL;DR — one command, green before you touch hardware

From the repo root (Windows PowerShell):

```powershell
pwsh scripts/verify.ps1
```

or POSIX:

```sh
sh scripts/verify.sh
```

To run *only* the firmware C suite exactly as the Makefile / CI does:

```sh
cd firmware/test
make            # builds + runs all 7 host targets, then compiles main.c clean
```

The **fullest** check is `scripts/verify.sh` (POSIX) / `scripts/verify.ps1` (Windows) from
the repo root: those build + run all 7 firmware C targets, compile `main.c` clean, **and**
run the host pytest suite. Use the verify scripts before bring-up; `make` is the firmware-only
subset.

Build flags are uniform: `gcc -Wall -Wextra -std=c11 -I../inc` (driver tests add `-I../drivers`).
Expected output (all green):

```
firmware can_frame: 5000 frames round-trip + bitflip OK
firmware calib: linear conversion + CAN telemetry round-trip OK
example frame id=0x103 data=BC 0A 39 30 03 01 00 BD
mcp2515 loopback: 2000 frames TX->RX byte-identical + codec valid OK
can_health: fault-bit clear/set policy OK (SPI no longer sticky)
firmware enum: 11 tests passed
firmware enum-integrate: 3 tests passed
firmware bench-3pod: 3 tests passed
```

If this is **not** green, do not power the board — fix the logic first.

---

## 1. Module map (what proves what)

Confirmed against source and the GitNexus call graph (`main` → `can_rx_service` →
`{mcp2515_poll_recv, inhabit_unpack, can_health_apply, enum_notify_peer}`;
`main` → `can_tx_tick` → `{mcp2515_send_std, mcp2515_poll_tx_done, inhabit_can_id, inhabit_pack}`;
`main` → `enum_tick` → `{enum_step, enum_out_drive}`).

| Module | File(s) | Pure logic? | Proves in software | Physical thing it stands in for |
|--------|---------|-------------|--------------------|---------------------------------|
| CAN codec (schema v1, **frozen**) | `inc/can_frame.h`, `src/can_frame.c` | yes | pack/unpack/XOR checksum round-trip + bitflip rejection | every byte that ever leaves the pod on CANH/CANL |
| Calibration | `inc/calib.h`, `src/calib.c` | yes | linear ADC→millideg fit + separate calib telemetry frame (ID `0x300+id`) | MT6701 analog → real joint angle |
| MCP2515 driver | `inc/mcp2515.h`, `drivers/mcp2515.c` | mostly (SPI abstracted) | reset→config→CNF→loopback, TX/RX round-trip, fault injection | SPI bus + CAN controller silicon |
| CAN health policy | `inc/can_health.h`, `src/can_health.c` | yes | fault-bit set/clear policy (non-sticky) | how the pod reports SPI/CAN faults on the wire |
| ENUM FSM | `inc/enum.h`, `src/enum.c` | yes | debounce, index claim = max(peer)+1, sentinel/overflow guards, ISR-safe latch | the ENUM_IN/ENUM_OUT daisy-chain ordering |
| Main loop / pin glue | `src/main.c` | no (target HAL/LL) | compiles clean host-side; ISR sets flag only | the actual board: clocks, GPIO, ADC, SPI, EXTI |

`src/main.c` is the only file that touches silicon directly. It is **structured so all
hard logic lives in the host-tested modules** above; `main.c` is thin pin glue + the
EXTI ISR (which does one thing: `flag_can_int = 1`). The TODO stubs in `main.c`
(`spi_transfer`, `encoder_read_raw`, clock/ADC/SPI `board_init`) are the only code that
*cannot* be proven host-side — they are the bring-up work [§6](#6-bring-up-order-on-the-bench).

---

## 2. Test → physical evidence matrix

Each row: the host test, what it proves in software, and the **board evidence** that
confirms the same property on the bench. "How it fails on HW / detection" is the
fail-loud story.

### 2.1 `test_can_frame` — CAN codec (frozen schema v1)
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc test_can_frame.c ../src/can_frame.c -o t && ./t`
- **Proves (software):** 5000 random states pack→unpack identically; ID = `0x100+node_id`;
  a single-bit corruption is rejected by the XOR checksum.
- **Physical evidence:** capture a live frame with a CAN sniffer (e.g. `candump can0`,
  PCAN-View, or a logic analyzer with a CAN decoder on the SN65HVD230 TX line) and confirm
  the 8 payload bytes decode to the [golden frames in §4](#4-golden-frames-3-pod-chain-derived-from-the-frozen-codec).
  Byte 7 must equal the XOR of bytes 0..6 on the wire.
- **HW failure / detection:** EMI / termination errors corrupt bytes mid-flight. The
  receiver's `inhabit_unpack()` returns `false` on a bad checksum, so a corrupted frame is
  *dropped*, not trusted. A persistently bad bus shows up as zero valid frames at the host.

### 2.2 `test_calib` — encoder calibration + calib telemetry
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc test_calib.c ../src/calib.c -o t && ./t`
- **Proves (software):** `inhabit_calib_adc_to_millideg` applies slope/intercept correctly;
  `inhabit_calib_fit_linear` recovers the line from 3 samples; the calib telemetry frame
  (ID `0x300+node_id`, separate from schema v1) round-trips with its own XOR checksum.
- **Physical evidence (ADC + magnet):** with the MT6701 magnet mounted, rotate the joint to
  two or three **known mechanical angles** (e.g. 0°, 90°, 180° against a printed protractor /
  index jig). Log `angle_raw_adc` at each, fit, then confirm a swept angle reads back within
  tolerance. Probe the MT6701 analog OUT → STM32 **A0** with a scope to confirm a clean,
  monotonic ramp across a full rotation (no flat spots = magnet centered / in range).
- **HW failure / detection:** magnet off-center / too far → nonlinear or clipped ADC ramp.
  Firmware raises `ST_MAGNET_OOB` when the raw value leaves the valid window, and
  `ST_CALIB_INVALID` if no good fit exists; `ST_ADC_FAULT` if the ADC read itself fails.
  (These bits are defined in `can_frame.h`; wiring the ADC window check is part of the
  `encoder_read_raw` TODO in `main.c`.)

### 2.3 `test_mcp2515` — SPI + CAN controller in **loopback**
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc -I../drivers test_mcp2515.c ../drivers/mcp2515.c ../src/can_frame.c -o t && ./t`
- **Proves (software):** CNF1/2/3 = the documented **500 kbit/s @ 16 MHz** constants
  (`0x00 / 0xB1 / 0x05`); SID encode/decode reversible for all 11-bit IDs; reset reports
  Config mode; LOOPBACK is *confirmed via CANSTAT* (never assumed); a frozen-codec frame
  loaded into TXB0 round-trips byte-identical into RXB0; `CANINTE` enables RX0/RX1 only (no
  TXnIE, no ERRIE/MERRE for the loopback milestone — see the rationale in `mcp2515.h`);
  fault injection surfaces `MCP_ERR_SPI` / `MCP_ERR_TX_TIMEOUT` / `MCP_ERR_RX_TIMEOUT`.
- **Physical evidence (SPI):** logic analyzer on **PA5=SCK, PA7=MOSI, PA6=MISO, PA4=CS**.
  On `mcp2515_init()` you should see, CS-framed: `0xC0` (RESET), then `READ 0x0E` returning
  `0x80` (CONFIG mode), then `WRITE` to CNF1/2/3 (`0x2A←0x00`, `0x29←0xB1`, `0x28←0x05`),
  `WRITE CANINTE 0x2B←0x03`, then a `BIT_MODIFY` of CANCTRL to `0x40` (LOOPBACK) and a
  `READ CANSTAT` returning `0x40`. **This is the single most important board check** — if
  the READ of CANSTAT after RESET is not `0x80`, the MCP2515 isn't talking (wrong CS, no
  16 MHz crystal, swapped MISO/MOSI).
- **Physical evidence (loopback CAN, no bus needed):** still in `MCP_MODE_LOOPBACK`, a TX
  on TXB0 sets RX0IF internally and pulls **/INT (PB6) low** — scope PB6 and watch it fall,
  then return high after `can_rx_service()` clears RX0IF. This proves the whole SPI↔CAN↔EXTI
  chain **without a transceiver or a second board**.
- **HW failure / detection:** any SPI timeout → `mcp2515_*` returns `MCP_ERR_SPI` →
  `board_init`/`can_tx_tick` sets `ST_SPI_FAULT`. Mode not confirmed → `MCP_ERR_MODE` →
  `ST_CAN_FAULT`. The loop never hangs: every poll is bounded by an explicit budget.

### 2.4 `test_can_health` — fault-bit policy
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc -I../drivers test_can_health.c ../src/can_health.c ../src/can_frame.c -o t && ./t`
- **Proves (software):** a healthy round-trip clears **both** `ST_SPI_FAULT` and
  `ST_CAN_FAULT` (non-sticky — one transient glitch can't poison status forever); real
  faults latch loud; unrelated bits (`ST_NOT_ENUMERATED`, `ST_ADC_FAULT`) are preserved.
- **Physical evidence:** on the bench, yank/short SPI or disconnect the bus briefly and
  watch the `status_flags` byte (byte 6) in the live CAN stream flip the corresponding bit,
  then **clear on its own** once the link recovers. This is the bench proof that faults are
  observable *and* recoverable from the host.
- **HW failure / detection:** this *is* the detection layer. If `status_flags` never changes
  under an induced fault, the policy isn't wired into `can_tx_tick`/`can_rx_service`.

### 2.5 `test_enum` — ENUM state machine (unit)
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc test_enum.c ../src/enum.c ../src/can_frame.c -o t && ./t`
- **Proves (software):** 11 cases — debounce rejects glitches; lone pod claims index 0;
  peer indices fold to `max+1`; the reserved `0xFF` sentinel is rejected (corrupt frame
  can't reset us to 0); a full chain (`0xFE`) faults loud instead of wrapping; the ISR→loop
  latch only takes effect on `enum_step`; post-DONE peer traffic is a no-op.
- **Physical evidence (ENUM line):** scope/LA on **ENUM_OUT = PA2** and **ENUM_IN = PA1**.
  First pod (host asserts its ENUM_IN, or PA1 pulled high) should: hold PA2 **low**, debounce,
  claim index 0, then after the delay drive **PA2 high** — watch the rising edge. The next
  pod's PA1 should follow that edge. A pod that never sees ENUM_IN keeps PA2 low and stays
  un-enumerated.
- **HW failure / detection:** a bouncy/floating ENUM line → the debounce (`ENUM_DEBOUNCE_TICKS`)
  filters it; PA1 has a pull-down so a disconnected first-in-chain pod reads de-asserted and
  never falsely enumerates. An un-indexed pod keeps `ST_NOT_ENUMERATED` set on the wire.

### 2.6 `test_enum_integrate` — ENUM → state → schema-v1 frame
- **Build/run:** `gcc -Wall -Wextra -std=c11 -I../inc test_enum_integrate.c ../src/enum.c ../src/can_frame.c -o t && ./t`
- **Proves (software):** the FSM's assigned `chain_index` actually reaches **byte 5** of the
  outbound schema-v1 frame (regression guard against `enum.c` being orphaned from `main.c`);
  pre-enumeration frames advertise `ST_NOT_ENUMERATED` so nothing trusts an un-indexed pod.
- **Physical evidence (2+ board chain):** power a 2-board daisy chain. On the host CAN log,
  pod 0 must transmit `chain_index = 0` (frame byte 5 = `0x00`) and pod 1 `chain_index = 1`
  (byte 5 = `0x01`) — and the CAN IDs (`0x100`, `0x101`) must match `0x100 + node_id`. Reverse
  the cable order and the indices must follow the *physical* order, not the node IDs.
- **HW failure / detection:** if byte 5 is stuck at 0 on every pod, ENUM isn't propagating
  (broken ENUM wire, or the FSM not ticked) — and `ST_NOT_ENUMERATED` will still be set,
  so the host sees an un-ordered chain rather than a silently wrong one.

---

## 3. Coverage gap callout (honest)

`scripts/verify.sh` and `scripts/verify.ps1` build and run **all seven** firmware C targets
(`test_can_frame`, `test_calib`, `test_mcp2515`, `test_can_health`, `test_enum`,
`test_enum_integrate`, `test_bench_3pod`) and then compile `src/main.c` clean — that is the
fullest firmware check, so prefer them before bring-up. The `firmware/test/Makefile` previously
**omitted `test_bench_3pod`**; it now builds all seven as well, matching the verify scripts.
`main.c`'s target-only code (HAL/LL clock/ADC/SPI init, the EXTI register config) is **not**
unit-testable host-side by construction — it is validated on the bench in [§6](#6-bring-up-order-on-the-bench),
not in CI. That separation is intentional: pure logic is proven before the board exists; pin
config is proven with a scope after it arrives.

---

## 4. Golden frames: 3-pod chain (illustrative — derived from the frozen codec)

> **Two golden-frame tables, two purposes.** The table below is the **illustrative** wire-format
> reference (hand-chosen plausible angles, `node_id == chain_index`). The **canonical harness**
> is `firmware/test/test_bench_3pod.c`, which compiles the frozen codec, drives the ENUM FSM,
> and asserts its own golden bytes at runtime (different scenario: `node_id = chain_index + 1`,
> IDs `0x101..0x103`). When in doubt, the compiled harness is the source of truth — this table
> only illustrates the format with rounder numbers.

These are the **exact bytes** a freshly enumerated 3-pod chain puts on the bus, with
plausible angles. They were generated by compiling `src/can_frame.c` (the frozen codec) and
calling `inhabit_pack()` — and independently reproduced **byte-identical** by the host
Python codec (`host/inhabit_can/codec.py`), confirming the cross-implementation contract.
Do **not** hand-edit; regenerate with the snippet in [§5](#5-regenerating-the-golden-frames) if the codec ever changes (it should not — it's frozen).

Scenario: chain seeded by the host at index 0, all pods healthy and enumerated
(`status_flags = 0x00`), `node_id == chain_index`. Layout (LE): `[0:1] raw_adc`,
`[2:3] millideg (i16)`, `[4] node_id`, `[5] chain_index`, `[6] status_flags`,
`[7] XOR of bytes 0..6`.

| Pod | CAN ID | raw_adc | millideg | node_id | chain_index | status | Payload bytes (hex) | byte7 = XOR(0..6) |
|-----|--------|---------|----------|---------|-------------|--------|---------------------|--------------------|
| 0 | `0x100` | 1365 | +12000 (12.000°) | 0 | 0 | `0x00` | `55 05 E0 2E 00 00 00 9E` | `0x9E` |
| 1 | `0x101` | 2048 | −4500 (−4.500°) | 1 | 1 | `0x00` | `00 08 6C EE 01 01 00 8A` | `0x8A` |
| 2 | `0x102` | 3000 | +30000 (30.000°) | 2 | 2 | `0x00` | `B8 0B 30 75 02 02 00 F6` | `0xF6` |

Byte-by-byte for pod 1 (worked example, shows LE + signed handling):
- `raw_adc = 2048 = 0x0800` → bytes `00 08`
- `millideg = -4500` → `int16` two's complement `0xEE6C` → bytes `6C EE`
- `node_id = 0x01`, `chain_index = 0x01`, `status_flags = 0x00`
- checksum = `00 ^ 08 ^ 6C ^ EE ^ 01 ^ 01 ^ 00 = 0x8A`

On the bench, point a CAN decoder at the bus and these three frames are exactly what a
healthy 3-pod chain must produce. A single different byte (other than legitimately changing
angle/status) means corruption or a codec mismatch.

One more known-good single frame, emitted by `test_mcp2515` itself for the host bridge test
(`raw=0x0ABC, millideg=12345, node_id=3, chain_index=1, status=0x00`):

```
id=0x103 data=BC 0A 39 30 03 01 00 BD
```

---

## 5. Regenerating the golden frames

The frozen codec is the source of truth; never hand-compute these. To reproduce §4:

```sh
cd firmware
cat > /tmp/derive.c <<'EOF'
#include "can_frame.h"
#include <stdio.h>
int main(void){
    inhabit_state_t pods[3] = {
        { 1365,  12000, 0, 0, 0x00 },
        { 2048,  -4500, 1, 1, 0x00 },
        { 3000,  30000, 2, 2, 0x00 },
    };
    for (int i = 0; i < 3; ++i) {
        uint8_t f[INHABIT_DLC];
        inhabit_pack(&pods[i], f);
        printf("id=0x%03X data=", inhabit_can_id(pods[i].node_id));
        for (int b = 0; b < (int)INHABIT_DLC; ++b) printf("%02X ", f[b]);
        printf("\n");
    }
    return 0;
}
EOF
gcc -Wall -Wextra -std=c11 -Iinc /tmp/derive.c src/can_frame.c -o /tmp/derive && /tmp/derive
```

Cross-check against the host Python codec (must be byte-identical):

```sh
cd host
python -c "
from inhabit_can.codec import State, encode_state
for p in (State(1365,12000,0,0),State(2048,-4500,1,1),State(3000,30000,2,2)):
    cid,d=encode_state(p); print(f'id=0x{cid:03X} data='+' '.join(f'{b:02X}' for b in d))
"
```

---

## 6. Bring-up order on the bench

> Blank fill-in evidence templates + pass/fail thresholds for each stage below (power, ADC sweep,
> /INT, frame rate, per-pod capture, ENUM/full-chain) live in `docs/bench/EVIDENCE_TEMPLATES.md`
> (HARDWARE-BLOCKED for the measured numbers).

Follows `firmware/CLAUDE.md` ("don't skip") and the root pin map. Validate each stage with a
scope/LA **before** moving to the next. Pin map (Rev-A, root `CLAUDE.md` — single source of
truth): `ENC_ADC=A0, ENUM_IN=PA1, ENUM_OUT=PA2, MCP2515 /INT=PB6 (EXTI line 6, falling),
CS=PA4, SCK=PA5, MISO=PA6, MOSI=PA7`.

1. **Power** — confirm 5V5 in and the regulated 3V3 logic rail before connecting anything
   to the MCU. Wrong rail order can latch up the STM32.
2. **Clocks** — flash a minimal blink / heartbeat; confirm the STM32 runs and the MCP2515
   **16 MHz crystal** oscillates (scope OSC1/OSC2). No crystal → MCP2515 is dead silicon and
   every SPI read of CANSTAT returns garbage.
3. **GPIO** — toggle PA2 (ENUM_OUT) and read PA1 (ENUM_IN); confirm levels and the PA1
   pull-down.
4. **ADC (encoder)** — implement `encoder_read_raw` (oversample + median/IIR filter per house
   rule). Scope MT6701 analog OUT on A0; rotate the magnet and confirm a clean monotonic
   ramp. Cross-check against `test_calib` math. Out-of-window → set `ST_MAGNET_OOB`/`ST_ADC_FAULT`.
5. **SPI** — implement `spi_transfer` (CS-framed full-duplex on SPI1, bounded TXE/RXNE wait,
   non-zero return on timeout). LA on PA4–PA7. **Gate: a `READ CANSTAT` after RESET returns
   `0x80` (Config mode).** Until that passes, nothing downstream is trustworthy.
6. **MCP2515 init** — `mcp2515_init(&io, MCP_MODE_LOOPBACK)`. Confirm CNF1/2/3 writes
   (`0x00/0xB1/0x05`) and CANSTAT reads back `0x40` (LOOPBACK). Failure latches
   `ST_SPI_FAULT`/`ST_CAN_FAULT`; the loop stays alive.
7. **CAN TX (loopback)** — let `can_tx_tick` send a frozen-codec frame. Scope **PB6**: /INT
   must fall when RX0IF sets. This proves SPI→CAN→EXTI end-to-end **with no transceiver**.
8. **CAN RX (loopback)** — `can_rx_service` reads RXB0, verifies the echo (id+len+checksum)
   against `g_tx_id`, and `can_health_apply` **clears** the fault bits on a healthy round-trip.
9. **ENUM** — connect a 2-board chain. Scope the ENUM_OUT→ENUM_IN handshake; confirm pod 0
   transmits `chain_index 0` and pod 1 `chain_index 1` on the host CAN log ([§2.6](#26-test_enum_integrate--enum--state--schema-v1-frame), [§4](#4-golden-frames-3-pod-chain-derived-from-the-frozen-codec)).
10. **Live bus** — only after loopback is proven: switch MCP2515 to `MCP_MODE_NORMAL`, add the
    SN65HVD230 transceiver, 120 Ω termination at both ends, and the SM24CANB TVS. Re-enable
    `ERRIE|MERRE` on `/INT` **only together with** an ERRIF/MERRF clear path + level-recovery
    sweep (see the standing note in `mcp2515.h` — otherwise the first bus error latches /INT
    low forever and the RX interrupt dies silently).

---

## 7. Flash / serial / CAN tooling quick reference

- **Flash (STM32C011):** SWD via ST-LINK — `STM32_Programmer_CLI -c port=SWD -w firmware.elf -rst`,
  or `openocd -f interface/stlink.cfg -f target/stm32c0x.cfg -c "program firmware.elf verify reset exit"`.
- **Serial (optional debug):** if a UART heartbeat is added, `115200 8N1`; keep it out of the
  hot path / ISRs (house rule).
- **CAN sniff:** USB-CAN (`candump can0` after `ip link set can0 up type can bitrate 500000`),
  PCAN-View, or a logic analyzer with a CAN decoder on the transceiver TX line. Bitrate is
  **500 kbit/s** (matches the CNF constants).
- **SPI/edge probing:** any 8-channel LA on PA4–PA7 (SPI) and PB6 (/INT) covers steps 5–8.

---

## 8. How each stage fails on hardware, and how the firmware detects it (summary)

| Stage | Plausible HW failure | Firmware detection |
|-------|----------------------|--------------------|
| Power | wrong rail order, brownout | (external) — confirm rails before connect |
| Clock | MCP2515 crystal not oscillating | CANSTAT read ≠ `0x80` after RESET → `MCP_ERR_MODE`/`ST_CAN_FAULT` |
| ADC | magnet off-center, open analog line | window check → `ST_MAGNET_OOB`; read fail → `ST_ADC_FAULT` |
| SPI | swapped MISO/MOSI, bad CS, timeout | bounded poll → `MCP_ERR_SPI` → `ST_SPI_FAULT` |
| CAN ctrl | mode not entered | CANSTAT mismatch → `MCP_ERR_MODE` → `ST_CAN_FAULT` |
| CAN TX/RX | bus error, no echo | TX/RX timeout → `ST_CAN_FAULT`; bad checksum echo dropped |
| ENUM | floating/broken ENUM line | debounce + PA1 pull-down; un-indexed → `ST_NOT_ENUMERATED` on wire |
| Bus integrity | EMI / missing termination | per-frame XOR checksum → corrupt frame rejected by `inhabit_unpack` |

Everything fails **loud** via `status_flags` on the wire and the loop never hangs — that is
the whole point of the design, and the bench tests above are how you confirm it on silicon.
