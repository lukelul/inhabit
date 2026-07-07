---
name: sinks
description: "Skill for the Sinks area of Inhabit-Software. 19 symbols across 6 files."
---

# Sinks

19 symbols | 6 files | Cohesion: 96%

## When to Use

- Working with code in `host/`
- Understanding how test_inmem_sink_samples_property_is_a_copy, test_parquet_atomic_sink_direct_strict_raises_on_quarantine, make_episode_sink work
- Modifying sinks-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `host/logger/sinks/inmem.py` | open, ingest, finalize, InMemorySink, __init__ |
| `host/logger/sinks/interface.py` | _enter_open, _check_ingestable, _enter_finalize, EpisodeSink, __init__ |
| `host/logger/sinks/parquet_atomic.py` | open, ingest, finalize, ParquetAtomicSink, __init__ |
| `host/tests/test_sinks.py` | test_inmem_sink_samples_property_is_a_copy, test_parquet_atomic_sink_direct_strict_raises_on_quarantine |
| `host/logger/sinks/__init__.py` | make_episode_sink |
| `host/tests/conformance/test_episode_sink_conformance.py` | sink |

## Entry Points

Start here when exploring this area:

- **`test_inmem_sink_samples_property_is_a_copy`** (Function) — `host/tests/test_sinks.py:144`
- **`test_parquet_atomic_sink_direct_strict_raises_on_quarantine`** (Function) — `host/tests/test_sinks.py:494`
- **`make_episode_sink`** (Function) — `host/logger/sinks/__init__.py:46`
- **`sink`** (Function) — `host/tests/conformance/test_episode_sink_conformance.py:29`
- **`InMemorySink`** (Class) — `host/logger/sinks/inmem.py:33`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `InMemorySink` | Class | `host/logger/sinks/inmem.py` | 33 |
| `EpisodeSink` | Class | `host/logger/sinks/interface.py` | 114 |
| `ParquetAtomicSink` | Class | `host/logger/sinks/parquet_atomic.py` | 45 |
| `test_inmem_sink_samples_property_is_a_copy` | Function | `host/tests/test_sinks.py` | 144 |
| `test_parquet_atomic_sink_direct_strict_raises_on_quarantine` | Function | `host/tests/test_sinks.py` | 494 |
| `make_episode_sink` | Function | `host/logger/sinks/__init__.py` | 46 |
| `sink` | Function | `host/tests/conformance/test_episode_sink_conformance.py` | 29 |
| `open` | Method | `host/logger/sinks/inmem.py` | 54 |
| `ingest` | Method | `host/logger/sinks/inmem.py` | 61 |
| `finalize` | Method | `host/logger/sinks/inmem.py` | 74 |
| `open` | Method | `host/logger/sinks/parquet_atomic.py` | 89 |
| `ingest` | Method | `host/logger/sinks/parquet_atomic.py` | 99 |
| `finalize` | Method | `host/logger/sinks/parquet_atomic.py` | 112 |
| `_enter_open` | Method | `host/logger/sinks/interface.py` | 181 |
| `_check_ingestable` | Method | `host/logger/sinks/interface.py` | 187 |
| `_enter_finalize` | Method | `host/logger/sinks/interface.py` | 194 |
| `__init__` | Method | `host/logger/sinks/inmem.py` | 46 |
| `__init__` | Method | `host/logger/sinks/interface.py` | 152 |
| `__init__` | Method | `host/logger/sinks/parquet_atomic.py` | 72 |

## Connected Areas

| Area | Connections |
|------|-------------|
| Tests | 2 calls |

## How to Explore

1. `context({name: "test_inmem_sink_samples_property_is_a_copy"})` — see callers and callees
2. `query({search_query: "sinks"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
