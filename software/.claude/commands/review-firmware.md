---
description: Adversarially review the current diff before merge
---
Invoke the `embedded-reviewer` agent on the pending changes (git diff). Apply the embedded-review
checklists. Return BLOCK/FIX/OK, highest-severity first, each with file:line and the real-hardware
failure it would cause. Scope (optional): $ARGUMENTS
