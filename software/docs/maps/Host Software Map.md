# Host Software Map

```mermaid
graph LR
    subgraph Frozen["Frozen Contracts"]
        CODEC[codec.py]
        ADAPT[adapter.py]
        PVT[pvt.py]
    end

    subgraph Bridge["Bridge"]
        SRC[sources.py] --> CONV[conversion.py]
        CONV --> BN[bridge_node.py]
    end

    subgraph Transport["Transport"]
        TI[interface.py]
        TF[file.py]
        TS[socketcan.py]
    end

    subgraph Logger["Logger"]
        REC[recorder.py]
        JIT[jitter.py]
        PIO[parquet_io.py]
    end

    subgraph Adapters["Adapters"]
        RA[replay_adapter.py]
        URA[ur_adapter.py]
        R2A[ros2_adapter.py]
    end

    SRC --> CODEC
    BN --> REC
    REC --> PVT
    REC --> PIO
    RA --> ADAPT
```

## Documents

- [[docs/host/Host Software Architecture|Host Software Architecture]]
- [[docs/sop/software/Verification SOP|Verification SOP]]
- [[docs/decisions/0006-RobotAdapter-Frozen-Contract|RobotAdapter]]
