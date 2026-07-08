# MASTER_TASK_QUEUE — executable decomposition of MASTER_PLAN.md

Status: TODO · ASSIGNED(worktree) · PR(#) · MERGED · BLOCKED. Each task is PR-sized, has explicit
tests + exit criteria, protects frozen contracts, requires Process Evidence. Coverage never drops.

## Phase index (decompose each as we reach it)
- **P-A** Plugin foundation & conformance ← decomposed below (active)

> **P-A live status (2026-06-30, main @ b760b7d):** A1 MERGED (#32). A2 PR #34 · A4 PR #36 ·
> A5 PR #35 · A6 PR #33 (all OPEN, verify-green, frozen-contracts-untouched, awaiting CodeRabbit +
> integration-merge). A7 worker running. A3 + A8 queued. Integration rule: verify on COMBINED main
> after every merge (the #28×A1 `sorted(Registry)` regression proved branch-CI alone is insufficient).
- P-B Simulation & synthetic data · P-C Time-sync/alignment · P-D Contact-event detection ·
  P-E Episode store/QA · P-F Export ecosystem · P-G Adapter ecosystem · P-H Session SDK+CLI ·
  P-I Perf/scale/robustness · P-J Packaging/docs/release ·
  **P-K** Live teleop session ops · **P-L** Operator dashboard/viz platform · **P-M** Multi-session + plugin marketplace/SDK
  (scope = BROADER teleop platform; cadence = fully autonomous, report per phase)

---

## P-A — Plugin foundation & contract conformance (CLOSING — 2026-07-01)

> **Status:** A1–A8 **MERGED** (#32 registry-core, #34 transport, #35 sensorsource, #33 eventdetector,
> #36 exporter, #37 episodesink, #41 A3 conformance harness, #42 A8 coverage gate). main @ `052fc64`,
> verify green (420 passed), ruff+mypy-strict clean, coverage ratchet live @ **90.91% branch** (CI),
> 0 frozen-contract edits (audited). One gap found by the exit audit: **SensorSource had only 1
> built-in** (`sim-proprio`) vs the "≥2 plugins each" exit bar → **A5b** below closes it. Then:
> reindex + orphan check + PHASE-A COMPLETE.

**A5b · Second SensorSource built-in (`replay`)** · lane: dataset · branch `feat/p-a/sensorsource-replay`
- Add `host/sensors/replay.py`: a `ReplaySource(SensorSource)` that deterministically replays a
  provided `list[PVTSample]` (the sensor-source analogue of `ReplayAdapter`) — independent-copy reads,
  fail-loud validation of recorded timestamps (positive/non-decreasing), `kind=PROPRIO`. Register
  `replay` on the existing SensorSource registry. Reusable for P-C alignment / P-E QA / P-H replay.
- Tests: determinism, independent-copy, read/stream agreement, empty/exhaustion, invalid-timestamp
  ValueError, kind invariant; passes the existing SensorSource conformance suite (update pinned guard).
- Exit: green; coverage ≥90%; PVTSample/SensorSource-ABC/RobotAdapter untouched. **Closes P-A "≥2".**

**A1 · Generic plugin registry core** · lane: dataset/core · branch `feat/p-a/registry-core` — ✅ MERGED #32
- Add `host/inhabit_core/registry.py`: a typed `Registry[T]` (`register(name)`, `make(name, **kw)`, `available()`, optional entry-point discovery). Refactor `host/adapters` `make_adapter` to use it (keep public API).
- Tests: registry register/make/unknown→ValueError/duplicate-guard; adapter registry still returns sim/replay/ros2/ur; lazy imports preserved.
- Exit: pytest+ruff+mypy(strict) green; coverage ≥90% on inhabit_core; no frozen-contract edits.

**A2 · Transport ABC + registry** · lane: transport · branch `feat/p-a/transport-registry`
- Formalize a `Transport` ABC (open/recv/send/close) in `host/transport/`; register file-replay, socketcan(mock), inmem; `make_transport(name)`. Keep existing classes working.
- Tests: registry; inmem transport round-trips frames; mock socketcan degrades cleanly w/o python-can.
- Exit: green; coverage ≥90% on host/transport; frozen codec untouched.

**A3 · Conformance test harness** · lane: dataset/tests · branch `feat/p-a/conformance-harness`
- `host/tests/conformance/`: parametrized abstract suites for RobotAdapter (connect/read_state/send_command/capabilities invariants) and Transport (recv/send/close invariants), auto-discovering all registered plugins.
- Tests: every registered adapter + transport passes its conformance suite.
- Exit: green; harness reusable; coverage ≥90%.

**A4 · Exporter ABC + registry (wrap lerobot/parquet)** · lane: export · branch `feat/p-a/exporter-registry`
- `Exporter` ABC (`export(episodes, out)` + `load(path)`); register lerobot + parquet behind it; `make_exporter(name)`. Round-trip contract test in conformance harness.
- Tests: each exporter write→read→assert-equal via the ABC; registry unknown→ValueError.
- Exit: green; coverage ≥90%; PVTSample schema untouched (gating logic preserved from #25).

**A5 · SensorSource ABC + registry + sim-proprio** · lane: dataset · branch `feat/p-a/sensorsource`
- `SensorSource` ABC (proprio/visual/tactile kinds) + registry; one `sim-proprio` plugin emitting seeded `PVTSample`-shaped proprio. (Prepares P-B/P-C.)
- Tests: sim-proprio deterministic (seeded); conformance suite for SensorSource.
- Exit: green; coverage ≥90%.

**A6 · EventDetector ABC + registry (stub)** · lane: dataset · branch `feat/p-a/eventdetector`
- `EventDetector` ABC (`detect(window)->events`) + registry + a no-op/threshold stub. (Prepares P-D.)
- Tests: ABC conformance; stub detector returns typed events; versioned.
- Exit: green; coverage ≥90%.

**A7 · EpisodeSink ABC + registry (wrap recorder/parquet_io)** · lane: dataset · branch `feat/p-a/episodesink`
- `EpisodeSink` ABC (`open/ingest/finalize`) + registry; parquet-atomic (wrap `EpisodeRecorder`) + inmem sinks. Keep quarantine/jitter/NaN gates (#25).
- Tests: parquet sink round-trips; inmem sink; quarantine still triggers; conformance suite.
- Exit: green; coverage ≥90%; frozen contracts untouched.

**A8 · Coverage gate in CI** · lane: release/primary · branch `feat/p-a/coverage-gate`
- Add `pytest --cov` with a ratcheting threshold (start at current measured %, enforce ≥ it, target 90%) to verify scripts + CI; record baseline in STATUS.md.
- Tests: CI fails if coverage drops; baseline documented.
- Exit: green; coverage gate live; no test deleted to game it.

### P-A exit (phase DONE only when all true)
All A1–A8 merged · every extension point has registry+ABC+conformance · ≥2 plugins each pass ·
verify green · coverage ratchet live ≥ baseline (→90%) · mypy strict · 0 frozen-contract edits ·
GitNexus reindexed showing the plugin cores wired (no orphans).

> Dispatch order: A1 → (A2,A4,A5,A6,A7 parallel) → A3 (needs registries) → A8 → A5b. Bind each to its
> role worktree per AGENT_BINDINGS.md, fresh branch off origin/main, Process Evidence, PR, merge-on-green.

---

## P-B — Simulation & synthetic PVT data (the hardware-free engine) — ✅ **PHASE COMPLETE 2026-07-04**

> B1 #44 · B2 #45 · B3 #47 · B4 #46 · B5 #48 · B6 #49 · B7 #50 · B6f #51 — all MERGED. Exit report
> with per-criterion evidence: STATUS.md §PHASE-B COMPLETE. 0 frozen-contract edits (audited).

**Goal:** build the *real* data-engine simulator — a seeded `SimRobot` + synthetic PVT scenario engine
that generates realistic, reproducible Proprioceptive·Visual·Tactile streams with **monotonic
timestamps**, so the whole pipeline is exercisable with zero hardware and byte-stable golden fixtures.
This is NOT the old `SimAdapter` stub (which returns `timestamp_ns=0` and state by-reference — a known
gap documented in `docs/sdk/ROBOT_SDK_MAPPING.md`); P-B builds the real thing alongside/replacing it.

**Invariants for every P-B task** (lead with the failure mode each prevents):
- **Frozen contracts untouched:** `PVTSample`/`PVT_SCHEMA_VERSION` and `RobotAdapter` are FROZEN — the
  sim *populates* existing fields (incl. the already-present `tactile_event`/`camera_frame_id`), never
  edits the schema. A schema change needs a `docs/decisions/00XX-*.md` record + approval. *(Prevents:
  silent schema drift breaking every downstream exporter/dataset.)*
- **Stdlib-only determinism (house style — NO numpy):** seed with `random.Random(seed)`; math in
  `math`. *(Prevents: non-portable, non-byte-stable fixtures across machines/CI.)*
- **One monotonic clock:** every sample stamped from a single monotonic source, strictly increasing;
  feed timestamps through `host/logger/jitter.py` (`compute_jitter`) and assert `backwards==0`,
  `dropouts==0`, within `JitterBudget`. *(Prevents: cross-modal misalignment — the core PVT failure.)*
- **Golden fixtures mirror `host/tests/fixtures/make_sample_canlog.py`:** a `make_sim_*` generator +
  committed golden + `.gitattributes` EOL pin + byte-identity test + documented regen command.
- Each task: fresh branch off origin/main, verify.ps1 + coverage ≥90% + ruff + mypy-strict, CodeRabbit
  + Process Evidence, orchestrator merges on green. Existing tests stay green.

**B1 · Seeded deterministic sim core** · lane: dataset · branch `feat/p-b/sim-seed-core` — ✅ MERGED #44
> Landed `host/sim/rng.py` `SeededRng` (frozen, stdlib-only, value-identity=seed, portable FNV-1a
> `spawn` for per-channel sub-streams) + `SimConfig.seed`/`rng()` (plumbed, output byte-identical).
> **B2 dispatched** (branch `feat/p-b/simrobot`).
- Introduce a seed-threaded generation core (`random.Random(seed)`, no numpy). Add `seed` to the
  synthetic generator config (`tools/dataset/sim_adapter.py` `SimConfig` and/or a new `host/sim/`
  module). Same seed → identical sequence; different seeds diverge; seed-unset reproduces today's
  byte-identical output (back-compat).
- Tests: same-seed converges / different-seed diverges; existing sim tests unchanged.
- Exit: green; coverage ≥90%; no numpy; frozen contracts untouched.

**B2 · Configurable `SimRobot` (DOF / kinematics / trajectory)** · lane: dataset/adapters · branch `feat/p-b/simrobot` — ✅ MERGED #45
> `host/sim/robot.py`: `SimRobot` (config DOF, sine/ramp/hold trajectory callables, monotonic
> non-zero timestamps, independent-copy reads, `SeededRng` threaded) + `SimRobotAdapter` (registered
> `sim_robot`, passes adapter conformance) — **closed the SimAdapter timestamp/by-reference gap**
> (ROBOT_SDK_MAPPING §4.7b, sim_robot ✅ / sim stays 🟡). **B3 (#47) + B4 (#46) MERGED 2026-07-01 (main @ cc91122, combined gate green, cov 92.3%). B5 dispatched.**
- A real `SimRobot` with configurable DOF + ≥2 pluggable trajectory models (e.g. sine + ramp/reach),
  emitting proprio `PVTSample`s with monotonic `timestamp_ns` and **independent-copy** reads. May be
  exposed behind the FROZEN `RobotAdapter` as a proper (non-stub) sim that fixes the
  `timestamp_ns=0`/by-reference gap — implementing the contract, never editing it.
- Tests: property (joint ranges within amplitude, N joints == DOF, strictly-increasing timestamps);
  trajectory determinism; independent-copy read.
- Exit: green; coverage ≥90%; frozen contracts untouched. If SimRobot satisfies the timestamp+copy
  contract, update the `sim` row in `ROBOT_SDK_MAPPING.md` 🟡→✅ (with evidence).

**B3 · Seeded proprio noise model** · lane: dataset · branch `feat/p-b/proprio-noise`
- Documented, bounded, seeded per-channel noise (angle/velocity/current/torque). Zero-noise config
  reproduces B2 output byte-for-byte.
- Tests: noisy values within documented bounds; zero-noise == B2; seed-reproducible draws.
- Exit: green; coverage ≥90%.

**B4 · Contact scenario spec (validated, serializable)** · lane: dataset · branch `feat/p-b/scenario-spec`
- A small scenario spec (dataclass + TOML/JSON) describing phased last-centimeter contact scripts
  (approach → `contact_start` → `slip`/`impact` → `release`) with fail-loud `validate()` raising
  `ValueError` (mirror `SimConfig.validate`).
- Tests: round-trip (serialize→load→equal); invalid specs raise; a golden scenario file is tested.
- Exit: green; coverage ≥90%.

**B5 · Synthetic tactile + visual sources from scenarios** · lane: dataset · branch `feat/p-b/sim-tactile-visual` — ✅ MERGED #48
- Drive `tactile_event` (using the existing `contact_start|slip|impact|release` tokens) and
  `camera_frame_id` from the scenario timeline — populating **already-frozen** PVTSample fields (NO
  schema bump). Add `sim-tactile` (TACTILE) + `sim-frames` (VISUAL) `SensorSource` plugins (the sources
  the `host/sensors` docstring already anticipates), registered on the existing SensorSource registry.
- Tests: scripted-contact episode carries the expected `tactile_event` tokens at scripted timestamps;
  `camera_frame_id` monotonic/unique; `sim-tactile`/`sim-frames` pass SensorSource conformance;
  `PVT_SCHEMA_VERSION` unchanged. *(Gives SensorSource ≥2 per modality; feeds P-D detectors.)*
- Exit: green; coverage ≥90%; frozen schema untouched.

**B6 · Golden fixtures + byte-stability harness** · lane: dataset · branch `feat/p-b/sim-golden` — ✅ MERGED #49 (+B6f #51 quantize)
- `make_sim_fixture.py` generator + committed golden episode(s) (canonical row dump and/or parquet),
  EOL/encoding pinned in `.gitattributes`, mirroring `make_sample_canlog`. Byte-identity test +
  one-line regeneration command.
- Tests: regenerated sim output byte-identical to the committed golden.
- Exit: green; coverage ≥90%.

**B7 · Jitter/clock property gate + CLI & registry wiring** · lane: dataset/release · branch `feat/p-b/sim-cli-jitter` — ✅ MERGED #50
- Route sim timestamps through `compute_jitter`; assert `backwards==0`/`dropouts==0`/within
  `JitterBudget`. Expose scenario selection via the dataset CLI (`--sim --scenario X`). Ensure sim
  sensor sources are registered/selectable.
- Tests: jitter property passes; `--sim --scenario X` exports a valid round-tripping lerobot dataset.
- Exit: green; coverage ≥90%; mypy strict.

### P-B exit (phase DONE only when all true)
Seeded `SimRobot` + noise + scenario spec + `sim-tactile`/`sim-frames` sources — all deterministic &
byte-stable · golden fixtures pinned · property tests (ranges, strictly-monotonic clock, jitter budget)
pass · every new plugin passes its conformance suite · verify green · coverage ratchet held ≥ baseline ·
mypy strict · **0 frozen-contract edits** · GitNexus reindexed (sim cores wired, no orphans).

> Dispatch order: B1 → B2 → (B3, B4 parallel) → B5 (needs B4) → B6 → B7. Each: role worktree, fresh
> branch off origin/main, Ponytail + docs + GitNexus, Process Evidence, PR, CodeRabbit, merge-on-green.

**P-B follow-up:**
- **B6f · Quantize golden floats for cross-platform byte-stability** · lane: dataset · branch
  `feat/p-b/golden-quantize` — ✅ MERGED #51 (escalated from queued to blocking when local verify went
  red on main) — the B6 golden serializes floats via exact `repr()`, byte-stable on the
  authoritative CI (Ubuntu libm) but off by a `math.sin`/`gauss` **last-ULP** on Windows/py3.13.
  Quantize the rendered floats (e.g. `f"{v:.9g}"`/round to ~9 sig figs) in `make_sim_fixture.render_row`
  AND canonicalize the parse-back comparison the same way; regenerate the golden. Exit: all golden tests
  pass on BOTH Windows-local and CI; byte-identity preserved across regenerations on either platform.

---

## P-C — Time-sync & multi-modal alignment — ✅ **PHASE COMPLETE 2026-07-08**

> C1 #52 · C2 #53 · C3 #54 · C4 #55 · C6 #56 · C5 #57 · C7 #59 — all MERGED. Exit report +
> MEASURED benchmark table in `STATUS.md` (PHASE-C COMPLETE, 2026-07-08). 3-state `SyncVerdict`
> (aligned/degraded/quarantined); gate provably fails on injected violations; committed evidence
> `docs/bench/P-C-TIMING-BENCH.*`. Simulation-proven; SDK map is SDK-doc-audited; hardware smoke
> stays bench-pending (`SDK_TIMEBASE_MAP §4`). (C7 merged from its pre-review commit during the
> 2026-07-08 parallel-work window; CodeRabbit nits re-applied in a follow-up host-lane PR.)

**Goal:** make the PVT pipeline **temporally correct** to a manufacturable bar: one monotonic timeline,
explicit clock domains, normalization that never silently "fixes" bad stamps, an alignment engine with
quality metadata, jitter/latency chaos benches, timing-auditable exports, SDK-ready adapter timestamp
contracts, and a benchmark gate the phase cannot close without. Simulation-proven; hardware evidence
stays bench-pending (never overclaim).

**Invariants for every P-C task** (lead with the failure mode each prevents):
- **Frozen contracts untouched:** `PVTSample`/`PVT_SCHEMA_VERSION`, `RobotAdapter`, CAN codec v1,
  `JointPodState.msg`. Timing records/alignment metadata live in NEW structures alongside the frozen
  sample — a schema change requires a `docs/decisions/00XX-*.md` record + approval. *(Prevents: schema
  drift breaking every downstream exporter.)*
- **No silent repair:** a bad/duplicate/backwards/out-of-domain timestamp is rejected or FLAGGED with
  provenance — never clamped, reordered, or guessed quietly. *(Prevents: fake synchronization that
  poisons training data undetectably.)*
- **Un-fakeable tests:** no "timestamp exists" assertions. Every task ships tests that FAIL if stamps
  are guessed/reordered/clamped/mis-aligned: exact-match, bounded-skew, out-of-order, duplicated,
  missing-modality, malformed-input, and seeded-chaos cases. Property-style where natural.
- **Stdlib-only determinism** (no numpy) · monotonic-vs-wall separation explicit · coverage ≥90%
  branch · mypy --strict · Ponytail (smallest useful change).

**C1 · Clock & timebase core** · lane: dataset/core · branch `feat/p-c/timebase-core` — ✅ MERGED #52
> `host/timing/`: ClockDomain (monotonic/wall/source), validated `Stamp` (cross-domain ordering
> RAISES), `require_monotonic` gate, LatticeClock/ScriptedClock (typed `ClockExhausted`). 65 tests,
> timing pkg 100% cov. CodeRabbit APPROVED (0 actionable). **C2 dispatched** (`feat/p-c/ts-normalize`).
- `host/timing/` (new): explicit timebase abstractions — `ClockDomain` (monotonic / wall / source-local),
  a monotonic-ns wrapper type, deterministic simulated clocks (fixed-lattice + scripted), and a stamped
  wrapper carrying `(raw_ns, domain)`. Reuse/absorb the `ClockNs` seam in `sensors.interface` (do NOT
  edit the SensorSource ABC surface). Wall-clock is representable but NEVER accepted where monotonic is
  required — type/validation error, not a warning.
- Tests: monotonicity enforcement; ordering; overflow/boundary values (0, negative, > 2^63-1 rejected);
  stable serialization round-trip; simulated clocks byte-deterministic across runs.
- Exit: green; ≥90% cov; frozen contracts untouched.

**C2 · Timestamp normalization layer** · lane: dataset · branch `feat/p-c/ts-normalize` — ✅ MERGED #53
> `host/timing/normalize.py`: NormalizationFlag (no catch-all) · TimingRecord (clean⊕flagged,
> MONOTONIC identity, SOURCE normalized==raw+skew — all construction-enforced) · Normalizer (WALL
> rejected; backwards FLAGGED never repaired; overflow flagged not clamped; idempotent). 100% cov.
> **C3 + C4 + C6 dispatched in parallel.**
- Canonical internal timing record (NEW dataclass, PVTSample untouched): original stamp, normalized
  monotonic stamp, source clock domain, and skew/uncertainty when known. Normalizer converts raw source
  stamps → canonical records; invalid stamps (non-positive/NaN/backwards-in-source) are rejected or
  flagged with a reason token — never silently repaired.
- Tests: property (ordering preserved; idempotence — normalizing twice is identity); invalid-stamp
  rejection per class; flagged-not-fixed proven (a bad input yields a flagged record, not a clean one).
- Exit: green; ≥90% cov.

**C3 · Multi-modal alignment engine** · lane: dataset · branch `feat/p-c/align-engine` — ✅ MERGED #54
> `host/timing/align.py`: EXACT/NEAREST/WINDOW + construction-enforced AlignmentResult invariants
> (stale-reuse ban; window-miss=NO_TARGET; coincidence always EXACT), dirty input rejected loud,
> flagged C2 records surfaced never used, interpolate_proprio numeric+finite only. 43 adversarial
> tests incl. shifted-clock integration.
- Align proprio/visual/tactile (+ future operator events) onto one timeline: nearest-neighbor and
  bounded-window association; interpolation only where physically safe (proprio yes, tactile events
  never). Every alignment result carries **quality metadata** (offset, method, in/out-of-budget flag) —
  values without provenance are banned.
- Hard tests: exact match · bounded skew · missing modality · out-of-order input rejected/flagged ·
  duplicated timestamps · large jitter → out-of-budget flag · no visual frame available · tactile event
  between proprio samples associates to the correct neighbor with recorded offset.
- Exit: green; ≥90% cov; alignment returns metadata, never bare values.

**C4 · Jitter/latency chaos bench** · lane: dataset/sim · branch `feat/p-c/chaos-bench` — ✅ MERGED #55
> `host/sim/chaos.py`: 8 seeded fault shapes (pure functions of (stamps, spec, seed); raise-never-
> clamp), 4 canonical BenchFixtures. 35 detection proofs — every fault mild-passes AND violating-
> fails-with-reasons (or its documented reference-instrument pair).
- Extend the sim stack (B2/B5 sources) with seeded, controlled fault injection: jitter, fixed delay,
  dropped frames, reordered delivery, skewed per-source clocks. Deterministic fixtures (same seed →
  same fault pattern). The alignment engine must either align within budget or quarantine/flag — tests
  assert BOTH paths (no always-pass thresholds; at least one case must quarantine).
- Tests: seeded chaos reproducibility; per-fault-type alignment outcome; quarantine actually triggers.
- Exit: green; ≥90% cov.

**C5 · Episode store + export timing metadata** · lane: export · branch `feat/p-c/export-timing-meta` — ✅ MERGED #57
> `host/timing/export_meta.py`: versioned TimingMeta sidecar (from_run-only, no fabrication;
> 3-state SyncVerdict aligned/degraded/quarantined via ONE shared rule; explicit reference
> timeline; unknown tokens/float versions refused) + fail-fast-before-writes exporter wiring
> (shared write_selected_timing_sidecar; legacy datasets load unchanged). 6/6 CodeRabbit
> comments fixed w/ regression tests. **C7 dispatched** (`feat/p-c/timing-bench-gate`) — last P-C task.
- Exports carry enough timing metadata to AUDIT sync: source stamp, normalized stamp, clock domain,
  alignment offset, frame/event association, sync-quality flags — as dataset-level/sidecar metadata
  (lerobot info/meta, parquet key-value metadata), NOT new PVTSample columns. Existing exporters keep
  round-tripping unchanged (back-compat tests stay green).
- Tests: round-trip of the timing metadata (write → load → equal) on lerobot + parquet; legacy datasets
  without the metadata still load; exporter conformance suite still passes.
- Exit: green; ≥90% cov; frozen schema untouched.

**C6 · SDK adapter time-source readiness** · lane: adapters · branch `feat/p-c/sdk-timebase-audit` — ✅ MERGED #56
> `docs/sdk/SDK_TIMEBASE_MAP.md`: evidence-cited per-SDK clock-domain audit (UR/Franka/KUKA/ROS2/
> custom-CAN) under strict status vocabulary; KUKA honestly `cannot-claim` (proprietary docs);
> ROS2 header.stamp = WALL by default → host-RX MONOTONIC stamping; + hardware smoke-test plan.
- Audit UR / Franka / KUKA / ROS2 / custom-CAN / generic adapters for timestamp sourcing; define per-SDK
  how stamps are provided or mapped to host monotonic (extend `docs/sdk/ROBOT_SDK_MAPPING.md` timing
  rows). Add adapter-conformance expectations for timestamp sourcing (monotonic, non-zero, declared
  domain). Precision language: "SDK-ready contract" / "simulation-proven" / "bench-pending" — never
  "hardware-ready" without bench evidence.
- Tests: conformance additions run against sim/replay/sim_robot (the no-hardware adapters); doc table
  complete for all six families.
- Exit: green; SDK timing map committed; no overclaims.

**C7 · P-C timing benchmark gate (phase gate)** · lane: dataset/release · branch `feat/p-c/timing-bench-gate`
- A benchmark suite + CLI report artifact measuring: monotonicity violations, max skew, mean alignment
  error, dropped-frame behavior, replay determinism, exporter round-trip stability, contact/event
  alignment accuracy. Includes the required CLI smoke: create a simulated episode → align modalities →
  export → reload → verify timing metadata. **P-C cannot close until this gate passes.**
- Tests: the gate fails on injected violations (prove it can fail); report artifact generated and
  parseable; smoke path green.
- Exit: gate green + report committed as evidence; phase-close criteria all machine-checked.

### P-C exit (phase DONE only when all true)
C1–C7 merged · one-monotonic-timeline enforced end-to-end with explicit clock domains · normalization
never silently repairs · alignment returns quality metadata · seeded chaos bench proves align-or-
quarantine · exports timing-auditable + back-compat · SDK timing map complete (no overclaims) · C7
benchmark gate green with committed report · verify green · coverage ≥90% · mypy strict ·
**0 frozen-contract edits** · GitNexus reindexed.

> Dispatch order: C1 → C2 → (C3, C4 parallel — C4 needs C1 clocks; C3 needs C2 records) → C5 → C6
> (parallel with C5) → C7 last. Lanes: dataset/export worker = C1-C5, adapters worker = C6,
> release = C7. Each: existing worktree, fresh branch off origin/main, Pre/Post-Work Evidence,
> PR, CodeRabbit adversarial round, orchestrator merges on green.

## P-D — Last-centimeter contact-event detection (DECOMPOSED 2026-07-08)

**Goal:** turn the time-aligned PVT window into **typed, labeled contact events** — the wedge of the
data engine (contact_start/release, current_spike, impact, slip). Every detector is a versioned
`EventDetector` plugin, graded against **labeled synthetic ground truth** with **precision/recall
thresholds that can fail**. Built on the merged P-A `EventDetector` ABC + `Event`/`EventKind`/`Window`
(`host/events/`) and the P-B/P-C scenario+timing stack. Simulation-proven; contact physics on real
silicon stays bench-pending (never overclaim a detector "works" from sim alone).

**Invariants for every P-D task** (lead with the failure mode each prevents):
- **Frozen contracts untouched:** `EventDetector`/`Event`/`EventKind`/`DETECTOR_SCHEMA_VERSION`,
  `PVTSample`/`PVT_SCHEMA_VERSION`. New event kinds/fields = a versioned schema change with a
  decision record, NOT a silent edit.
- **Un-fakeable grading:** the scorer must penalize BOTH misses (a silent/noop detector fails recall)
  AND false positives (a spam detector fails precision). A detection just outside tolerance is a
  miss, not a match; wrong-kind-right-time is not a match; one truth ↔ one detection (no double credit).
- **Labeled ground truth from the scenario scripts**, never re-detected: a scenario declares the
  contact moments it scripts; a free-space scenario yields zero labels (the false-positive negative case).
- **Deterministic:** same scenario+seed → identical labels and identical detector output (no wall clock).
- **Detection uses only the window's own aligned timestamps** (C1 monotonic), never a fresh clock.
- **Lane:** `host/` (data-pipeline) only; PRs off fresh `origin/main`; ≥90% branch; ruff+mypy strict.

**D1 · Labeled ground truth + precision/recall scorer** · lane: dataset · branch `feat/p-d/label-scorer` — **PR (dispatched)**
- Ground-truth `list[Event]` from a scenario's scripted contact timeline (`host/events/labels.py`) +
  `score_events(truth, detected, tolerance_ns)` → `DetectionScore` (TP/FP/FN, precision/recall/F1, per-kind).
- Tests: perfect=1.0; noop→recall<1; spam→precision low; ±tolerance boundary exact; wrong-kind no match;
  one-to-one matching; free-space yields [] truth; determinism. **Foundation — D2–D7 gate through this.**

**D2 · Contact detector (contact_start / contact_release)** · lane: dataset · branch `feat/p-d/contact-detector`
- The core wedge: force/current rise→`contact_start`, fall→`contact_release` over the aligned window.
  Versioned plugin via `make_event_detector`. Meets a documented P/R threshold on the labeled suite.
- Tests: meets threshold on contact scenarios; no false positives on free-space; hysteresis (no chatter).

**D3 · Current-spike detector** · lane: dataset · branch `feat/p-d/current-spike`
- Motor-current jump (bind/jam/hard contact) → `current_spike`. Threshold on the labeled suite; must
  NOT fire on ordinary contact ramps (distinguish spike from steady contact).

**D4 · Impact detector** · lane: dataset · branch `feat/p-d/impact`
- Abrupt velocity discontinuity + vibration → `impact`. Threshold on labeled impact scenarios; must
  separate impact from a normal contact_start.

**D5 · Slip detector** · lane: dataset · branch `feat/p-d/slip`
- Grasped-object micro-vibration + unexpected velocity → `slip`. Threshold on `slip_recovery`-class
  scenarios; must not confuse slip with release.

**D6 · Vibration / MEMS-audio surrogate channel + detector** · lane: dataset · branch `feat/p-d/vibration`
- A synthetic vibration/contact-audio surrogate channel (extends the B5 sensor-source stack, no
  `PVTSample` change — sidecar/derived) feeding a vibration detector that sharpens impact/slip recall.

**D7 · P-D detection phase-gate** · lane: dataset/release · branch `feat/p-d/detection-gate`
- Aggregate precision/recall report across ALL detectors on the labeled suite (the C7 analog for
  detection): committed `docs/bench/P-D-DETECTION.*` artifact, per-detector P/R vs threshold, gate
  exit≠0 when any detector misses its bar. **P-D cannot close until this gate passes.**

### P-D exit (phase DONE only when all true)

D1–D7 merged · labeled synthetic episodes with scripted ground truth · each detector meets its
precision/recall threshold on the suite · scorer provably penalizes miss AND false-positive · every
detector versioned (`DETECTOR_SCHEMA_VERSION`) · detection phase-gate green with committed report ·
verify green · coverage ≥90% · mypy strict · **0 frozen-contract edits** · GitNexus reindexed.

> Dispatch order: **D1 first** (scorer is the spine everything grades through) → then D2–D6 in
> parallel (each an independent detector plugin + its labeled-suite threshold) → D7 last (aggregate
> gate). Lane: `host/` data-pipeline only, single-lane PRs, CodeRabbit adversarial round, merge on green.
