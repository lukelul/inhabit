# AGENT_BINDINGS — role-bound worktrees (reuse existing; do not create duplicates)

Each worktree is a fixed-role agent. Reuse these; only create a new worktree if one is dirty,
branch-locked, or busy with an active PR. Before assigning: `git fetch origin`, confirm clean,
`git switch -c <task-branch> origin/main` inside the worktree (never reuse an old merged branch).
Every worker: Ponytail → read docs → GitNexus → name skills/docs/files/tests → protect frozen
contracts → verify.ps1 → PR → fix CodeRabbit → Process Evidence (WORKER_PROCESS_EVIDENCE.md). Do not merge.

State snapshot: 2026-06-29, main @5cf5fbe, 0 open PRs, verify green (136), GitNexus 2,029 nodes.

| Worktree | Role | Scope | Current branch | State | Active task |
|----------|------|-------|----------------|-------|-------------|
| `inhabit-enum` | firmware / ENUM | firmware/, docs/firmware/, docs/hardware/bringup/ | bench-v0.2/firmware-bench-harness-enum (merged) | IDLE · 🔒 two-board ENUM bench-blocked | none (needs Rev-A board; evidence: 2 pods → chain_index 0,1) |
| `inhabit-calib` | firmware / calibration | firmware/, tools/, docs/firmware/ | feat/calib (merged) | IDLE · 🔒 ADC sweep bench-blocked | none (needs board; evidence: monotonic angle_millideg across magnet rotation) |
| `inhabit-transport` | transport / bridge | host/transport/, host/inhabit_bridge/, docs/host/ | feat/transport (merged) | IDLE | candidate: implement slcan transport (audit: documented-as-planned) — assign only if user wants USB-slcan support (else YAGNI) |
| `inhabit-adapters` | adapters / ROS2 | host/adapters/, host/inhabit_bridge/, docs/host/ | feat/adapters (merged) | ⚠️ DIRTY (1 file) — clean before reuse | none |
| `inhabit-dataset` | dataset / export (owns main git ops) | host/logger/, host/export/, host/tests/, tools/dataset/, docs/data/ | worker/dataset-idle (kept synced to origin/main) | ACTIVE-orchestrator git base | none (dataset corruption gate already merged #25) |
| `inhabit-viz` | viz / demo | host/viz/, demo docs, operator runbooks | feat/viz (merged) | IDLE | none (viz + DEMO.md shipped #9/#19) |
| `inhabit-export-cli` | export CLI / dataset support | tools/dataset/, host/export/, docs/data/ | feat/export-cli (merged) | IDLE | none (export CLI shipped #13, gated #25) |
| `Inhabit-Software` (primary) | docs / release / orchestrator | docs/, README.md, STATUS.md, PROGRESS/ORCHESTRATION/ULTRACODE_*/AGENT_BINDINGS | main (clean) | ACTIVE-orchestrator | this binding + STATUS.md + post-#14 doc reconciliation |

## Standing facts
- Frozen contracts (CAN codec v1, RobotAdapter, PVTSample/PVT_SCHEMA_VERSION, JointPodState.msg): never edit.
- All Round 1–4 + ULTRACODE PRs merged; vault unified on main (#14). No code-worker has a non-churn
  task right now — most are IDLE (work shipped) or 🔒 HARDWARE-BLOCKED. Honest state, not fake assignment.
- Cleanup: merged role branches can be pruned per CLEANUP.md (worktree prune first). `inhabit-adapters`
  has 1 uncommitted file — inspect/clean before reusing it.
