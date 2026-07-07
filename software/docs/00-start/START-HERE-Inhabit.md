# START HERE -- Inhabit Onboarding Guide

Welcome. This guide gets you productive on the Inhabit project in one sitting.

---

## What Inhabit Is

A **universal teleoperation kernel**: modular smart joint pods (hardware) + an ML-native data ingestion layer (software) that turns human robot control into synchronized **Proprioceptive-Visual-Tactile (PVT)** training data.

The joint pod is the physical API. The data engine is the business. The "last centimeter" (contact, occlusion, force, friction, recovery) is the wedge that current robot foundation models lack.

We are **not** building a controller. We build the data pipeline.

---

## How the Repo Is Organized

```text
Inhabit-Software/
  firmware/          STM32C011 joint-pod firmware (C)
    src/             Source: main.c, can_frame.c, enum.c, calib.c, can_health.c
    inc/             Headers: can_frame.h, mcp2515.h, enum.h, calib.h, can_health.h
    drivers/         MCP2515 SPI driver
    test/            Host-side C unit tests
  host/              ROS 2 (Jazzy) bridge, adapters, PVT logger (Python)
    inhabit_can/     CAN codec, RobotAdapter, PVTSample (FROZEN)
    inhabit_bridge/  CAN->ROS2 bridge node, sources, conversion
    transport/       CanTransport interface, file replay, socketcan
    adapters/        ReplayAdapter, ROS2Adapter, URAdapter (stub)
    logger/          EpisodeRecorder, jitter, parquet I/O
    inhabit_msgs/    ROS 2 message definitions (JointPodState)
    viz/             Visualization (TBD)
    export/          Dataset export (TBD)
    tests/           Python tests
  tools/             calibrate.py, can_replay, dataset utilities
  scripts/           verify.ps1, verify.sh
  .claude/           Agent brain: CLAUDE.md, skills, agents, commands
  .github/workflows/ CI pipeline (ci.yml)
  docs/              This documentation vault
```

---

## What to Read First

1. This file
2. [[KNOWLEDGE-TRANSFER|KNOWLEDGE-TRANSFER.md]] -- full project snapshot
3. [[docs/architecture/System Architecture|System Architecture]] -- data flow diagram
4. `AGENTS.md` -- the three locked contracts
5. [[BENCHMARKS.md|BENCHMARKS]] -- what "done" means

---

## How to Run Verification

```powershell
# PowerShell (Windows):
pwsh scripts/verify.ps1

# Bash (Linux/CI):
bash scripts/verify.sh
```

This runs:
- Firmware C tests (can_frame, calib, mcp2515, can_health, enum)
- Host Python tests (pytest)
- ruff lint (advisory locally, blocking in CI)
- mypy type check (advisory locally, blocking in CI)

Green = safe to commit.

---

## How to Understand the Architecture

Read the data flow: **MT6701 encoder -> STM32 ADC -> calibration -> CAN frame (schema v1) -> MCP2515 TX -> CAN bus -> host codec -> bridge node -> JointPodState -> logger -> PVT episode -> parquet export**.

See [[docs/architecture/System Architecture]] for the full diagram.

---

## How Not to Break Frozen Contracts

Four artifacts are **frozen** -- imported, never edited:

| Contract | Files |
|----------|-------|
| CAN schema v1 | `firmware/inc/can_frame.h`, `firmware/src/can_frame.c`, `host/inhabit_can/codec.py` |
| RobotAdapter | `host/inhabit_can/adapter.py` |
| PVTSample | `host/inhabit_can/pvt.py` |
| JointPodState.msg | `host/inhabit_msgs/` |

New telemetry = new CAN ID block, never repurposed bytes. New robot = new adapter file, never a new `if` in core code.

---

## How PRs Are Created and Reviewed

1. Work on a feature branch (or worktree for parallel agents)
2. Run `scripts/verify.ps1` locally
3. Push and open a PR via `gh pr create`
4. **CodeRabbit** reviews automatically (configured in `.coderabbit.yaml`)
5. **embedded-reviewer** agent reviews firmware/host diffs
6. No unresolved Major CodeRabbit comments before merge
7. Squash merge + delete branch
8. Run `verify.ps1` on `main` after merge
9. Re-index GitNexus: `npx gitnexus analyze --force`

See [[docs/sop/review/PR Review and Merge SOP]] for details.

---

## How to Use GitNexus

GitNexus indexes the repo as a code intelligence knowledge graph.

```bash
# Setup (one-time)
npx gitnexus setup

# Index the repo
npx gitnexus analyze --skip-agents-md

# Browse the graph
npx gitnexus serve
```

As an agent, use the MCP tools:
- `impact({target: "symbolName"})` -- before editing anything
- `context({name: "symbolName"})` -- full caller/callee/flow info
- `query({search_query: "concept"})` -- find execution flows
- `detect_changes()` -- before committing

---

## How to Use Obsidian

Open the repo root in Obsidian as a vault. Navigate from [[00-Inhabit Home]] to reach any document. All links use `[[wikilinks]]`.

---

## How to Use the Agent System

See [[docs/agents/Agent Operating Model]] and `RUNBOOK.md`.

- 6 Claude agents + Codex, each in a git worktree
- Contracts locked before fanning out
- `embedded-reviewer` gates every merge
- CodeRabbit reviews every PR
- GitNexus re-indexed after merges

---

## How to Contribute Safely

1. Read this file and `AGENTS.md`
2. Never touch frozen contracts
3. Work in your lane (firmware/ or host/ or host/logger)
4. Run verification before pushing
5. Open small, reviewable PRs
6. Lead with the failure mode -- what breaks and how we detect it
7. When unsure about hardware pins, say so and ask -- do not guess silicon
