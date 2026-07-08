# Working together without merge conflicts

Two or more people (and AI sessions) share this repo. Merge conflicts happen when
**two people change the same file before either one merges.** These rules make that
almost impossible. They are boring on purpose — boring is what keeps a shared repo sane.

## The 5 rules

1. **Never commit straight to `main`.** Everyone works on their own branch and opens a
   Pull Request (PR). `main` only changes through a merged PR. (Direct pushes to `main`
   are what caused the firmware version clash on 2026-07-08.)

2. **Stay in your lane.** Each person owns a set of folders (see the table). You may
   *read* anything, but only *edit* files in your lane without a heads-up. This is the
   single most important rule — if two people never edit the same file, git never has a
   conflict to resolve.

3. **Start every task from fresh `main`:**
   ```bash
   git fetch origin
   git checkout -B my-feature origin/main   # branch off the latest main
   ```
   Small branches that start from today's `main` barely ever conflict.

4. **Small PRs, merged often.** A 1–3 file PR that merges the same day cannot drift far
   from `main`. A giant week-long branch is a conflict guarantee. When in doubt, ship
   smaller.

5. **One merge at a time, then everyone re-syncs.** After *any* PR merges, everyone with
   an open branch runs `git fetch origin && git rebase origin/main` to pull the change in.
   If you hit a conflict there, you resolve it in *your* branch — never on `main`.

## Lanes (who edits what)

| Lane | Folders / files | Owner |
|------|-----------------|-------|
| **Firmware & hardware** | `firmware/**` | (friend) |
| **CAD / robot description** | `inhabit_description/**`, `host/**/custom_can*`, SW2URDF tooling | (friend) |
| **Data pipeline (timing, sim, export, dataset, detection)** | `host/timing/**`, `host/sim/**`, `host/logger/**`, `host/export/**`, `host/tools/dataset/**`, `docs/bench/**`, `docs/sdk/**` | (Youssef + Claude) |
| **Shared — coordinate before editing** | root `*.md`, `CLAUDE.md` files, `MASTER_PLAN.md`, `MASTER_TASK_QUEUE.md`, and the **frozen contracts**: `host/inhabit_can/pvt.py` (`PVTSample`/`PVT_SCHEMA_VERSION`), `RobotAdapter`, the CAN codec, `JointPodState.msg` | everyone — ping first |

> If a task needs a file outside your lane, say so in chat first ("I need to touch
> `firmware/x`") so the lane owner isn't editing it at the same time.

## If a PR shows "conflicts" on GitHub

Don't panic and don't edit on `main`. In your branch:
```bash
git fetch origin
git rebase origin/main          # replay your work on top of the latest main
# git shows the conflicting files; open each, keep the right lines, then:
git add <fixed-file>
git rebase --continue
git push --force-with-lease      # updates your PR; --force-with-lease is the safe force
```
`--force-with-lease` only overwrites *your own* branch and refuses if someone else pushed
to it meanwhile — so it can never clobber a teammate.

## Frozen contracts (never change casually)

`PVTSample` / `PVT_SCHEMA_VERSION`, `RobotAdapter`, the CAN message schema v1, and
`JointPodState.msg` are shared interfaces everything depends on. Changing one silently
breaks the other person's code. Change these **only** with a written decision record and a
version bump, agreed by both people first.

## For AI sessions (Claude / Fable) working this repo

- You are one of the "people" above. Pick a lane, branch off fresh `origin/main`, open PRs,
  never direct-push to `main`.
- Before editing, `git fetch origin`, then check whether an open PR already touches the files
  you plan to edit: `gh pr list` lists the open PRs, and `gh pr diff <n> --name-only` (or
  `gh pr view <n> --json files`) shows the files each one changes — `gh pr list` alone does not.
  If the firmware lane is active, don't rewrite `firmware/**`.
- Keep diffs surgical (one concern per PR) so a lane owner can review and merge fast.
- See `ORCHESTRATOR_HANDOFF.md` for the full mission/guardrails context.
