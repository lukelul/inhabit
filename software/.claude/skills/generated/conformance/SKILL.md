---
name: conformance
description: "Skill for the Conformance area of Inhabit-Software. 36 symbols across 12 files."
---

# Conformance

36 symbols | 12 files | Cohesion: 76%

## When to Use

- Working with code in `host/`
- Understanding how list_adapters, test_adapter_via_registry, test_conformance_finalize_before_open_raises work
- Modifying conformance-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/tests/conformance/test_transport_conformance.py` | _make_frames, test_recv_before_open_raises, test_timestamps_monotonic, test_send_is_noop, _write_canlog (+3) |
| `host/tests/conformance/test_adapter_conformance.py` | test_connect_is_idempotent, test_read_state_returns_robot_state, test_capabilities_positive_dof, test_dof_matches_state_length, test_send_command_accepted (+1) |
| `host/inhabit_can/adapter.py` | connect, read_state, send_command, capabilities |
| `host/tests/conformance/test_episode_sink_conformance.py` | _make_valid_sample, test_open_ingest_finalize_lifecycle, test_double_finalize_raises, test_ingest_after_finalize_raises |
| `host/tests/conformance/test_exporter_conformance.py` | _make_episode, test_round_trip, test_round_trip_field_equality, test_empty_export |
| `host/tests/test_registry_core.py` | test_sim_adapter_builds_and_works, test_replay_adapter_builds_and_works |
| `host/logger/sinks/interface.py` | finalize, __exit__ |
| `host/export/base.py` | export, load |
| `host/adapters/__init__.py` | list_adapters |
| `host/tests/test_adapters.py` | test_list_adapters |

## Entry Points

Start here when exploring this area:

- **`list_adapters`** (Function) — `host/adapters/__init__.py:66`
- **`test_adapter_via_registry`** (Function) — `host/tests/test_sim_robot.py:366`
- **`test_conformance_finalize_before_open_raises`** (Function) — `host/tests/test_sinks.py:460`
- **`connect`** (Method) — `host/inhabit_can/adapter.py:26`
- **`read_state`** (Method) — `host/inhabit_can/adapter.py:28`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `list_adapters` | Function | `host/adapters/__init__.py` | 66 |
| `test_adapter_via_registry` | Function | `host/tests/test_sim_robot.py` | 366 |
| `test_conformance_finalize_before_open_raises` | Function | `host/tests/test_sinks.py` | 460 |
| `connect` | Method | `host/inhabit_can/adapter.py` | 26 |
| `read_state` | Method | `host/inhabit_can/adapter.py` | 28 |
| `send_command` | Method | `host/inhabit_can/adapter.py` | 30 |
| `capabilities` | Method | `host/inhabit_can/adapter.py` | 32 |
| `test_connect_is_idempotent` | Method | `host/tests/conformance/test_adapter_conformance.py` | 35 |
| `test_read_state_returns_robot_state` | Method | `host/tests/conformance/test_adapter_conformance.py` | 39 |
| `test_capabilities_positive_dof` | Method | `host/tests/conformance/test_adapter_conformance.py` | 46 |
| `test_dof_matches_state_length` | Method | `host/tests/conformance/test_adapter_conformance.py` | 51 |
| `test_send_command_accepted` | Method | `host/tests/conformance/test_adapter_conformance.py` | 55 |
| `test_state_reflects_command` | Method | `host/tests/conformance/test_adapter_conformance.py` | 60 |
| `test_list_adapters` | Method | `host/tests/test_adapters.py` | 315 |
| `test_sim_adapter_builds_and_works` | Method | `host/tests/test_registry_core.py` | 263 |
| `test_replay_adapter_builds_and_works` | Method | `host/tests/test_registry_core.py` | 270 |
| `finalize` | Method | `host/logger/sinks/interface.py` | 176 |
| `test_open_ingest_finalize_lifecycle` | Method | `host/tests/conformance/test_episode_sink_conformance.py` | 44 |
| `test_double_finalize_raises` | Method | `host/tests/conformance/test_episode_sink_conformance.py` | 51 |
| `test_ingest_after_finalize_raises` | Method | `host/tests/conformance/test_episode_sink_conformance.py` | 59 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 12 calls |
| Inhabit_can | 1 calls |

## How to Explore

1. `context({name: "list_adapters"})` — see callers and callees
2. `query({search_query: "conformance"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
