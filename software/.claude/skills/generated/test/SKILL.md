---
name: test
description: "Skill for the Test area of Inhabit-Software. 68 symbols across 11 files."
---

# Test

68 symbols | 11 files | Cohesion: 72%

## When to Use

- Working with code in `firmware/`
- Understanding how enum_init, enum_notify_peer, enum_step work
- Modifying test-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `firmware/test/test_calib.c` | test_adc_validation, test_fit_linear, test_fit_rejects_insufficient, test_fit_rejects_degenerate, test_fit_two_points (+11) |
| `firmware/test/test_enum.c` | tick_n, test_single_pod_enumerates_to_zero, test_debounce_rejects_glitch, test_peer_index_increments, test_two_pod_chain (+9) |
| `firmware/src/main.c` | mcp_int_exti_init, enum_gpio_init, enum_in_level, enum_out_drive, board_init (+5) |
| `firmware/src/calib.c` | inhabit_calib_adc_valid, inhabit_calib_fit_linear, inhabit_calib_id, inhabit_calib_adc_to_millideg, calib_xor7 (+2) |
| `firmware/test/test_bench_3pod.c` | tick_all, test_partial_chain_fault, print_frame, test_3pod_chain_frames, test_pre_enum_all_fail_loud (+1) |
| `firmware/test/test_enum_integrate.c` | enum_tick, test_index0_reaches_frame, test_peer_index_propagates_to_frame, test_pre_enum_frame_fails_loud, main |
| `firmware/src/can_frame.c` | xor7, inhabit_can_id, inhabit_pack, inhabit_unpack |
| `firmware/src/enum.c` | enum_init, enum_notify_peer, enum_step |
| `firmware/test/test_can_frame.c` | main |
| `firmware/src/can_health.c` | can_health_apply |

## Entry Points

Start here when exploring this area:

- **`enum_init`** (Function) — `firmware/src/enum.c:3`
- **`enum_notify_peer`** (Function) — `firmware/src/enum.c:13`
- **`enum_step`** (Function) — `firmware/src/enum.c:29`
- **`main`** (Function) — `firmware/test/test_enum.c:268`
- **`inhabit_can_id`** (Function) — `firmware/src/can_frame.c:8`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `enum_init` | Function | `firmware/src/enum.c` | 3 |
| `enum_notify_peer` | Function | `firmware/src/enum.c` | 13 |
| `enum_step` | Function | `firmware/src/enum.c` | 29 |
| `main` | Function | `firmware/test/test_enum.c` | 268 |
| `inhabit_can_id` | Function | `firmware/src/can_frame.c` | 8 |
| `inhabit_pack` | Function | `firmware/src/can_frame.c` | 10 |
| `inhabit_unpack` | Function | `firmware/src/can_frame.c` | 21 |
| `main` | Function | `firmware/test/test_bench_3pod.c` | 187 |
| `main` | Function | `firmware/test/test_can_frame.c` | 7 |
| `main` | Function | `firmware/test/test_enum_integrate.c` | 99 |
| `can_health_apply` | Function | `firmware/src/can_health.c` | 4 |
| `main` | Function | `firmware/src/main.c` | 212 |
| `main` | Function | `firmware/test/test_can_health.c` | 13 |
| `inhabit_calib_adc_valid` | Function | `firmware/src/calib.c` | 12 |
| `inhabit_calib_fit_linear` | Function | `firmware/src/calib.c` | 23 |
| `inhabit_calib_id` | Function | `firmware/src/calib.c` | 55 |
| `main` | Function | `firmware/test/test_calib.c` | 204 |
| `inhabit_calib_adc_to_millideg` | Function | `firmware/src/calib.c` | 16 |
| `inhabit_calib_unpack` | Function | `firmware/src/calib.c` | 68 |
| `inhabit_calib_pack` | Function | `firmware/src/calib.c` | 57 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → Mcp2515_reset` | cross_community | 4 |
| `Main → Mcp2515_read_reg` | cross_community | 4 |
| `Main → Mcp2515_write_reg` | cross_community | 4 |
| `Main → Mcp2515_bit_modify` | cross_community | 4 |
| `Main → Xor7` | cross_community | 4 |
| `Board_init → Mcp2515_bit_modify` | cross_community | 4 |
| `Board_init → Mcp2515_read_reg` | cross_community | 4 |
| `Main → Enum_init` | cross_community | 3 |
| `Main → Enum_gpio_init` | intra_community | 3 |
| `Main → Mcp_int_exti_init` | intra_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Drivers | 4 calls |

## How to Explore

1. `context({name: "enum_init"})` — see callers and callees
2. `query({search_query: "test"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
