# Hardware Stack Map

```mermaid
graph TB
    subgraph Pod["Smart Joint Pod (Rev-A)"]
        MAG[Magnet] --> ENC[MT6701 Encoder]
        ENC -->|Analog OUT| MCU[STM32C011]
        MCU -->|SPI| CAN_CTRL[MCP2515]
        CAN_CTRL --> XCV[SN65HVD230]
        XCV --> TVS[SM24CANB TVS]
        TVS --> BUS_H[CANH]
        TVS --> BUS_L[CANL]
        MCU -->|PA1| ENUM_IN[ENUM IN]
        MCU -->|PA2| ENUM_OUT[ENUM OUT]
    end

    subgraph Power["Power"]
        V55[5V5 Bus] --> REG[3.3V Regulator]
        REG --> VCC[VCC_BUS 3.3V]
    end

    BUS_H --> NEXT_POD[Next Pod / Host]
    BUS_L --> NEXT_POD
    ENUM_OUT --> NEXT_ENUM[Next Pod ENUM_IN]
```

## Documents

- [[docs/hardware/Hardware Stack|Hardware Stack]]
- [[docs/hardware/bringup/Hardware Bring-Up SOP|Bring-Up SOP]]
- [[docs/hardware/pcba/PCBA and Fabrication SOP|PCBA SOP]]
- [[docs/risks/Risk Register|Risk Register]]
