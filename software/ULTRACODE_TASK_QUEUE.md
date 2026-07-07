# ULTRACODE_TASK_QUEUE — prioritized hardening tasks (from ULTRACODE_AUDIT.md)

Status: ASSIGNED → in a worker lane · DONE → PR open · MERGED · HARDWARE-BLOCKED.
Every worker PR must include the Process Evidence section (WORKER_PROCESS_EVIDENCE.md).
Frozen contracts (CAN v1, RobotAdapter, PVTSample/PVT_SCHEMA_VERSION, JointPodState.msg) untouched.

## Lane C — Dataset/export corruption gate  · branch `ultracode/dataset-export-gate` · ASSIGNED
- **C1 [BLOCKER]** `tools/dataset/__main__.py:33-46` exports corrupt-checksum frames (REPRODUCED 4/3).
  Fix: skip `if not checksum_valid` (mirror recorder.py:119-121) or route CLI through EpisodeRecorder.
- **C2 [BLOCKER]** `host/export/lerobot.py:92` `export_lerobot` has no jitter/monotonicity gate; `_infer_timing` drops backward gaps.
  Fix: run `compute_jitter` per episode, refuse/flag on backwards>0 or over-budget, OR scope to recorder-passed input + document.
- **C3 [IMPORTANT]** `lerobot.py:45-60` groups by adjacency not timestamp → interleaved pods split an instant. Fix: group by `timestamp_ns` (dict after sort).
- **C4 [IMPORTANT]** No NaN/inf rejection. Fix: reject non-finite joint_angle/velocity in `EpisodeRecorder.ingest` (math.isfinite).
- **C5 [POLISH]** `DATASET_READINESS.md:8-9` scope wording (recorder vs gate-free CLI).
- Tests required: corrupt-frame CLI export now drops it (assert count); backwards-ts episode refused/flagged; interleaved-pod grouping correct; NaN/inf rejected. exit: pytest+ruff+mypy green, Process Evidence, CodeRabbit clean. NOT hardware-blocked.

## Lane A — Firmware doc/Makefile drift  · branch `ultracode/firmware-doc-makefile` · ASSIGNED
- **A1 [BLOCKER]** INT-pin contradiction: `firmware/README.md:12`, root `.claude/CLAUDE.md` pin-map note, `.claude/skills/stm32-firmware/SKILL.md` say "A3 vs B6 unverified" — code commits to PB6. Fix: "MCP2515 /INT = PB6 (confirmed; EXTI line 6, falling edge)".
- **A2 [IMPORTANT]** `firmware/test/Makefile` omits `test_bench_3pod` + hardcodes `cc`. Fix: add target + clean entry; `CC ?= cc`.
- **A3 [IMPORTANT]** `firmware/BENCH_TESTS.md` "6 targets"→7; inverted coverage callout (:178-179); stale expected-output (add `bench-3pod: 3 tests passed`); steer operators to verify scripts over `make`.
- **A4 [POLISH]** add one `inhabit_calib_id()` assert in `test_calib.c`; cross-reference/label the two golden-frame tables.
- Tests required: all 7 firmware C tests build+pass incl. via Makefile; verify.ps1 green. exit: as above. NOT hardware-blocked. (Note: edits root .claude/CLAUDE.md + firmware/README.md — NOT in PR #14's file set, so no conflict.)

## Lane F — Hygiene + host-doc truthfulness  · branch `ultracode/release-hygiene` · ASSIGNED
- **F1 [IMPORTANT]** `git rm --cached firmware/test/run_test` (tracked ELF) + widen `.gitignore` `run_test_mcp2515`→`run_test*`.
- **F2 [IMPORTANT]** `host/README.md:99` pytest command → repo-root invocation (or add pythonpath).
- **F3 [POLISH]** `OPERATING.md:209` dead `SocketCanSource` attribution; `:80` stale repo path.
- **F4 [POLISH]** document SAFE branch/worktree prune (merged: feat/firmware, feat/host, feat/data, feat/ci, feat/enum, feat/dataset, calib-work, etc.) — DOCUMENT only, do not execute deletions.
- Tests required: verify.ps1 green; confirm run_test no longer tracked. exit: as above. NOT hardware-blocked.

## HARDWARE-BLOCKED — bring-up evidence templates (Lane E, deferred; needs Rev-A board)
- **E1** power V/I/short thresholds; **E2** ADC sweep counts + OOB window; **E3** /INT pulse timing/level; **E4** per-pod frame rate + bus load; **E5** per-pod capture fill-in template; **E6** ENUM edge tolerances + full-chain-log acceptance (frame count/dropped budget/jitter).
- A doc author MAY pre-stage the blank templates + threshold scaffolding now (software-doable); the measured numbers require silicon. If staged, that becomes Lane E branch `ultracode/hardware-evidence-templates`. Otherwise HARDWARE-BLOCKED with the exact measurements listed in ULTRACODE_AUDIT.md §6.

## Not assigned (no real finding) — Lanes B (transport) & D (viz): SOLID per audit. WAITING (no safe task).

---
## RESULT — all software/docs tasks MERGED (main @23747d2, verify green 136)
- Lane C `ultracode/dataset-export-gate` → **MERGED (#25)** — corrupt-frame export gated (4→3 reproduced), per-episode jitter/monotonicity gate, timestamp grouping, NaN/inf rejection, +write→read tests.
- Lane A `ultracode/firmware-doc-makefile` → **MERGED (#24)** — INT-pin PB6 contradiction fixed; Makefile `.PHONY`+`test_bench_3pod`+`CC ?= cc`; BENCH_TESTS drift; calib test. (CodeRabbit calib-ID 0x300 comment SKIPPED-WITH-REASON: sanctioned separate ID block, not a v1 violation.)
- Lane F `ultracode/release-hygiene` → **MERGED (#22)** — untracked run_test ELF + widened .gitignore; host/README pytest cmd; OPERATING refs; CLEANUP.md.
- Lane E `ultracode/hardware-evidence-templates` → **MERGED (#23)** — blank bench evidence templates + thresholds; measured values **HARDWARE-BLOCKED** (E1–E6 evidence listed in ULTRACODE_AUDIT.md §6 + docs/bench/EVIDENCE_TEMPLATES.md + docs/bringup-log.md).
- Lanes B (transport) / D (viz) → not assigned (audit: SOLID).
- HARDWARE-BLOCKED (need Rev-A board): bring-up numeric values per EVIDENCE_TEMPLATES.md (power V/I/short, ADC sweep+OOB, /INT timing, per-pod rate, ENUM edges, full-chain-log acceptance).

All 4 lane PRs were CodeRabbit-APPROVED + verify-green + carried complete Process Evidence before merge.
