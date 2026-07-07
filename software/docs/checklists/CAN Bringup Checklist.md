# CAN Bringup Checklist

## Loopback Phase
- [ ] MCP2515 in loopback mode
- [ ] TX frame sent via TXB0
- [ ] TXREQ clears (TX complete)
- [ ] RX0IF set (frame received in RXB0)
- [ ] /INT asserts on PB6 (EXTI fires)
- [ ] Frame read back matches transmitted frame
- [ ] XOR checksum verified
- [ ] Status flags: no ST_SPI_FAULT, no ST_CAN_FAULT
- [ ] can_health_apply clears faults on healthy round-trip

## Live Bus Phase
- [ ] Switch MCP2515 to normal mode
- [ ] USB-CAN adapter connected
- [ ] 120-ohm termination at both chain ends
- [ ] Pod transmits frames visible on host (`candump` or codec)
- [ ] Frame rate ~1 kHz (or configured rate)
- [ ] Host can send frames to pod
- [ ] Payload decodes correctly per schema v1
- [ ] No error frames on bus
