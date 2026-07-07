# Firmware Stack Map

```mermaid
graph TB
    MAIN[main.c<br>Loop + ISR] --> CF[can_frame.c/h<br>FROZEN]
    MAIN --> CH[can_health.c/h]
    MAIN --> CAL[calib.c/h]
    MAIN --> ENUM[enum.c/h]
    MAIN --> DRV[mcp2515.c/h]

    ISR[EXTI4_15 ISR<br>PB6 /INT] -.->|flag_can_int| MAIN
    TICK[SysTick ISR] -.->|tick_1khz| MAIN
    ADC_ISR[ADC ISR] -.->|flag_adc_ready| MAIN

    subgraph Tests
        T1[test_can_frame.c]
        T2[test_calib.c]
        T3[test_mcp2515.c]
        T4[test_can_health.c]
        T5[test_enum.c]
    end
```

## Documents

- [[docs/firmware/Firmware Architecture|Firmware Architecture]]
- [[docs/firmware/Firmware SOP|Firmware SOP]]
- [[docs/decisions/0001-CAN-Schema-v1|CAN Schema v1]]
- [[docs/decisions/0002-ENUM-Protocol|ENUM Protocol]]
- [[docs/decisions/0004-MCP2515-SPI-CAN-Architecture|MCP2515 Architecture]]
