# PVT Data Pipeline

## What PVT Means

**Proprioceptive-Visual-Tactile** -- the three data streams a robot needs for contact-rich manipulation:

### Proprioceptive Data (Current)
- Joint angles (radians, from calibrated encoder)
- Joint velocity (TBD, future)
- Motor current (TBD, future)
- Estimated torque (TBD, future)
- Chain index, node ID, status flags

### Visual Data (Future)
- Wrist camera frames
- Scene camera frames
- Depth images
- Stereo pairs
- Egocentric views
- Referenced by `camera_frame_id` in PVTSample

### Tactile / Contact Data (Future)
- Force measurements
- Vibration signatures
- Current spikes (motor contact detection)
- Strain gauge readings
- MEMS microphone acoustic features
- Slip / impact / release events
- Referenced by `tactile_event` in PVTSample: `contact_start | slip | impact | release | None`

---

## Current Implemented Fields

```python
PVTSample:
    timestamp_ns: int        # monotonic host clock (time.monotonic_ns)
    episode_id: str          # unique episode identifier
    chain_index: int         # pod position in kinematic chain
    joint_angle: float       # radians (from angle_rad)
    joint_velocity: float    # 0.0 (not yet wired)
    motor_current: float     # 0.0 (not yet wired)
    estimated_torque: float  # 0.0 (not yet wired)
    camera_frame_id: str | None  # None (not yet wired)
    tactile_event: str | None    # None (not yet wired)
    task_label: str          # user-provided task description
    schema_version: int      # 1
```

---

## Episode Structure

An **Episode** is an atomic, append-only collection of PVTSamples from one demonstration:
- `episode_id`: unique string identifier
- `task_label`: what the human was doing (e.g., "insert peg", "open drawer")
- `samples`: ordered list of PVTSample

### Lifecycle
1. `EpisodeRecorder` opened with episode_id, output directory, task label
2. Decoded `JointPodState` messages ingested one at a time (append-only)
3. Bad-checksum frames optionally dropped (counted)
4. `finalize()` called at episode end:
   - Measures jitter over full timeline
   - Checks against `JitterBudget`
   - PASS -> atomic parquet write
   - FAIL -> quarantine (sidecar JSON, no parquet)

### Atomicity Guarantee
- Nothing hits disk until `finalize()`
- Parquet written to `.part` temp, then `os.replace` (atomic rename)
- `fsync` on data and parent directory (POSIX)
- Crash mid-write -> at most a `.part` file; readers never see partial episodes

---

## Timestamp Alignment

**ONE monotonic host clock. No exceptions.**

- `time.monotonic_ns()` is read at CAN frame RX time
- Written into `JointPodState.header_stamp_ns`
- Flows into `PVTSample.timestamp_ns`
- NEVER wall clock (wall clock can jump, NTP adjust, DST change)
- Video and tactile streams (future) must reference the same monotonic clock

### Jitter Measurement

Inter-sample intervals: `dt[i] = t[i+1] - t[i]`

| Metric | Definition |
|--------|------------|
| `period_ns` | Median interval (robust nominal rate estimate) |
| `jitter_p99_ns` | 99th percentile of `\|dt - period\|` |
| `jitter_max_ns` | Worst deviation |
| `dropouts` | Intervals > 2.5x period (missed frame) |
| `backwards` | Intervals <= 0 (clock violation) |

### Jitter Budget (Defaults)

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `max_jitter_p99_ns` | 2,000,000 (2 ms) | +/-20% at 10ms nominal; alignable to 30/60 fps |
| `max_gap_factor` | 2.5 | A missed frame = hole in window |
| `min_samples` | 2 | Need at least one interval for timing signal |

---

## Export Formats

### Parquet (Primary)
- One file per episode: `<episode_id>.parquet`
- Explicit Arrow schema matching `SAMPLE_COLUMNS`
- Footer metadata:
  - `inhabit.episode_id`
  - `inhabit.schema_version`
  - `inhabit.task_label`
  - `inhabit.jitter_stats` (JSON)
  - `inhabit.jitter_budget` (JSON)
  - `inhabit.contact_detector_version`
- Read by: pandas, polars, Arrow, Spark, HuggingFace datasets, lerobot

### .canlog (Raw CAN Recording)
- JSONL format: `{"v":1, "t_ns":..., "id":..., "data":"hex..."}`
- Recorded by `FileRecorder` (transport layer)
- Replayed by `FileReplayTransport`

### Future Formats
- HDF5 for high-rate sensor blobs (audio, video features)
- lerobot-style episode directories
- Training-ready datasets with metadata manifests

---

## Schema Versioning

- `PVT_SCHEMA_VERSION = 1` (current)
- `MIGRATIONS` dict: maps version N -> version N+1 transform functions
- `migrate_row()` walks chain until current version
- **Rule:** never silently rename/remove a field. Add a migration.
- Version is written into every parquet file and every sample row

---

## Quarantine

When an episode fails the jitter budget:
- **No parquet is written** to the dataset directory
- A sidecar JSON is written to `<out_dir>/quarantine/<episode_id>.quarantine.json`
- Records: episode_id, task_label, n_samples, reasons, jitter_stats, detector_version
- `strict=True` mode raises `QuarantineError` (for batch jobs)

---

## Why This Matters for Robot Learning

- **Contact-rich manipulation** requires time-aligned proprioceptive + visual + tactile data
- Current datasets lack active-tactile ground truth (proprioception during contact)
- Robots fail at the "last centimeter" because training data doesn't capture it
- PVT episodes with jitter-gated timing quality produce ML-ready data that actually aligns
- The pipeline is the product -- hardware is the data acquisition endpoint

---

## Related Files

- `host/inhabit_can/pvt.py` -- schema (FROZEN)
- `host/logger/recorder.py` -- episode recorder
- `host/logger/jitter.py` -- jitter measurement
- `host/logger/parquet_io.py` -- parquet I/O
- `host/logger/CLAUDE.md` -- logger-local rules
- `host/transport/file.py` -- .canlog format
