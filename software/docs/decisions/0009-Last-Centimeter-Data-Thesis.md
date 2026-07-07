# ADR-0009: Last Centimeter Data Thesis

## Status
Proposed

## Context
Robot foundation models fail during contact because training datasets lack tactile ground truth for the manipulation phase.

## Decision
Invest in contact-sensing hardware (MEMS mic + motor current) and build the PVT pipeline to capture and label contact events during human demonstrations.

## Failure Mode Prevented
- Training on data that stops being useful at contact (the whole point of manipulation)
- Relying only on cameras that can't see through the gripper

## Alternatives Considered
1. Force/torque sensors only -- rejected: expensive, not modular enough
2. Simulation-only contact data -- rejected: sim-to-real gap for contact is huge
3. Post-hoc labeling from video -- rejected: can't label what you can't see

## Consequences
- Positive: unique data asset (no one else is collecting synchronized PVT with contact labels)
- Positive: cheap sensors (MEMS mic ~$0.50, motor current is "free")
- Trade-off: unproven hypothesis (needs experimental validation)

## Related Source Files
- `host/inhabit_can/pvt.py` (`tactile_event` field)

## Open Questions
- MEMS mic detection accuracy for different manipulation tasks
- Motor current correlation with contact events across different loads
- Minimum viable sensor set for reliable contact detection
