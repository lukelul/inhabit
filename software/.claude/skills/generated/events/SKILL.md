---
name: events
description: "Skill for the Events area of Inhabit-Software. 5 symbols across 2 files."
---

# Events

5 symbols | 2 files | Cohesion: 100%

## When to Use

- Working with code in `host/`
- Understanding how NoopDetector, ThresholdDetector, EventDetector work
- Modifying events-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/events/detectors.py` | NoopDetector, ThresholdDetector, detect, _read |
| `host/events/interface.py` | EventDetector |

## Entry Points

Start here when exploring this area:

- **`NoopDetector`** (Class) — `host/events/detectors.py:27`
- **`ThresholdDetector`** (Class) — `host/events/detectors.py:44`
- **`EventDetector`** (Class) — `host/events/interface.py:123`
- **`detect`** (Method) — `host/events/detectors.py:98`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `NoopDetector` | Class | `host/events/detectors.py` | 27 |
| `ThresholdDetector` | Class | `host/events/detectors.py` | 44 |
| `EventDetector` | Class | `host/events/interface.py` | 123 |
| `detect` | Method | `host/events/detectors.py` | 98 |
| `_read` | Method | `host/events/detectors.py` | 116 |

## How to Explore

1. `context({name: "NoopDetector"})` — see callers and callees
2. `query({search_query: "events"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
