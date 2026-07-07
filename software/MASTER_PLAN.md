# MASTER_PLAN — Inhabit Data Engine (software-only, plugin-everything, verifiable)

> Pivot (2026-06-29): hardware bring-up is OUT OF SCOPE here (parked, plugin-mocked). This plan
> drives the **software** to production / "manufacturable" quality: a plugin-architected, ML-native
> teleoperation **PVT data engine** that is fully exercisable in pure simulation with verifiable
> correctness end-to-end. Every milestone has machine-checkable exit criteria. Executed by /loops.

## North star
**Inhabit Data Engine** — ingest synchronized **Proprioceptive · Visual · Tactile (PVT)** streams
from *any* robot (swappable adapters) over *any* transport, align them on one monotonic clock,
detect last-centimeter contact events, record atomic versioned episodes, QA them, and export
ML-ready datasets (lerobot / parquet / HDF5) — all runnable with **no hardware**, proven by tests.
*The data engine is the business; everything else is a plugin.*

## Architecture law: everything is a plugin behind a stable, versioned contract
Core code NEVER branches on concrete type. Each extension point is a registry with entry-point
discovery + an abstract base + a **conformance test suite** every implementation must pass:

| Extension point | Base (frozen contract) | Plugins (sim-backed; no hardware) |
|---|---|---|
| Robot | `RobotAdapter` | sim, replay, ur, franka, kuka, ros2, custom-can |
| Transport | `Transport` | file-replay, socketcan(mock), slcan(mock), sim, inmem |
| Sensor source | `SensorSource` (proprio/visual/tactile) | sim-proprio, sim-frames, sim-tactile |
| Event detector | `EventDetector` | current-spike, vibration, slip, impact, contact |
| Exporter | `Exporter` | lerobot, parquet, hdf5 |
| Sink / recorder | `EpisodeSink` | parquet-atomic, inmem, quarantine |

Frozen contracts (never edited except by a versioned decision record): CAN codec schema v1,
`RobotAdapter`, `PVTSample`/`PVT_SCHEMA_VERSION`, `JointPodState.msg`. New capability = new plugin
or new versioned ID block, never a breaking change.

## Quality bar ("perfection" gate) — enforced in CI on every PR
- `verify.ps1`/`verify.sh` green (firmware C host-tests + host pytest).
- **Coverage ≥ 90%** on touched packages (ratchet upward; never down).
- ruff clean · mypy --strict clean · no new warnings.
- Each plugin passes its interface **conformance test**; each exporter is **round-trip** (write→read→assert-equal).
- CodeRabbit hard gate + Process Evidence (WORKER_PROCESS_EVIDENCE.md) on every PR.
- Determinism: seeded, reproducible; golden fixtures byte-stable.
- No frozen-contract edits without a `docs/decisions/00XX-*.md` record + orchestrator approval.

## Phase roadmap (each phase = a milestone; PR-gated; verifiable exit criteria)

### P-A — Plugin foundation & contract conformance
Generalize the `make_adapter` registry pattern to ALL extension points (Transport, SensorSource,
EventDetector, Exporter, EpisodeSink) with entry-point discovery + abstract bases. Build a reusable
**conformance test harness** (`host/tests/conformance/`) parametrized over every registered plugin.
- Exit: every extension point has a registry + ABC + conformance suite; ≥2 plugins each pass; mypy strict; coverage ≥90% on the plugin core.

### P-B — Simulation & synthetic data (the hardware-free engine)
`SimRobot` + sensor-source plugins generating realistic, seeded PVT: trajectories (configurable
DOF/kinematics), proprio noise, synthetic visual frame refs, tactile force/vibration, scripted
contact scenarios via a small scenario spec. Deterministic golden fixtures.
- Exit: scenario spec tested; sim emits byte-stable fixtures; property tests (ranges, monotonic clock); coverage ≥90%.

### P-C — Time-sync & multi-modal alignment engine
First-class alignment of proprio/visual/tactile to one monotonic clock: jitter measurement, skew
detection, resampling/interpolation, drift handling. Plugin-clean.
- Exit: inject skew/jitter → realign within budget (tests); property-based timing tests; quarantine on over-budget; coverage ≥90%.

### P-D — Last-centimeter contact-event detection (the wedge)
`EventDetector` plugins (current-spike, vibration/MEMS-audio surrogate, slip, impact, contact_start/
release) over synthetic + replay data, with labeled scenarios and precision/recall gates.
- Exit: labeled synthetic episodes; each detector meets a precision/recall threshold on the suite; detector versioned; coverage ≥90%.

### P-E — Episode store, QA & dataset lifecycle
Hardened atomic episode store; schema-version migrations; dataset-level QA (completeness, jitter,
label coverage, dedup, provenance); quarantine pipeline; large-dataset handling.
- Exit: round-trip + migration tests; QA gates enforced; 10k-episode perf test within budget; coverage ≥90%.

### P-F — ML-ready export ecosystem (plugins)
Exporters: lerobot (hardened) + parquet + hdf5, each round-trippable + cross-format equivalent;
HF `datasets`/torch load smoke (optional-dep guarded).
- Exit: each exporter write→read→assert-equal; cross-format equality test; HF/torch load smoke; coverage ≥90%.

### P-G — Multi-robot adapter ecosystem (plugins, sim/mock-backed)
Adapters for UR, Franka, KUKA, generic ROS2, custom-CAN — all mock/sim-backed (no hardware),
capability negotiation, each passing RobotAdapter conformance + a sim integration test.
- Exit: every adapter passes conformance + sim e2e; capability matrix documented; coverage ≥90%.

### P-H — Teleop session orchestration & SDK + CLI
Clean SDK + CLI: config-driven plugin selection (adapter+transport+source+detector+exporter), a
`record → align → detect → QA → export` session pipeline, live viz, resumable sessions.
- Exit: one-command sim session → validated dataset; SDK API tests; config-driven plugin wiring tested; coverage ≥90%.

### P-I — Performance, scale & robustness
Throughput/latency benchmarks with budgets; backpressure; streaming large episodes; fuzz + property
tests; fault injection (dropouts, corruption, clock jumps) → graceful degradation.
- Exit: perf budgets met + tracked; fuzz suite green; soak test; chaos tests pass; coverage ≥90%.

### P-J — Packaging, docs, release & "manufacturable" polish
pip-installable packages, semver + CHANGELOG, generated API docs, runnable examples, CI matrix
(py3.11/3.12: lint/type/test/coverage), dependency/security audit, reproducible build.
- Exit: clean install in a fresh venv; docs build; coverage ≥ target repo-wide; tagged release artifact; CI matrix green.

### P-K — Live teleop session ops layer (sim-driven, no hardware)
Real-time session lifecycle (start/pause/resume/stop) streaming PVT through the engine live;
operator controls; live event annotation; resumable session state machine; backpressure under load.
- Exit: live sim session e2e with real-time alignment + event stream; state-machine + backpressure tests; coverage ≥90%.

### P-L — Operator dashboard & viz platform (plugin renderers)
Beyond ASCII: a structured live telemetry API + pluggable renderers (TUI / JSON-stream / web-ready),
multi-pod multi-modal display, session timeline, live QA indicators.
- Exit: dashboard renders a live sim session; renderer-plugin conformance; deterministic snapshot tests; coverage ≥90%.

### P-M — Multi-session manager + plugin marketplace + extensibility SDK
Manage many concurrent sessions/datasets; a plugin discovery/validation "marketplace" (entry-point
based) with a third-party plugin SDK + project template + a validation harness; cross-platform
capability/version negotiation.
- Exit: a sample *external* plugin installs via the marketplace path and passes conformance; multi-session manager tested; plugin SDK + template + docs; coverage ≥90%.

## Execution model (/loops)
Each loop: pick the next unblocked task from MASTER_TASK_QUEUE.md → bind to a role worktree →
Ponytail + read docs + GitNexus (learn deps/impact) → write code + tests → verify.ps1 + coverage →
PR + CodeRabbit + Process Evidence → orchestrator merges when green → reindex GitNexus → update
STATUS.md/PROGRESS.md/MASTER_TASK_QUEUE.md. Never break frozen contracts. No fake churn. Advance
phase-by-phase; a phase is DONE only when every exit criterion is machine-verified.

Authoritative current state: STATUS.md. Task decomposition: MASTER_TASK_QUEUE.md.
