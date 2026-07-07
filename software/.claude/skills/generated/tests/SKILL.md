---
name: tests
description: "Skill for the Tests area of Inhabit-Software. 650 symbols across 77 files."
---

# Tests

650 symbols | 77 files | Cohesion: 77%

## When to Use

- Working with code in `host/`
- Understanding how sample_from_pod_state, read_episode, test_arbitrary_canlog_round_trips work
- Modifying tests-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/tests/test_export_timing_meta.py` | test_lerobot_round_trip, _backwards_episode, test_refused_episode_meta_omitted_with_warning, test_three_flagged_records_in_means_flagged_three_out, test_out_of_budget_result_in_means_quarantine_out (+31) |
| `host/tests/test_timing_normalize.py` | _mono, test_clean_record_constructs_and_is_a_value, test_neither_clean_nor_flagged_rejected, test_both_clean_and_flagged_rejected, test_flagged_record_constructs (+26) |
| `host/tests/test_timing_align.py` | test_exact_match_is_exact_offset_zero, test_exact_method_rejects_non_coincident, test_nearest_within_budget_matches_with_signed_offset, test_nearest_beyond_budget_is_flagged_and_unpublished, test_large_jitter_beyond_budget_every_ref_flagged (+22) |
| `host/tests/test_calibration_helper.py` | test_calib_can_id, test_encode_rejects_out_of_range_adc, test_encode_rejects_out_of_range_millideg, test_encode_rejects_out_of_byte_range_fields, test_decode_stamps_monotonic_rx_with_injected_clock (+21) |
| `host/tests/test_sinks.py` | test_corrupt_checksum_quarantined_through_recorder_wrapped_by_sink, _sample, test_nan_joint_value_rejected_by_parquet_sink, test_inf_joint_value_rejected_keeps_episode_clean, test_nan_rejected_by_inmem_sink (+19) |
| `host/tests/test_scenario.py` | test_validate_accepts_examples, test_validate_rejects_empty_name, test_validate_rejects_unknown_kind, test_validate_rejects_non_positive_duration, test_validate_rejects_negative_start (+19) |
| `host/tests/test_sensors.py` | _strip_ts, test_reopen_replays_identical_data, test_noise_free_is_pure_sweep_and_deterministic, test_injected_clock_drives_timestamps, test_default_stepping_clock_is_monotonic (+19) |
| `host/tests/test_registry_core.py` | _fresh, test_make_returns_instance, test_make_forwards_kwargs, test_unknown_name_raises_value_error_listing_available, test_duplicate_register_raises_value_error (+19) |
| `host/tests/test_events.py` | test_noop_returns_empty_on_empty_window, test_threshold_emits_above_threshold, test_threshold_uses_absolute_value, test_threshold_must_be_positive, test_threshold_empty_window (+18) |
| `host/tests/test_sim_chaos.py` | test_no_spec_is_identity, test_different_seed_differs_for_stochastic_faults, test_extending_a_chain_does_not_shift_earlier_faults, test_drop_probability_is_seeded_and_deterministic, test_reorder_window_exceeding_sequence_rejected (+18) |

## Entry Points

Start here when exploring this area:

- **`sample_from_pod_state`** (Function) — `host/inhabit_can/pvt.py:99`
- **`read_episode`** (Function) — `host/logger/parquet_io.py:130`
- **`test_arbitrary_canlog_round_trips`** (Function) — `host/tests/test_dataset_readiness.py:72`
- **`test_e2e_replay_bridge_state_writer_round_trip`** (Function) — `host/tests/test_e2e_pipeline.py:101`
- **`test_parquet_interleaved_footer_jitter_is_deduped`** (Function) — `host/tests/test_exporter_registry.py:402`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `Widget` | Class | `host/tests/test_registry_core.py` | 33 |
| `RedWidget` | Class | `host/tests/test_registry_core.py` | 38 |
| `BlueWidget` | Class | `host/tests/test_registry_core.py` | 43 |
| `GreenWidget` | Class | `host/tests/test_registry_core.py` | 76 |
| `Other` | Class | `host/tests/test_registry_core.py` | 124 |
| `sample_from_pod_state` | Function | `host/inhabit_can/pvt.py` | 99 |
| `read_episode` | Function | `host/logger/parquet_io.py` | 130 |
| `test_arbitrary_canlog_round_trips` | Function | `host/tests/test_dataset_readiness.py` | 72 |
| `test_e2e_replay_bridge_state_writer_round_trip` | Function | `host/tests/test_e2e_pipeline.py` | 101 |
| `test_parquet_interleaved_footer_jitter_is_deduped` | Function | `host/tests/test_exporter_registry.py` | 402 |
| `test_codec_to_episode_round_trip` | Function | `host/tests/test_integration.py` | 47 |
| `test_episode_roundtrip_multisample` | Function | `host/tests/test_logger.py` | 57 |
| `test_sample_from_pod_state_maps_radians` | Function | `host/tests/test_logger.py` | 114 |
| `test_jitter_clean_stream_period_and_zero_jitter` | Function | `host/tests/test_logger.py` | 128 |
| `test_within_budget_passes` | Function | `host/tests/test_logger.py` | 137 |
| `test_over_budget_jitter_quarantined` | Function | `host/tests/test_logger.py` | 150 |
| `test_dropout_quarantined` | Function | `host/tests/test_logger.py` | 166 |
| `test_backwards_clock_quarantined` | Function | `host/tests/test_logger.py` | 177 |
| `test_too_few_samples_quarantined` | Function | `host/tests/test_logger.py` | 187 |
| `test_strict_raises_on_quarantine` | Function | `host/tests/test_logger.py` | 195 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → _timestamp` | cross_community | 7 |
| `_load_scenario_episode → Sigma` | cross_community | 7 |
| `_load_scenario_episode → Spawn` | cross_community | 7 |
| `_load_scenario_episode → Gauss` | cross_community | 7 |
| `Load_lerobot_timing_meta → _member_from_token` | cross_community | 6 |
| `Load_lerobot_timing_meta → _validate_count` | cross_community | 6 |
| `Load_lerobot_timing_meta → _histogram_from_counter` | cross_community | 6 |
| `Load_parquet_timing_meta → _member_from_token` | cross_community | 6 |
| `Load_parquet_timing_meta → _validate_count` | cross_community | 6 |
| `Load_parquet_timing_meta → _histogram_from_counter` | cross_community | 6 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Inhabit_can | 14 calls |
| Timing | 11 calls |
| Conformance | 8 calls |
| Logger | 6 calls |
| Export | 4 calls |
| Sensors | 3 calls |
| Transport | 3 calls |
| Sim | 2 calls |

## How to Explore

1. `context({name: "sample_from_pod_state"})` — see callers and callees
2. `query({search_query: "tests"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
