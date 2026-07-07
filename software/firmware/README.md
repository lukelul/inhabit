# firmware/ — Rev-A STM32C011 joint node (C)

Skeleton. Implement the `TODO(firmware-engineer)` markers using the `stm32-firmware`,
`can-protocol`, and `pcb-bringup` skills. Read `firmware/CLAUDE.md` first.

- `inc/can_frame.h` + `src/can_frame.c` — CAN schema v1 codec (DONE, tested). Mirrors the
  Python codec in `host/inhabit_can/codec.py` byte-for-byte. **Don't fork it.**
- `src/main.c` — main-loop skeleton (flags set by ISRs, logic in loop).
- `test/` — host-side gcc test (no STM toolchain): `cd test && make`.

House rules: no heap after init, no blocking in ISRs, faults set `status_flags`, prove CAN in
loopback before live bus. MCP2515 /INT = PB6 (confirmed; EXTI line 6, falling edge).
