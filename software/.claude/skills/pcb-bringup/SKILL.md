---
name: pcb-bringup
description: Use when physically bringing up the Rev-A board or debugging hardware — power-on, shorts checks, flashing, verifying encoder/SPI/CAN on a scope, two-board chain, or diagnosing why a stage fails. Triggers on "bring up", "power on", "no CAN", "short", "scope", "logic analyzer", "doesn't enumerate", "flash".
---

# Rev-A Board Bring-Up

Bring up **one stage at a time**. Do not proceed until the current stage is verified on a
scope/logic analyzer/CAN sniffer. This skill is a guided procedure + failure tree.

## Phase 1 — Power
1. **Before power:** DMM continuity check between 5V5 / VCC_BUS / 3V3 and GND — must be open.
   Inspect bottom-side PCBA orientation (root CLAUDE.md flags this as a risk).
2. Power via bench supply with **current limit** (start ~100 mA). Note inrush.
3. Verify VCC_BUS / 3V3 rail with DMM, then scope for ripple. STM dev module powered.
- *Fault: high current at limit* ⇒ short or backwards part. Power off, reinspect, thermal-cam.

## Phase 2 — MCU + Encoder
4. Flash a blink/UART-alive image via SWD. Confirm the chip is alive and clocks are right.
5. Read ENC_ADC (A0). Rotate the magnet — angle should sweep monotonically.
- *Fault: flat/noisy ADC* ⇒ magnet alignment/distance, MT6701 MODE pin, or ADC channel wrong.

## Phase 3 — CAN bring-up
6. **MCP2515 in loopback first** (no transceiver needed): prove SPI + framing.
   - Scope SCK; verify CS toggles; read a known register (e.g. CANSTAT) — wrong value ⇒ SPI
     wiring/mode (CPOL/CPHA) or wrong CS pin.
7. Verify 16 MHz crystal actually oscillates (scope OSC1, or read time-base behavior).
8. Configure bitrate **for 16 MHz osc**. Exit to Normal mode; confirm via CANSTAT.
9. Transmit one frame; capture on a USB-CAN sniffer. Check CANH/CANL differential on scope
   (recessive ~2.5 V both, dominant split ~3.5/1.5 V). Termination = 120 Ω at bus ends.
- *Fault: no frames / error frames* ⇒ bitrate/osc mismatch (most common), missing termination,
  TX/RX swapped to transceiver, or ground offset between boards.

## Phase 4 — Two-board daisy chain + ENUM
10. Share the 5-wire bus across two boards. Both should TX their state frames.
11. Seed ENUM from host/first node; verify board 0 → chain_index 0 asserts ENUM_OUT →
    board 1 → chain_index 1. Watch the ENUM line on a scope.
- *Fault: both claim index 0* ⇒ ENUM_IN not seen (wiring), or state machine races — add a
  settle delay and re-read.

## Logging
After each stage, append result + scope screenshot reference to `docs/bringup-log.md`.
A bring-up you didn't log is a bring-up you'll redo.
