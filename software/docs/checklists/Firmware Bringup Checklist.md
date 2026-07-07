# Firmware Bringup Checklist

- [ ] Board powers on with correct 3.3V rail
- [ ] ST-LINK connects via SWD
- [ ] Firmware flashed successfully
- [ ] MCU boots (debug output visible)
- [ ] ADC reads from PA0 (MT6701 encoder)
- [ ] SPI communication to MCP2515 works (register read/write)
- [ ] MCP2515 enters configuration mode after reset
- [ ] CNF1/2/3 written correctly for 500 kbps at 16 MHz
- [ ] MCP2515 enters loopback mode
- [ ] CAN TX completes (TXREQ clears)
- [ ] CAN RX via /INT works (PB6 EXTI)
- [ ] Loopback round-trip passes (checksum valid)
- [ ] Status flags correct (no spurious faults)
