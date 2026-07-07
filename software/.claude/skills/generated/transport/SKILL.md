---
name: transport
description: "Skill for the Transport area of Inhabit-Software. 17 symbols across 7 files."
---

# Transport

17 symbols | 7 files | Cohesion: 89%

## When to Use

- Working with code in `host/`
- Understanding how FileReplayTransport, InMemTransport, CanTransport work
- Modifying transport-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/transport/interface.py` | CanTransport, open, __enter__, close, __exit__ |
| `host/transport/inmem.py` | open, close, send, InMemTransport |
| `host/transport/file.py` | FileReplayTransport, close, __exit__ |
| `host/tests/test_transport_registry.py` | test_send_copies_data_defensively, test_close_drains_and_blocks |
| `host/tests/conformance/test_transport_conformance.py` | test_loopback |
| `host/transport/slcan.py` | SlcanTransport |
| `host/transport/socketcan.py` | SocketCanTransport |

## Entry Points

Start here when exploring this area:

- **`FileReplayTransport`** (Class) — `host/transport/file.py:120`
- **`InMemTransport`** (Class) — `host/transport/inmem.py:30`
- **`CanTransport`** (Class) — `host/transport/interface.py:16`
- **`SlcanTransport`** (Class) — `host/transport/slcan.py:17`
- **`SocketCanTransport`** (Class) — `host/transport/socketcan.py:14`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `FileReplayTransport` | Class | `host/transport/file.py` | 120 |
| `InMemTransport` | Class | `host/transport/inmem.py` | 30 |
| `CanTransport` | Class | `host/transport/interface.py` | 16 |
| `SlcanTransport` | Class | `host/transport/slcan.py` | 17 |
| `SocketCanTransport` | Class | `host/transport/socketcan.py` | 14 |
| `test_loopback` | Method | `host/tests/conformance/test_transport_conformance.py` | 90 |
| `test_send_copies_data_defensively` | Method | `host/tests/test_transport_registry.py` | 109 |
| `test_close_drains_and_blocks` | Method | `host/tests/test_transport_registry.py` | 129 |
| `open` | Method | `host/transport/inmem.py` | 54 |
| `close` | Method | `host/transport/inmem.py` | 57 |
| `send` | Method | `host/transport/inmem.py` | 62 |
| `close` | Method | `host/transport/file.py` | 75 |
| `open` | Method | `host/transport/interface.py` | 20 |
| `close` | Method | `host/transport/interface.py` | 24 |
| `__exit__` | Method | `host/transport/file.py` | 84 |
| `__enter__` | Method | `host/transport/interface.py` | 35 |
| `__exit__` | Method | `host/transport/interface.py` | 39 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 3 calls |

## How to Explore

1. `context({name: "FileReplayTransport"})` — see callers and callees
2. `query({search_query: "transport"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
