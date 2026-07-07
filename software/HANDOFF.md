# HANDOFF — Inhabit Software (read this first)

Single-file knowledge transfer to continue the project in a fresh session. Pair with
`CLAUDE.md`, `AGENTS.md`, `ORCHESTRATION.md`, `BENCHMARKS.md`, `RUNBOOK.md`, `REVIEW-GUIDE.md`.

## 1. What Inhabit is
A universal teleoperation kernel: modular smart-joint pods (hardware) + an ML-native data
ingestion layer (software) that turns human robot control into synchronized
Proprioceptive–Visual–Tactile (PVT) training data. The joint pod is the physical API; the
data engine is the business; the "last centimeter" (contact/occlusion/force) is the wedge.
This repo is the SOFTWARE half only — hardware (Altium) lives in a separate repo. Never mix them.

## 2. Frozen contracts (import only — never modify without a versioned decision + failure-mode note)
- CAN schema v1 — `firmware/inc/can_frame.h` ↔ `host/inhabit_can/codec.py` (byte-identical, tested).
- `RobotAdapter` — `host/inhabit_can/adapter.py`.
- `PVTSample` — `host/inhabit_can/pvt.py`.
- `JointPodState.msg` — `host/inhabit_msgs/msg/`.

## 3. Repo layout (current)
```
firmware/  can_frame, mcp2515 (driver), can_health, calib, enum, main.c + host-gcc tests
host/
  inhabit_can/    codec, adapter, pvt (the contracts)
  inhabit_bridge/ ROS2 node: CAN -> JointPodState (+ launch, conversion, sources)
  inhabit_msgs/   JointPodState.msg
  inhabit_core/   plugin registry core
  sensors/ transport/ adapters/ export/ events/  <- plugin families (registry pattern)
  sim/            simulation: seeded RNG core (B1), SimRobot (B2)
  logger/         jitter, parquet_io, recorder (PVT episodes)
  viz/            live joint-angle visualizer
  tests/          436+ tests incl. conformance/ + test_integration.py (end-to-end)
scripts/  verify.ps1 (Windows) / verify.sh (CI) — the single "is it working" gate
.claude/  CLAUDE.md brain, 12 skills (6 Inhabit + 6 Ponytail), 6 agents, 5 commands, Stop-hook
.github/workflows/ci.yml  — runs verify + pytest-cov + ruff + mypy on every PR
```

## 4. Tooling wired in
- **Ponytail** (skills in `.claude/skills/`) — minimal-code discipline, auto-activates.
- **CodeRabbit** — GitHub App reviews every PR using `.coderabbit.yaml` (firmware/host rules).
- **GitNexus** — code knowledge graph: `npx gitnexus serve` (web UI) / `analyze --force` (reindex).
- **CI** — GitHub Actions runs `scripts/verify.sh` on every PR/push; coverage gate `fail_under=90`.
- **Stop-hook** (`.claude/settings.json`) — every agent runs `verify.ps1` before it can stop.
- **Worktrees** — one per track under `C:\Users\youss\dev\inhabit-<lane>`; only the orchestrator merges.

## 5. Roadmap & current state (PAUSED mid-loop)
Phases: P-A (plugin foundation) ✅ COMPLETE. P-B (simulation/dataset) IN PROGRESS.
- Merged to `main`: all of P-A + **B1** (seeded sim RNG core) + **B2** (configurable SimRobot).
- In flight (P-B):
  - **PR #46 — B4 scenario spec:** APPROVED by CodeRabbit but CONFLICTING. Needs rebase on main
    (expected `host/sim/__init__.py` clash with B2). Resolve the conflict, re-verify, then merge.
  - **PR #47 — B3 proprio noise:** CodeRabbit asked to replace reflective `getattr` with an
    explicit `match` in `NoiseSpec.sigma()` (valid — mypy-strict). Edit was applied locally in the
    `inhabit-dataset` worktree but is UNCOMMITTED, unverified, unpushed. See §7.
  - **B5 / B6 / B7:** queued, not started.
- No background workers running; loop halted; no wakeup scheduled.

## 6. How to resume the autonomous loop
1. Start GitNexus: `cd <repo>; npx gitnexus serve` (leave running).
2. Start the orchestrator (bypass = hands-off): `claude --dangerously-skip-permissions`, then:
   "You are the Inhabit orchestrator. Resume the P-B loop. First finish the loose end in §7 of
   HANDOFF.md. Then: rebase PR #46 on main and merge it; confirm PR #47's match-fix is committed,
   verified, pushed, and merge when CI+CodeRabbit are green. Then dispatch B5/B6/B7 as independent
   worktree tracks toward BENCHMARKS.md. Merge order respects contract deps. After each merge:
   git pull, pwsh scripts/verify.ps1, npx gitnexus analyze --force. Loop until BENCHMARKS 1-8 are
   green, then STOP. Frozen contracts: CAN v1, RobotAdapter, PVTSample, JointPodState.msg. Use
   Ponytail. Only you merge. Lead every decision with the failure mode."
3. Optionally one worker terminal per active lane (see `RUNBOOK.md`), each pinned to its folder+PR.

## 7. LOOSE END to resolve first
Uncommitted edit in the `inhabit-dataset` worktree: `host/sim/robot.py` — the #47 `NoiseSpec.sigma()`
`getattr`→`match` fix. Recommended: FINISH it (don't revert — the change is correct).
```
cd C:\Users\youss\dev\inhabit-dataset
pwsh ..\Inhabit-Software\scripts\verify.ps1     # must be green
git add host/sim/robot.py
git commit -m "B3: explicit match in NoiseSpec.sigma() per CodeRabbit (mypy-strict)"
git push                                        # updates PR #47 for re-review
```

## 8. Environment gotchas (real, will bite you)
- **Python 3.11 required** — `events/`, `sensors/` use `enum.StrEnum` (3.11+). On 3.10 you get
  5 collection errors; that is NOT a bug on main.
- **Keep the repo OUT of OneDrive** — it's at `C:\Users\youss\dev\Inhabit-Software`. Git inside
  OneDrive causes `.git/*.lock` "Operation not permitted" failures.
- **Coverage gate** — `fail_under=90` (branch). New code needs tests or CI fails. Never lower it.
- **Run pytest from `host/`** (pythonpath=".") or `pytest host` from root; conformance tests import
  bare package names (`from events import ...`).
- **verify.ps1** detects gcc/clang/cc and python/python3/py; ruff+mypy advisory, pytest+C test gate.

## 9. Definition of done → then ultracode
When `BENCHMARKS.md` items 1–8 are green (verify green on main, CI green, every subsystem tested,
end-to-end integration passes, GitNexus shows no orphaned modules), STOP the round loop and run a
single `ultracode` hardening pass: repo-wide audit of CAN timing, ISR safety, schema drift, and
untested paths, with independent verification of each finding. Do NOT run ultracode before then.
