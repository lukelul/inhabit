# AGENTS.md — shared rules for ALL coding agents (Claude, Codex, Copilot, etc.)

Claude Code reads `.claude/CLAUDE.md`; Codex and others read this file. They must stay in sync.
This is the short, shared contract. Full detail: `.claude/CLAUDE.md` and `.claude/skills/`.

## The 3 locked contracts (never break without a versioned decision)
1. **CAN schema v1** — ID `0x100 + node_id`, 8-byte payload:
   `[angle_raw_adc u16 LE][angle_millideg i16 LE][node_id u8][chain_index u8][status_flags u8][xor checksum u8]`.
   New telemetry = a NEW CAN ID block, never repurposed bytes.
2. **PVT sample schema** — time-aligned proprioceptive+visual+tactile; monotonic timestamps;
   atomic, append-only episodes; versioned fields.
3. **RobotAdapter interface** — connect / read_state / send_command / capabilities.
   Core code never branches on robot type.

## House rules
- Firmware (C, STM32C011): no heap after init; no blocking in ISRs; faults set `status_flags`,
  never hang; filter encoder ADC; prove SPI/CAN in loopback before live bus. The MCP2515 INT pin
  (A3 vs B6) is UNVERIFIED — confirm against the schematic, do not guess.
- Host (Python, ROS 2 Jazzy): type hints; ruff+mypy clean; robot logic behind RobotAdapter only.
- Be lazy in the ponytail sense: YAGNI, stdlib/native before deps, one line over fifty — but never
  cut validation, error handling, security, or accessibility.
- Small, reviewable diffs. Lead findings with the real-hardware failure mode.

## Lanes (so parallel agents don't collide)
firmware/ = firmware agent · host/ (ROS2) = ros2 agent · host/logger + dataset = data agent.
Agree the shared interface FIRST, then work in your lane on your own git worktree.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Inhabit-Software** (3877 symbols, 6963 relationships, 101 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Inhabit-Software/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Inhabit-Software/clusters` | All functional areas |
| `gitnexus://repo/Inhabit-Software/processes` | All execution flows |
| `gitnexus://repo/Inhabit-Software/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |
| Work in the Tests area (650 symbols) | `.claude/skills/generated/tests/SKILL.md` |
| Work in the Test area (68 symbols) | `.claude/skills/generated/test/SKILL.md` |
| Work in the Sim area (41 symbols) | `.claude/skills/generated/sim/SKILL.md` |
| Work in the Conformance area (36 symbols) | `.claude/skills/generated/conformance/SKILL.md` |
| Work in the Sensors area (31 symbols) | `.claude/skills/generated/sensors/SKILL.md` |
| Work in the Timing area (30 symbols) | `.claude/skills/generated/timing/SKILL.md` |
| Work in the Sinks area (19 symbols) | `.claude/skills/generated/sinks/SKILL.md` |
| Work in the Inhabit_bridge area (19 symbols) | `.claude/skills/generated/inhabit-bridge/SKILL.md` |
| Work in the Export area (18 symbols) | `.claude/skills/generated/export/SKILL.md` |
| Work in the Transport area (17 symbols) | `.claude/skills/generated/transport/SKILL.md` |
| Work in the Adapters area (16 symbols) | `.claude/skills/generated/adapters/SKILL.md` |
| Work in the Inhabit_can area (14 symbols) | `.claude/skills/generated/inhabit-can/SKILL.md` |
| Work in the Drivers area (11 symbols) | `.claude/skills/generated/drivers/SKILL.md` |
| Work in the Inhabit_core area (9 symbols) | `.claude/skills/generated/inhabit-core/SKILL.md` |
| Work in the Logger area (8 symbols) | `.claude/skills/generated/logger/SKILL.md` |
| Work in the Can_replay area (6 symbols) | `.claude/skills/generated/can-replay/SKILL.md` |
| Work in the Events area (5 symbols) | `.claude/skills/generated/events/SKILL.md` |

<!-- gitnexus:end -->
