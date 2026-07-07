# POST-GREEN ROADMAP — Inhabit (Phase A)

> **Post-#14 update (2026-06-29):** the docs vault (PR #14) is MERGED on main; mentions of it as
> "pending / unmerged / 📦" below are historical. P1 ✅, P2/P3/P4/P5 software ✅, P6 🔒 hardware.
> Current authoritative status: **STATUS.md**.

The software finish line (BENCHMARKS.md items 1–8) is **green** on `main`. This roadmap is the
new finish line: get the project bench-ready (docs + a hardware-free demonstrable data path) and
clearly fence off what genuinely needs the physical Rev-A board.

Status legend: ✅ done · 🟡 in progress · ⏳ waiting (no useful software task now) ·
🔒 HARDWARE-BLOCKED (needs the physical board; not a failure) · 📦 already in PR #14 vault (pending merge).

> Rule: HARDWARE-BLOCKED ≠ failed. Each such item names the exact bench evidence that closes it.
> Avoid busywork: do not duplicate the PR #14 docs vault; reference it and fill only real gaps.

---

## P1 — Docs PR clean
- ✅ **PR #14 is docs-only.** Every committed file is markdown (`docs/` vault + root READMEs);
  no `.py/.c/.h` in the PR's commits.
- ✅ verify.ps1 green on `main`.
- ⚠️ **Maintainer action — leaked uncommitted source in the docs working tree.** The primary
  checkout (on `docs/obsidian-technical-sop-vault`) has these uncommitted files that are NOT in
  PR #14 and are already on `main` via PR #11 — restore/remove before any `git add -A`:
  - `host/inhabit_bridge/bridge_node.py` (modified) → `git restore host/inhabit_bridge/bridge_node.py`
  - `host/inhabit_bridge/README.md` (modified) → `git restore host/inhabit_bridge/README.md`
  - `host/inhabit_bridge/launch/bridge.launch.py` (modified) → `git restore host/inhabit_bridge/launch/bridge.launch.py`
  - `host/inhabit_bridge/transport_source.py` (untracked) → delete (already on main)
  - `host/inhabit_bridge/tests/` (untracked) → delete (already on main)
  Then PR #14 merges cleanly as docs-only.

## P2 — Hardware bring-up package
Most procedures already authored in the PR #14 vault (📦, pending merge); bench execution is 🔒.
- 📦 first-power checklist → `docs/checklists/Before First Power Checklist.md`
- 📦 ADC/encoder smoke-test → `docs/checklists/Firmware Bringup Checklist.md` + `docs/hardware/bringup/Hardware Bring-Up SOP.md`
- 📦 MCP2515/CAN loopback → `docs/checklists/CAN Bringup Checklist.md`
- 📦 two-board ENUM test → `docs/checklists/ENUM Bringup Checklist.md`
- 📦 failure diagnosis table → `docs/risks/Risk Register.md` (+ Hardware Failure Report template)
- **Gap:** these are unmerged. Closing P2 = merge PR #14, then 🔒 execute on the board.

## P3 — Live CAN readiness
- ✅ canlog replay path exists in code (`host/transport/file.py`, `tools/can_replay`).
- ✅ bridge selectable-source path exists (`host/inhabit_bridge` file/socketcan via `transport_source.py`, PR #11).
- 🟡 **host transport smoke-test command** — needs a committed command/doc on `main` (see P4 lane).
- 🔒 socketcan/slcan live capture — needs a USB-CAN adapter + board. Bench evidence to close:
  `candump can0` showing 0x100+node_id frames at the expected rate.

## P4 — Real-frame data path
- ✅ chain wired + e2e test (`host/tests/test_e2e_pipeline.py`, PR #8): replay→bridge→JointPodState→logger→round-trip.
- 🟡 **one replayable sample `.canlog` fixture** — does NOT exist on `main` yet → ASSIGNED (dataset lane).
- 🟡 **documented export validation command** (fixture → bridge → logger → lerobot export, assert round-trip) → ASSIGNED.
- 🔒 real CAN frame from a powered board → close with a captured `.canlog` from the bench replacing the synthetic fixture.

## P5 — Visualization readiness
- ✅ viz runner exists (`python -m viz`, PR #9) with a README.
- 🟡 **live/replay viz command + expected output + failure cases** — fold a smoke-test using the P4 fixture (viz lane / dataset lane).
- 🔒 live viz from a real bus → bench, after P3 hardware.

## P6 — Hardware-gated TODOs (🔒, with bench evidence to close)
- **MCP2515 /INT EXTI on PB6** — scope shows /INT falling edge on PB6 driving an RX service; loopback then live.
- **Two-board CAN bus + ENUM ordering** — two pods enumerate to chain_index 0,1; both telemetry frames on the bus.
- **Inter-sample jitter within budget** — measured p99 jitter on a live bus inside the recorder's budget.
- **`colcon build` on Ubuntu 24.04 / ROS 2 Jazzy** — green ament build of `inhabit_msgs` + `inhabit_bridge` + `ros2 launch` smoke.
- **Encoder ADC sweep** — MT6701 magnet rotation → monotonic angle_millideg across range.

---

## Current state — MONITOR MODE (software side of Phase A complete)
- P1 ✅ (PR #14 docs-only; one maintainer restore step listed above — yours to merge).
- P2 📦 (authored in #14, merge to land; bench execution 🔒).
- **P3/P4/P5 software side ✅ DONE** — PR #15 (merged, main @b94350a) added the committed
  `host/tests/fixtures/sample.canlog` fixture + `test_postgreen_smoke.py` (replay→bridge→
  JointPodState→logger→lerobot export round-trip AND replay→viz), plus the exact copy-paste
  commands in `docs/hardware-free-data-path-smoke-test.md` and `host/viz/README.md`. verify green
  (121+ tests). The remaining P3/P4/P5 items (live socketcan capture, real bench frame, live viz)
  are 🔒 — close by swapping the synthetic fixture for a captured `.canlog` from a powered board.
- P6 🔒 — all need the physical board; bench evidence defined above.

**🟦 MONITOR MODE active.** No software work remains for Phase A. The next blockers are:
(1) maintainer merges PR #14 (docs vault, with the P1 restore step), and (2) physical Rev-A bench
testing (P2 execution + all P6 items). The orchestrator now only watches PRs and keeps this file
+ ORCHESTRATION.md current — it does not invent code.
