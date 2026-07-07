# Data Pipeline Map

```mermaid
flowchart TD
    CAN[CAN Frame<br>8 bytes] --> DECODE[decode_state<br>codec.py]
    DECODE --> FIELDS[PodFields<br>conversion.py]
    FIELDS --> MSG[JointPodState<br>bridge_node.py]
    MSG --> INGEST[recorder.ingest]
    INGEST --> EPISODE[Episode<br>pvt.py]
    EPISODE --> FINALIZE[recorder.finalize]
    FINALIZE --> JITTER{jitter check}
    JITTER -->|PASS| WRITE[write_episode<br>parquet_io.py]
    JITTER -->|FAIL| QUARANTINE[quarantine/<br>.json sidecar]
    WRITE --> PARQUET[.parquet file]
    PARQUET --> READ[read_episode]
    READ --> SAMPLES[PVTSample list]
```

## Documents

- [[docs/data/PVT Data Pipeline|PVT Data Pipeline]]
- [[docs/decisions/0005-PVT-Data-Pipeline|ADR-0005]]
- [[docs/checklists/Data Logging Checklist|Data Logging Checklist]]
