# START HERE — Inhabit Nexus (terminal-ready)

Everything is installed in this repo. Open a terminal and run these in order. That's it.

```bash
# 0. go to the project
cd "C:\Users\youss\OneDrive\Documents\Altium_Projects\Inhabit-Software"
```

## 1. The brain (already here — just verify)
```bash
claude                 # start Claude Code in this folder; the brain auto-loads
# inside Claude Code:
/agents                # → 6 agents (firmware-engineer, ros2-integrator, ...)
/                      # → /bringup /can-msg /ros2-node /review-firmware /orchestrate
```
Skills (12) load automatically by description — 6 Inhabit + 6 Ponytail. Nothing to do.

## 2. Ponytail — full plugin (adds always-on mode + hooks)
The skills already work. This adds the `/ponytail lite|full|ultra` switches and auto-activation.
```bash
# inside Claude Code:
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail
```
(Needs Node.js on PATH for the always-on hooks; skills work even without it.)

## 3. GitNexus — the VISUAL knowledge-graph brain you can see
Run these in a normal terminal (not inside Claude), from the repo root.
```bash
# one-time: wire GitNexus into your editors as an MCP server
npx gitnexus setup

# build the knowledge graph. --skip-agents-md PROTECTS the CLAUDE.md brain we wrote.
npx gitnexus analyze --skip-agents-md

# SEE IT: launch the local web UI, then open the URL it prints (usually http://localhost:3000)
npx gitnexus serve

# optional: generate a browsable wiki from the graph
npx gitnexus wiki
```
Useful extras: `npx gitnexus status` · `npx gitnexus analyze --force` (re-index) ·
`npx gitnexus list`.

> Heads-up: right now this repo is mostly Altium files (schematic, PCB, BOM) plus the brain's
> markdown, so the graph will be sparse. It gets rich once you add `firmware/` and `host/` code —
> re-run `npx gitnexus analyze --force` after you write code and the graph fills in.

## 4. First real move
```bash
# inside Claude Code:
/orchestrate "bring CAN telemetry up across two boards and log it"
# or, a great first task while the board is in fab:
#   "verify the MCP2515 INT pin (A3 vs B6) from Inhabit.SchDoc and update the brain"
```

## 5. Documentation vault
Open `docs/` in Obsidian or start at [`00-Inhabit Home.md`](00-Inhabit%20Home.md).
New engineer? Read [`docs/00-start/START-HERE-Inhabit.md`](docs/00-start/START-HERE-Inhabit.md).

## How the two "brains" fit together
- **.claude/ (the brain we built):** your standards, schema, agents, workflows. Tells Claude HOW
  to work on Inhabit. Travels in git.
- **GitNexus (the visual brain):** indexes the actual repo into a graph + wiki you can browse, and
  lets Claude query "what calls what." Tells Claude WHAT is in the code.
They complement each other: opinion + map.
