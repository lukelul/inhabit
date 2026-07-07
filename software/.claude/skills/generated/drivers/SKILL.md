---
name: drivers
description: "Skill for the Drivers area of Inhabit-Software. 11 symbols across 2 files."
---

# Drivers

11 symbols | 2 files | Cohesion: 83%

## When to Use

- Working with code in `firmware/`
- Understanding how mcp2515_reset, mcp2515_read_reg, mcp2515_write_reg work
- Modifying drivers-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `firmware/drivers/mcp2515.c` | mcp2515_reset, mcp2515_read_reg, mcp2515_write_reg, mcp2515_bit_modify, mcp2515_set_mode (+5) |
| `firmware/test/test_mcp2515.c` | main |

## Entry Points

Start here when exploring this area:

- **`mcp2515_reset`** (Function) — `firmware/drivers/mcp2515.c:12`
- **`mcp2515_read_reg`** (Function) — `firmware/drivers/mcp2515.c:18`
- **`mcp2515_write_reg`** (Function) — `firmware/drivers/mcp2515.c:26`
- **`mcp2515_bit_modify`** (Function) — `firmware/drivers/mcp2515.c:32`
- **`mcp2515_set_mode`** (Function) — `firmware/drivers/mcp2515.c:41`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `mcp2515_reset` | Function | `firmware/drivers/mcp2515.c` | 12 |
| `mcp2515_read_reg` | Function | `firmware/drivers/mcp2515.c` | 18 |
| `mcp2515_write_reg` | Function | `firmware/drivers/mcp2515.c` | 26 |
| `mcp2515_bit_modify` | Function | `firmware/drivers/mcp2515.c` | 32 |
| `mcp2515_set_mode` | Function | `firmware/drivers/mcp2515.c` | 41 |
| `mcp2515_init` | Function | `firmware/drivers/mcp2515.c` | 53 |
| `mcp2515_encode_sid` | Function | `firmware/drivers/mcp2515.c` | 82 |
| `mcp2515_send_std` | Function | `firmware/drivers/mcp2515.c` | 90 |
| `mcp2515_poll_tx_done` | Function | `firmware/drivers/mcp2515.c` | 109 |
| `mcp2515_poll_recv` | Function | `firmware/drivers/mcp2515.c` | 127 |
| `main` | Function | `firmware/test/test_mcp2515.c` | 76 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Main → Mcp2515_reset` | cross_community | 4 |
| `Main → Mcp2515_read_reg` | cross_community | 4 |
| `Main → Mcp2515_write_reg` | cross_community | 4 |
| `Main → Mcp2515_bit_modify` | cross_community | 4 |
| `Board_init → Mcp2515_bit_modify` | cross_community | 4 |
| `Board_init → Mcp2515_read_reg` | cross_community | 4 |
| `Can_tx_tick → Mcp2515_encode_sid` | cross_community | 3 |
| `Can_tx_tick → Mcp2515_write_reg` | cross_community | 3 |
| `Can_tx_tick → Mcp2515_read_reg` | cross_community | 3 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Test | 3 calls |

## How to Explore

1. `context({name: "mcp2515_reset"})` — see callers and callees
2. `query({search_query: "drivers"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
