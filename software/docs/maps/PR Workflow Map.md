# PR Workflow Map

```mermaid
flowchart TD
    CODE[Write code] --> TEST[Run verify.ps1]
    TEST -->|Pass| PUSH[Push branch]
    TEST -->|Fail| FIX1[Fix tests]
    FIX1 --> TEST

    PUSH --> PR[gh pr create]
    PR --> CI[CI runs]
    PR --> CR[CodeRabbit reviews]

    CI -->|Green| CHECK1[CI OK]
    CI -->|Red| FIX2[Fix CI failures]
    FIX2 --> PUSH

    CR -->|Approved| CHECK2[Review OK]
    CR -->|Changes requested| FIX3[Address comments]
    FIX3 --> PUSH

    CHECK1 --> GATE{All gates?}
    CHECK2 --> GATE
    GATE -->|Yes| MERGE[gh pr merge --squash]
    GATE -->|No| WAIT[Wait for remaining]

    MERGE --> VERIFY[verify.ps1 on main]
    VERIFY --> REINDEX[GitNexus re-index]
```

## Merge Order Rule
Schema-defining track first:
1. Firmware (CAN frame producers)
2. Host (CAN frame consumers)
3. Data (PVT consumers)
4. Docs / viz

## Documents

- [[docs/sop/review/PR Review and Merge SOP|PR Review & Merge SOP]]
- [[docs/checklists/Before Merge Checklist|Before Merge Checklist]]
