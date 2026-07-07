# PROGRESS — Inhabit heartbeat log

Newest entry first. One entry per orchestrator loop. Measurable state only, no fake churn. Since the
2026-06-29 MASTER_PLAN pivot the loop actively builds the **software PVT data engine** (P-A…P-M);
hardware bring-up is a separate parked track, additive not blocking.

---

## 2026-07-05T2x:xxZ — P-C surge: C3 #54 + C4 #55 + C6 #56 MERGED (workers salvaged) → C5 in flight
- **main** @ `1e7eff3` · five of seven P-C tasks live (C1-C4 + C6) · 0 open PRs · coverage ~93.3%.
- **Worker outage handled:** all three parallel workers (C3/C4/C6) hit a session limit mid-task,
  leaving complete implementations but no tests/PRs. Salvaged directly per the rate-limit protocol:
  orchestrator adversarially reviewed each implementation line-by-line, wrote the test suites
  (C3: 43 adversarial cases incl. shifted-clock integration; C4: 35 detection proofs incl.
  mild-passes/violating-fails pairs per fault), completed C6's KUKA section (honest `cannot-claim` —
  proprietary docs; third-party Quanser evidence fetched and labeled), ran all gates, opened PRs.
- **CodeRabbit rounds (all comments valid, all fixed):** #54 — two missing AlignmentResult
  invariants (window-miss≠OUT_OF_BUDGET; coincidence-must-be-EXACT) + finite interpolation values
  + shared fixture; #55 — finite float gate at the FaultSpec validator (NaN drift_ppm reached
  round()); #56 — approved clean, zero comments.
- **Stale-base hazard fired and was caught** on C3: branch predated main's docs commit — the
  pre-commit `git diff origin/main --name-only` check (recorded in project memory by the C2 worker)
  flagged it; rebased before commit. The hazard protocol works.
- **C5 dispatched** (export timing metadata: auditable sync sidecar, no fabrication, legacy-safe).
- **Next:** merge C5 → C7 benchmark phase-gate (CLI smoke + report artifact; must provably fail on
  injected violations) → PHASE-C COMPLETE report with MEASURED bounds.

---

## 2026-07-04T1x:xxZ — P-C/C1 merged (timebase core) → C2 dispatched; verify FULLY green
- **main** @ `6650dfb` · **ALL VERIFIABLE CHECKS PASSED**: 706 passed / 15 skipped / **0 failed**
  (goldens green on Windows post-B6f) · ruff clean · mypy --strict clean (104 files) · coverage
  ratchet held.
- **C1 (#52) MERGED** — CodeRabbit **APPROVED with 0 actionable comments** on first review; verify
  green; orchestrator line-by-line adversarial review passed. `host/timing/`: ClockDomain
  (monotonic/wall/source, serialization-stable tokens), validated `Stamp` (bool/0/negative/>int64
  rejected loud; cross-domain ordering RAISES), `require_monotonic` wall-clock gate, LatticeClock +
  ScriptedClock (deterministic, typed `ClockExhausted` — never repeat/clamp). Timing pkg 100% cov.
- **C2 dispatched** (`feat/p-c/ts-normalize`, dataset worker): flagged-never-repaired TimingRecords
  (original + normalized + domain + skew; clean⊕flagged exclusivity; WALL rejected at the boundary;
  idempotent; ordering preserved) — the anti-fake-synchronization layer.
- GitNexus reindex @ 6650dfb: first attempt hit the intermittent LadybugDB WAL error; retry running.
- **Next:** merge C2 → dispatch C3 (alignment engine) + C4 (chaos bench) in parallel → C5 → C6 → C7
  benchmark phase-gate → demo-readiness audit (end-to-end CLI smoke, error-free demo runbook).

---

## 2026-07-04T0x:xxZ — **PHASE-B COMPLETE** (B5 #48, B6 #49, B7 #50, B6f #51 merged) → P-C active, C1 dispatched
- **main** @ `9424a0b` (+#51) · Windows-local verify **green end-to-end post-B6f**: 640 passed / 15
  skipped / 0 failed · **92.5% branch** · ruff + mypy --strict clean (100 files) · CI green throughout.
- **B7 (#50) MERGED** after an adversarial CodeRabbit round: the ask (full sample-for-sample equality
  in the CLI round-trip, not spot-checks) was valid — verified feasibility first (CLI uses
  `build_scenario_episode` defaults; strictly-increasing timeline makes the loader sort
  order-preserving; parquet float64 is exact), fixed in `6c181a3`, re-approved, merged.
- **B6f (#51):** the deferred golden-portability follow-up became a **blocker** (local verify/Stop-hook
  red on main), so it was fixed immediately: floats quantized to 9 sig digits via ONE shared
  `quantize_sample` canonicalization (renderer + parse-back), golden regenerated on Windows, and **CI
  Ubuntu regenerating byte-identically is the cross-platform proof**. Golden suite 12/12 both platforms.
- **GitNexus**: full clean rebuild @ `9424a0b` — 3,302 nodes / 5,857 edges / 123 clusters / 85 flows;
  skills regenerated (new `sim` area). Caveat: MCP server one storage version behind the CLI index
  (v41 vs v42) — CLI/skills used for the P-C surface map (checked: `sim` skill; `compute_jitter`/
  `JitterBudget` production callers = export gates + recorder + sim + CLI; `ClockNs`/`monotonic_ns`
  seam = sensors/bridge/transports/ros2_adapter/events).
- **P-C decomposed** (C1–C7 in MASTER_TASK_QUEUE.md): timebase core → normalization (never silently
  repair) → alignment engine with quality metadata → seeded chaos bench → export timing metadata →
  SDK adapter time contracts → **C7 benchmark phase-gate**. Un-fakeable-test invariant baked into
  every task. **C1 dispatched** (`feat/p-c/timebase-core`, dataset lane).
- PHASE-B exit report with per-criterion evidence: STATUS.md.

---

## 2026-07-01T19:xxZ — P-B/B3 + B4 merged → combined-main green → B5 dispatched
- **main** @ `cc91122` · combined-main gate GREEN: firmware C green · host **580 passed / 15 skipped** ·
  coverage **92.3% branch** (ratchet held) · ruff + mypy --strict clean (94 files). (Linux sandbox
  py3.10 + StrEnum shim; CI py3.11 authoritative.)
- **B3 (#47) MERGED:** CodeRabbit `getattr`→`match` in `NoiseSpec.sigma()` applied (`939e0d8`) —
  mypy now statically verifies the NOISE_CHANNELS↔field mapping.
- **B4 (#46) MERGED:** rebased onto main; `host/sim/__init__.py` resolved as B2+B4 export union (all
  B2 SimRobot exports preserved; ruff caught `example_scenario` missing from `__all__` — fixed pre-push).
- **GitNexus reindex PENDING** on Windows (`npx gitnexus clean --all --force && npx gitnexus analyze
  --force --skills`) — sandbox npm blocked from LadybugDB native-binary CDN.
- **B5 dispatched** (`feat/p-b/sim-tactile-visual`, dataset lane): `sim-tactile` (TACTILE) +
  `sim-frames` (VISUAL) SensorSources driven off the B4 scenario timeline onto FROZEN PVTSample fields
  (`tactile_event`, `camera_frame_id`) — NO schema bump; SensorSource conformance required.
- **Next:** B5 PR → CodeRabbit → merge → B6 (goldens) → B7 (jitter gate + CLI) → P-B exit audit.

---

## 2026-07-01T14:xxZ — P-B/B2 merged (SimRobot) → parallel tracks B3 + B4 (via /orchestrate)
- **main** @ `15783e2` · coverage **91.6% branch** · ruff + mypy --strict clean.
- **B2 (#45) MERGED:** `SimRobot` (config DOF, sine/ramp/hold trajectory callables, monotonic
  non-zero timestamps, independent-copy reads, `SeededRng` threaded) + `SimRobotAdapter` wired behind
  the FROZEN RobotAdapter as `sim_robot` (passes adapter conformance) — **closed the SimAdapter
  timestamp=0/by-reference gap**; ROBOT_SDK_MAPPING sim_robot ✅ / sim stays 🟡 (no overclaim).
  CodeRabbit round: DOF-unique `2πi/dof` phase spread (fixed lockstep at dof≥7) + send_command
  DOF-length validation — both valid, fixed (`1c40a6d`), merged.
- **Parallelized via /orchestrate:** dispatched **B3** (seeded proprio noise, `feat/p-b/proprio-noise`,
  inhabit-dataset) and **B4** (contact scenario spec, `feat/p-b/scenario-spec`, inhabit-export-cli) to
  run concurrently. **B4 = PR #46** (validated/serializable scenario, frozen tactile tokens, golden
  byte-stable); CodeRabbit flagged slip/impact-with-no-open-grasp — valid, fixed (`0e33107`), awaiting
  re-review → merge. B3 in flight.
- **Merge order** B2→B4→B3→B5→B6→B7 (only B5 touches sensors registry, only B7 the CLI — no conflicts).
- **Next:** merge B4 + B3 → B5 (sim-tactile/sim-frames sources) → B6 (goldens) → B7 (jitter/CLI).

---

## 2026-07-01T04:2xZ — P-B/B1 merged (seeded sim RNG core) → B2 dispatched
- **main** @ `17cd5ec` · **verify green**: firmware C + host (469 tests on the B1 branch) · ruff clean ·
  mypy --strict clean (88 files) · **coverage 91.13% branch** (ratchet held).
- **B1 (#44) MERGED:** `host/sim/rng.py` `SeededRng` — frozen, stdlib-only (no numpy) seeded RNG;
  value-identity is the seed (byte-stable repr, eq/hash by seed); `spawn(label)` gives independent
  per-channel sub-streams via portable FNV-1a (dodges PYTHONHASHSEED). `SimConfig.seed`/`rng()` plumbed
  but unconsumed (output byte-identical; B3 draws noise). **CodeRabbit round:** flagged the `Random`
  leaking into repr/eq (falsifying the byte-stable-log claim) + seed validation belonging at the class
  boundary — both valid, fixed in `b30fb3f` (`field(init=False,repr=False,compare=False)` + `__post_init__`
  int-seed guard + value-semantics/validation tests), re-approved, merged.
- **B2 dispatched** (branch `feat/p-b/simrobot`, dataset worker): configurable SimRobot — ≥2 trajectory
  models, monotonic seeded timestamps, independent-copy reads, consuming `SeededRng`; may wire behind the
  FROZEN RobotAdapter to fix the SimAdapter `timestamp_ns=0`/by-reference gap.
- **Next:** review+merge B2 → B3 (proprio noise) → B4 (scenario spec) → B5 (tactile/visual sources) →
  B6 (golden fixtures) → B7 (jitter/CLI). GitNexus reindexed at 17cd5ec.

---

## 2026-07-01T04:0xZ — PHASE-A COMPLETE (plugin foundation) → P-B active
- **main** @ `052fc64` (+A5b #43 merging) · **verify green**: firmware C + **449 host passed / 15 skipped**
  · ruff clean · mypy --strict clean · **coverage ratchet live @ 90.9% branch** (CI 90.91%).
- **Merged this loop:** #41 (A3 conformance harness — all 6 extension points, 49 cases), #40
  (ROBOT_SDK_MAPPING docs; fixed the `sim` readiness overclaim 🟡, CodeRabbit re-approved), #42
  (A8 coverage gate). **#43 (A5b replay SensorSource)** open, verify-green, adversarially reviewed,
  awaiting CodeRabbit → merge.
- **A8 real-bug catch:** the coverage gate was **green-but-not-enforcing** — verify ran `pytest host`
  from the repo root, where coverage.py can't see `[tool.coverage]` in `host/pyproject.toml`, so it
  measured the whole tree (~97%, tests included) and `fail_under` silently no-op'd. Fixed to run from
  `host/` (like mypy); now enforces product-only 90.9% branch. Confirmed on CI (Ubuntu 90.91%).
- **P-A exit audit:** 6/6 extension points have registry+ABC+**≥2 plugins**+conformance (A5b closed the
  SensorSource ≥2 gap with a real, reusable `replay` source — not fake churn); **0 frozen-contract
  edits** (RobotAdapter/PVTSample/CAN-v1/JointPodState.msg audited); verify green; ratchet live.
- **P-B decomposed** into B1–B7 in MASTER_TASK_QUEUE.md (seeded core → SimRobot → noise → scenario spec
  → sim-tactile/visual sources → golden fixtures → jitter/CLI); stdlib-only, monotonic-clock, frozen
  contracts protected.
- **Next:** merge #43 → GitNexus reindex (`--wal-checkpoint-threshold`, orphan check) → dispatch **B1**.
  Note: a GitNexus reindex hit a LadybugDB WAL-checkpoint error; retry with the larger threshold.

---

## 2026-06-28T04:0xZ — ULTRACODE_BENCH_READY hardening: Phase 0 + audit dispatched
- **main** @ `796759a` · verify last-green 123 (code unchanged) · open PRs: #14 only
- **Phase 0 (#14):** all 4 requested fixes ALREADY applied on head `6ea2c5d` (Four-contracts wording + JointPodState listed; firmware build example = one test src/binary; README heading blank lines; Experiment Log requires monotonic source/value). Nothing to commit. #14 remains blocked by merge-conflict (DIRTY) + CodeRabbit not-yet-flipped — conflict is a content-merge on the maintainer's vault, not auto-resolving it.
- **Phase 2 audit DISPATCHED** (read-only, 8 categories, GitNexus+code) → findings become ULTRACODE_TASK_QUEUE.md. No lanes launched yet (avoid Round-4 re-churn; assign only for concrete audit findings).
- **Note:** this is the MANUAL hardening loop (worker agents + CodeRabbit), NOT the Workflow ultracode (user hasn't said the literal "run ultracode").
- **Next agent:** audit returns → create ULTRACODE_AUDIT.md + ULTRACODE_TASK_QUEUE.md → assign lanes for real findings only. **Next human:** merge #14 (resolve its conflict) / Rev-A bench.

---

## 2026-06-28T03:58Z — monitor clean, no change
- **main** @ `1dc18ac` · **open PRs** 1 (#14 docs vault, OPEN/CONFLICTING — maintainer gate) · no new PRs
- BENCH_READY_V0_2 software side done; no software lane work. verify/reindex unchanged (no code delta).
- **Blocked:** #14 human merge + Rev-A bench (P6). **Next agent:** none until #14 merges or a new PR/bench evidence appears.

---

## 2026-06-28T03:2xZ — Round 4 software side COMPLETE (#19 merged)
- **main** @ `649e3bb` · **verify ✅ 123 passed** (incl. firmware bench-3pod) · **GitNexus** 1,285 nodes / 2,267 edges cycle-free
- **#19 (L5 viz demo) MERGED** — docs-only, verify-green, both CR comments addressed (one outdated/resolved, one re-flagged-nothing); stale CHANGES_REQUESTED was a non-flipping review-state, merged with logged rationale (precedent #15).
- **BENCH_READY_V0_2 software side = DONE:** Lanes 1/3/4/5 merged (6 PRs total this round: #21,#20,#18,#17,#19). Lanes 2/6 deferred (need #14 vault).
- **Open PRs:** only #14 (docs vault — maintainer gate).
- **Remaining (non-software):** (1) maintainer merges #14 → unblocks Lanes 2/6 + context pass + ultracode; (2) Rev-A bench (P6). Switching to 1800s idle cadence.
- **Next human:** merge #14 / power board · **Next agent:** none until #14 merges or bench evidence arrives.

---

## 2026-06-28T03:1xZ — Round 4: 4 lane PRs MERGED
- **main** @ `3b1ad1d` · **verify ✅ 123 passed** (firmware: can_frame/calib/mcp2515/can_health/enum/enum_integrate/**bench-3pod**) · **GitNexus** 1,252 nodes / 2,233 edges
- **Merged this cycle:** #21 (L1 firmware BENCH_TESTS docs), #18 (L3 live-can runbook), #17 (L4 dataset readiness + 2 seam tests), **#20 (L1 firmware 3-pod C test + verify wiring + evidence doc)** — all CodeRabbit-APPROVED, verify green.
- **#20 note:** a second Lane-1 PR (branch `...-enum`) — NOT a dup; added the executable `test_bench_3pod.c` (golden 3-pod frames) + wired it into verify.ps1/.sh. Confirmed builds+passes before merge.
- **Open:** #19 (L5 viz demo) — worker re-fixed (`cd741be`, corrected invented t_ns/jitter → real fixture values), awaiting CodeRabbit re-review. #14 = maintainer gate.
- **Next agent:** poll CodeRabbit on #19 → merge → BENCH_READY_V0_2 software side complete. **Next human:** merge #14 (unblocks Lanes 2/6 + ultracode).

---

## 2026-06-28T03:1xZ — Round 4 lanes all produced PRs
- **main** @ `1e67668` · **open PRs** 5: #14 (gate), #21 L1-firmware, #19 L5-viz, #18 L3-live-can, #17 L4-dataset
- All 4 lane PRs: **verify ✅, docs-focused, frozen contracts untouched**, disjoint files (no cross-conflicts).
- **CodeRabbit gate:** #18 + #17 = CHANGES_REQUESTED (1 Minor each — fenced-code language + time-sync note; consistent cwd) → bounced to their workers. #19 + #21 = review pending.
- **Merged this loop:** none yet (CodeRabbit hard gate).
- **#14:** still the blocking gate (maintainer merge) for Lanes 2/6 + context pass + ultracode.
- **Next agent:** workers re-fix #18/#17 → re-review → merge clean lane PRs (verify+reindex). **Next human:** merge #14.

---

## 2026-06-28T02:5xZ — Round 4 (BENCH_READY_V0_2) launched
- **main** @ `02c549d` (#16 CodeRabbit-fix to #15 merged since last tick) · **open PRs** 1 (#14 docs)
- **verify:** ✅ green on main · **GitNexus:** 1,145 nodes / 2,076 edges (cycle-free)
- **Phase 0:** #16 ✅ merged; **#14 explicitly BLOCKED** (gate) — docs-only ✅ but CONFLICTING +
  CodeRabbit CHANGES_REQUESTED (29 prose comments) + tangled in maintainer working tree. It carries
  the docs vault the mandatory context pass + Lanes 2/6 depend on.
- **Phase 1 created:** BENCH_READY_V0_2.md + ULTRACODE_READY.md (new, conflict-free).
- **Lanes dispatched (code-keyed, new files, GitNexus+code context):** 1 firmware-bench-harness,
  3 live-can-readiness, 4 dataset-export-readiness, 5 viz-demo-operator.
- **Lanes deferred ⛔ (blocked on #14 vault):** 2 hardware-evidence-kit, 6 release/risk-hardening.
- **Next human:** merge PR #14 (unblocks context pass + Lanes 2/6 + ultracode). **Next agent:** Lanes 1/3/4/5 → PRs.

---

## 2026-06-28T02:27Z — monitor clean, no change
- **main** @ `a80d688` · **open PRs** 1 (#14 docs, docs-only ✅) · **latest merged** #15
- **verify:** code unchanged since last green (`cb002f8`, 121 passed); only docs/heartbeat commits since → no re-run
- **GitNexus:** 1,144 / 2,075 (unchanged — no code delta)
- **Changed since last heartbeat:** nothing but the prior heartbeat commit
- **Blocked:** 🔒 HARDWARE (P2 exec, all P6) + PR #14 human merge
- **Next human:** merge #14 / power Rev-A board · **Next agent:** none (MONITOR MODE)

---

## 2026-06-28T01:55Z — monitor clean, no change
- **main** @ `b45f83a` · **open PRs** 1 (#14 docs, docs-only ✅) · **latest merged** #15
- **verify:** last CI green on `b45f83a` (only commit since 01:47Z = the heartbeat doc; code unchanged → no re-run needed)
- **GitNexus:** 1,144 / 2,075 (unchanged — no code delta)
- **Changed since last heartbeat:** only the PROGRESS.md/ORCHESTRATION dashboard commit
- **Blocked:** 🔒 HARDWARE (P2 exec, all P6) + PR #14 human merge
- **Next human:** merge #14 / power Rev-A board · **Next agent:** none (MONITOR MODE)

---

## 2026-06-28T01:47Z — monitor clean
- **Branch:** main @ `cb002f8`
- **Open PRs:** 1 — #14 (docs vault, docs-only ✅, 0 non-doc files)
- **Latest merged:** #15 post-green fixture + data-path/viz smoke-test (2026-06-28T00:34Z)
- **verify.ps1:** ✅ 121 passed · ruff clean · mypy clean
- **GitNexus:** 1,144 nodes / 2,075 edges / 45 clusters / 40 flows · cycle-free
- **Changed since last heartbeat:** nothing (first heartbeat; #15 landed previous cycle)
- **Blocked:** P2 execution + all P6 = 🔒 HARDWARE-BLOCKED (Rev-A bench); PR #14 merge = human action
- **Next human action:** merge PR #14 (after P1 restore step in POST_GREEN_ROADMAP.md); power the Rev-A board
- **Next agent action:** none — MONITOR MODE. No software work exists until bench evidence is available.

### Standing status (software side of Phase A = DONE)
Rounds 1–3 merged: 13 PRs (CAN codec, firmware enum/calib, transport, adapters, dataset, viz,
e2e test, registry, export CLI, viz runner, post-green fixture). BENCHMARKS 1–8 green.
POST_GREEN_ROADMAP: P1 ✅, P2 📦(in #14), P3/P4/P5 software ✅, P6 🔒.

**No software progress possible until physical board evidence is available.** The next measurable
state change will come from: PR #14 merging, a new PR, or a captured `.canlog` / scope trace from
the Rev-A bench.

## 2026-06-28T04:1xZ — ULTRACODE: audit done, 4 fix-lanes dispatched
- main @ f12ba4d · verify green 123 · open PRs: #14 (gate)
- Audit (read-only, 8 cat) DONE → ULTRACODE_AUDIT.md + ULTRACODE_TASK_QUEUE.md committed. Verdict: contracts/codec/recorder/viz SOLID; 1 reproduced data-corruption BLOCKER + doc/code drift + hygiene; bring-up numbers HARDWARE-BLOCKED.
- Dispatched (PR + CodeRabbit + Process Evidence): Lane C ultracode/dataset-export-gate (BLOCKERS C1/C2 + C3/C4/C5), Lane A ultracode/firmware-doc-makefile (BLOCKER A1 INT-pin + A2/A3/A4), Lane F ultracode/release-hygiene (untrack run_test ELF + host-doc fixes + cleanup doc), Lane E ultracode/hardware-evidence-templates (blank bench templates; values HARDWARE-BLOCKED).
- Lanes B/D NOT launched (audit: SOLID — no fake churn). Kept PR/CodeRabbit pipeline (not Workflow) per mandatory CodeRabbit gate.
- Next agent: gate+merge lane PRs (require Process Evidence). Next human: merge #14.

## 2026-06-28T05:0xZ — ULTRACODE: all 4 fix-lane PRs open; CodeRabbit gating
- main @ 4e0f24c · verify green (lane PRs verify-green: #25 136 / others 123) · open PRs: #14 (gate) + #22 #23 #24 #25 (ultracode lanes)
- All 4 lanes delivered PRs with Process Evidence: #25 Lane C (data-corruption BLOCKER fixed, 4→3 repro, gate+grouping+NaN+tests), #24 Lane A (INT-pin + Makefile + BENCH_TESTS), #23 Lane E (bench evidence templates), #22 Lane F (untrack ELF + host-doc + CLEANUP.md).
- CodeRabbit: all 4 CHANGES_REQUESTED. Bounced #25 (3: parquet-reindex assert + recorder round-trip test + DATASET_READINESS pipeline reconcile), #23 (2: result-vocab + MD040 fence), #22 (2: portable path + git branch -d prereq). #24 re-review pending (review predated last commit).
- Merge-time note: #23 & #24 both touch firmware/BENCH_TESTS.md → merge one, rebase other.
- Next agent: workers re-fix → re-review → merge clean (require Process Evidence). Next human: merge #14.

## 2026-06-28T05:1xZ — ULTRACODE_BENCH_READY: software/docs hardening COMPLETE
- main @ b4fa7cd · verify ✅ 136 passed (firmware ×7 incl. bench-3pod + host) · GitNexus 1,350 nodes / 2,406 edges cycle-free
- **All 4 ULTRACODE fix-lanes MERGED** (CodeRabbit-APPROVED + Process Evidence): #25 dataset corruption gate (the reproduced BLOCKER), #24 firmware INT-pin/Makefile, #22 hygiene (untracked ELF), #23 hardware evidence templates.
- Caught + correctly skipped a CodeRabbit FALSE POSITIVE (calib 0x300 ID is a sanctioned separate block, not a v1 violation — forcing 0x100 would collide with telemetry).
- ULTRACODE_AUDIT.md + ULTRACODE_TASK_QUEUE.md closed out; every task DONE/MERGED/HARDWARE-BLOCKED.
- **DONE criteria met (software/docs):** open PRs only #14; verify green; GitNexus reindexed; all lane PRs approved; audit+queue complete; hardware items list exact evidence.
- **Remaining (not software):** (1) maintainer merges PR #14 (docs vault) → unblocks BENCH_READY Lanes 2/6 + context pass; (2) Rev-A bench (P6) — numeric values per docs/bench/EVIDENCE_TEMPLATES.md.
- Switching to idle monitor (1800s). Next agent: on #14 merge → launch Lanes 2/6; on new PR → gate+merge. Next human: merge #14 / power board.

## 2026-06-28T05:40Z — monitor clean, no change
- main @ `53c6a98` · open PRs: #14 only (maintainer gate) · no new PRs · ULTRACODE software/docs hardening complete. Blocked: #14 merge + Rev-A bench (P6).

## 2026-06-28T06:11Z — monitor clean, no change
- main @ `4a9c86b` · open PRs: #14 only (maintainer gate) · no new PRs. Blocked: #14 merge + Rev-A bench (P6). No software work remains.

## 2026-06-28T06:42Z — monitor clean, no change
- main @ `99754aa` · open PRs: #14 only (maintainer gate) · no new PRs. Idle cadence → hourly (blocker is human/hardware). Blocked: #14 merge + Rev-A bench (P6).

## 2026-06-28T07:43Z — monitor clean, no change
- main @ `ebfe76c` · open PRs: #14 only (maintainer gate) · no new PRs. Blocked: #14 merge + Rev-A bench (P6).

## 2026-06-28T23:3xZ — PR #14 MERGED — vault unified on main
- main @ `98d0343` · verify ✅ 136 · GitNexus 2,029 nodes / 3,086 edges (vault added) · **0 open PRs**
- Conflict resolution merged (9b3218c): POST_GREEN_ROADMAP→main current; preserved vault + all #15–#25 work; untracked 39 pyc; 4 named CodeRabbit fixes intact; backup at backup/pr14-before-conflict-resolution.
- Now UNBLOCKED: the mandatory context pass (vault on main) + deferred BENCH_READY Lanes 2 (hardware-evidence-kit) & 6 (release/risk/second-brain). Loop is PAUSED — not auto-launching; awaiting resume.
- Remaining real blockers: Rev-A bench (P6, numeric values in docs/bench/EVIDENCE_TEMPLATES.md).

## 2026-06-29T00:0xZ — orchestrator: role bindings + STATUS + post-#14 doc reconcile
- main @ `5cf5fbe` · 0 open PRs · verify green 136 · GitNexus 2,029 nodes.
- Created AGENT_BINDINGS.md (8 worktrees → roles + honest state) + STATUS.md (single-source status).
- Reconciled stale "#14 unmerged/deferred" notes in BENCH_READY_V0_2.md + POST_GREEN_ROADMAP.md → point to STATUS.md.
- Honest state: all code roles IDLE (shipped) or 🔒 HARDWARE-BLOCKED (enum/calib bench); no non-churn worker task to assign. inhabit-adapters worktree dirty(1) — flagged for cleanup. Candidate: slcan impl (YAGNI unless user wants it).
- Remaining frontier: Rev-A bench (P6, docs/bench/EVIDENCE_TEMPLATES.md).

## 2026-06-30T0xZ — RATE-LIMIT PAUSE (resets 1:40am America/Chicago)
- main @ `0e9bbc1` · verify green 161 · GitNexus 2,161 nodes.
- **P-A/A1 registry core MERGED (#32)** — Registry[T] + adapter refactor, inhabit_core 100 ov, frozen contracts untouched.
- **BLOCKED by account session limit:** P-A batch (A2 transport / A4 exporter / A5 sensorsource / A6 eventdetector / A7 episodesink) did NOT start — A2 worker hit the limit immediately. Plan-hardening ultracode workflow (wf_94ea7070-866) failed on the limit (5 partial review lenses, no synthesis/decomposition).
- RESUME ON RESET: dispatch the P-A batch (A2/A4/A5/A6/A7) → A3 conformance → A8 coverage gate. Re-run plan decomposition (inline or workflow) for P-B..P-M when capacity returns.
- This is an infra cap, not a defect. No agents dispatched while limited (avoids burn).

## 2026-06-30 — P-A BATCH IN FLIGHT (resumed after limit) + 4 PRs merged + integration hotfix
- main @ `b760b7d` · verify green (183, now BLOCKING full-tree mypy+ruff) · GitNexus 2,222 nodes / 3,455 edges.
- **Merged 4 ultracode PRs:** #30 transport(slcan+counters), #28 adapters(ML-harden), #26 fw-enum(7-pod), #27 viz(hardening).
- **Integration regression caught + hotfixed (b760b7d):** #28 added `list_adapters()` doing `sorted(_REGISTRY)`, but A1(#32) made `_REGISTRY` a non-iterable `Registry[T]`. Each PR green alone; combined main RED. Fixed to `Registry.names()`. *Lesson: verify on COMBINED main after every merge — branch CI does not re-check against post-merge main.*
- **verify.ps1 hardened:** mypy was advisory + only `host/inhabit_can`; now BLOCKING + `cd host && mypy .` (full tree, tests incl.) to match CI exactly. This exact gap let A2 pass locally but fail CI mypy. Also `.gitignore` fixed (space-joined patterns ignored nothing → one-per-line).
- **P-A batch dispatched (A1 merged → fan-out):** A2 transport-registry (PR #34, built directly, 99% cov), A4 exporter-registry (PR #36, 99% cov, #25 gates preserved), A5 sensorsource+sim-proprio (PR #35, 100% cov), A6 eventdetector (PR #33, 100% cov). A7 episodesink — worker running. All frozen-contracts-untouched; CodeRabbit pending on the P-A PRs.
- **#29 calib** (earlier ultracode PR) now APPROVED + verify + CodeRabbit green (worker pushed parity+timestamp+degenerate-fit fixes before stalling on cosmetic cleanup) — merge candidate.
- NEXT: merge #29; merge P-A PRs as CodeRabbit clears (verify-on-combined-main each); then A3 conformance harness → A8 coverage gate → P-A exit audit → decompose P-B.
