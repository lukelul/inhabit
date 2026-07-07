# Level 6 Orchestration Playbook — Inhabit

You are the manager. Claude agents are the team. The CAN schema and the `RobotAdapter`
interface are the **contracts** that let tracks run in parallel without colliding.

## The four parallel tracks
| Track | Agent | Worktree/branch | Owns | Contract it depends on |
|-------|-------|-----------------|------|------------------------|
| Firmware | `firmware-engineer` | `wt-firmware` / `feat/fw-*` | `firmware/` | CAN schema v1 |
| Host/ROS2 | `ros2-integrator` | `wt-host` / `feat/host-*` | `host/` ROS2 | CAN schema v1, RobotAdapter |
| Data pipeline | `data-pipeline-engineer` | `wt-data` / `feat/data-*` | `host/logger`, `dataset/` | PVT sample schema |
| Hardware bring-up | `hardware-bringup` | (bench, on `main`) | physical board, `docs/bringup-log.md` | pin map |

Every track is gated by `embedded-reviewer` before merge.

## Golden rule: agree the interface FIRST
Most parallel-work disasters come from two agents inventing incompatible interfaces. Before you
fan out, lock: (1) CAN schema v1, (2) the PVT sample schema, (3) the RobotAdapter signature.
These live in CLAUDE.md / skills so every agent reads the same truth. Change them only by an
explicit, versioned decision — never mid-track.

## Git worktrees (so agents don't fight over files)
```bash
git worktree add ../inhabit-wt-firmware feat/fw-can-bringup
git worktree add ../inhabit-wt-host     feat/host-bridge
git worktree add ../inhabit-wt-data     feat/data-logger
git worktree list
git worktree remove ../inhabit-wt-firmware   # when done
```

## Dispatch loop (what you actually do as manager)
1. `/orchestrate <goal>` → get the decomposition + dispatch plan.
2. Confirm the shared contracts are locked.
3. Launch one agent per track in its worktree. Give each: its CLAUDE.md, its skill, its DoD.
4. Integration checkpoint: each track produces a small PR; the reviewer agent gates each.
   Merge in dependency order (schema-defining track first).
5. `/clear` between unrelated dispatches to keep context lean.

## Live agent workflow docs
Detailed SOPs, checklists, and architecture references live in the Obsidian vault under `docs/`.
Start at [`00-Inhabit Home.md`](00-Inhabit%20Home.md) or go directly to:
- [`docs/agents/Agent Operating Model.md`](docs/agents/Agent%20Operating%20Model.md)
- [`docs/sop/development/Autonomous Development SOP.md`](docs/sop/development/Autonomous%20Development%20SOP.md)
- [`docs/sop/review/PR Review and Merge SOP.md`](docs/sop/review/PR%20Review%20and%20Merge%20SOP.md)

## Anti-slop guardrails
- **Bloated context:** keep CLAUDE.md lean; detail lives in skills, pulled on demand.
- **Skill overload:** curated skills beat generic ones.
- **Candy-shop MCPs:** install only MCPs a track needs.
- **Five flavors of slop:** without locked contracts, parallel agents produce incompatible work.

---

## Live orchestration status (auto-updated by the orchestrator loop)

Gate rule: merge a PR only when CI `verify` is green AND CodeRabbit has no unresolved Major
comments AND `embedded-reviewer` returns OK, in merge order. `verify.ps1` after each merge;
GitNexus reindex after the batch (mid-batch reindex prevents no failure → skipped as busywork).

### Round 1 — COMPLETE ✅ (all 6 merged to `main`, squash + branch-deleted)
| PR | Lane | Result |
|----|------|--------|
| #2 enum | firmware | merged (post-`ENUM_DONE` guard + monotonic pending fix) |
| #3 calib | firmware | merged (was already in `main`) |
| #6 transport | host | merged (versioned `.canlog`, 8-byte enforcement, non-object-JSON guard) |
| #4 adapters | host | merged (idempotent connect, truthful+positive dof, positive/monotonic timestamps) |
| #5 dataset | data | merged (chain_index persisted, derived fps+jitter metadata) |
| #1 viz | host | merged (center-aligned bar, stable sort, call-time stdout) |

`main` green: **98 pytest passed**, ruff + mypy clean, Actions `verify` green, GitNexus cycle-free.

### Round 2 — COMPLETE ✅ (6 PRs merged to main @914e942, squash; stray duplicate #7 closed)
| PR | Lane | Result |
|----|------|--------|
| #10 enum-integrate | firmware | merged — ENUM FSM wired into main.c (chain_index from FSM, ISR-safe) |
| #11 bridge-transport | host | merged — file-replay + socketcan as selectable bridge CAN sources |
| #12 adapter-registry | host | merged — make_adapter() factory behind RobotAdapter |
| #8 e2e-test | data | merged — full replay→bridge→JointPodState→writer→round-trip (item 6) |
| #13 export-cli | data | merged — episode→lerobot export CLI |
| #9 viz-runner | host | merged — `python -m viz` renders JointPodState/replay stream |

### BENCHMARKS.md items 1–8 status (after Round 2, main @914e942)
- 1 verify.ps1 ✅ (117 passed) · 2 each subsystem tested ✅ · 3 frozen contracts untouched ✅ ·
  4 CodeRabbit no blockers ✅ (all R2 PRs 0 comments) · 6 e2e test ✅ (PR #8) ·
  7 Actions verify green on main ✅ · 8 GitNexus no orphans ✅ (reindex 1089 nodes / 1997 edges,
  cycle-free; enum→main.c, adapters→registry, lerobot→export-cli, ascii_viz→viz-runner all wired)
- **5 embedded-reviewer ✅** — OK on merged R2 diff (no BLOCK; one non-blocking CI-coverage FIX
  applied in `scripts/verify.sh`: now runs test_enum_integrate + main.c compile, commit 5c38949)

### 🟢 BENCHMARKS 1–8 ALL GREEN — Round 1+2 complete (main @5c38949)
All software benchmarks met. Round 1+2 (12 PRs) merged. Now in Post-Green Phase A.

---

## Round 3 — Post-Green Phase A (finish line: POST_GREEN_ROADMAP.md)
Most P2 hardware docs already exist in PR #14's vault (📦, pending merge); most bench items are
🔒 HARDWARE-BLOCKED. The only genuinely-missing software is a replayable fixture + smoke-test.
Assign only useful work; everything else is waiting / blocked (NOT busywork).

| Lane | Status | Assignment / reason |
|------|--------|---------------------|
| dataset | ✅ **DONE** (PR #15 merged) | Sample `.canlog` fixture + hardware-free smoke-test (replay→bridge→JointPodState→logger→lerobot export + viz) + P3/P4/P5 command docs. Closed the software side of P3+P4+P5. |
| transport | ⏳ waiting | Replay path documented by the dataset smoke-test; live socketcan/slcan capture is 🔒 (needs USB-CAN + board). No new software task. |
| viz | ⏳ waiting | Runner + README shipped (#9); a viz smoke-test is folded into the dataset fixture. No separate task. |
| adapters | ⏳ waiting | Bridge selectable-source already documented (#11 README + #14 host docs). No new software task. |
| enum | 🔒 HARDWARE-BLOCKED | Two-board ENUM bring-up needs the physical chain; runbook/checklist 📦 in PR #14. Bench evidence: two pods enumerate to chain_index 0,1. |
| calib | 🔒 HARDWARE-BLOCKED | MT6701 ADC/magnet sweep needs the board; calibration math already tested (`test_calibration_helper.py`), decision 📦 in PR #14. Bench evidence: monotonic angle_millideg across magnet rotation. |

### 🟦 MONITOR MODE ACTIVE (post-#15)
All Phase-A software work is done (PR #15 merged, main green). No lane has a real software task —
all are ⏳ waiting / 🔒 hardware-blocked. The orchestrator now only: watches PRs each loop, keeps
this file + POST_GREEN_ROADMAP.md current, and does NOT invent code.
**Next blockers (not software):** (1) maintainer merges PR #14 (docs-only; do the P1 restore step
first), (2) physical Rev-A bench testing — P2 execution + all P6 items (PB6 /INT scope, two-board
ENUM 0/1, MT6701 sweep, live-bus jitter, Jazzy colcon).

### Round 4 — BENCH_READY_V0_2 (lanes detailed in BENCH_READY_V0_2.md)
Context consulted: on-main code (firmware/, host/, tools/) + GitNexus reindex (1,145 nodes /
2,076 edges, cycle-free). Obsidian vault docs are in unmerged PR #14 → context pass for vault-
dependent lanes is gated on #14. Phase 0: #16 merged; **#14 explicitly BLOCKED (maintainer gate)**.

Active lanes (fresh branches off origin/main, new files only, frozen contracts untouched):
- Lane 1 `bench-v0.2/firmware-bench-harness` — firmware-engineer — exit: verify green, C tests pass, bench-test→evidence docs + expected 3-pod CAN frames.
- Lane 3 `bench-v0.2/live-can-readiness` — ros2-integrator — exit: one replay cmd + one live-CAN cmd (hw-gated marked) + troubleshooting; verify green.
- Lane 4 `bench-v0.2/dataset-export-readiness` — data-pipeline-engineer — exit: canlog→parquet/lerobot path clear, quarantine rules documented, real-`.canlog` swap-in; verify green.
- Lane 5 `bench-v0.2/viz-demo-operator` — ros2-integrator — exit: no-hardware replay demo runnable, expected ASCII documented, troubleshooting; verify green.
Deferred (blocked on #14 vault): Lane 2 hardware-evidence-kit, Lane 6 release/risk-hardening.

### 📊 Latest loop snapshot — 2026-06-28T02:5xZ · Round 4 launched; #14 = gate (see PROGRESS.md / BENCH_READY_V0_2.md)
- Open PRs: **1** (#14 docs, docs-only ✅). Merged total: 13 (Rounds 1–3).
- main `cb002f8` · verify ✅ 121 passed · GitNexus 1,144 nodes / 2,075 edges (cycle-free).
- Lanes: **all ⏳ waiting / 🔒 hardware-blocked** — no active software lane.
  - enum 🔒 (two-board bench) · calib 🔒 (MT6701 sweep) · transport ⏳ (live capture 🔒) ·
    adapters ⏳ (done) · dataset ⏳ (done, #15) · viz ⏳ (done, #9).
- **Next HUMAN action:** merge PR #14 (after P1 restore) · power Rev-A board.
- **Next AGENT action:** none — MONITOR MODE; no software work until bench evidence exists.

Frozen contracts unchanged. PR #14 is docs-only (clean); see POST_GREEN_ROADMAP.md P1 for the
one maintainer restore step (leaked uncommitted bridge files, already on main via #11).

### Environment note (maintainer action)
PRIMARY working tree (C:/Users/youss/dev/Inhabit-Software) is on `docs/obsidian-technical-sop-vault`
with your uncommitted obsidian/docs work PLUS leaked Lane-B bridge files (agents cd'd into the
main checkout). The orchestrator did NOT touch it; all verify/merge/doc-update ran from the clean
`inhabit-dataset` worktree (main). Recommend: review/commit the docs branch, then `git restore`
the stray host/inhabit_bridge files there — they are already correctly on main via PR #11.

Frozen contracts (CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg): unchanged.

---
### PR #14 (docs vault) MERGED — main @98d0343 (2026-06-28)
Obsidian/SOP vault unified on main with all bench-ready + ULTRACODE work. 0 open PRs. Lanes 2/6 now runnable (loop paused; launch on resume). Next: Rev-A bench (P6).
