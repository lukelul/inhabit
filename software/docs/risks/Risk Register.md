# Risk Register

## Hardware Risks

| # | Risk | Severity | Likelihood | Failure Mode | Detection | Mitigation | Owner | Status |
|---|------|----------|------------|--------------|-----------|------------|-------|--------|
| H1 | Wrong PCBA rotation (bottom-side) | HIGH | MEDIUM | Components placed upside down, board non-functional | Visual inspection, fab house 3D preview | Verify orientation in Altium 3D view + fab preview before ordering | Hardware lead | OPEN -- bottom-side orientation UNVERIFIED |
| H2 | MCP2515 oscillator mismatch | HIGH | LOW | CAN bit timing wrong, no communication | CAN bus analyzer, register readback | Verify 16 MHz crystal matches CNF1/2/3 configuration | Firmware | OPEN |
| H3 | CAN bus termination missing | MEDIUM | HIGH | Signal reflections, communication errors | Oscilloscope on CANH/CANL | Add 120-ohm resistors at both chain ends | Hardware lead | OPEN |
| H4 | Encoder magnet misalignment | HIGH | MEDIUM | Nonlinear output, dead zones, noisy readings | ADC sweep test at known angles | Mount fixture with adjustable height; calibration per pod | Hardware lead | OPEN |
| H5 | Noisy ENC_ADC | MEDIUM | HIGH | Jittery angle readings, poor training data | ADC noise floor measurement | Firmware filtering: oversample + median/IIR | Firmware | OPEN |
| H6 | 5V5/VCC_BUS confusion | MEDIUM | MEDIUM | Applying 5V to 3.3V logic, component damage | Schematic review, clear labeling | Document clearly in pin map; label on PCB silkscreen | Documentation | OPEN |
| H7 | STM dev module pin mismatch | HIGH | LOW | Wrong connections, board non-functional | Continuity check after soldering | Verify pinout against datasheet before soldering | Hardware lead | OPEN |
| H8 | ENUM race/noise | MEDIUM | MEDIUM | Wrong chain ordering, duplicate indexes | Multi-pod repeat test (10x) | Debounce (10 ticks), post-ENUM_DONE guard, chain overflow guard | Firmware | MITIGATED (firmware guards implemented) |

## Software Risks

| # | Risk | Severity | Likelihood | Failure Mode | Detection | Mitigation | Owner | Status |
|---|------|----------|------------|--------------|-----------|------------|-------|--------|
| S1 | Schema drift (firmware vs host) | HIGH | LOW | CAN frames decode incorrectly | Round-trip tests (C + Python) | Frozen contract: `can_frame.h` and `codec.py` locked, tested together | All | MITIGATED |
| S2 | Timestamp drift | HIGH | MEDIUM | PVT streams misaligned, useless training data | Jitter measurement + budget gate | Single monotonic clock, quarantine out-of-budget episodes | Data | MITIGATED |
| S3 | Dataset corruption | HIGH | LOW | Partial or invalid episodes in dataset | Round-trip read/write test | Atomic parquet writes (.part + rename + fsync), quarantine on failure | Data | MITIGATED |
| S4 | Agent modifying frozen contracts | HIGH | MEDIUM | Breaking change to schema/interface | CodeRabbit review, `impact()` analysis | AGENTS.md + CLAUDE.md rules, CI tests, reviewer agent | Orchestrator | MITIGATED |
| S5 | Stale GitNexus index | LOW | HIGH | Agents get wrong impact analysis | `detect_changes()` discrepancies | Re-index after merge batches: `npx gitnexus analyze --force` | Orchestrator | OPEN |
| S6 | CodeRabbit ignored | MEDIUM | LOW | Invalid changes merge to main | PR merge checklist | Merge criteria require no unresolved Major comments | Orchestrator | MITIGATED |
| S7 | Workers creating busywork | LOW | MEDIUM | Unnecessary changes, bloated diffs | Ponytail review, human oversight | Ponytail mode active, YAGNI principle, small reviewable diffs | Orchestrator | MITIGATED |
| S8 | Hardware not matching simulation | HIGH | MEDIUM | Code works in test but fails on real board | Hardware bring-up testing | Loopback mode first, then live bus; scope verification | Hardware lead | OPEN |

## Related Documents

- [[docs/hardware/bringup/Hardware Bring-Up SOP]]
- [[docs/hardware/pcba/PCBA and Fabrication SOP]]
- [[docs/sop/review/PR Review and Merge SOP]]
- [[docs/agents/Agent Operating Model]]

## Related Tests

- `firmware/test/test_can_frame.c` -- schema round-trip
- `firmware/test/test_enum.c` -- ENUM state machine
- `host/tests/` -- codec, bridge, logger, adapter tests
