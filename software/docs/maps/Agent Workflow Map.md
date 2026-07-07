# Agent Workflow Map

```mermaid
flowchart TD
    MGR[Manager<br>Terminal 1] -->|/orchestrate| PLAN[Dispatch Plan]
    PLAN --> LOCK{Contracts<br>locked?}
    LOCK -->|Yes| FW[firmware-engineer<br>Terminal 2]
    LOCK -->|Yes| HOST[ros2-integrator<br>Terminal 3]
    LOCK -->|Yes| DATA[data-pipeline-engineer<br>Terminal 4]
    LOCK -->|No| FIX[Lock contracts first]

    FW --> PR_FW[PR: feat/fw-*]
    HOST --> PR_HOST[PR: feat/host-*]
    DATA --> PR_DATA[PR: feat/data-*]

    PR_FW --> REVIEW[embedded-reviewer<br>Terminal 6]
    PR_HOST --> REVIEW
    PR_DATA --> REVIEW

    PR_FW --> CR[CodeRabbit<br>GitHub]
    PR_HOST --> CR
    PR_DATA --> CR

    REVIEW --> MERGE{All gates<br>passed?}
    CR --> MERGE
    MERGE -->|Yes| SQUASH[Squash merge<br>dependency order]
    MERGE -->|No| FIXPR[Fix + re-review]
    SQUASH --> VERIFY[verify.ps1]
    VERIFY --> REINDEX[GitNexus<br>re-index]
```

## Documents

- [[docs/agents/Agent Operating Model|Agent Operating Model]]
- [[docs/sop/development/Autonomous Development SOP|Autonomous Development SOP]]
- [[docs/sop/review/PR Review and Merge SOP|PR Review & Merge SOP]]
