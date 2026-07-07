# Rev-A Bring-Up Log

> Append one entry per stage as you bring up a physical Rev-A board on instruments
> (`pcb-bringup` skill: "a bring-up you didn't log is a bring-up you'll redo"). Work ONE
> stage at a time (power → MCU/encoder → CAN loopback → live CAN → 2-board chain → ENUM) and
> do not advance until the current stage's gate is met. Fill the matching template in
> `docs/bench/EVIDENCE_TEMPLATES.md`, then summarize the result + artifact reference here.
>
> **Status: no hardware results yet — all stages HARDWARE-BLOCKED (no Rev-A board on the
> bench).** The entries below are placeholders; each links the template that defines its
> pass/fail gate.

| Date (UTC) | Stage | Template | Result (PASS/FAIL/BLOCKED/HARDWARE-BLOCKED) | Key value(s) | Artifact ref | Notes |
|------------|-------|----------|----------------------------|--------------|--------------|-------|
| `___` | E1 power | `EVIDENCE_TEMPLATES.md` §E1 | HARDWARE-BLOCKED | 5V5=`___` 3V3=`___` idle=`___`mA CANH-CANL=`___`Ω | `___` | no board |
| `___` | E2 encoder (ADC) | §E2 | HARDWARE-BLOCKED | A0 span=`___` OOB=[`___`,`___`] | `___` | no board |
| `___` | E3 /INT loopback | §E3 | HARDWARE-BLOCKED | CANSTAT=`___` PB6 low=`___`V | `___` | no board |
| `___` | E4 live CAN rate | §E4 | HARDWARE-BLOCKED | per-ID=`___`fps load=`___`% | `___` | no board |
| `___` | E5 per-pod capture | §E5 | HARDWARE-BLOCKED | ID=`___` checksum ok=`___` | `___` | no board |
| `___` | E6 chain / ENUM | §E6 | HARDWARE-BLOCKED | indices=`___` jitter_p99=`___`ms | `___` | no board |

## Stage log (free-form, newest first)

_(append narrative entries here as stages are run — what was measured, which failure-tree
branch was hit if any, and the fix)_
