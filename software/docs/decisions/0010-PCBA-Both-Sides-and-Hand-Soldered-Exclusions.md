# ADR-0010: PCBA Both-Sides and Hand-Soldered Exclusions

## Status
Accepted

## Context
The Rev-A board has components on both sides. The STM32 dev module has a different footprint than the bare chip and cannot be placed by PCBA pick-and-place.

## Decision
- Order both-sides PCBA (if board layout requires it)
- Exclude STM32 dev module from PCBA BOM/CPL
- Hand-solder the dev module after PCBA arrives
- Document excluded parts in PCBA remarks

## Failure Mode Prevented
- Fab house attempting to place a dev module with wrong footprint (board damage)
- Bottom-side components placed with wrong orientation (orientation UNVERIFIED -- must confirm before ordering)

## Alternatives Considered
1. Redesign to single-side only -- rejected: board layout constraints
2. Use bare STM32 chip in Rev-A -- rejected: hand-soldering QFP/QFN is harder than dev module
3. Skip PCBA, hand-assemble everything -- rejected: too much labor for passive components

## Consequences
- Positive: PCBA handles most components; hand-solder only the dev module
- Trade-off: extra hand-assembly step after PCBA
- Risk: bottom-side orientation must be verified before ordering

## Related Source Files
- Hardware repo (Altium project -- separate repo)

## Open Questions
- Exact components on bottom side (verify from Altium 3D view)
- Whether bottom-side PCBA is actually needed or all critical parts fit on top
