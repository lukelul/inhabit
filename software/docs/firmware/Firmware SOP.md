# Firmware Development and Validation SOP

## How to Add a Firmware Module

1. Create `firmware/src/<module>.c` and `firmware/inc/<module>.h`
2. Keep the module pure (no HAL dependencies if possible) for testability
3. Follow house rules: no heap after init, no blocking in ISRs, fail loud via status_flags
4. Add a host-side test: `firmware/test/test_<module>.c`
5. Update `scripts/verify.ps1` to compile and run the new test
6. Wire the module into `main.c` (flags/polling, never direct ISR calls)

---

## How to Add C Tests

1. Create `firmware/test/test_<module>.c`
2. Include the module header and source
3. Write test functions, call them from `main()` in the test file
4. Use `assert()` for test conditions
5. Add the build+run line to `scripts/verify.ps1`:

```powershell
& $cc -Wall -Wextra -std=c11 -I../inc test_<module>.c ../src/<module>.c -o "$bin/t_<module>.exe"
if($LASTEXITCODE){throw "build <module>"}
& "$bin/t_<module>.exe"
if($LASTEXITCODE){throw "run <module>"}
```

6. Run `pwsh scripts/verify.ps1` to verify

---

## How to Run Verification

```powershell
pwsh scripts/verify.ps1
```

This compiles and runs all C tests (can_frame, calib, mcp2515, can_health, enum) plus Python tests.

---

## How to Preserve Frozen CAN Schema

- **Never edit** `firmware/inc/can_frame.h` or `firmware/src/can_frame.c`
- New telemetry = new CAN ID block (e.g., calibration uses `0x300 + node_id`)
- New payload fields = new struct + new pack/unpack functions in a new file
- Keep existing byte layout in v1 schema unchanged

---

## How to Validate MCP2515 Changes

1. Run `test_mcp2515.c` (mock SPI, loopback)
2. If changing register addresses or init sequence, verify against datasheet DS20001801
3. If changing bit timing (CNF registers), recalculate for 16 MHz crystal at desired bitrate
4. On hardware: verify in loopback mode first, then normal mode
5. Scope SPI bus (CS, SCK, MISO, MOSI) to confirm signal integrity

---

## How to Validate Calibration Changes

1. Run `test_calib.c` -- tests linear fit and telemetry pack/unpack
2. If changing calibration model (e.g., nonlinear), update `calib.h` types
3. Verify telemetry CAN ID block doesn't collide with schema v1 (0x100+) or future blocks
4. On hardware: collect known-angle samples, verify fit quality

---

## How to Validate ENUM Changes

1. Run `test_enum.c` -- tests all state transitions, debounce, peer notification, overflow
2. Key invariants:
   - Post-ENUM_DONE: peer traffic is ignored (guard against late CAN frames)
   - Chain overflow (> 0xFE): stays un-enumerated
   - Debounce: 10 consecutive ticks before accepting ENUM_IN
   - ISR safety: `enum_notify_peer` uses single-word stores only
3. On hardware: test with 2+ boards, reset repeatedly to check ordering consistency

---

## How to Prepare for Hardware Testing

1. Build firmware: `gcc -Wall -Wextra -std=c11 firmware/src/*.c firmware/drivers/*.c -I firmware/inc -o firmware.elf` (or via CubeMX/Makefile for on-target)
2. Flash via ST-LINK
3. Connect scope/logic analyzer to SPI and CAN lines
4. Follow [[docs/hardware/bringup/Hardware Bring-Up SOP]] stage by stage

---

## Debugging: CAN Does Not Transmit

1. Check `ST_SPI_FAULT` in status_flags -- SPI communication to MCP2515 failing
2. Scope SPI: is CS toggling? Is SCK running? Is MISO returning data?
3. Read CANSTAT -- is MCP2515 in the expected mode (loopback or normal)?
4. Read CANINTF -- is RX0IF or ERRIF set?
5. Check TXB0CTRL -- is TXREQ stuck high?
6. Verify 16 MHz crystal is oscillating (probe crystal pins)
7. Check that `mcp2515_init()` returns `MCP_OK`

---

## Debugging: ADC Readings Are Wrong

1. Check analog connection from MT6701 OUT to PA0
2. Verify VCC supply to MT6701 (should be 3.3V or 5V per datasheet)
3. Check magnet presence and distance (~1-3mm above IC)
4. Read raw ADC values -- should sweep 0 to ~4095 over 360 degrees
5. If noisy: increase oversampling count, check for SPI/CAN switching noise coupling
6. If nonlinear: magnet not centered or wrong polarity (must be diametrically magnetized)

---

## Debugging: ENUM Order Is Wrong

1. Check ENUM_IN/ENUM_OUT wiring between pods
2. Verify Pod A ENUM_OUT connects to Pod B ENUM_IN (not reversed)
3. Check that ENUM_IN is actually going HIGH (measure with scope)
4. Verify CAN bus is working (peer observation depends on CAN frames)
5. Check debounce timing -- is ENUM_IN stable for 10+ ticks?
6. If both pods claim index 0: ENUM_OUT not reaching Pod B, or CAN peer frames not being received
7. Check `enum_notify_peer` is being called from CAN RX path
