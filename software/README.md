# Inhabit — Software & Firmware (Nexus setup)

The **software half** of Inhabit, kept separate from the hardware. The Altium PCB/schematic
project lives in its own repo; this one holds firmware, host/ROS 2, the data pipeline, and the
Level-6 Claude "Nexus" setup. Don't mix the two.

```text
firmware/   STM32C011 joint-pod firmware (C)      — to be built
host/       ROS 2 (Jazzy) bridge, adapters, PVT logger (Python) — to be built
.claude/    the brain: CLAUDE.md, 12 skills, 6 agents, 5 commands
```

## Start here

1. `START_HERE.md` — exact terminal commands (Claude Code, Ponytail, GitNexus).
2. `NEXUS-MAP.html` — open in a browser to see the whole setup visually.
3. `INHABIT_6_LEVEL_PLAYBOOK.md` — the 6 mastery levels applied to this project.
4. `RUNBOOK.md` — run 6 Claude agents + Codex in parallel across 8 terminals.
5. `ORCHESTRATION.md` — worktree orchestration details.
6. `SETUP_GUIDE.md` — install details for Claude Code + Cowork, MCP/plugin shortlist.

## The contracts (lock before parallel work)

CAN schema v1 · PVT sample schema · `RobotAdapter` interface — all in `.claude/CLAUDE.md` and
the skills. Change only by explicit, versioned decision.

## Documentation / Obsidian Vault

Open the repository root in Obsidian as the vault so the root-level `.obsidian/` settings and the docs tree stay in sync. Start at [`00-Inhabit Home.md`](00-Inhabit%20Home.md) for the command center, or open [`docs/README.md`](docs/README.md) for the vault index. Full project snapshot: [`KNOWLEDGE-TRANSFER.md`](KNOWLEDGE-TRANSFER.md).

## Relationship to the hardware repo
Hardware (Altium): board design, schematic, BOM, Gerbers. This repo consumes the hardware's
**pin map and CAN bus**, nothing else. Keep that boundary clean.
