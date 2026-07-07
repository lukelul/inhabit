# Autonomous Development SOP

## Required Terminals (8-Terminal Layout)

| # | Terminal | Folder | Run | Role |
|---|---------|--------|-----|------|
| 1 | MANAGER | repo root (main) | `claude` | `/orchestrate`, merge PRs, keep contracts locked |
| 2 | Firmware | `../inhabit-fw` | `claude` | "act as firmware-engineer" |
| 3 | Host/ROS2 | `../inhabit-host` | `claude` | "act as ros2-integrator" |
| 4 | Data | `../inhabit-data` | `claude` | "act as data-pipeline-engineer" |
| 5 | Bring-up | repo root | `claude` | "act as hardware-bringup" |
| 6 | Reviewer | repo root | `claude` | `/review-firmware` per branch |
| 7 | Research | repo root | `claude` | "act as research-scout" |
| 8 | Codex | `../inhabit-codex` | `codex` | Second coding agent |

---

## GitNexus Server

Run in a separate terminal (not one of the 8):
```bash
npx gitnexus serve
# Open http://localhost:3000 in a browser
```

Keep running throughout the session. Agents query the MCP server for impact analysis.

---

## Startup Procedure

### 1. Create Worktrees
```bash
git worktree add ../inhabit-fw    feat/fw-<feature>
git worktree add ../inhabit-host  feat/host-<feature>
git worktree add ../inhabit-data  feat/data-<feature>
git worktree add ../inhabit-codex feat/codex-<feature>
git worktree list
```

### 2. Lock Contracts
In Terminal 1 (Manager), verify contracts are agreed:
```
/orchestrate "<goal>"
```
Confirm the CAN schema v1, PVT sample schema, and RobotAdapter interface are locked before dispatching.

### 3. Dispatch Agents
In each agent terminal, paste the track assignment:
- T2: "implement <firmware feature> per stm32-firmware + can-protocol skills"
- T3: "implement <host feature> per ros2-node skill"
- T4: "implement <data feature> per pvt-data-logger skill"

They run simultaneously, converging on the shared contracts.

---

## Branch and PR Flow

### Branch Naming
- `feat/fw-<feature>` -- firmware
- `feat/host-<feature>` -- host/ROS2
- `feat/data-<feature>` -- data pipeline
- `docs/<topic>` -- documentation

### PR Creation
```bash
gh pr create --title "<type>: <short description>" --body "..."
```

### CodeRabbit Review
- Automatic on PR creation
- Check: `gh pr view <number> --comments`
- Resolve Major comments before merge

### CI Checking
```bash
gh pr checks <number>
```

### Merge Order
Merge in dependency order (schema-defining first):
1. Firmware (CAN frame producers)
2. Host (CAN frame consumers)
3. Data (PVT consumers)
4. Visualization / docs

```bash
gh pr merge <number> --squash --delete-branch
```

---

## Post-Merge

### Verify Main
```bash
git checkout main && git pull
pwsh scripts/verify.ps1
```

### Re-Index GitNexus
```bash
npx gitnexus analyze --force
```

### Update Obsidian Docs
If architecture or SOPs changed, update relevant docs in `docs/`.

### Update ORCHESTRATION.md
Update the live status table with merged PRs and next actions.

---

## Human Intervention Rules

Intervene when:
- An agent modifies a frozen contract (BLOCK immediately)
- Impact analysis returns CRITICAL risk
- Two agents produce conflicting interfaces (contract wasn't locked)
- CI fails on main after merge
- CodeRabbit raises a valid security/safety concern
- Agent is stuck in a loop (not making progress)

---

## Shutdown/Restart Procedure

### Clean Shutdown
1. Let all agents finish their current task
2. Push any uncommitted work
3. Remove worktrees:
```bash
git worktree remove ../inhabit-fw
git worktree remove ../inhabit-host
git worktree remove ../inhabit-data
git worktree remove ../inhabit-codex
```

### Recovery from Stale Worktrees
```bash
# Check what exists
git worktree list

# If a worktree has uncommitted changes, navigate to it and commit/stash
cd ../inhabit-fw && git stash

# Force remove if necessary (data loss risk!)
git worktree remove --force ../inhabit-fw
```

### Recovery from Failed PRs
1. Check CI failure: `gh pr checks <number>`
2. Fix in the worktree, push
3. Re-request CodeRabbit review if needed
4. If unfixable, close PR and start fresh

### Recovery from Merge Conflicts
1. In the worktree: `git fetch origin main && git rebase origin/main`
2. Resolve conflicts, continue rebase
3. Force push: `git push --force-with-lease`
4. Check CI re-runs

### Recovery from Duplicate GitNexus Indexes
```bash
npx gitnexus clean
npx gitnexus analyze --force
```
