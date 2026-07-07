---
name: inhabit-core
description: "Skill for the Inhabit_core area of Inhabit-Software. 9 symbols across 1 files."
---

# Inhabit_core

9 symbols | 1 files | Cohesion: 100%

## When to Use

- Working with code in `host/`
- Understanding how decorator, register, make work
- Modifying inhabit_core-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/inhabit_core/registry.py` | register, decorator, _register, make, names (+4) |

## Entry Points

Start here when exploring this area:

- **`decorator`** (Function) — `host/inhabit_core/registry.py:82`
- **`register`** (Method) — `host/inhabit_core/registry.py:63`
- **`make`** (Method) — `host/inhabit_core/registry.py:100`
- **`names`** (Method) — `host/inhabit_core/registry.py:119`
- **`available`** (Method) — `host/inhabit_core/registry.py:126`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `decorator` | Function | `host/inhabit_core/registry.py` | 82 |
| `register` | Method | `host/inhabit_core/registry.py` | 63 |
| `make` | Method | `host/inhabit_core/registry.py` | 100 |
| `names` | Method | `host/inhabit_core/registry.py` | 119 |
| `available` | Method | `host/inhabit_core/registry.py` | 126 |
| `_register` | Method | `host/inhabit_core/registry.py` | 90 |
| `_maybe_discover` | Method | `host/inhabit_core/registry.py` | 138 |
| `_iter_entry_points` | Method | `host/inhabit_core/registry.py` | 163 |
| `_format_names` | Method | `host/inhabit_core/registry.py` | 173 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Available → _iter_entry_points` | intra_community | 4 |
| `Make → _iter_entry_points` | intra_community | 3 |
| `Register → _format_names` | intra_community | 3 |
| `Decorator → _format_names` | intra_community | 3 |

## How to Explore

1. `context({name: "decorator"})` — see callers and callees
2. `query({search_query: "inhabit_core"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
