# ULTRACODE_BENCH_READY — Hardening Audit (2026-06-28, main @d39d506)

Read-only audit across 8 categories (GitNexus + code, claims reproduced). Verify: 123 host tests
+ 7 firmware C tests green. **Frozen contracts, codec, firmware logic, recorder, and viz are SOLID.**
The real software work is one reproduced data-corruption path + doc-vs-code drift + hygiene debt.

## Verdict
NOT purely hardware-blocked: there is a reproduced **data-corruption path** (lerobot CLI /
`export_lerobot` ingest frames the `EpisodeRecorder` rejects), a cluster of **doc↔code drift**
(INT pin "unverified" vs PB6-confirmed code; Makefile omits `test_bench_3pod`; inverted coverage
callout), and **hygiene** (committed ELF binary; 40 branches / 20 worktrees). All surgical →
worth one hardening round before the board. Bring-up numeric thresholds/templates are the only
genuinely HARDWARE-BLOCKED items.

## Findings by category (severity)
1. **Contract drift** — SOLID. CAN v1 byte-identical (C↔Py), RobotAdapter/PVTSample/JointPodState clean. No action.
2. **Firmware** — core SOLID. BLOCKER: INT-pin contradiction (firmware/README.md:12 + root .claude/CLAUDE.md pin-map + .claude/skills/stm32-firmware/SKILL.md say "A3 vs B6 unverified" while main.c/mcp2515.c/firmware/CLAUDE.md commit to **PB6 confirmed**). IMPORTANT: Makefile omits `test_bench_3pod`; `cc` hardcoded (use `CC ?= cc`); BENCH_TESTS.md says "6 targets"/inverted coverage callout/stale expected-output (missing bench-3pod line); steer operators to verify scripts not `make`. POLISH: `inhabit_calib_id()` untested; two golden-frame tables differ (label canonical); `MCP_ERR_MODE` branch untested.
3. **Host bridge/transport** — mostly SOLID (slcan honestly "planned", socketcan lazy-import). IMPORTANT: host/README.md:99 `pytest tests/` fails from host/ (tools import) → document repo-root run. POLISH: OPERATING.md:209 cites dead `SocketCanSource`; :80 stale repo name.
4. **Dataset/export** — recorder SOLID. **BLOCKER**: `tools/dataset/__main__.py:33-46` builds JointPodState but never checks `checksum_valid` → exports corrupt frames (REPRODUCED: 3 good+1 bad → 4 exported). **BLOCKER**: `export_lerobot` (lerobot.py:92) has no jitter/monotonicity gate; `_infer_timing` silently drops backward gaps. IMPORTANT: frame grouping by adjacency not timestamp (lerobot.py:45-60); no NaN/inf rejection in recorder ingest. POLISH: DATASET_READINESS.md:8-9 overstates ("nothing half-valid ever exported" false for CLI); quarantine sidecar not fsync'd.
5. **Viz/demo** — SOLID. Every no-hardware command + expected output byte-verified; 19 viz tests pass. No action.
6. **Hardware bring-up** — all HARDWARE-BLOCKED. Gaps are missing numeric thresholds + fill-in templates (power V/I/short, ADC sweep counts/OOB, /INT timing, per-pod frame rate, ENUM edge tolerances, full-chain-log acceptance). Doc authors can pre-stage blank templates now; values need silicon.
7. **Repo hygiene** — no tracked pycache/.obsidian/gitnexus-skills (SOLID). IMPORTANT: `firmware/test/run_test` is a committed Linux ELF (.gitignore covers `run_test_mcp2515` but not bare `run_test`). POLISH: 40 branches / 20 worktrees; merged ones safe to prune (document, don't execute).
8. **Doc truthfulness** — INT-pin contradiction (§2), DATASET_READINESS overstatement (§4), inverted coverage callout (§2), host/README pytest + firmware `make` commands that don't run as written. Otherwise truthful.

Full reproduction details captured in ULTRACODE_TASK_QUEUE.md per task.

---
## CLOSE-OUT (main @23747d2)
**Software/docs/tooling hardening COMPLETE.** All audit software/docs findings fixed & merged
(#25 dataset corruption gate, #24 firmware INT-pin/Makefile, #22 hygiene, #23 hardware templates).
verify.ps1 green (136 tests), GitNexus reindexed (1,350 nodes / 2,406 edges, cycle-free), all lane
PRs CodeRabbit-APPROVED. Remaining work is **HARDWARE-BLOCKED** — the bench numeric values in
ULTRACODE_AUDIT.md §6 / docs/bench/EVIDENCE_TEMPLATES.md (need the physical Rev-A board) — plus the
one human gate: maintainer merges PR #14 (docs vault).
