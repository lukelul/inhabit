# Hardware Stack -- Rev-A Smart Joint Sensor Node

## Purpose

The Rev-A board is a **validation sensor node**, not the final actuated joint pod. It proves:
- Cheap absolute angle sensing
- Daisy-chained CAN telemetry
- Physical enumeration (ENUM protocol)
- Repeatable modular manufacturing

---

## Component Inventory

### MT6701 Magnetic Encoder
- **Role:** Absolute angle sensing (0-360 degrees)
- **Interface:** Analog output to STM32 ADC (PA0)
- **Why analog (Rev-A):** Avoids early I2C/SSI/ABZ complexity. Digital interfaces planned for Rev-B.
- **Magnet:** Diametrically magnetized disc, mounted on rotating shaft above the IC
- **Output:** Proportional voltage (0V to VCC) representing 0-360 degrees
- **Key risk:** Magnet misalignment causes nonlinear output and dead zones

### STM32C011F6P6 MCU
- **Role:** Core processor -- reads encoder ADC, runs ENUM FSM, communicates via SPI to MCP2515
- **Form factor (Rev-A):** Dev module, hand-soldered onto carrier board
- **Form factor (Rev-B):** Bare chip soldered directly
- **Peripherals used:** ADC (PA0), SPI1 (PA4-PA7), GPIO (PA1/PA2 ENUM), EXTI (PB6 for MCP2515 /INT)
- **Clock:** Internal oscillator (no external crystal on STM32)

### MCP2515 CAN Controller
- **Role:** Provides CAN 2.0B via SPI (STM32C011 has no native CAN peripheral)
- **Crystal:** 16 MHz external oscillator
- **Bit rate:** 500 kbps (CNF1/CNF2/CNF3 configured for 16 MHz)
- **Modes:** Configuration, Normal, Loopback (bring-up uses loopback first)
- **Interrupt:** /INT pin (active-low, open-drain) -> STM32 PB6 (CONFIRMED)
- **TX:** TXB0 only (single buffer, polled for completion)
- **RX:** RXB0, accept-all filter mode during bring-up
- **Datasheet:** Microchip DS20001801

### SN65HVD230 CAN Transceiver
- **Role:** Converts logic-level CAN TX/RX from MCP2515 to differential CANH/CANL bus signals
- **Supply:** 3.3V logic
- **Features:** Built-in slope control for EMI reduction
- **Key concern:** Requires proper 120-ohm bus termination at both ends of chain

### SM24CANB-02HTG TVS Protection
- **Role:** ESD/transient voltage suppression on CAN bus lines
- **Protection:** Clamps CANH/CANL against ESD and voltage spikes

---

## 5-Wire Daisy Chain Bus

| Wire | Signal | Purpose |
|------|--------|---------|
| 1 | 5V5 | Power input to board |
| 2 | GND | Ground reference |
| 3 | CANH | CAN bus high |
| 4 | CANL | CAN bus low |
| 5 | ENUM | Enumeration signal (GPIO, pod-to-pod) |

### Power Architecture
- **Input:** 5V5 on the bus connector
- **Logic rail:** VCC_BUS / 3.3V (regulated on-board)
- **Key risk:** Confusion between 5V5 input and 3.3V logic rail. 5V5 is the bus power; 3.3V is regulated from it.

### CANH/CANL
- Differential CAN bus signals
- Require 120-ohm termination at each end of the chain
- TVS protected (SM24CANB-02HTG)

### ENUM Line
- ENUM_IN (PA1): from previous pod (or host seed)
- ENUM_OUT (PA2): to next pod
- HIGH = asserted; pod sees ENUM_IN high -> starts claiming index
- Debounced (10 ticks) against glitches

---

## PCB Manufacturing Assumptions

- **Fabrication:** Standard 2-layer or 4-layer PCB (TBD from Altium project)
- **Assembly (PCBA):** Both-sides assembly expected
- **Hand-soldered parts:** STM32 dev module (excluded from PCBA pick-and-place)
- **Test pads:** TBD -- should provide access to SPI, CAN, ENUM, power rails

---

## Known Hardware Risks

See [[docs/risks/Risk Register]] for the full register.

| Risk | Severity | Status |
|------|----------|--------|
| Bottom-side PCBA orientation UNVERIFIED | HIGH | Confirm from schematic/Gerbers before writing register code |
| MCP2515 crystal frequency mismatch | HIGH | Must be 16 MHz to match CNF bit timing |
| CAN bus termination missing | MEDIUM | Need 120-ohm resistors at chain ends |
| Encoder magnet misalignment | HIGH | Causes nonlinear output, dead zones |
| Noisy ENC_ADC | MEDIUM | Requires firmware filtering (oversample + median/IIR) |
| 5V5/VCC_BUS confusion | MEDIUM | Document clearly which is input vs regulated |

---

## Future Revisions

### Rev-B: Bare MCU Integration
- STM32C011 soldered directly (no dev module)
- Possibly integrated CAN peripheral (different MCU)
- Digital encoder interface (I2C/SSI)
- Motor driver pads

### Future Actuated Joint Pod
- Motor + driver circuitry
- Current sensing for motor torque estimation
- Motor back-EMF sensing

### Future Last-Centimeter Sensors
- MEMS microphone for acoustic contact detection
- Vibration sensor
- Strain gauge / force-sensitive resistor
- Motor current spike correlation with contact events

---

## Related Files

- `firmware/CLAUDE.md` -- firmware-local rules
- `firmware/inc/can_frame.h` -- CAN schema v1
- `firmware/inc/mcp2515.h` -- MCP2515 register map
- `firmware/src/main.c` -- pin map implementation
- `.claude/CLAUDE.md` -- canonical pin map
