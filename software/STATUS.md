# STATUS.md — Inhabit Current State

## Current phase

**P-D — Last-centimeter contact-event detection** (ACTIVE; decomposed D1–D7 in `MASTER_TASK_QUEUE.md`).
**P-C (Time-sync & multi-modal alignment) is COMPLETE** — exit report below.
**P-B (Simulation & synthetic PVT data) is COMPLETE** — report further below.

> **Multi-dev coordination (2026-07-08):** this repo is now worked by more than one person/session
> in parallel. To prevent the merge clash that dropped reviewed firmware on 2026-07-08, follow
> `COLLABORATION.md`: **lanes** (firmware/CAD vs `host/` data-pipeline vs shared frozen contracts),
> branch off fresh `origin/main`, small single-lane PRs, never direct-push to `main`. P-4 (CAD
> ingestion) landed on main out-of-band via `afa5af3` — owned by the firmware/CAD lane, not this
> data-pipeline track.

## Main branch

* Main commit: `6d0049d` (firmware silicon layer adopted). P-C stack (`host/timing/**` C1–C7 +
  `docs/bench/P-C-TIMING-BENCH.*`) fully present; P-4 CAD ingestion (`afa5af3`) also landed.
* Open PRs (data-pipeline lane): C7 review-nits re-apply, PHASE-C report + P-D plan, P-D/D1
  (label+scorer). Firmware lane: PR #60 (STM32C0 ADC compile fix) — firmware owner to merge.
* Last host verify (2026-07-08, Windows/py3.13 local): **973 passed / 15 skipped, 0 failed**;
  coverage **92.34% branch** (ratchet ≥90 held); ruff clean; mypy --strict clean (114 files).
  CI (Ubuntu/py3.11, authoritative) green on every merged PR.
* GitNexus: last full rebuild @ `6648711` (3,877 nodes / 6,963 edges); reindex due once the
  P-C/P-4 landings + open PRs settle.

## PHASE-C COMPLETE — exit report (2026-07-08)

**Merged PRs:** C1 #52 (clocks/stamps) · C2 #53 (normalization, flagged-never-repaired) ·
C3 #54 (multi-modal alignment engine) · C4 #55 (deterministic timing-chaos bench) ·
C6 #56 (SDK timebase audit) · C5 #57 (exported timing metadata) · C7 #59 (benchmark phase-gate).
*(C7 was merged from its pre-review commit during the parallel-work window; the three CodeRabbit
review nits are re-applied in a follow-up host-lane PR — see Open PRs.)*

**Claim tiers (be precise — this is the standing honesty rule):**
- **simulation-proven** — a seeded, deterministic test/bench demonstrates it. Everything in the
  MEASURED table below is this tier.
- **SDK-doc-audited** — vendor docs read + cited; no device touched (the SDK timebase map).
- **bench-pending** — needs physical hardware; explicitly open (the hardware smoke test).

**MEASURED timing-benchmark table** (`docs/bench/P-C-TIMING-BENCH.md`, seed 7, scenario
`slip_recovery`; regenerate: `cd host && python -m timing.bench --seed 7 --out <dir>`):

| case | verdict | mono. viol. | flagged/records | non-matched/results | max abs offset (ns) | p99 (ns) | contact events | det. |
|---|---|---|---|---|---|---|---|---|
| clean_baseline | aligned_within_budget | 0 | 0/166 | 0/144 | 20,000,000 | 20,000,000 | 25/25 | yes |
| can_jitter_mild | aligned_within_budget | 0 | 0/425 | 0/245 | 199,634 | 199,092 | 25/25 | yes |
| camera_variable_33ms | degraded | 0 | 0/205 | 50/140 | 1,937,014 | 1,937,014 | 25/25 | yes |
| burst_stall_200ms | quarantined | 20 | 20/425 | 25/263 | 0 | 0 | 20/25 | yes |
| skewed_source_clock | quarantined | 0 | 0/425 | 200/250 | — | — | 25/25 | yes |

All five cases replay byte-identically (seeded, no wall clock) and round-trip through **both**
exporters (lerobot + parquet). The gate **provably fails** on injected violations: `--demand-clean`
over this suite exits non-zero (burst/skew are QUARANTINED, not aligned) — no always-pass thresholds.

**Evidence, per exit criterion:**
- **Clock discipline (C1):** `ClockDomain` (monotonic/wall/source) + frozen `Stamp`; cross-domain
  ordering RAISES; WALL leakage rejected. Deterministic `LatticeClock`/`ScriptedClock`.
- **Normalization (C2):** backwards-in-source / unknown-skew / out-of-range are **flagged, never
  repaired**; MONOTONIC identity; SOURCE consistency (`normalized == raw + skew`) construction-enforced.
- **Alignment modes (C3):** **EXACT** (offset 0 coincidence), **NEAREST** (bounded skew), **WINDOW**
  (event association within a window). Events are **never interpolated**; stale reuse banned; misses
  are flagged `out_of_budget`/`no_target`, never guessed.
- **Quarantine behavior (C5, 3-state `SyncVerdict`):** `aligned_within_budget` (clean) →
  `degraded` (defects present, every modality still usable) → `quarantined` (a modality unusable:
  whole timeline flagged, or alignment attempted with zero matches). Verdict is **derived from the
  counts, never asserted** — a summary that flatters its own data cannot be constructed.
- **Exported metadata (C5):** versioned `TimingMeta` sidecar travels with the dataset (per-modality
  clock domain, flag/quality histograms, offset stats, budget, verdict); `from_run`-only, no
  fabrication; unknown tokens/versions refused; legacy datasets load as `None` (back-compat).
- **SDK timebase audit (C6, `docs/sdk/SDK_TIMEBASE_MAP.md`) — SDK-doc-audited, not hardware:**
  UR RTDE = controller-uptime, no host sync; Franka = strictly-monotonic uptime; **KUKA = cannot
  claim** a host-aligned clock from docs; **ROS 2 `header.stamp` = WALL by default** → must re-stamp
  on host-RX monotonic; custom-CAN = monotonic RX contract.
- **Benchmark phase-gate (C7):** the MEASURED table above; committed regenerable artifact; gate
  fails on injected violations; determinism + exporter round-trips enforced unconditionally.

**Next hardware test (bench-pending — needs the physical two-node bench):** `SDK_TIMEBASE_MAP §4`
— two-node CAN breadboard, measure real host-RX skew against injected timing, capture the first
hardware-in-loop dataset, and confirm the monotonic-RX contract on silicon. **No hardware evidence
exists yet; every number above is simulation-proven.**

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
