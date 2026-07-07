# STATUS.md — Inhabit Current State

## Current phase

**P-C — Time-sync & multi-modal alignment** (ACTIVE, decomposed C1–C7 in `MASTER_TASK_QUEUE.md`).
**PHASE-B (Simulation & synthetic PVT data) is COMPLETE** — full report below.

## Main branch

* Main commit: `9424a0b` (P-B/B7 #50) + B6f #51 (golden float quantize — cross-platform byte-stability).
* Last verified (2026-07-04, Windows/py3.13 local, post-B6f): firmware C tests green; host **640 passed / 15 skipped, 0 failed**; coverage **92.5% branch** (ratchet ≥90 held); ruff clean; mypy --strict clean (100 files). CI (Ubuntu/py3.11, authoritative) green on every merged PR.
* Last GitNexus index: **fresh full rebuild** (clean --all --force + analyze --force --skills @ `9424a0b`): **3,302 nodes / 5,857 edges / 123 clusters / 85 flows**; skills regenerated (new `sim` area).
* Known tooling caveat: the GitNexus **MCP server** binary is one storage version behind the CLI-written index (v41 vs v42) — MCP queries error until the server restarts/upgrades; the CLI index + generated skills are current and were used for the P-C surface map.

## PHASE-B COMPLETE — exit report (2026-07-04)

**Merged PRs:** #44 (B1 seeded RNG core) · #45 (B2 configurable SimRobot + `sim_robot` adapter) ·
#47 (B3 seeded bounded per-channel proprio noise) · #46 (B4 contact scenario spec) ·
#48 (B5 sim-tactile + sim-frames scenario-driven SensorSources) · #49 (B6 golden episode fixture +
byte-stability harness) · #50 (B7 jitter/clock property gate + `--sim --scenario` CLI) ·
#51 (B6f golden float quantize — cross-platform).

**Evidence, per exit criterion:**
- **Sim determinism:** same (config, seed) → identical episodes (`as_row()` equality tests across
  SimRobot trajectories, noise, scenario sources); `SeededRng` value-identity + portable FNV-1a
  `spawn` sub-streams; seed NEVER perturbs `timestamp_ns` (pinned across seeds in
  `test_sim_cli_jitter.py`).
- **Golden byte-stability:** committed `pick_place.episode.txt` (225 rows, 3 modalities, LF-pinned);
  regeneration byte-identical on **both** Windows/py3.13 and CI Ubuntu/py3.11 after B6f quantization
  (9-sig-digit canonical floats — below the ~15-digit cross-libm agreement of `sin`/`gauss`).
- **Jitter/clock property:** every built-in scenario × seeds {0, 7, 12345}: strictly-increasing unique
  stamps on a uniform 10 ms lattice → `compute_jitter` measures `backwards==0`, `dropouts==0`,
  `jitter_max==0`; the gate provably fails loud on an unmeetable budget.
- **Conformance (new plugins):** `sim_robot` passes the RobotAdapter conformance suite (no skips);
  `sim-tactile`/`sim-frames`/`replay` pass SensorSource conformance; exporter round-trip: CLI
  `--sim --scenario X` export reloads **sample-for-sample equal** (full `as_row()` equality).
- **Frozen contracts: 0 edits** — `PVTSample`/`PVT_SCHEMA_VERSION`, `RobotAdapter`, CAN codec v1,
  `JointPodState.msg` untouched across #44–#51 (git-log audited); sim populates existing frozen
  fields (`tactile_event` tokens, `camera_frame_id`) only. No numpy anywhere (stdlib-only invariant).
- **Caveats (honest):** golden floats are canonically 9-sig-digit quantized (full precision lives in
  the generators, not the fixture); hardware evidence remains **bench-pending** (everything above is
  simulation-proven; no hardware claims); GitNexus MCP-server version skew (above).

**Handoff → P-C:** the sim stack emits deterministic multi-modal episodes on one monotonic lattice —
P-C makes timing a first-class, auditable contract: explicit clock domains (C1), normalization that
never silently repairs (C2), alignment with quality metadata (C3), seeded chaos benches (C4),
timing-auditable exports (C5), SDK adapter time contracts (C6), and a benchmark phase-gate (C7).

## Open PRs / in flight

* C1 (clock & timebase core) — branch `feat/p-c/timebase-core`, dataset lane (dispatched; PR on completion).
* Queued per dispatch order: C2 → (C3, C4) → C5 → C6 → C7 (see `MASTER_TASK_QUEUE.md` §P-C).

## Recently merged PRs

* Phase A: #32, #33, #34, #35, #36, #37, #41, #42, #43.
* Phase B: #44, #45, #46, #47, #48, #49, #50, #51 (see exit report above).

## Current blockers

### Hardware-blocked

* Rev-A bench evidence (rail V, ADC sweep, MCP2515 /INT, ENUM edges, full-chain CAN log) — PARKED
  track, additive not blocking; the engine is simulation-proven. See `docs/bench/EVIDENCE_TEMPLATES.md`.

### Human/action blockers

* None. P-C proceeds autonomously.

## Active task queue

See `MASTER_TASK_QUEUE.md` §P-C (C1 ACTIVE · C2–C7 queued) and §P-B (B1–B7 + B6f MERGED — phase DONE).

Task states: TODO · ACTIVE · REVIEWING · MERGE-READY · MERGED · DONE · HARDWARE-BLOCKED.

## Verification

Last command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Last result:

```text
640 passed / 15 skipped / 0 failed · coverage 92.5% branch (gate >=90) · ruff clean · mypy --strict clean (100 files) · firmware C green (Windows-local, post-B6f; CI Ubuntu authoritative and green)
```

## GitNexus

Last command:

```powershell
npx gitnexus@latest clean --all --force; npx gitnexus@latest analyze --force --skills
```

Last result:

```text
Repository indexed successfully — 3,302 nodes / 5,857 edges / 123 clusters / 85 flows @ 9424a0b; skills regenerated (incl. new `sim` area). (Set GITNEXUS_WAL_CHECKPOINT_THRESHOLD=268435456 if the LadybugDB WAL checkpoint error recurs.)
```

## Operating rules

* Read this file at session start.
* Update this file before session end.
* Do not commit heartbeat-only churn.
* Protect frozen contracts (CAN codec v1, RobotAdapter, PVTSample/PVT_SCHEMA_VERSION, JointPodState.msg); stdlib-only determinism (no numpy); adversarial review + CodeRabbit before every merge.
* If safe work exists, create a task and assign it; if no safe software work exists, mark the exact hardware evidence required.
