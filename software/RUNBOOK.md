# RUNBOOK — running 6 Claude agents + Codex in parallel (8 terminals)

The goal: you are the manager. Multiple coding agents work at once, each in its own git
**worktree** (a separate working copy of the same repo), all bound by the shared contracts in
`AGENTS.md` / `.claude/CLAUDE.md`. They don't talk to each other — they stay coherent because they
obey the same schema and interface, and CodeRabbit + the reviewer agent gate every merge.

## 0. One-time prerequisites
```bash
node --version            # need 22+
npm install -g @openai/codex     # Codex CLI   -> codex --version
# Claude Code already installed; gh (GitHub CLI) recommended: https://cli.github.com
```
Install CodeRabbit on the GitHub repo (no CI needed): https://coderabbit.ai → Login with GitHub →
authorize → pick this repo. The `.coderabbit.yaml` in the root tunes it for our firmware/host rules.

## 1. Create the worktrees (run once, from the repo root)
```bash
git worktree add ../inhabit-fw    feat/firmware
git worktree add ../inhabit-host  feat/host
git worktree add ../inhabit-data  feat/data
git worktree add ../inhabit-codex feat/codex
git worktree list
```

## 2. The 8-terminal layout (VS Code: split the terminal panel into a grid)
| # | Terminal           | Folder              | Run                | Role |
|---|--------------------|---------------------|--------------------|------|
| 1 | MANAGER (you)      | repo root (main)    | `claude`           | `/orchestrate`, merge PRs, keep contracts locked |
| 2 | firmware agent     | ../inhabit-fw       | `claude`           | "act as firmware-engineer" |
| 3 | ros2 agent         | ../inhabit-host     | `claude`           | "act as ros2-integrator" |
| 4 | data agent         | ../inhabit-data     | `claude`           | "act as data-pipeline-engineer" |
| 5 | bring-up agent     | repo root           | `claude`           | "act as hardware-bringup" (bench work) |
| 6 | reviewer agent     | repo root           | `claude`           | `/review-firmware` on each branch before merge |
| 7 | research scout     | repo root           | `claude`           | "act as research-scout" (datasheets, papers) |
| 8 | CODEX              | ../inhabit-codex    | `codex`            | second coding agent: parallel feature OR cross-check the others' diffs |

That's 6 Claude agents (2–7) + manager (1) + Codex (8) = 8 terminals, all live at once.
Codex reads `AGENTS.md`, so it obeys the same contracts as the Claude agents.

## 3. The dispatch loop (what you actually do)
1. **Lock the interface first.** In T1: `/orchestrate "bring CAN telemetry up across two boards and log it"`.
   It decomposes into tracks and names the agent + worktree + done-criteria for each. Confirm the
   shared CAN message / RobotAdapter signature is settled BEFORE fanning out.
2. **Dispatch.** In each agent terminal, paste its task (e.g. T2: "implement MCP2515 CAN TX per the
   stm32-firmware + can-protocol skills; loopback first"). They run simultaneously.
3. **Lean.** Ponytail is active in every session — agents write the minimum that works.
4. **Gate.** When a branch is ready: in T6 run `/review-firmware` (the embedded-reviewer agent),
   then push the branch and open a PR — **CodeRabbit** reviews it automatically on GitHub.
5. **Merge in dependency order** (the schema-defining track first) from T1.
6. **Re-graph.** After merges: `npx gitnexus analyze --force` → the code map updates → the next
   round of agents queries a richer map. (Keep `npx gitnexus serve` open in a browser tab.)
7. `/clear` between unrelated dispatches to keep each context lean.

## 4. Two agents "building together" — how it actually works
Run T2 (firmware) and T3 (host) at the same time. They never message each other. They converge
because firmware emits CAN schema v1 and the host parses CAN schema v1 — the contract is the
handshake. Codex (T8) can take a third lane, or you point it at the open PRs to find what the
Claude agents missed. Different engines, same rulebook = real cross-checking, not echo.

## 5. The non-negotiable rule
**Agree the contract before you fan out, every feature.** Six agents + Codex amplify each other
only when they share one schema/interface. Skip that and you get eight incompatible versions of
the same thing. The contracts live in `AGENTS.md` and `.claude/CLAUDE.md` so every engine reads
the same truth.

## SOPs
Detailed SOPs live in the Obsidian vault:
- [`docs/sop/development/Autonomous Development SOP.md`](docs/sop/development/Autonomous%20Development%20SOP.md)
- [`docs/sop/review/PR Review and Merge SOP.md`](docs/sop/review/PR%20Review%20and%20Merge%20SOP.md)
- [`docs/sop/software/Verification SOP.md`](docs/sop/software/Verification%20SOP.md)
- [`docs/agents/Agent Operating Model.md`](docs/agents/Agent%20Operating%20Model.md)

## Cleanup
```bash
git worktree remove ../inhabit-fw    # when a track is merged & done
```
