# firmware/ — Rev-A STM32C011 joint node

Scope: the embedded C that runs on each joint pod. Inherits all rules from root CLAUDE.md.

## Layout (target)
```
firmware/
  src/        main.c, can.c, encoder.c, enum.c, status.c
  inc/        headers mirroring src/
  drivers/    STM32 HAL/LL, MCP2515 driver
  Core/       CubeMX-generated (regenerate, never hand-edit by hand outside USER CODE blocks)
  test/       host-side unit tests for pure logic (filtering, packing, checksum)
```

## Hard rules
- No `malloc`/`free` after init. Static allocation only.
- No blocking calls (`HAL_Delay`, busy SPI) inside ISRs. ISRs set flags; main loop acts.
- Encoder: oversample + filter ADC (median-of-N or IIR) before publishing. Raw and filtered
  both available for debugging.
- Every outbound CAN frame follows schema v1 in root CLAUDE.md. Compute byte 7 checksum.
- On any fault (SPI timeout, ADC out of range, CAN error), set the matching `status_flags`
  bit and keep the loop alive. Never silently hang.
- MCP2515 /INT is on **PB6** (confirmed against schematic): active-low, EXTI line 6,
  falling-edge. The EXTI ISR only sets `flag_can_int`; no SPI/blocking in the ISR.

## Bring-up order (don't skip)
power → clocks → GPIO → ADC (encoder) → SPI → MCP2515 init → CAN TX → ENUM → CAN RX.
Validate each stage with a scope/logic analyzer before moving on. See skill `pcb-bringup`.

## Definition of done for a firmware change
Builds clean (no new warnings) · logic unit-tested host-side · checksum verified ·
status_flags exercised · diff reviewed by `embedded-reviewer` agent.
