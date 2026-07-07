# Agent Operating Model

## Overview

Inhabit uses a multi-agent orchestration system where a human manager directs specialized Claude agents (and optionally Codex) working in parallel on isolated git worktrees. Convergence comes from shared contracts, not agent-to-agent communication.

---

## Roles

### Orchestrator (Human Manager)

- Runs in Terminal 1 on repo root (`main` branch)
- Uses `/orchestrate` to decompose goals into track assignments
- Locks contracts BEFORE fanning out agents
- Merges PRs in dependency order
- Runs verification after each merge
- Re-indexes GitNexus after merge batches
- Uses `/clear` between unrelated dispatches

### Worker Agents

| Agent | Lane | Worktree | Branch Pattern | Owns |
|-------|------|----------|----------------|------|
| `firmware-engineer` | Firmware | `../inhabit-fw` | `feat/fw-*` | `firmware/` |
| `ros2-integrator` | Host/ROS2 | `../inhabit-host` | `feat/host-*` | `host/` (ROS2 parts) |
| `data-pipeline-engineer` | Data | `../inhabit-data` | `feat/data-*` | `host/logger/`, `dataset/` |
| `hardware-bringup` | Hardware | repo root | (bench) | Physical board |
| `research-scout` | Research | repo root | -- | Papers, datasheets |

### Review Agent
- `embedded-reviewer`: adversarial review of firmware and host diffs
- Invoked via `/review-firmware` before each merge
- Returns BLOCK / FIX / OK with file:line and failure mode

### CodeRabbit
- Automated PR review on GitHub
- Configured via `.coderabbit.yaml` (tuned for firmware/host rules)
- Reviews every PR automatically
- Blocking: unresolved Major comments must be resolved before merge
- Non-blocking: minor suggestions can be noted and deferred

### Codex (Optional)
- Runs in Terminal 8 on `../inhabit-codex` worktree
- Reads `AGENTS.md` -- obeys same contracts
- Used for: parallel feature work, or cross-checking Claude agents' diffs
- Different engine, same rulebook = real cross-checking

### GitNexus
- Code intelligence MCP indexing the repo as a knowledge graph
- **Must run `impact()` before editing any symbol**
- **Must run `detect_changes()` before committing**
- **Must warn user** if impact analysis returns HIGH or CRITICAL risk
- Re-index after merge batches: `npx gitnexus analyze --force`
- Serves a browsable web UI: `npx gitnexus serve`
- Never use find-and-replace for renames -- use `rename` tool

### CI Role
- `.github/workflows/ci.yml` runs on every PR and push to main
- Tests: pytest, ruff (blocking), mypy (blocking)
- `scripts/verify.ps1` / `scripts/verify.sh` run firmware C tests + host pytest

### Obsidian Role
- This documentation vault provides the operating manual for humans and agents
- Updated after significant changes
- Agents can reference docs for SOPs and architecture

---

## Contract Enforcement

Four locked contracts prevent parallel agents from producing incompatible work:

1. **CAN schema v1**: ID `0x100 + node_id`, 8-byte layout, XOR checksum
2. **PVT sample schema**: time-aligned PVT, monotonic timestamps, versioned fields
3. **RobotAdapter interface**: `connect / read_state / send_command / capabilities`
4. **JointPodState.msg**: `host/inhabit_msgs/JointPodState.msg` is frozen; keep its fields aligned with the bridge and logger pipeline

**Rule:** Lock contracts BEFORE dispatching agents. Change only by explicit, versioned decision.

---

## PR Merge Rules

1. Merge in dependency order (schema-defining track first)
2. Squash merge + delete branch
3. All CI checks green
4. No unresolved Major CodeRabbit comments
5. `embedded-reviewer` returns OK
6. Run `scripts/verify.ps1` after each merge on `main`
7. GitNexus re-index after merge batch

---

## Worktree Rules

```bash
# Create worktrees (one per track)
git worktree add ../inhabit-wt-firmware feat/fw-can-bringup
git worktree add ../inhabit-wt-host     feat/host-bridge
git worktree add ../inhabit-wt-data     feat/data-logger

# Each worktree gets its own Claude session
cd ../inhabit-wt-firmware && claude

# Cleanup when done
git worktree remove ../inhabit-wt-firmware
```

---

## Frozen Contract Rules

- Never edit files containing frozen contracts
- New telemetry = new CAN ID block (never repurpose existing bytes)
- New robot = new adapter file (never `if robot_type ==` in core)
- Schema changes = version bump + migration function
- `JointPodState.msg` remains frozen; updates require a versioned protocol decision
- Agents must verify via `impact()` that changes don't touch frozen symbols

---

## How ORCHESTRATION.md Is Updated

The orchestrator updates the "Live orchestration status" table in `ORCHESTRATION.md` after each round:
- PR status (CI, CodeRabbit, state)
- Blocked PRs with exact fix requests
- Next action
- Frozen contract verification

---

## How BENCHMARKS.md Controls the Finish Line

Items 1-5 gate each PR. Items 6-8 gate the system. When 1-8 are all green, flip on ultracode for repo-wide hardening.

---

## What Each Agent Is Allowed to Touch

| Agent | Can Touch | Must Not Touch |
|-------|-----------|----------------|
| `firmware-engineer` | `firmware/` | `host/`, frozen contracts |
| `ros2-integrator` | `host/` (non-logger) | `firmware/`, frozen contracts |
| `data-pipeline-engineer` | `host/logger/`, `dataset/` | `firmware/`, frozen contracts |
| `hardware-bringup` | `docs/bringup-log.md`, physical board | Code (except debug prints) |
| `research-scout` | Nothing (read-only) | Everything |
| `embedded-reviewer` | Nothing (review only) | Everything |

---

## What to Do When an Agent Gets Stuck

1. Check if it's blocked by a frozen contract (it should be)
2. Check if it needs information from another lane (use the contract, not direct communication)
3. If genuinely stuck on a technical issue, ask the research-scout agent
4. If blocked by a PR review, resolve CodeRabbit comments first
5. If CI is failing, debug locally before retrying
6. If worktree is stale, rebase on main
7. If GitNexus index is stale, re-index: `npx gitnexus analyze --force`
8. Use `/clear` and restart with a fresh context
