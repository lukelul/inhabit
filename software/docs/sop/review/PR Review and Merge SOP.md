# PR Review and Merge SOP

## Review Flow

### 1. List Open PRs
```bash
gh pr list
```

### 2. Check CI Status
```bash
gh pr checks <number>
```
All checks must be green before merge.

### 3. View PR Details
```bash
gh pr view <number>
gh pr view <number> --comments
```

### 4. CodeRabbit Review

CodeRabbit reviews automatically. Check its comments:

| Comment Type | Action |
|-------------|--------|
| Major (blocking) | Must be resolved before merge |
| Minor (suggestion) | Note and address if appropriate |
| Nitpick | Optional, can defer |
| LGTM / Approved | Ready to merge |

### 5. Embedded Reviewer
Run `/review-firmware` in the reviewer terminal for firmware/host diffs.
Returns: BLOCK (critical issue) / FIX (needs change) / OK (safe to merge).

---

## Merge Criteria

All must be true:
- [ ] CI checks green (`gh pr checks`)
- [ ] No unresolved Major CodeRabbit comments
- [ ] `embedded-reviewer` returns OK
- [ ] Frozen contracts untouched (CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg)
- [ ] New code has at least one test
- [ ] Changes only in the track's own directory

---

## Squash Merge Policy

Always squash merge to keep `main` history clean:
```bash
gh pr merge <number> --squash --delete-branch
```

---

## Post-Merge Verification

### Verify Main
```bash
git checkout main && git pull
pwsh scripts/verify.ps1
```

### GitNexus Re-Index
After a batch of merges (not after every single merge):
```bash
npx gitnexus analyze --force
```

---

## Handling Problems

### CI Fails
1. Check which step failed: `gh pr checks <number>`
2. Read the CI log: `gh run view <run_id> --log`
3. Fix in the branch, push
4. Wait for CI to re-run

### CodeRabbit Comments Are Wrong
1. Reply to the comment explaining why it's incorrect
2. If genuinely wrong, resolve the conversation
3. Document the reasoning in the PR description

### Worker Touched Frozen Contracts
1. **BLOCK the merge immediately**
2. Comment on the PR explaining which contract was violated
3. Worker must rewrite the change to use the contract as-is
4. If the contract genuinely needs to change, that's a separate versioned decision (see [[docs/decisions/Decision Record Template]])

### Branch Is Stale
1. In the branch:
```bash
git fetch origin main
git rebase origin/main
# resolve any conflicts
git push --force-with-lease
```
2. CI will re-run automatically
3. Re-request CodeRabbit review if needed
