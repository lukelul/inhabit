# ADR-0002: ENUM Protocol

## Status
Accepted

## Context
Identical joint pods need to discover their position in a kinematic chain without pre-configuration.

## Decision
GPIO-based chain ordering:
1. All pods power on un-indexed (ST_NOT_ENUMERATED set)
2. Pod with ENUM_IN asserted claims `chain_index = max(peer CAN indexes) + 1` or 0 if none
3. Debounce ENUM_IN for 10 ticks before accepting
4. Delay 5 ticks after assignment, then assert ENUM_OUT
5. Chain overflow (> 0xFE) -> stays un-enumerated
6. Post-ENUM_DONE guard: late/duplicate peer traffic ignored

## Failure Mode Prevented
- Glitch on ENUM line causing false enumeration (debounce)
- Late CAN peer frame corrupting committed chain_index (post-DONE guard)
- Chain overflow wrapping index back to 0 (0xFF sentinel + max guard)
- ISR race on peer index update (single-word store + latch handoff)

## Alternatives Considered
1. Software enumeration via host command -- rejected: requires host awareness, not truly modular
2. DIP switches on each pod -- rejected: not plug-and-play, manufacturing burden
3. I2C enumeration -- rejected: needs extra bus, CAN already available for peer discovery

## Consequences
- Positive: fully automatic, no configuration needed
- Positive: works for chains up to 255 pods
- Trade-off: depends on ENUM line physical wiring between pods

## Related Source Files
- `firmware/src/enum.c`, `firmware/inc/enum.h`

## Related Tests
- `firmware/test/test_enum.c`

## Open Questions
- None
