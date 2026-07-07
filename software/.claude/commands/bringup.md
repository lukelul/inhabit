---
description: Start or resume guided Rev-A hardware bring-up for the current stage
---
Use the `pcb-bringup` skill and the `hardware-bringup` agent. Determine which stage we're on
(check docs/bringup-log.md if present), then guide me through the next stage ONLY: list the exact
checks, the expected scope/DMM readings, and the failure tree if it goes wrong. Do not skip ahead.
Stage to work on (optional): $ARGUMENTS
