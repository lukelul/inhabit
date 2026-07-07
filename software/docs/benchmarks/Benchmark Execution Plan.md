# Benchmark Execution Plan

Maps BENCHMARKS.md items 1-8 to required code, tests, and exit criteria.

---

## Per-Track Benchmarks (1-5): Every Branch, Before Merge

### 1. `scripts/verify.ps1` Passes

| Attribute | Value |
|-----------|-------|
| Required code | `firmware/test/test_*.c`, `host/tests/test_*.py` |
| Required tests | All C tests compile+run, all pytest tests pass |
| Hardware proof | None (host-side only) |
| Current status | GREEN -- working |
| Owner lane | All tracks |
| Exit criteria | Zero test failures on the branch |

### 2. New Subsystem Ships with >= 1 Test

| Attribute | Value |
|-----------|-------|
| Required code | Any new module in `firmware/src/` or `host/` |
| Required tests | At least one test file covering the new module |
| Hardware proof | None |
| Current status | GREEN -- all current modules have tests |
| Owner lane | Whoever creates the module |
| Exit criteria | `ls firmware/test/test_<module>.c` or `ls host/tests/test_<module>.py` exists and passes |

### 3. Files in Own Directory, Frozen Contracts Untouched

| Attribute | Value |
|-----------|-------|
| Required code | N/A (constraint check) |
| Required tests | `git diff` review against frozen files |
| Hardware proof | None |
| Current status | GREEN -- enforced by review process |
| Owner lane | All tracks + reviewer |
| Exit criteria | Diff shows no changes to `codec.py`, `can_frame.h`, `adapter.py`, `pvt.py`, `inhabit_msgs/` |

### 4. CodeRabbit No Unresolved Blocking Comments

| Attribute | Value |
|-----------|-------|
| Required code | N/A (review check) |
| Required tests | `gh pr view --comments` |
| Hardware proof | None |
| Current status | GREEN -- enforced by merge SOP |
| Owner lane | PR author |
| Exit criteria | CodeRabbit shows APPROVED or all Major comments resolved |

### 5. `embedded-reviewer` Returns OK

| Attribute | Value |
|-----------|-------|
| Required code | N/A (review check) |
| Required tests | `/review-firmware` output |
| Hardware proof | None |
| Current status | GREEN -- used for all firmware PRs |
| Owner lane | Reviewer agent |
| Exit criteria | Output is "OK" (not BLOCK or FIX) |

---

## System-Level Benchmarks (6-8): Green Light for Ultracode

### 6. End-to-End: Replayed CAN -> Bridge -> Episode -> Round-Trip

| Attribute | Value |
|-----------|-------|
| Required code | `host/inhabit_bridge/`, `host/logger/`, `host/inhabit_can/` |
| Required tests | Integration test: replay source -> bridge -> recorder -> parquet write -> read -> assert equal |
| Hardware proof | None (uses ReplaySource) |
| Current status | TBD -- need integration test that chains all components |
| Owner lane | Data pipeline + Host |
| Exit criteria | One automated pytest that proves the full pipeline round-trips |

### 7. GitHub Actions `verify` Workflow Green on `main`

| Attribute | Value |
|-----------|-------|
| Required code | `.github/workflows/ci.yml`, `scripts/verify.sh` |
| Required tests | CI passes: C tests + pytest + ruff + mypy |
| Hardware proof | None |
| Current status | GREEN -- CI is configured and running |
| Owner lane | All |
| Exit criteria | `gh run list --workflow=verify` shows latest run green |

### 8. GitNexus Re-Index Shows No Orphaned Modules

| Attribute | Value |
|-----------|-------|
| Required code | All modules properly importing/exporting |
| Required tests | `npx gitnexus analyze --force` + review clusters |
| Hardware proof | None |
| Current status | TBD -- depends on index freshness |
| Owner lane | Orchestrator |
| Exit criteria | Every module appears in at least one cluster; no "orphaned" nodes |

---

## Hardware-Gated Benchmarks (Deferred)

These do NOT block software benchmarks 1-8.

| Benchmark | Requirement | Status |
|-----------|-------------|--------|
| `colcon build` on Ubuntu 24.04 / ROS 2 Jazzy | Need Jazzy environment | DEFERRED |
| Live two-board CAN bus + jitter measurement | Need 2x assembled Rev-A boards | DEFERRED |
| MCP2515 /INT on verified pin (PB6) | Need hardware + scope | DEFERRED (pin CONFIRMED in schematic) |

---

## When 1-8 Are Green

Run ultracode:
> "Audit firmware + host for CAN-timing races, ISR safety, schema drift, and untested paths; verify every finding with an independent agent before reporting."

See [[docs/sop/release/Release and Handoff SOP]].
