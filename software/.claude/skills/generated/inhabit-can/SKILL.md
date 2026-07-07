---
name: inhabit-can
description: "Skill for the Inhabit_can area of Inhabit-Software. 14 symbols across 5 files."
---

# Inhabit_can

14 symbols | 5 files | Cohesion: 71%

## When to Use

- Working with code in `host/`
- Understanding how test_sim_adapter, can_id, encode_state work
- Modifying inhabit_can-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/inhabit_can/adapter.py` | connect, read_state, send_command, capabilities |
| `host/tests/test_adapters.py` | test_connect_and_read, test_send_command_updates_state, test_capabilities |
| `host/inhabit_can/codec.py` | can_id, _xor7, encode_state |
| `host/tests/test_codec.py` | test_sim_adapter, test_roundtrip_and_bitflip |
| `host/tests/test_integration.py` | _pod_state, test_corrupt_checksum_frame_dropped |

## Entry Points

Start here when exploring this area:

- **`test_sim_adapter`** (Function) — `host/tests/test_codec.py:18`
- **`can_id`** (Function) — `host/inhabit_can/codec.py:28`
- **`encode_state`** (Function) — `host/inhabit_can/codec.py:39`
- **`test_roundtrip_and_bitflip`** (Function) — `host/tests/test_codec.py:4`
- **`test_corrupt_checksum_frame_dropped`** (Function) — `host/tests/test_integration.py:87`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_sim_adapter` | Function | `host/tests/test_codec.py` | 18 |
| `can_id` | Function | `host/inhabit_can/codec.py` | 28 |
| `encode_state` | Function | `host/inhabit_can/codec.py` | 39 |
| `test_roundtrip_and_bitflip` | Function | `host/tests/test_codec.py` | 4 |
| `test_corrupt_checksum_frame_dropped` | Function | `host/tests/test_integration.py` | 87 |
| `connect` | Method | `host/inhabit_can/adapter.py` | 41 |
| `read_state` | Method | `host/inhabit_can/adapter.py` | 44 |
| `send_command` | Method | `host/inhabit_can/adapter.py` | 47 |
| `capabilities` | Method | `host/inhabit_can/adapter.py` | 50 |
| `test_connect_and_read` | Method | `host/tests/test_adapters.py` | 19 |
| `test_send_command_updates_state` | Method | `host/tests/test_adapters.py` | 26 |
| `test_capabilities` | Method | `host/tests/test_adapters.py` | 33 |
| `_xor7` | Function | `host/inhabit_can/codec.py` | 32 |
| `_pod_state` | Function | `host/tests/test_integration.py` | 31 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `_run → _xor7` | cross_community | 6 |
| `Main → _xor7` | cross_community | 5 |
| `Main → _xor7` | cross_community | 5 |
| `Render_stream → _xor7` | cross_community | 5 |
| `Frames → Can_id` | cross_community | 3 |
| `Frames → _xor7` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 6 calls |

## How to Explore

1. `context({name: "test_sim_adapter"})` — see callers and callees
2. `query({search_query: "inhabit_can"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
