# Hardware Bring-Up SOP -- Rev-A Smart Joint Sensor Node

## Required Tools

- Bench power supply (adjustable, current-limited)
- Multimeter (continuity, voltage)
- Oscilloscope or logic analyzer (SPI, CAN bus probing)
- ST-LINK V2 or compatible SWD programmer
- USB-CAN adapter (for host-side validation)
- Diametrically magnetized disc magnet (for MT6701)
- Soldering station (for STM32 dev module)
- Magnifying glass / microscope (visual inspection)

---

## Stage 1: Visual Inspection

- [ ] Inspect PCB for solder bridges, cold joints, missing components
- [ ] Verify all ICs are oriented correctly (check pin 1 dots, notches)
- [ ] WARNING: Bottom-side PCBA orientation is **UNVERIFIED** -- confirm from schematic/Gerbers
- [ ] Verify MCP2515 crystal is present and properly seated (16 MHz)
- [ ] Check CAN bus connector/pads for shorts
- [ ] Verify STM32 dev module footprint matches the board pads

**If failed:** Document defects with photos. Do not apply power.

---

## Stage 2: Continuity & Shorts Checks (Power Off)

- [ ] Check 5V5 to GND for short (should be open/high resistance)
- [ ] Check VCC_BUS/3V3 to GND for short
- [ ] Check CANH to CANL for short (should be open)
- [ ] Check CANH to GND, CANL to GND (should be open through TVS, high impedance)
- [ ] Check SPI lines (PA4-PA7) are not shorted to each other or to GND/VCC

**If failed:** Trace the short before proceeding. Common cause: solder bridge under QFP/QFN.

---

## Stage 3: Power-On (No MCU)

- [ ] Set bench supply to 5.5V, current limit to **TBD** (start at 100 mA, typical draw TBD)
- [ ] Connect 5V5 and GND only
- [ ] Apply power, observe current draw
- [ ] Expected: low current draw (regulator quiescent + passive components)
- [ ] Measure VCC_BUS/3V3 rail -- should be 3.3V +/- 5%
- [ ] If current draw is excessive (> TBD mA), disconnect immediately

**If failed:** Excessive current = short on regulated rail. Check regulator, bypass caps.

---

## Stage 4: STM32 Dev Module Soldering

- [ ] Solder STM32C011 dev module onto board pads
- [ ] Verify pin alignment (PA0=ENC_ADC, PA1=ENUM_IN, PA2=ENUM_OUT, PA4=CS, PA5=SCK, PA6=MISO, PA7=MOSI, PB6=INT)
- [ ] Check solder joints under magnification
- [ ] Re-check continuity: SPI lines, ENUM lines, ADC input

**If failed:** Reflow solder joints. Check for bridges between adjacent pins.

---

## Stage 5: Firmware Flashing

- [ ] Connect ST-LINK to SWD header (SWDIO, SWCLK, GND, 3V3)
- [ ] Power the board from bench supply (5V5)
- [ ] Flash firmware using STM32CubeProgrammer or `st-flash`
- [ ] Verify flash write succeeds
- [ ] Verify MCU boots (check LED or debug printf if available)

**If failed:**
- No SWD connection: check wiring, verify target power, try power cycling
- Flash write fails: verify correct MCU target selected, check SWD pin connections

---

## Stage 6: ADC Validation (Encoder)

- [ ] Place magnet above MT6701 at correct distance (~1-3mm, check datasheet)
- [ ] Read ADC value from PA0 (debug output or logic analyzer)
- [ ] Rotate magnet slowly -- ADC value should sweep through full range
- [ ] Verify linear relationship between angle and ADC count
- [ ] Check for dead zones or nonlinear regions (magnet alignment issue)
- [ ] Run calibration: record ADC at known angles, verify `calib.c` fit

**If failed:**
- No ADC change: check analog connection from MT6701 OUT to PA0
- Nonlinear: adjust magnet height/centering
- Noisy: verify ADC filtering in firmware, check for coupling from SPI/CAN

---

## Stage 7: SPI / MCP2515 Validation

- [ ] Put MCP2515 in loopback mode (firmware default)
- [ ] Read CANSTAT register -- should show configuration mode after reset
- [ ] Write and read-back a register to verify SPI communication
- [ ] Check SPI signals on scope/logic analyzer: CS, SCK, MISO, MOSI
- [ ] Verify 16 MHz crystal oscillation (scope on CLKOUT if enabled, or probe crystal pins)

**If failed:**
- SPI timeout (ST_SPI_FAULT): check CS (PA4) toggling, check SPI clock, verify MISO/MOSI not swapped
- Wrong CANSTAT: crystal not oscillating, check solder on crystal pins

---

## Stage 8: CAN Validation (Loopback)

- [ ] Firmware transmits via TXB0 in loopback mode
- [ ] Verify TX completes (TXREQ clears)
- [ ] Verify /INT asserts (PB6 goes low) when RXB0 receives loopback frame
- [ ] Read back frame from RXB0 and verify checksum
- [ ] Check that `can_health_apply` clears SPI/CAN fault flags on successful round-trip

**If failed:**
- TX timeout: MCP2515 not in correct mode, check CNF registers
- No /INT: check PB6 connection, EXTI configuration, CANINTE register (RX0IE bit)
- Checksum fail: data corruption in SPI transfer

---

## Stage 9: CAN Validation (Live Bus)

- [ ] Switch MCP2515 to normal mode
- [ ] Connect USB-CAN adapter to CANH/CANL
- [ ] Verify 120-ohm termination at both ends
- [ ] Send a frame from the pod -- observe on host with `candump` or host codec
- [ ] Send a frame from host -- observe pod receives

**If failed:**
- No bus activity: check transceiver, CANH/CANL wiring, termination
- Garbled frames: bit rate mismatch (verify 500 kbps on both ends)

---

## Stage 10: ENUM Validation

- [ ] Power one pod with ENUM_IN tied HIGH (host seed)
- [ ] Verify pod claims chain_index = 0, clears ST_NOT_ENUMERATED
- [ ] Verify ENUM_OUT goes HIGH after delay
- [ ] Observe on CAN: chain_index=0 in telemetry frames

**If failed:**
- Stuck in ENUM_WAIT: ENUM_IN not reaching threshold, check wiring
- Wrong chain_index: peer CAN frames being misinterpreted

---

## Stage 11: Two-Board Daisy Chain

- [ ] Connect two pods: Pod A ENUM_OUT -> Pod B ENUM_IN
- [ ] Seed Pod A ENUM_IN with HIGH
- [ ] Power both pods
- [ ] Verify Pod A claims chain_index=0, Pod B claims chain_index=1
- [ ] Verify both pods transmit CAN frames with correct chain_index
- [ ] Verify host sees both pod frames on CAN bus
- [ ] Verify no ENUM race conditions (reset and repeat 10x)

**If failed:**
- Both claim index 0: ENUM_OUT from Pod A not reaching Pod B
- Wrong order: CAN peer observation timing issue, check ENUM debounce

---

## Stage 12: Logging Validation

- [ ] Connect USB-CAN adapter to host
- [ ] Run the bridge launch with a replay file: `ros2 launch inhabit_bridge bridge.launch.py source:=file path:=/tmp/recording.canlog`
- [ ] Verify JointPodState messages published
- [ ] Run EpisodeRecorder to log an episode
- [ ] Read back parquet file and verify round-trip equality
- [ ] Check jitter stats in parquet footer metadata

**If failed:**
- No messages: check CAN source configuration, USB-CAN adapter
- Jitter exceeded: check USB-CAN adapter buffering, host load

---

## Pass/Fail Criteria

| Stage | Pass | Fail Action |
|-------|------|-------------|
| Visual | No defects visible | Document, rework or reject board |
| Shorts | No shorts on power/signal | Trace and fix before power-on |
| Power-on | 3.3V rail correct, current nominal | Investigate regulator / short |
| Flash | MCU boots, firmware runs | Check SWD, power, target config |
| ADC | Full-range sweep, linear, low noise | Check magnet, wiring, filtering |
| SPI | Register read/write correct | Check wiring, crystal, CS |
| CAN loopback | TX+RX round-trip, /INT works | Check MCP2515 config, EXTI |
| CAN live | Host sees pod frames | Check transceiver, termination |
| ENUM | Correct index assignment | Check GPIO, debounce, CAN timing |
| Two-board | Both pods ordered correctly | Check ENUM wiring, CAN isolation |
| Logging | Parquet round-trip passes | Check host software, USB-CAN |

---

## Safety Warnings

- Always current-limit the power supply during initial power-on
- Never apply 5V directly to 3.3V logic pins
- ESD precautions when handling bare PCBs
- Verify voltage levels before connecting scope probes (ground loops)
- Keep magnets away from magnetic media and pacemakers
