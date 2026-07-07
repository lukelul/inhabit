---
name: embedded-review
description: Use to review embedded C or ROS 2/Python diffs for the Inhabit project against the house rules before merge. Triggers on "review this firmware", "review the diff", "code review", "is this safe", "PR review", "check this driver".
---

# Inhabit Embedded/Host Review

Review against the project's hard rules. Output a verdict (BLOCK / FIX / OK) with file:line refs.

## Firmware checklist
- [ ] No dynamic allocation after init; no blocking calls in ISRs.
- [ ] ISRs only set flags / move data; logic runs in main loop.
- [ ] CAN frames match schema v1; checksum computed; correct endianness (LE).
- [ ] Faults set `status_flags`; no silent hang or infinite retry.
- [ ] Encoder ADC filtered; magnet-OOB handled.
- [ ] Pin/peripheral usage matches the **confirmed** schematic (flag any A3-vs-B6 INT guess).
- [ ] MCP2515 timing computed for 16 MHz osc; mode transitions verified via CANSTAT.
- [ ] No new compiler warnings; pure logic has host-side tests.

## Host / ROS 2 checklist
- [ ] Robot-specific logic stays behind `RobotAdapter`; no `isinstance` on robot types in core.
- [ ] Time-sync preserved; timestamps monotonic; jitter measured.
- [ ] Schema changes versioned with migrations; no silent field changes.
- [ ] QoS appropriate; nodes parameterized & launch-driven; logic unit-tested off-graph.
- [ ] ruff + mypy clean; Jazzy pinned.

## Review style
Lead with the highest-severity issue and the failure it would cause on real hardware
(bus lockup, ESD, occluded contact mislabeled, etc.). Be specific; suggest the fix. Praise is fine
but brief. A clean diff gets an explicit OK.
