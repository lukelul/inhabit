---
name: export
description: "Skill for the Export area of Inhabit-Software. 18 symbols across 10 files."
---

# Export

18 symbols | 10 files | Cohesion: 80%

## When to Use

- Working with code in `host/`
- Understanding how frame_is_finite, instant_order, gate_episode work
- Modifying export-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/export/_gate.py` | frame_is_finite, instant_order, gate_episode |
| `host/export/parquet.py` | export, load, ParquetExporter |
| `host/timing/export_meta.py` | write_timing_sidecar, select_episode_timing, write_selected_timing_sidecar |
| `host/export/lerobot_exporter.py` | _drop_nonfinite, LeRobotExporter |
| `host/logger/parquet_io.py` | _episode_table, write_episode |
| `host/tests/test_dataset_roundtrip.py` | test_cli_parquet_export_roundtrip |
| `host/tests/test_export_timing_meta.py` | test_deleted_sidecar_reads_as_legacy |
| `host/export/base.py` | Exporter |
| `host/export/registry.py` | make_exporter |
| `host/tests/conformance/test_exporter_conformance.py` | exporter |

## Entry Points

Start here when exploring this area:

- **`frame_is_finite`** (Function) — `host/export/_gate.py:30`
- **`instant_order`** (Function) — `host/export/_gate.py:42`
- **`gate_episode`** (Function) — `host/export/_gate.py:59`
- **`write_episode`** (Function) — `host/logger/parquet_io.py:73`
- **`test_cli_parquet_export_roundtrip`** (Function) — `host/tests/test_dataset_roundtrip.py:145`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `Exporter` | Class | `host/export/base.py` | 61 |
| `LeRobotExporter` | Class | `host/export/lerobot_exporter.py` | 75 |
| `ParquetExporter` | Class | `host/export/parquet.py` | 68 |
| `frame_is_finite` | Function | `host/export/_gate.py` | 30 |
| `instant_order` | Function | `host/export/_gate.py` | 42 |
| `gate_episode` | Function | `host/export/_gate.py` | 59 |
| `write_episode` | Function | `host/logger/parquet_io.py` | 73 |
| `test_cli_parquet_export_roundtrip` | Function | `host/tests/test_dataset_roundtrip.py` | 145 |
| `write_timing_sidecar` | Function | `host/timing/export_meta.py` | 880 |
| `select_episode_timing` | Function | `host/timing/export_meta.py` | 977 |
| `write_selected_timing_sidecar` | Function | `host/timing/export_meta.py` | 1002 |
| `make_exporter` | Function | `host/export/registry.py` | 42 |
| `exporter` | Function | `host/tests/conformance/test_exporter_conformance.py` | 26 |
| `export` | Method | `host/export/parquet.py` | 91 |
| `load` | Method | `host/export/parquet.py` | 186 |
| `test_deleted_sidecar_reads_as_legacy` | Method | `host/tests/test_export_timing_meta.py` | 802 |
| `_drop_nonfinite` | Function | `host/export/lerobot_exporter.py` | 38 |
| `_episode_table` | Function | `host/logger/parquet_io.py` | 64 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Export → _median_sorted` | cross_community | 4 |
| `Export → _percentile_sorted` | cross_community | 4 |
| `Load → Migrate_row` | cross_community | 4 |
| `Export → Add` | cross_community | 3 |
| `Export → Frame_is_finite` | intra_community | 3 |
| `Export → Instant_order` | intra_community | 3 |
| `Export → Add` | cross_community | 3 |
| `Export → Frame_is_finite` | cross_community | 3 |
| `Export → Select_episode_timing` | cross_community | 3 |
| `Finalize → _episode_table` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 5 calls |
| Logger | 2 calls |

## How to Explore

1. `context({name: "frame_is_finite"})` — see callers and callees
2. `query({search_query: "export"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
