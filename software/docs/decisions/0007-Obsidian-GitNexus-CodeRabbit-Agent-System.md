# ADR-0007: Obsidian + GitNexus + CodeRabbit Agent System

## Status
Accepted

## Context
A solo founder running multiple coding agents in parallel needs: (1) code intelligence to prevent breaking changes, (2) automated PR review to catch what agents miss, (3) documentation that serves both humans and future agents.

## Decision
- **GitNexus:** MCP-based code intelligence. Agents must run `impact()` before edits and `detect_changes()` before commits.
- **CodeRabbit:** Automated PR review on GitHub. No unresolved Major comments before merge.
- **Obsidian vault:** Technical documentation with wikilinks, SOPs, architecture references, checklists.
- **Agent contracts:** AGENTS.md + CLAUDE.md define shared rules. Frozen contracts prevent parallel agents from diverging.

## Failure Mode Prevented
- Agent breaking a function it didn't understand (impact analysis catches upstream callers)
- Invalid code merging to main (CodeRabbit + embedded-reviewer gate)
- Knowledge lost between sessions (Obsidian vault persists context)
- Parallel agents producing incompatible interfaces (frozen contracts)

## Alternatives Considered
1. No code intelligence -- rejected: agents would break things constantly
2. Manual PR review only -- rejected: too slow for parallel agent workflow
3. Wiki (GitHub/Notion) instead of Obsidian -- rejected: Obsidian is local, version-controlled, wikilink-native
4. Single agent (no parallelism) -- rejected: too slow for multi-track development

## Consequences
- Positive: scalable multi-agent development
- Positive: documentation travels with the code
- Trade-off: setup complexity (multiple terminals, worktrees, MCP servers)
- Trade-off: GitNexus index can become stale (re-index after merges)

## Related Source Files
- `.claude/CLAUDE.md`, `AGENTS.md`
- `.coderabbit.yaml`
- `docs/` (this vault)

## Related Tests
- N/A (process, not code)

## Open Questions
- How often should GitNexus be re-indexed? (Currently: after merge batches)
