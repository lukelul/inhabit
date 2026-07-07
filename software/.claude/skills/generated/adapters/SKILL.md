---
name: adapters
description: "Skill for the Adapters area of Inhabit-Software. 16 symbols across 6 files."
---

# Adapters

16 symbols | 6 files | Cohesion: 100%

## When to Use

- Working with code in `host/`
- Understanding how ReplayAdapter, ROS2Adapter, URAdapter work
- Modifying adapters-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/adapters/ur_adapter.py` | URAdapter, connect, read_state, send_command, capabilities |
| `host/tests/test_adapters.py` | test_connect_is_idempotent, test_connect_raises, test_read_state_raises, test_send_command_raises, test_capabilities_no_force_until_implemented |
| `host/adapters/ros2_adapter.py` | ROS2Adapter, connect |
| `host/inhabit_can/adapter.py` | RobotAdapter, SimAdapter |
| `host/adapters/replay_adapter.py` | ReplayAdapter |
| `host/sim/robot.py` | SimRobotAdapter |

## Entry Points

Start here when exploring this area:

- **`ReplayAdapter`** (Class) — `host/adapters/replay_adapter.py:14`
- **`ROS2Adapter`** (Class) — `host/adapters/ros2_adapter.py:18`
- **`URAdapter`** (Class) — `host/adapters/ur_adapter.py:10`
- **`RobotAdapter`** (Class) — `host/inhabit_can/adapter.py:24`
- **`SimAdapter`** (Class) — `host/inhabit_can/adapter.py:35`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `ReplayAdapter` | Class | `host/adapters/replay_adapter.py` | 14 |
| `ROS2Adapter` | Class | `host/adapters/ros2_adapter.py` | 18 |
| `URAdapter` | Class | `host/adapters/ur_adapter.py` | 10 |
| `RobotAdapter` | Class | `host/inhabit_can/adapter.py` | 24 |
| `SimAdapter` | Class | `host/inhabit_can/adapter.py` | 35 |
| `SimRobotAdapter` | Class | `host/sim/robot.py` | 477 |
| `connect` | Method | `host/adapters/ros2_adapter.py` | 55 |
| `test_connect_is_idempotent` | Method | `host/tests/test_adapters.py` | 230 |
| `connect` | Method | `host/adapters/ur_adapter.py` | 29 |
| `test_connect_raises` | Method | `host/tests/test_adapters.py` | 194 |
| `read_state` | Method | `host/adapters/ur_adapter.py` | 32 |
| `test_read_state_raises` | Method | `host/tests/test_adapters.py` | 199 |
| `send_command` | Method | `host/adapters/ur_adapter.py` | 35 |
| `test_send_command_raises` | Method | `host/tests/test_adapters.py` | 204 |
| `capabilities` | Method | `host/adapters/ur_adapter.py` | 38 |
| `test_capabilities_no_force_until_implemented` | Method | `host/tests/test_adapters.py` | 209 |

## How to Explore

1. `context({name: "ReplayAdapter"})` — see callers and callees
2. `query({search_query: "adapters"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
