# System Architecture Map

## Data Flow

```mermaid
flowchart LR
    ENC[MT6701] -->|analog| ADC[STM32 ADC]
    ADC --> CAL[calib.c]
    CAL --> PACK[can_frame.c]
    PACK -->|SPI| MCP[MCP2515]
    MCP -->|CANH/CANL| BUS((CAN Bus))
    BUS --> CODEC[codec.py]
    CODEC --> CONV[conversion.py]
    CONV --> BRIDGE[bridge_node.py]
    BRIDGE -->|JointPodState| REC[recorder.py]
    REC --> JIT{jitter.py}
    JIT -->|PASS| PQ[parquet_io.py]
    JIT -->|FAIL| QR[quarantine/]
    PQ --> DS[(Dataset)]
```

## Key Documents

- [[docs/architecture/System Architecture|Full Architecture]]
- [[docs/hardware/Hardware Stack|Hardware Stack]]
- [[docs/firmware/Firmware Architecture|Firmware Architecture]]
- [[docs/host/Host Software Architecture|Host Software Architecture]]
- [[docs/data/PVT Data Pipeline|PVT Data Pipeline]]

## Frozen Contracts

- [[docs/decisions/0001-CAN-Schema-v1|CAN Schema v1]] -- `can_frame.h` / `codec.py`
- [[docs/decisions/0006-RobotAdapter-Frozen-Contract|RobotAdapter]] -- `adapter.py`
- [[docs/decisions/0005-PVT-Data-Pipeline|PVTSample]] -- `pvt.py`
