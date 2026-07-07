# Agent Round Checklist

## Before Dispatch
- [ ] Contracts locked (CAN schema v1, RobotAdapter, PVTSample)
- [ ] `/orchestrate` run, decomposition reviewed
- [ ] Worktrees created for each active track
- [ ] GitNexus server running (`npx gitnexus serve`)
- [ ] Each agent assigned specific task with done-criteria

## During Execution
- [ ] Agents working in isolated worktrees
- [ ] No agent touching another track's files
- [ ] Ponytail mode active (minimum viable changes)
- [ ] Agents running `impact()` before edits
- [ ] Agents running tests as they go

## Before Merge
- [ ] Each PR reviewed by `embedded-reviewer`
- [ ] Each PR reviewed by CodeRabbit
- [ ] All CI checks green
- [ ] Merge order determined (schema-defining first)

## After Merge
- [ ] `verify.ps1` run on `main` after each merge
- [ ] GitNexus re-indexed after merge batch
- [ ] ORCHESTRATION.md updated with round results
- [ ] Worktrees cleaned up
- [ ] `/clear` run between rounds
