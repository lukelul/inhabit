# Hardware Bringup Map

```mermaid
flowchart TD
    VISUAL[1. Visual Inspection] --> SHORTS[2. Continuity / Shorts]
    SHORTS --> POWER[3. Power-On]
    POWER --> SOLDER[4. STM32 Soldering]
    SOLDER --> FLASH[5. Firmware Flash]
    FLASH --> ADC[6. ADC Validation]
    ADC --> SPI[7. SPI / MCP2515]
    SPI --> CAN_LB[8. CAN Loopback]
    CAN_LB --> CAN_LIVE[9. CAN Live Bus]
    CAN_LIVE --> ENUM_1[10. ENUM Single]
    ENUM_1 --> ENUM_2[11. Two-Board Chain]
    ENUM_2 --> LOG[12. Logging Validation]
    LOG --> DONE((Board<br>Validated))
```

Each stage has pass/fail criteria. Do not proceed if a stage fails.

## Documents

- [[docs/hardware/bringup/Hardware Bring-Up SOP|Hardware Bring-Up SOP]]
- [[docs/sop/hardware/Hardware Test SOP|Hardware Test SOP]]
- [[docs/checklists/Before First Power Checklist|Before First Power]]
- [[docs/checklists/Firmware Bringup Checklist|Firmware Bringup]]
- [[docs/checklists/CAN Bringup Checklist|CAN Bringup]]
- [[docs/checklists/ENUM Bringup Checklist|ENUM Bringup]]
