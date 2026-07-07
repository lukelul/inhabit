---
name: stm32-firmware
description: Use when writing, modifying, or debugging STM32C011 firmware for the Inhabit joint pod — encoder ADC reads, MCP2515 SPI/CAN bring-up, EXTI/ISR setup, status flags, or any bare-metal C on the Rev-A board. Triggers on "firmware", "STM32", "MCP2515", "SPI", "register", "ISR", "HAL", "CubeMX".
---

# STM32C011 Firmware (Inhabit joint pod)

## Before you write code
1. **Confirm the pin map** against `.claude/CLAUDE.md`. MCP2515 /INT = PB6 (confirmed; EXTI
   line 6, falling edge). For any other pin you are unsure of, check the schematic net first;
   if you cannot confirm, ask.
2. **Confirm the peripheral instance** (which SPI, which ADC channel, which EXTI line). The
   STM32C011 is small; don't assume peripherals that aren't bonded out.
3. Decide HAL vs LL. Use LL for the hot path (SPI/ADC) where determinism matters; HAL for setup.

## House rules (non-negotiable)
- No dynamic allocation after init. No blocking in ISRs. ISRs set flags; the main loop acts.
- Every CAN frame conforms to schema v1 (see can-protocol skill). Compute the byte-7 checksum.
- On fault, set the matching `status_flags` bit and keep the loop alive. Never hang silently.
- Filter encoder ADC noise (median-of-N or single-pole IIR) before publishing.

## MCP2515 bring-up checklist
- Crystal: 16 MHz. Set CNF1/CNF2/CNF3 for the target bitrate (e.g. 500 kbit/s) **for a 16 MHz
  osc specifically** — wrong osc assumption is the #1 CAN bug.
- Sequence: RESET cmd → wait → enter Config mode → set CNF + filters/masks → set TXB/RXB →
  set INT enables (CANINTE) → Normal mode. Verify mode via CANSTAT, don't assume.
- Loopback mode first (no bus needed) to prove SPI + framing before touching the transceiver.
- INT pin is active-low; configure EXTI on the confirmed pin, debounce in firmware not hardware.

## Encoder (MT6701 analog)
- Single-ended ADC on ENC_ADC (A0). Oversample (e.g. 16x) + filter.
- Map ADC counts → millidegrees with a calibration offset/scale stored in flash/config.
- Magnet alignment matters: out-of-range or non-monotonic readings ⇒ set a status bit.

## Skeleton main loop
```c
while (1) {
    if (flag_adc_ready)  { angle = filter(adc_read()); flag_adc_ready = 0; }
    if (flag_can_int)    { mcp2515_service(); flag_can_int = 0; }
    if (tick_1khz)       { pack_and_queue_can(angle, node_id, chain_index, status);
                           tick_1khz = 0; }
    enum_step();              // advance chain enumeration state machine
    status_publish_if_due();
}
```

## Definition of done
Builds with no new warnings · pure logic (filter, pack, checksum) unit-tested host-side ·
loopback CAN proven before live bus · status_flags exercised · small reviewable diff.
