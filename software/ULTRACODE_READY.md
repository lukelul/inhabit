# ULTRACODE_READY — preconditions before running the hardening pass

`ultracode` = a repo-wide final-hardening multi-agent pass (find stale docs, integration gaps,
dead paths, missing tests, hidden contract drift; propose fixes/PRs; do NOT create chaos).
It is **user-triggered only** — run it only when the user explicitly says "run ultracode",
and only after every box below is ticked.

## Preconditions (all must be ✅)
- [ ] PR queue clear: all open PRs merged or explicitly blocked. — *now: #14 open (blocked, maintainer)*
- [~] BENCH_READY_V0_2 lane PRs merged. — *✅ Lanes 1/3/4/5 merged (#21/#20/#18/#17/#19); Lanes 2/6 blocked on #14*
- [ ] `verify.ps1` green on `main`. — *✅ as of 02c549d*
- [ ] GitNexus reindexed on `main`, cycle-free, no orphans. — *✅ 1,145 nodes / 2,076 edges*
- [ ] CodeRabbit clean (no CHANGES_REQUESTED) on all open PRs. — *now: #14 CHANGES_REQUESTED*
- [ ] Obsidian vault merged to `main` (PR #14) so the second brain is canonical. — *now: ❌ unmerged*
- [ ] Frozen contracts unchanged (CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg). — *✅*

## Scope when it runs
- Stale docs vs. code · integration seams · dead/unreachable paths · untested paths ·
  hidden contract drift · then propose minimal fixes/PRs, each gated by CodeRabbit + verify.ps1.
- NOT: speculative rewrites, frozen-contract changes, or churn.

## Current verdict
**NOT READY** — two boxes block: PR #14 unmerged (vault not canonical; CodeRabbit CHANGES_REQUESTED).
Closing #14 + landing Lanes 2/6 flips this to READY. Do not run ultracode until then.
