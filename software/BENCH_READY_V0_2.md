# BENCH_READY_V0_2 — readiness for physical Rev-A bring-up

> **Post-#14 update (2026-06-29):** PR #14 (docs vault) is MERGED; main @5cf5fbe, 0 open PRs.
> References below to "#14 unmerged" / "Lanes 2/6 deferred" / "📦 pending vault" are historical.
> Current authoritative status: **STATUS.md**. Remaining work is hardware-gated (docs/bench/EVIDENCE_TEMPLATES.md).

**Milestone:** the repo is ready so that when the PCB arrives, a (tired) human can go
first-power → flash → encoder → CAN loopback → live bus → two-board ENUM → data logging →
dataset export → visualization → demo capture, with deterministic procedures and evidence
templates, and every hardware-gated step states the exact evidence that closes it.

Software finish line (BENCHMARKS 1–8) is already green. This milestone is about *bench readiness*,
not new product code. No frozen-contract edits (CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg).

## Status — Round 4 software side ✅ COMPLETE (2026-06-28, main @649e3bb)
Lanes 1/3/4/5 merged (6 PRs: #21 firmware bench docs, #20 firmware 3-pod C test + verify wiring,
#18 live-can runbook, #17 dataset readiness + seam tests, #19 viz demo runbook). `verify.ps1` green
(123 tests incl. firmware bench-3pod), GitNexus 1,285 nodes / 2,267 edges cycle-free.
**Remaining = non-software:** PR #14 (maintainer merges the docs vault → unblocks Lanes 2/6 +
mandatory context pass + ultracode) and P6 hardware (Rev-A bench). Lanes 2/6 stay deferred until #14.

## Readiness matrix
| Capability | State | Where |
|---|---|---|
| CAN codec v1 (C+Py, byte-identical) | ✅ on main | `firmware/.../can_frame.*`, `host/inhabit_can/codec.py` |
| MCP2515 SPI + CAN TX/RX loopback (polled) | ✅ on main (host-tested) | `firmware/drivers/mcp2515.c` |
| ENUM FSM wired into main loop | ✅ on main | `firmware/src/{main,enum}.c` |
| MT6701 calibration math | ✅ on main (tested) | `tools/calibrate.py`, `host/tests/test_calibration_helper.py` |
| Host bridge → JointPodState (Jazzy) | ✅ on main (headless) | `host/inhabit_bridge/` |
| Transport: file replay + socketcan source | ✅ on main | `host/transport/`, `inhabit_bridge/transport_source.py` |
| Adapters + registry (sim/replay/ros2/ur) | ✅ on main | `host/adapters/` |
| PVT logger → parquet + jitter quarantine | ✅ on main | `host/logger/` |
| lerobot export + CLI | ✅ on main | `host/export/`, `tools/dataset/__main__.py` |
| ASCII viz + runner | ✅ on main | `host/viz/` |
| Sample `.canlog` fixture + hardware-free e2e smoke | ✅ on main | `host/tests/fixtures/sample.canlog`, `test_postgreen_smoke.py` |
| Hardware bring-up SOPs / checklists | 📦 in PR #14 (unmerged vault) | `docs/hardware/...`, `docs/checklists/...` |
| First-power / encoder / SPI / loopback / ENUM / logging on the board | 🔒 HARDWARE-BLOCKED | needs Rev-A board |
| Blank bench evidence templates + thresholds (power/ADC/INT/rate/capture/ENUM) | ✅ staged (values HARDWARE-BLOCKED) | `docs/bench/EVIDENCE_TEMPLATES.md` |

## Lanes (Round 4 — bench readiness)
Lanes 1/3/4/5 run now (keyed to on-main code; new files; GitNexus + code as context). Lanes 2/6
are **blocked on PR #14** because they require the merged docs vault (avoid duplicating/conflicting
with it). See ORCHESTRATION.md for branches/owners/exit criteria and PROGRESS.md for the heartbeat.

| Lane | Branch | State | Note |
|---|---|---|---|
| 1 firmware bench harness | `bench-v0.2/firmware-bench-harness` | 🟡 active | firmware code on main; new bench-test→evidence docs + expected 3-pod CAN frames |
| 3 live CAN / transport readiness | `bench-v0.2/live-can-readiness` | 🟡 active | operator commands + troubleshooting keyed to transport/bridge + fixture |
| 4 dataset / export readiness | `bench-v0.2/dataset-export-readiness` | 🟡 active | validation checklist; real-`.canlog` swap-in; quarantine rules |
| 5 viz / demo operator | `bench-v0.2/viz-demo-operator` | 🟡 active | demo script + expected ASCII + troubleshooting |
| 2 hardware evidence kit | (deferred) | ⛔ blocked on #14 | evidence templates overlap #14 vault; merge #14 first |
| 6 release/risk/second-brain | (deferred) | ⛔ blocked on #14 | edits vault + tracking docs; merge #14 first |

## Exit criteria for BENCH_READY_V0_2
- Lanes 1/3/4/5 merged (verify.ps1 green, CodeRabbit clean, new files only, contracts frozen).
- PR #14 merged (vault on main) → Lanes 2/6 run and merge.
- Every hardware step has an evidence template + exact pass/fail-or-TBD threshold.
- ULTRACODE_READY.md checklist all ticked (then, and only then, ultracode may run).

## The gate: PR #14 (docs vault)
Docs-only ✅, but **CONFLICTING + CodeRabbit CHANGES_REQUESTED (29 prose comments)** and tangled in
the maintainer's uncommitted working tree (leaked bridge files + uncommitted `.obsidian/`).
**This is the single human blocker for the whole round** (it carries the vault the context pass and
Lanes 2/6 depend on). Action: maintainer merges #14 — resolve root-doc conflicts (take `main`'s
`ORCHESTRATION.md`/`PROGRESS.md` live state, #14's vault content), `git restore` the leaked
`host/inhabit_bridge/*` files first (already on main via #11), and address/accept CodeRabbit's prose nits.
