---
name: inhabit-bridge
description: "Skill for the Inhabit_bridge area of Inhabit-Software. 19 symbols across 4 files."
---

# Inhabit_bridge

19 symbols | 4 files | Cohesion: 90%

## When to Use

- Working with code in `host/`
- Understanding how stamp_from_monotonic_ns, build_message, test_build_message_populates_all_fields_and_monotonic_stamp work
- Modifying inhabit_bridge-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/inhabit_bridge/sources.py` | frames, CanSource, ReplaySource, SimSource, SocketCanSource (+4) |
| `host/inhabit_bridge/bridge_node.py` | stamp_from_monotonic_ns, build_message, _run, _publish, _make_node (+1) |
| `host/tests/test_bridge.py` | test_build_message_populates_all_fields_and_monotonic_stamp, test_stamp_split_round_trips, test_sim_source_produces_valid_publishable_messages |
| `host/inhabit_bridge/transport_source.py` | TransportSource |

## Entry Points

Start here when exploring this area:

- **`stamp_from_monotonic_ns`** (Function) — `host/inhabit_bridge/bridge_node.py:42`
- **`build_message`** (Function) — `host/inhabit_bridge/bridge_node.py:50`
- **`test_build_message_populates_all_fields_and_monotonic_stamp`** (Function) — `host/tests/test_bridge.py:94`
- **`test_stamp_split_round_trips`** (Function) — `host/tests/test_bridge.py:114`
- **`test_sim_source_produces_valid_publishable_messages`** (Function) — `host/tests/test_bridge.py:149`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `CanSource` | Class | `host/inhabit_bridge/sources.py` | 51 |
| `ReplaySource` | Class | `host/inhabit_bridge/sources.py` | 74 |
| `SimSource` | Class | `host/inhabit_bridge/sources.py` | 109 |
| `SocketCanSource` | Class | `host/inhabit_bridge/sources.py` | 149 |
| `TransportSource` | Class | `host/inhabit_bridge/transport_source.py` | 27 |
| `stamp_from_monotonic_ns` | Function | `host/inhabit_bridge/bridge_node.py` | 42 |
| `build_message` | Function | `host/inhabit_bridge/bridge_node.py` | 50 |
| `test_build_message_populates_all_fields_and_monotonic_stamp` | Function | `host/tests/test_bridge.py` | 94 |
| `test_stamp_split_round_trips` | Function | `host/tests/test_bridge.py` | 114 |
| `test_sim_source_produces_valid_publishable_messages` | Function | `host/tests/test_bridge.py` | 149 |
| `main` | Function | `host/inhabit_bridge/bridge_node.py` | 200 |
| `frames` | Method | `host/inhabit_bridge/sources.py` | 125 |
| `open` | Method | `host/inhabit_bridge/sources.py` | 55 |
| `close` | Method | `host/inhabit_bridge/sources.py` | 63 |
| `_make_node` | Function | `host/inhabit_bridge/bridge_node.py` | 111 |
| `_run` | Method | `host/inhabit_bridge/bridge_node.py` | 168 |
| `_publish` | Method | `host/inhabit_bridge/bridge_node.py` | 177 |
| `__enter__` | Method | `host/inhabit_bridge/sources.py` | 66 |
| `__exit__` | Method | `host/inhabit_bridge/sources.py` | 70 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `_run → _xor7` | cross_community | 6 |
| `_run → Fields_from_state` | cross_community | 5 |
| `_run → Stamp_from_monotonic_ns` | intra_community | 4 |
| `Frames → Can_id` | cross_community | 3 |
| `Frames → _xor7` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 3 calls |
| Inhabit_can | 1 calls |

## How to Explore

1. `context({name: "stamp_from_monotonic_ns"})` — see callers and callees
2. `query({search_query: "inhabit_bridge"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
