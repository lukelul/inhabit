---
name: logger
description: "Skill for the Logger area of Inhabit-Software. 8 symbols across 5 files."
---

# Logger

8 symbols | 5 files | Cohesion: 52%

## When to Use

- Working with code in `host/`
- Understanding how compute_jitter, test_fixed_delay_invisible_to_interval_stats_but_caught_vs_reference, test_drop_every_k_shrinks_count_and_shifts_measured_period work
- Modifying logger-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/logger/jitter.py` | _percentile_sorted, _median_sorted, compute_jitter |
| `host/tests/test_sim_chaos.py` | test_fixed_delay_invisible_to_interval_stats_but_caught_vs_reference, test_drop_every_k_shrinks_count_and_shifts_measured_period |
| `host/export/lerobot.py` | _infer_timing |
| `host/logger/recorder.py` | measure |
| `host/tests/test_sim_robot.py` | test_timestamps_pass_jitter_budget |

## Entry Points

Start here when exploring this area:

- **`compute_jitter`** (Function) — `host/logger/jitter.py:118`
- **`test_fixed_delay_invisible_to_interval_stats_but_caught_vs_reference`** (Function) — `host/tests/test_sim_chaos.py:101`
- **`test_drop_every_k_shrinks_count_and_shifts_measured_period`** (Function) — `host/tests/test_sim_chaos.py:134`
- **`test_timestamps_pass_jitter_budget`** (Function) — `host/tests/test_sim_robot.py:78`
- **`measure`** (Method) — `host/logger/recorder.py:229`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `compute_jitter` | Function | `host/logger/jitter.py` | 118 |
| `test_fixed_delay_invisible_to_interval_stats_but_caught_vs_reference` | Function | `host/tests/test_sim_chaos.py` | 101 |
| `test_drop_every_k_shrinks_count_and_shifts_measured_period` | Function | `host/tests/test_sim_chaos.py` | 134 |
| `test_timestamps_pass_jitter_budget` | Function | `host/tests/test_sim_robot.py` | 78 |
| `measure` | Method | `host/logger/recorder.py` | 229 |
| `_infer_timing` | Function | `host/export/lerobot.py` | 100 |
| `_percentile_sorted` | Function | `host/logger/jitter.py` | 97 |
| `_median_sorted` | Function | `host/logger/jitter.py` | 108 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Export → _median_sorted` | cross_community | 4 |
| `Export → _percentile_sorted` | cross_community | 4 |
| `Export → _median_sorted` | cross_community | 4 |
| `Export → _percentile_sorted` | cross_community | 4 |
| `Finalize → _median_sorted` | cross_community | 4 |
| `Finalize → _percentile_sorted` | cross_community | 4 |
| `_infer_timing → _median_sorted` | intra_community | 3 |
| `_infer_timing → _percentile_sorted` | intra_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 5 calls |

## How to Explore

1. `context({name: "compute_jitter"})` — see callers and callees
2. `query({search_query: "logger"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
