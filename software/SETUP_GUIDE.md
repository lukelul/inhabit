# Setup Guide — install this in Claude Code AND Cowork

## What's in this bundle
```
inhabit-claude-setup/
  .claude/
    CLAUDE.md                 # the brain (Level 3)
    skills/<6 skills>/SKILL.md # your workflows (Level 5)
    agents/<6 agents>.md       # your team (Level 6)
    commands/<5 commands>.md    # slash commands (Level 5)
  firmware/CLAUDE.md           # firmware-local memory
  host/CLAUDE.md               # host-local memory
  ORCHESTRATION.md             # Level 6 playbook
  INHABIT_6_LEVEL_PLAYBOOK.md  # the mastery map
  SETUP_GUIDE.md               # this file
```

## A. Claude Code (terminal) — primary for firmware/ROS2 work
1. Put the repo on disk and copy `.claude/`, `firmware/CLAUDE.md`, `host/CLAUDE.md` into it
   (keep the same relative paths). Commit them — the team shares one brain.
2. Verify discovery:
   - `/agents` → should list firmware-engineer, ros2-integrator, data-pipeline-engineer,
     hardware-bringup, embedded-reviewer, research-scout.
   - `/help` or type `/` → should show /bringup, /can-msg, /ros2-node, /review-firmware, /orchestrate.
   - Skills load automatically by description; trigger words are in each SKILL.md.
3. Worktrees for parallel agents: see ORCHESTRATION.md (`git worktree add ...`), one `claude`
   session per worktree.

## B. Cowork (this app) — primary for research, data, planning, scheduled runs
1. Connect a folder (the repo) so Claude can read/write the same `.claude/`.
2. The same skills/agents work; spawn one agent per track for parallel work, and use a
   worktree-isolated agent for risky changes.
3. Use **scheduled tasks** for recurring jobs: a nightly "summarize bring-up log + open risks,"
   or a weekly "scan new arXiv robot-learning papers relevant to last-centimeter data."
4. Use **artifacts** for a live dashboard (e.g. latest bring-up status, dataset episode counts)
   that refreshes from your connectors.

## C. MCPs — surgical selection (Level 4, avoid the candy shop)
Install per track, not all at once. High-value for Inhabit:
- **GitHub** — the repo, PRs, issues. (Core for both environments.)
- **Exa** (`web_search_exa`, `get_code_context_exa`) — pull STM32/MCP2515 datasheet details and
  ROS 2 API docs into context fast.
- **Microsoft Learn** — trusted docs for toolchain/driver questions.
- **alphaXiv** — arXiv robot-learning / imitation-learning / world-model papers for the data thesis.
- **Local serial/CAN bridge** — for hardware bring-up, a small MCP or script exposing a USB-CAN
  sniffer + SWD flash to the agent (host-side; you build this as you reach Phase 2).
Skip finance/CRM/marketing MCPs — they're pure context tax here.

## D. Plugins worth installing (from the ecosystem)
- **Skill Creator** (Anthropic) — author/iterate/eval new Inhabit skills as workflows emerge (L5).
- **GitHub CLI** plugin — repo automation from the terminal.
- **Playwright** — only if/when you build a web dashboard or test the data-viz UI.
- **Supabase** / a Postgres plugin — when the data engine needs a backend for episode metadata.
- **Firecrawl / a research plugin** — bulk-pull datasheets and vendor docs for the $80 pod BOM.
Add them via `/plugin marketplace add` then `/plugin install` in Claude Code; install matching
ones in Cowork. Rule of thumb: install when a track needs it, remove when the track is done.

## E. First 30 minutes
1. Copy the bundle in, confirm `/agents` and `/` show everything.
2. Skim `INHABIT_6_LEVEL_PLAYBOOK.md` and `ORCHESTRATION.md`.
3. Sanity prompt: "Using the can-protocol skill, generate the C and Python codecs for schema v1
   plus round-trip tests." Confirm the output matches CLAUDE.md byte-for-byte.
4. When the board arrives: `/bringup` and go stage by stage.
5. As real workflows repeat, use Skill Creator to add skills — keep the set small and curated.
