# ADR-0004: MCP2515 SPI CAN Architecture

## Status
Accepted

## Context
The STM32C011 has no native CAN peripheral. An external CAN controller is needed.

## Decision
MCP2515 over SPI with 16 MHz crystal at 500 kbps. /INT on PB6 (EXTI, falling edge). Loopback mode for bring-up, then normal mode.

## Failure Mode Prevented
- Using a non-verified interrupt pin (A3 vs B6 confusion resolved: B6 CONFIRMED)
- SPI blocking in ISR (house rule: ISR only sets flag_can_int)
- Undetected SPI failure (every SPI call returns MCP_ERR_SPI on failure)
- Hung CAN controller (bounded poll budgets on TX and RX)

## Alternatives Considered
1. MCU with native CAN (STM32G0/G4) -- rejected for Rev-A: STM32C011 was already selected for cost/availability
2. MCP2518FD (CAN-FD) -- rejected: CAN 2.0B is sufficient for current data rate
3. Polled /INT (no EXTI) -- rejected: polling wastes CPU cycles; EXTI is efficient

## Consequences
- Positive: well-documented controller (Microchip DS20001801)
- Positive: SPI is straightforward to debug with logic analyzer
- Trade-off: external controller adds board space and SPI overhead
- Trade-off: limited to CAN 2.0B (no FD)

## Related Source Files
- `firmware/drivers/mcp2515.c`, `firmware/inc/mcp2515.h`
- `firmware/src/main.c` (EXTI setup, TX/RX paths)

## Related Tests
- `firmware/test/test_mcp2515.c`

## Open Questions
- SPI clock speed at 3.3V: verify MCP2515 max SPI clock at Vdd=3.3V (may be lower than 10 MHz at 5V)
