# ADR-0005: PVT Data Pipeline

## Status
Accepted (PVTSample schema FROZEN)

## Context
ML training for contact-rich manipulation requires time-aligned proprioceptive, visual, and tactile data. The pipeline must be schema-versioned and produce ML-ready exports.

## Decision
- PVTSample dataclass with versioned schema and migration chain
- Episode: atomic, append-only collection
- Jitter budget gate: quarantine episodes that exceed timing quality threshold
- Parquet export: columnar, typed, self-describing, lerobot/HF-compatible
- Atomic writes: .part + os.replace + fsync

## Failure Mode Prevented
- Timestamp misalignment between streams (single monotonic clock)
- Silent schema changes breaking old data (versioned + migrations)
- Partial episodes in dataset (atomic write + quarantine)
- Jittery data corrupting training (budget gate)

## Alternatives Considered
1. CSV export -- rejected: loses types, no schema, not self-describing
2. HDF5 only -- rejected: HDF5 is better for blobs, parquet for tabular
3. No jitter gate -- rejected: bad timing data would pollute training sets
4. Wall clock timestamps -- rejected: can jump, NTP adjust, DST change

## Consequences
- Positive: ML-ready from day one (lerobot, HuggingFace datasets ingest parquet)
- Positive: old data migrates forward automatically
- Positive: quarantine provides quality signal, not data loss
- Trade-off: requires pyarrow dependency

## Related Source Files
- `host/inhabit_can/pvt.py`
- `host/logger/recorder.py`, `host/logger/jitter.py`, `host/logger/parquet_io.py`

## Related Tests
- `host/tests/test_logger.py` (and others in host/tests/)

## Related Benchmarks
- BENCHMARKS.md item 6 (end-to-end round-trip)

## Open Questions
- What jitter budget is appropriate for different deployment scenarios?
- HDF5 integration for video/audio blobs (future)
