---
name: timing
description: "Skill for the Timing area of Inhabit-Software. 30 symbols across 5 files."
---

# Timing

30 symbols | 5 files | Cohesion: 77%

## When to Use

- Working with code in `host/`
- Understanding how validate_stamp_ns, result_count, matched_count work
- Modifying timing-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/timing/export_meta.py` | _validate_count, _validate_offset_ns, _validate_histogram, _histogram_total, __post_init__ (+11) |
| `host/timing/stamp.py` | validate_stamp_ns, __post_init__, _raw_in_same_domain, __lt__, __le__ (+2) |
| `host/timing/align.py` | __post_init__, _validate_timeline, _validate_budget_ns, __post_init__ |
| `host/timing/clocks.py` | __init__, __init__ |
| `host/sim/chaos.py` | __post_init__ |

## Entry Points

Start here when exploring this area:

- **`validate_stamp_ns`** (Function) — `host/timing/stamp.py:75`
- **`result_count`** (Method) — `host/timing/export_meta.py:421`
- **`matched_count`** (Method) — `host/timing/export_meta.py:417`
- **`out_of_budget_count`** (Method) — `host/timing/export_meta.py:620`
- **`missing_target_count`** (Method) — `host/timing/export_meta.py:628`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `validate_stamp_ns` | Function | `host/timing/stamp.py` | 75 |
| `result_count` | Method | `host/timing/export_meta.py` | 421 |
| `matched_count` | Method | `host/timing/export_meta.py` | 417 |
| `out_of_budget_count` | Method | `host/timing/export_meta.py` | 620 |
| `missing_target_count` | Method | `host/timing/export_meta.py` | 628 |
| `from_dict` | Method | `host/timing/export_meta.py` | 440 |
| `_validate_timeline` | Function | `host/timing/align.py` | 309 |
| `_validate_count` | Function | `host/timing/export_meta.py` | 111 |
| `_validate_offset_ns` | Function | `host/timing/export_meta.py` | 133 |
| `_validate_histogram` | Function | `host/timing/export_meta.py` | 176 |
| `_histogram_total` | Function | `host/timing/export_meta.py` | 218 |
| `_histogram_count` | Function | `host/timing/export_meta.py` | 222 |
| `_member_from_token` | Function | `host/timing/export_meta.py` | 158 |
| `_histogram_from_counter` | Function | `host/timing/export_meta.py` | 231 |
| `_histogram_from_dict` | Function | `host/timing/export_meta.py` | 238 |
| `_validate_budget_ns` | Function | `host/timing/align.py` | 121 |
| `__post_init__` | Method | `host/sim/chaos.py` | 548 |
| `__post_init__` | Method | `host/timing/align.py` | 218 |
| `__init__` | Method | `host/timing/clocks.py` | 66 |
| `__init__` | Method | `host/timing/clocks.py` | 104 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Load_lerobot_timing_meta → _member_from_token` | cross_community | 6 |
| `Load_lerobot_timing_meta → _validate_count` | cross_community | 6 |
| `Load_lerobot_timing_meta → _histogram_from_counter` | cross_community | 6 |
| `Load_parquet_timing_meta → _member_from_token` | cross_community | 6 |
| `Load_parquet_timing_meta → _validate_count` | cross_community | 6 |
| `Load_parquet_timing_meta → _histogram_from_counter` | cross_community | 6 |
| `Load_lerobot_timing_meta → _validate_offset_ns` | cross_community | 5 |
| `Load_parquet_timing_meta → _validate_offset_ns` | cross_community | 5 |
| `Align_modalities → Validate_stamp_ns` | cross_community | 4 |
| `__post_init__ → _validate_count` | intra_community | 3 |

## How to Explore

1. `context({name: "validate_stamp_ns"})` — see callers and callees
2. `query({search_query: "timing"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
