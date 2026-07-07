# The 6-Level Claude Mastery Playbook — applied to Inhabit

The levels aren't a ladder you climb once; they're layers that stack. A Level 6 setup is a
Level 3 brain + Level 4 tools + Level 5 skills, *orchestrated*. Skipping the foundation is the
one trap that breaks everything above it: five agents producing five flavors of slop. This bundle
gives you all six layers, tuned for a ROS 2 / STM32 / CAN robotics project.

---

## Level 1 — The Prompter ("Claude is a tool")
**Master when:** your prompts are clear, specific, and you can read/evaluate the output.
**For Inhabit:** be concrete. Not "write CAN code" but "encode joint state per schema v1 in
`can-protocol`, little-endian, with XOR checksum, plus a round-trip test." Specificity is the
single biggest quality lever.
**Trap — regression to the mean:** no context = Claude guesses = average-of-training-data slop.
The fix is every level below.

## Level 2 — The Conversationalist
**Master when:** you iterate — show output, correct, refine — instead of one-shotting.
**For Inhabit:** treat bring-up as a dialogue. Paste the scope reading, the CANSTAT value, the
error frame; let Claude reason from real evidence rather than guessing silicon. Iterate in tight
loops on a logic analyzer trace.

## Level 3 — The Context Engineer ("you're a curator")  ← the foundation
**Master when:** you maintain a lean CLAUDE.md, think about what Claude sees vs. doesn't, and
`/clear` between tasks.
**For Inhabit (built):** `.claude/CLAUDE.md` is your brain — vision, the Rev-A pin map, CAN schema,
PVT contract, conventions, operating rules. Per-directory memory in `firmware/CLAUDE.md` and
`host/CLAUDE.md` keeps each domain's context local.
**Trap — bloated CLAUDE.md:** LLM-generated context files made agents *worse* in most settings
(ETH Zurich result). Less is more. Detail belongs in skills, pulled on demand — which is exactly
how this bundle is structured. Prune anything that isn't load-bearing for most tasks.

## Level 4 — The Toolsmith ("you equip Claude")
**Master when:** you install the *right* MCPs per project and connect Claude to the outside world.
**For Inhabit:** surgical selection (see `SETUP_GUIDE.md`). GitHub for the repo; Exa/Microsoft
Learn for STM32 datasheets and ROS docs; alphaXiv for robot-learning papers; a serial/CAN bridge
locally for hardware. Skip the rest.
**Trap — the candy shop:** every MCP you add is context tax and another way for the agent to get
distracted. Install per-track, not "all of them."

## Level 5 — The Skilled ("Claude becomes YOURS")
**Master when:** custom skills encode YOUR standards and workflows, so nobody else's Claude works
like yours.
**For Inhabit (built):** six skills — `stm32-firmware`, `can-protocol`, `ros2-node`, `pcb-bringup`,
`pvt-data-logger`, `embedded-review` — plus slash commands (`/bringup`, `/can-msg`, `/ros2-node`,
`/review-firmware`, `/orchestrate`). These turn repeated explanations into one-line invocations.
**Trap — skill overload:** 20–30 curated beats 1,000 generic. We deliberately shipped 6. Add a new
skill only when a workflow repeats and you keep re-typing the same context. Use the official
**Skill Creator** to author new ones; have it eval triggering accuracy.

## Level 6 — The Orchestrator ("you're a manager")
**Master when:** you run multiple agents at once, use worktrees for isolation, and decide WHAT
gets done, not HOW.
**For Inhabit (built):** `ORCHESTRATION.md` + six subagents (`firmware-engineer`, `ros2-integrator`,
`data-pipeline-engineer`, `hardware-bringup`, `embedded-reviewer`, `research-scout`). The CAN schema
and `RobotAdapter` interface are the contracts that let firmware, host, and data tracks run in
parallel git worktrees without colliding.
**Trap — skipping the foundation:** orchestration without Levels 3–5 = five agents inventing five
incompatible interfaces. The guardrail is: **lock the shared contracts first** (CAN schema v1, PVT
schema, RobotAdapter signature), then fan out.

---

## Your fastest path to a Level 6 Inhabit run
1. Drop this `.claude/` into the repo. That's Levels 3 + 5 instantly.
2. Connect 1–3 MCPs from `SETUP_GUIDE.md` (Level 4) — only what the current track needs.
3. Lock the contracts (already written in CLAUDE.md / skills).
4. `/orchestrate "bring CAN telemetry up across two boards and log it"` → dispatch agents to
   worktrees (Level 6).
5. `/review-firmware` gates every merge. `/clear` between dispatches.
