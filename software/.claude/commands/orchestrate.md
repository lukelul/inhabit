---
description: Plan and dispatch parallel work across firmware / host / data tracks (Level 6)
---
Act as the orchestrator. For the goal in $ARGUMENTS:
1. Decompose into independent tracks (firmware / ros2 / data / hardware) with clear interfaces
   (the CAN schema and RobotAdapter are the contracts that let tracks run in parallel).
2. For each track, name the agent to run it, the worktree/branch, the definition of done, and the
   integration checkpoint.
3. Flag cross-track dependencies and what must be agreed FIRST (usually a schema/interface).
4. Output a dispatch plan I can execute (one terminal/worktree per track), then offer to launch them.
