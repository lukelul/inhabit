# ADR-0006: RobotAdapter Frozen Contract

## Status
Accepted (FROZEN)

## Context
The system must support multiple robot protocols without the core code branching on robot type.

## Decision
Abstract `RobotAdapter` interface: `connect()`, `read_state()`, `send_command()`, `capabilities()`. Core code never branches on robot type. New robot = new adapter file. Frozen.

## Failure Mode Prevented
- Robot-specific code leaking into core (makes pipeline brittle)
- Breaking existing adapters when adding new ones
- Core code growing conditional branches for each robot

## Alternatives Considered
1. Robot-specific modules with shared utilities -- rejected: leads to `if robot == "ur"` everywhere
2. ROS 2 action servers per robot -- rejected: too heavyweight for the adapter pattern
3. Plugin discovery (entry points) -- rejected for now: YAGNI at current scale

## Consequences
- Positive: clean separation of concerns
- Positive: SimAdapter enables full pipeline testing without hardware
- Positive: new robots are additive (new file, no existing code changes)
- Trade-off: interface may be too narrow for some robots (mitigated by `capabilities()`)

## Related Source Files
- `host/inhabit_can/adapter.py`
- `host/adapters/replay_adapter.py`, `host/adapters/ur_adapter.py`, `host/adapters/ros2_adapter.py`

## Related Tests
- `host/tests/test_*` (adapter-related tests)

## Open Questions
- None (frozen)
