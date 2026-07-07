# Hardware Test SOP

## Bench Test Flow

Follow this order. Do not skip stages.

| Stage | Test | Pass Criteria | Fail Action |
|-------|------|---------------|-------------|
| 1 | Visual inspection | No defects visible | Document, rework or reject |
| 2 | Continuity / shorts | No shorts on power or signal rails | Trace short before power-on |
| 3 | First power-on | 3.3V rail correct, current < limit | Investigate regulator/short |
| 4 | ADC test | Full-range sweep, linear, low noise | Check magnet, wiring |
| 5 | SPI test | MCP2515 register read/write correct | Check wiring, crystal |
| 6 | CAN test (loopback) | TX + RX round-trip, /INT works | Check MCP2515 config |
| 7 | CAN test (live bus) | Host sees pod frames | Check transceiver, termination |
| 8 | ENUM test (single) | Correct index assignment | Check GPIO, CAN |
| 9 | Multi-node test | Both pods ordered correctly | Check ENUM wiring |
| 10 | Logging test | Parquet round-trip passes | Check host software |

See [[docs/hardware/bringup/Hardware Bring-Up SOP]] for detailed per-stage instructions.

---

## First Power-On

- [ ] Current-limit power supply to 100 mA (adjust TBD based on measured quiescent)
- [ ] Apply 5V5 to power input
- [ ] Measure current draw (should be low, < TBD mA)
- [ ] Measure 3.3V rail (should be 3.3V +/- 5%)
- [ ] Check for hot components (regulator or IC getting warm = problem)

---

## ADC Test

- [ ] Place diametrically magnetized disc above MT6701
- [ ] Read raw ADC value (debug output)
- [ ] Rotate magnet through 360 degrees
- [ ] Verify ADC sweeps full range (~0 to ~4095)
- [ ] Check linearity at 0, 90, 180, 270 degree positions
- [ ] Note: noisy readings may need firmware filtering

---

## CAN Test

### Loopback Mode
- [ ] Firmware default is loopback mode
- [ ] Verify TX completes without error
- [ ] Verify /INT asserts on PB6
- [ ] Read back frame and verify checksum
- [ ] Check status_flags: no ST_SPI_FAULT or ST_CAN_FAULT

### Live Bus Mode
- [ ] Switch to normal mode in firmware
- [ ] Connect USB-CAN adapter
- [ ] Ensure 120-ohm termination at both ends
- [ ] Run `candump can0` or host codec
- [ ] Verify frames arrive at expected rate (~1 kHz)
- [ ] Verify payload decodes correctly per schema v1

---

## ENUM Test

### Single Pod
- [ ] Tie ENUM_IN HIGH
- [ ] Power on
- [ ] Verify chain_index = 0 in CAN frames
- [ ] Verify ST_NOT_ENUMERATED cleared
- [ ] Verify ENUM_OUT goes HIGH

### Two Pods
- [ ] Wire Pod A ENUM_OUT to Pod B ENUM_IN
- [ ] Seed Pod A ENUM_IN with HIGH
- [ ] Power both
- [ ] Verify Pod A: chain_index = 0
- [ ] Verify Pod B: chain_index = 1
- [ ] Repeat 10 times for consistency

---

## Encoder Magnet Test

- [ ] Mount magnet on rotating fixture
- [ ] Measure ADC at 30-degree increments (12 positions)
- [ ] Calculate error vs. expected linear mapping
- [ ] If error > TBD degrees: adjust magnet height/centering
- [ ] Record calibration data for `calib.c` fit

---

## Multi-Node Test (3+ Pods)

- [ ] Daisy-chain 3+ pods via ENUM line
- [ ] Seed first pod with ENUM_IN HIGH
- [ ] Power all pods
- [ ] Verify chain_index: 0, 1, 2, ...
- [ ] Verify all pods transmit on CAN with unique node_id and chain_index
- [ ] Verify host sees all pods in telemetry

---

## Logging Test

- [ ] Connect USB-CAN adapter to host
- [ ] Start bridge node with socketcan source
- [ ] Record an episode (10 seconds minimum)
- [ ] Confirm each sample has a monotonic `timestamp_ns`
- [ ] Finalize episode
- [ ] Read back parquet file
- [ ] Assert: samples match what was transmitted
- [ ] Check jitter stats in metadata
- [ ] Confirm a failed episode is quarantined and no parquet is emitted for it

---

## Failure Diagnosis

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| No power LED | No 5V5, blown regulator | Measure 5V5 and 3.3V rails |
| High current draw | Short circuit | Continuity check, look for solder bridges |
| No SWD connection | Bad wiring, no power | Check ST-LINK connections, target power |
| ADC stuck at 0 or max | No magnet, wrong pin | Check MT6701 wiring to PA0 |
| SPI timeout | Bad wiring, crystal dead | Scope SPI, check crystal oscillation |
| No CAN TX | MCP2515 not in right mode | Read CANSTAT, check init sequence |
| No /INT pulse | CANINTE wrong, PB6 wiring | Scope PB6, read CANINTE register |
| ENUM stuck | ENUM_IN not HIGH | Scope PA1, check seed signal |
| Wrong chain order | CAN peer observation fails | Check CAN bus, ENUM timing |

---

## Hardware Sign-Off Checklist

- [ ] All bench test stages passed
- [ ] ADC calibration data recorded
- [ ] CAN round-trip verified (loopback and live)
- [ ] ENUM ordering verified (2+ pods, 10x repetitions)
- [ ] Jitter measured and within budget
- [ ] Photos of assembled board archived
- [ ] Known issues documented
- [ ] Board labeled with serial number / revision
