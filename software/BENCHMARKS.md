# BENCHMARKS — the bar each track must clear (then we run ultracode)

An agent's work is "done" only when ALL of these are green. `scripts/verify.ps1` checks the
first two automatically; the rest are reviewed per-PR.

## Per-track (every branch, before merge)
1. `scripts/verify.ps1` passes — C codec test + host pytest, no failures.
2. The new subsystem ships with ≥1 test of its own (no untested code).
3. New files only live in the track's own directory; the CAN codec, RobotAdapter, PVTSample,
   and JointPodState.msg are treated as FROZEN contracts (imported, never edited).
4. CodeRabbit PR review has no unresolved blocking comments.
5. `embedded-reviewer` (or `/review-firmware` for firmware) returns OK.

## System-level (the green light for ultracode)
6. End-to-end: replayed CAN frames → `inhabit_bridge` publishes `JointPodState` →
   episode writer records → round-trip read asserts equal. One automated test proves it.
7. GitHub Actions `verify` workflow is green on `main`.
8. GitNexus re-index (`npx gitnexus analyze --force`) shows every subsystem connected,
   no orphaned modules.

## Hardware-gated (deferred to the Jazzy bench — NOT blocking software benchmarks)
- `colcon build` on Ubuntu 24.04 / ROS 2 Jazzy.
- Live two-board CAN bus + measured inter-sample jitter within budget.
- MCP2515 /INT EXTI on the verified pin (B6 — confirm against schematic).

## When 1–8 are green
Flip on `ultracode` and run a repo-wide hardening workflow:
"Audit firmware + host for CAN-timing races, ISR safety, schema drift, and untested paths;
verify every finding with an independent agent before reporting."
