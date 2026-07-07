# Branch & worktree cleanup (SAFE reference)

> **DOCUMENT ONLY.** This file lists what is *safe* to clean and the rules for
> doing it. It does **not** run any deletion. Verify the merge state yourself
> (commands below) before deleting anything — branch lists drift as PRs land.

## The one rule that prevents data loss

**Prune the worktree before deleting an unmerged branch.**

`git branch -d` refuses to delete an unmerged branch (good). `git branch -D`
*force*-deletes it and throws away commits that exist only on that branch — if
the branch also has a checked-out worktree, you lose both the branch ref and the
uncommitted/unmerged work in that worktree. So:

1. Only `-D` (force-delete) a branch you have confirmed is either merged or truly
   disposable.
2. If a branch is checked out in a worktree, remove the worktree first:
   `git worktree remove <path>` (or `git worktree remove --force <path>` if it
   has local changes you have decided to discard). A branch cannot be deleted
   while it is the HEAD of a live worktree.
3. Prefer `git branch -d` (lowercase) — it only deletes branches already merged
   into the current HEAD, so it cannot silently drop work. Because it checks the
   *current HEAD* (not `origin/main`), be on `main` first — see the note under
   "Branches fully merged" below.

Run `git worktree prune` afterwards to clear stale worktree metadata.

## Verify before you delete

```bash
git fetch origin
# branches whose tip is already an ancestor of origin/main (safe to -d):
git branch --merged origin/main
# per-branch, authoritative check:
git merge-base --is-ancestor <branch> origin/main && echo MERGED || echo UNMERGED
# does a branch have a live worktree? (prune it first if so):
git worktree list
```

## Branches fully merged into `origin/main` — SAFE to delete

Verified with `git merge-base --is-ancestor <branch> origin/main` on
`ultracode/release-hygiene` (off `origin/main`). None of these had a live
worktree at audit time, so each can be deleted directly.

> **Be on `main` first.** Merged-ness here is checked against `origin/main`, but
> `git branch -d` only deletes branches merged into your **current HEAD**. Run
> `git checkout main && git pull --ff-only` (or otherwise be on a branch that
> already contains these merges) *before* `git branch -d <branch>`. Then the
> safe lowercase `-d` cannot fail with "not fully merged" and tempt you into the
> dangerous `git branch -D`.

```bash
git checkout main && git pull --ff-only   # current HEAD now contains the merges
git branch -d <branch>                     # safe: refuses anything not merged into HEAD
```

- `feat/firmware`
- `feat/firmware-int-b6`
- `feat/host`
- `feat/data`
- `feat/ci`
- `feat/codex`
- `calib-work`

## Listed but NOT merged — do **not** blind-delete

These were proposed for cleanup but their tips are **not** ancestors of
`origin/main` (they carry commits not on main). Treat as unmerged: confirm the
work is captured (merged via a renamed branch, or genuinely abandoned) before
removing. If you do delete, follow the prune-worktree-first rule above and use
`git branch -D` knowingly:

- `feat/enum` — UNMERGED at audit time
- `feat/dataset` — UNMERGED at audit time
- `fix/dataset-postgreen-cr-comments` — UNMERGED at audit time

## Worktrees

Many feature branches are checked out as worktrees under
`.claude/worktrees/` and sibling lane checkouts like `<repo>/../inhabit-<lane>`
(e.g. `/abs/path/to/inhabit-<lane>`). List the real paths on your machine with
`git worktree list`. Remove a worktree **before** deleting its branch:

```bash
git worktree remove <path>   # add --force only to discard local changes
git worktree prune
```

Do not remove worktrees marked `locked` in `git worktree list` without first
confirming the owning agent/task is done.
