---
name: sensors
description: "Skill for the Sensors area of Inhabit-Software. 31 symbols across 8 files."
---

# Sensors

31 symbols | 8 files | Cohesion: 92%

## When to Use

- Working with code in `host/`
- Understanding how test_read_and_stream_before_open_raise, test_read_before_open_raises, test_count_zero_emits_nothing work
- Modifying sensors-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/sensors/sim_scenario.py` | _ScenarioSource, SimTactileSource, SimFramesSource, read, _make_sample (+3) |
| `host/sensors/interface.py` | SensorSource, open, read, stream, __enter__ (+2) |
| `host/sensors/sim_proprio.py` | SimProprioSource, read, _make_sample, metadata |
| `host/tests/test_sensors.py` | _IncompatibleSource, test_read_before_open_raises, test_count_zero_emits_nothing, metadata |
| `host/sensors/replay.py` | ReplaySource, read, stream |
| `host/tests/test_sensors_scenario.py` | test_read_and_stream_before_open_raise, test_tactile_labels_track_injected_clock, test_read_after_exhaustion_keeps_returning_none |
| `host/tests/conformance/test_sensor_conformance.py` | test_stream_yields_samples |
| `host/tools/dataset/scenario_episode.py` | _collect_registry_stream |

## Entry Points

Start here when exploring this area:

- **`test_read_and_stream_before_open_raise`** (Function) — `host/tests/test_sensors_scenario.py:292`
- **`test_read_before_open_raises`** (Function) — `host/tests/test_sensors.py:322`
- **`test_count_zero_emits_nothing`** (Function) — `host/tests/test_sensors.py:357`
- **`test_tactile_labels_track_injected_clock`** (Function) — `host/tests/test_sensors_scenario.py:152`
- **`test_read_after_exhaustion_keeps_returning_none`** (Function) — `host/tests/test_sensors_scenario.py:212`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `SensorSource` | Class | `host/sensors/interface.py` | 108 |
| `ReplaySource` | Class | `host/sensors/replay.py` | 52 |
| `SimProprioSource` | Class | `host/sensors/sim_proprio.py` | 54 |
| `SimTactileSource` | Class | `host/sensors/sim_scenario.py` | 171 |
| `SimFramesSource` | Class | `host/sensors/sim_scenario.py` | 226 |
| `test_read_and_stream_before_open_raise` | Function | `host/tests/test_sensors_scenario.py` | 292 |
| `test_read_before_open_raises` | Function | `host/tests/test_sensors.py` | 322 |
| `test_count_zero_emits_nothing` | Function | `host/tests/test_sensors.py` | 357 |
| `test_tactile_labels_track_injected_clock` | Function | `host/tests/test_sensors_scenario.py` | 152 |
| `test_read_after_exhaustion_keeps_returning_none` | Function | `host/tests/test_sensors_scenario.py` | 212 |
| `open` | Method | `host/sensors/interface.py` | 133 |
| `read` | Method | `host/sensors/interface.py` | 141 |
| `stream` | Method | `host/sensors/interface.py` | 149 |
| `test_stream_yields_samples` | Method | `host/tests/conformance/test_sensor_conformance.py` | 23 |
| `read` | Method | `host/sensors/sim_proprio.py` | 163 |
| `read` | Method | `host/sensors/sim_scenario.py` | 127 |
| `metadata` | Method | `host/sensors/sim_scenario.py` | 212 |
| `metadata` | Method | `host/sensors/sim_scenario.py` | 269 |
| `close` | Method | `host/sensors/interface.py` | 137 |
| `read` | Method | `host/sensors/replay.py` | 128 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → Stream` | cross_community | 5 |
| `Main → Make_sensor_source` | cross_community | 5 |
| `Stream → _make_sample` | cross_community | 3 |
| `Stream → _make_sample` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 2 calls |

## How to Explore

1. `context({name: "test_read_and_stream_before_open_raise"})` — see callers and callees
2. `query({search_query: "sensors"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
