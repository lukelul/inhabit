---
name: can-replay
description: "Skill for the Can_replay area of Inhabit-Software. 6 symbols across 4 files."
---

# Can_replay

6 symbols | 4 files | Cohesion: 83%

## When to Use

- Working with code in `tools/`
- Understanding how test_recorder_requires_open, main, write work
- Modifying can_replay-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tools/can_replay/__main__.py` | _cmd_record, _cmd_replay, main |
| `host/tests/test_transport.py` | test_recorder_requires_open |
| `host/transport/file.py` | write |
| `host/transport/socketcan.py` | recv |

## Entry Points

Start here when exploring this area:

- **`test_recorder_requires_open`** (Function) — `host/tests/test_transport.py:119`
- **`main`** (Function) — `tools/can_replay/__main__.py:68`
- **`write`** (Method) — `host/transport/file.py:53`
- **`recv`** (Method) — `host/transport/socketcan.py:47`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_recorder_requires_open` | Function | `host/tests/test_transport.py` | 119 |
| `main` | Function | `tools/can_replay/__main__.py` | 68 |
| `write` | Method | `host/transport/file.py` | 53 |
| `recv` | Method | `host/transport/socketcan.py` | 47 |
| `_cmd_record` | Function | `tools/can_replay/__main__.py` | 18 |
| `_cmd_replay` | Function | `tools/can_replay/__main__.py` | 46 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → Recv` | intra_community | 3 |
| `Main → Write` | intra_community | 3 |
| `Main → Recv` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 2 calls |

## How to Explore

1. `context({name: "test_recorder_requires_open"})` — see callers and callees
2. `query({search_query: "can_replay"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
