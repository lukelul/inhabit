# Last Centimeter Map

```mermaid
flowchart LR
    subgraph Current["Phase 1: Current"]
        P[Proprioceptive<br>CAN telemetry]
    end

    subgraph Phase2["Phase 2: Motor Current"]
        MC[Motor Current ADC]
        CD[Contact Detector]
    end

    subgraph Phase3["Phase 3: MEMS Mic"]
        MIC[MEMS Microphone]
        ACO[Acoustic Features]
    end

    subgraph Phase4["Phase 4: Visual"]
        CAM[Camera Sync]
        VF[Video Frames]
    end

    subgraph Phase5["Phase 5: Full PVT"]
        PVT_EP[PVT Episodes<br>ML-ready]
    end

    P --> PVT_EP
    MC --> CD --> PVT_EP
    MIC --> ACO --> PVT_EP
    CAM --> VF --> PVT_EP
```

## Documents

- [[docs/last-centimeter/Last Centimeter Data Thesis|Last Centimeter Data Thesis]]
- [[docs/teleop/Universal Teleop Kernel|Universal Teleop Kernel]]
- [[docs/data/PVT Data Pipeline|PVT Data Pipeline]]
- [[docs/decisions/0009-Last-Centimeter-Data-Thesis|ADR-0009]]
