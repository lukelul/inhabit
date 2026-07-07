# P-C timing benchmark — measured phase-gate report (C7)

- bench version: 1
- regenerate: `cd host && python -m timing.bench --scenario slip_recovery --seed 7 --out <output-dir>`
- gate mode: `default` — **PASS**
- offsets are published EXACT/NEAREST alignment offsets (ns); WINDOW event-association offsets live in each report's `timing_meta`. Percentiles are nearest-rank (`ceil(p/100*n)`).

| case | verdict | mono. viol. | flagged/records | non-matched/results | max abs offset (ns) | p95 (ns) | p99 (ns) | contact events | deterministic | lerobot rt | parquet rt |
|---|---|---|---|---|---|---|---|---|---|---|---|
| clean_baseline | aligned_within_budget | 0 | 0/166 | 0/144 | 20,000,000 | 10,000,000 | 20,000,000 | 25/25 (1.000) | yes | ok | ok |
| can_jitter_mild | aligned_within_budget | 0 | 0/425 | 0/245 | 199,634 | 189,415 | 199,092 | 25/25 (1.000) | yes | ok | ok |
| camera_variable_33ms | degraded | 0 | 0/205 | 50/140 | 1,937,014 | 1,781,464 | 1,937,014 | 25/25 (1.000) | yes | ok | ok |
| burst_stall_200ms | quarantined | 20 | 20/425 | 25/263 | 0 | 0 | 0 | 20/25 (0.800) | yes | ok | ok |
| skewed_source_clock | quarantined | 0 | 0/425 | 200/250 | - | - | - | 25/25 (1.000) | yes | ok | ok |

## Dropped-frame behavior (input -> delivered -> surviving)

- **clean_baseline**: contact_events 25->25->25, frames 47->47->47, proprio 47->47->47, tactile 47->47->47 — episode gate PASSED
- **can_jitter_mild**: contact_events 25->25->25, disturbed 200->200->200, reference 200->200->200 — episode gate PASSED
- **camera_variable_33ms**: contact_events 25->25->25, disturbed 90->90->90, reference 90->90->90 — episode gate PASSED
- **burst_stall_200ms**: contact_events 25->25->25, disturbed 200->200->180, reference 200->200->200 — episode gate REFUSED: monotonic clock went backwards on 1 interval(s); 1 dropout(s): interval > 2.5x period
- **skewed_source_clock**: contact_events 25->25->25, disturbed 200->200->200, reference 200->200->200 — episode gate PASSED

## Gate thresholds

- `burst_stall_200ms`: {"allowed_verdicts": ["quarantined"], "max_abs_offset_ns": 0, "max_flagged_records": 20, "max_monotonicity_violations": 20, "max_p99_abs_offset_ns": 0, "min_contact_accuracy": 0.5}
- `camera_variable_33ms`: {"allowed_verdicts": ["aligned_within_budget", "degraded"], "max_abs_offset_ns": 2000000, "max_flagged_records": 0, "max_monotonicity_violations": 0, "max_p99_abs_offset_ns": 2000000, "min_contact_accuracy": 1.0}
- `can_jitter_mild`: {"allowed_verdicts": ["aligned_within_budget", "degraded"], "max_abs_offset_ns": 200000, "max_flagged_records": 0, "max_monotonicity_violations": 0, "max_p99_abs_offset_ns": 200000, "min_contact_accuracy": 1.0}
- `clean_baseline`: {"allowed_verdicts": ["aligned_within_budget"], "max_abs_offset_ns": 20000000, "max_flagged_records": 0, "max_monotonicity_violations": 0, "max_p99_abs_offset_ns": 20000000, "min_contact_accuracy": 1.0}
- `skewed_source_clock`: {"allowed_verdicts": ["quarantined"], "max_abs_offset_ns": null, "max_flagged_records": 0, "max_monotonicity_violations": 0, "max_p99_abs_offset_ns": null, "min_contact_accuracy": 1.0}

## Gate result

- all thresholds satisfied
