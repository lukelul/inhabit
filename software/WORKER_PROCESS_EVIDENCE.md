# WORKER PROCESS EVIDENCE — mandatory for every worker output / PR

The orchestrator REJECTS any worker output or PR that lacks a complete **Process Evidence**
section with NAMED artifacts. Vague reports ("used GitNexus", "checked docs", "all good",
"monitor clean") are rejected and the task is bounced back. Name the actual files, modules,
tests, and review state.

## Required section (paste in the worker's final report + the PR body)

### Process Evidence

**1. Worker identity**
- Lane name:
- Terminal / worktree path:
- Branch name:
- PR number (if any):

**2. Skill / context usage** (exact paths, not "consulted docs")
- `.claude/skills/.../SKILL.md` files consulted: <list exact files>
- Obsidian / repo docs consulted: <exact file paths>
- GitNexus modules / flows checked: <exact module names / flow ids / queries run>

**3. Codebase impact**
- Source files inspected: <exact paths>
- Source files modified: <exact paths>
- Tests affected: <exact test files / test names>
- Frozen contracts touched (CAN codec v1 / RobotAdapter / PVTSample / JointPodState.msg): **yes/no** (must be no unless an approved versioned decision)

**4. Validation**
- `verify.ps1` result: <pass/fail + key counts>
- Focused tests run: <exact commands + results>
- CodeRabbit reviewDecision: <APPROVED / CHANGES_REQUESTED / none yet>
- Unresolved CodeRabbit comments: <list file:line, or "none">

**5. Justification**
- Why this task belongs to this lane:
- Why the chosen files are the correct files:
- What would be unsafe to touch (and why):

## Orchestrator enforcement
- Before merging or accepting any PR, confirm the Process Evidence section is present and
  concrete. If any field is vague or missing → bounce to the worker, do not merge.
- This applies to all `ultracode/<lane>-*` and `bench-v0.2/*` worker PRs.
- Read-only audit agents report findings (not a PR), but must still name the files/modules
  they inspected so findings are verifiable.
