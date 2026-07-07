# ADR-0008: Universal Teleop Kernel

## Status
Accepted

## Context
The robotics ML field lacks synchronized, contact-rich demonstration data. Building a single-purpose robot controller doesn't address this gap.

## Decision
Build a **universal teleoperation kernel**: modular hardware pods + protocol-agnostic software pipeline that produces ML-ready PVT datasets from any robot.

## Failure Mode Prevented
- Building hardware that only works with one robot (adapter pattern prevents this)
- Collecting data that can't be used for training (schema versioning + jitter gate)
- Missing the "last centimeter" data (PVT triplet captures contact phase)

## Alternatives Considered
1. Build a robot arm company -- rejected: the data pipeline is the moat, not the hardware
2. Camera-only data collection -- rejected: cameras can't see through grippers during contact
3. Use existing teleoperation systems -- rejected: none produce synchronized PVT with contact labels

## Consequences
- Positive: hardware + software + data flywheel
- Positive: protocol-agnostic means broad applicability
- Trade-off: ambitious scope (hardware + firmware + host + ML pipeline)

## Related Source Files
- `.claude/CLAUDE.md` (vision section)
- `host/inhabit_can/pvt.py` (data schema)
- `host/inhabit_can/adapter.py` (protocol abstraction)

## Open Questions
- Optimal pod cost target for volume manufacturing
- Which manipulation benchmarks to target first
