---
name: sim
description: "Skill for the Sim area of Inhabit-Software. 41 symbols across 8 files."
---

# Sim

41 symbols | 8 files | Cohesion: 92%

## When to Use

- Working with code in `host/`
- Understanding how sine, ramp, hold work
- Modifying sim-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/sim/robot.py` | _phase_offset, sine, ramp, hold, __post_init__ (+7) |
| `host/sim/chaos.py` | _checked, _require_strictly_increasing, _fault_jitter, _fault_fixed_delay, _fault_burst_delay (+6) |
| `host/tests/test_sim_robot.py` | test_sine_matches_closed_form, test_ramp_hits_amplitude_extremes, test_hold_and_sine_and_ramp_are_distinct, test_phase_offsets_unique_across_all_dof, test_sample_at_is_pure_no_cursor_mutation (+1) |
| `host/tests/test_sim_noise.py` | _channel, test_noise_stays_within_clamp_bound, test_per_channel_independence, test_noise_sample_at_is_pure |
| `host/sim/scenario.py` | to_dict, dumps, loads |
| `host/tests/test_scenario.py` | test_dict_round_trip_equality, test_json_round_trip_equality, test_golden_fixture_round_trips_to_the_scenario |
| `host/sim/rng.py` | randint |
| `host/inhabit_can/pvt.py` | as_row |

## Entry Points

Start here when exploring this area:

- **`sine`** (Function) — `host/sim/robot.py:220`
- **`ramp`** (Function) — `host/sim/robot.py:233`
- **`hold`** (Function) — `host/sim/robot.py:252`
- **`test_sine_matches_closed_form`** (Function) — `host/tests/test_sim_robot.py:240`
- **`test_ramp_hits_amplitude_extremes`** (Function) — `host/tests/test_sim_robot.py:247`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `sine` | Function | `host/sim/robot.py` | 220 |
| `ramp` | Function | `host/sim/robot.py` | 233 |
| `hold` | Function | `host/sim/robot.py` | 252 |
| `test_sine_matches_closed_form` | Function | `host/tests/test_sim_robot.py` | 240 |
| `test_ramp_hits_amplitude_extremes` | Function | `host/tests/test_sim_robot.py` | 247 |
| `test_hold_and_sine_and_ramp_are_distinct` | Function | `host/tests/test_sim_robot.py` | 287 |
| `test_phase_offsets_unique_across_all_dof` | Function | `host/tests/test_sim_robot.py` | 382 |
| `test_noise_stays_within_clamp_bound` | Function | `host/tests/test_sim_noise.py` | 83 |
| `test_per_channel_independence` | Function | `host/tests/test_sim_noise.py` | 101 |
| `test_dict_round_trip_equality` | Function | `host/tests/test_scenario.py` | 251 |
| `test_json_round_trip_equality` | Function | `host/tests/test_scenario.py` | 257 |
| `test_golden_fixture_round_trips_to_the_scenario` | Function | `host/tests/test_scenario.py` | 345 |
| `test_noise_sample_at_is_pure` | Function | `host/tests/test_sim_noise.py` | 72 |
| `test_sample_at_is_pure_no_cursor_mutation` | Function | `host/tests/test_sim_robot.py` | 156 |
| `trajectory` | Function | `host/sim/robot.py` | 191 |
| `test_duplicate_trajectory_name_rejected` | Function | `host/tests/test_sim_robot.py` | 278 |
| `randint` | Method | `host/sim/rng.py` | 79 |
| `sigma` | Method | `host/sim/robot.py` | 145 |
| `enabled` | Method | `host/sim/robot.py` | 165 |
| `to_dict` | Method | `host/sim/scenario.py` | 273 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _timestamp` | cross_community | 7 |
| `_load_scenario_episode → Sigma` | cross_community | 7 |
| `_load_scenario_episode → Spawn` | cross_community | 7 |
| `_load_scenario_episode → Gauss` | cross_community | 7 |
| `_load_scenario_episode → _traj` | cross_community | 6 |
| `Read_state → Sigma` | cross_community | 5 |
| `Read_state → Spawn` | cross_community | 5 |
| `Read_state → Gauss` | cross_community | 5 |
| `Read_state → _timestamp` | cross_community | 4 |
| `Read_state → _traj` | cross_community | 4 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 8 calls |

## How to Explore

1. `context({name: "sine"})` — see callers and callees
2. `query({search_query: "sim"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
