# host/logger/ — PVT episode recorder, time-sync, ML export

Turns a stream of decoded joint states (Track 2 `JointPodState`) into atomic,
jitter-gated, ML-ready PVT episodes. The dataset is the business; this is its writer.

## Modules
- `jitter.py`  — `JitterStats`, `JitterBudget`, `compute_jitter`. ONE monotonic clock;
  measure inter-sample timing; gate on a documented budget. Pure stdlib.
- `parquet_io.py` — `write_episode` / `read_episode`. Parquet is the primary export
  (columnar, typed, self-describing, lerobot/HF-datasets ingestible). Atomic write via
  `.part` + `os.replace`. Episode-level provenance (jitter stats, budget, contact
  detector version) lives in the parquet footer.
- `recorder.py` — `EpisodeRecorder`: open -> ingest (append-only) -> finalize
  (measure jitter, gate, EXPORT or QUARANTINE). `RecorderResult`, `QuarantineError`.

## Time-sync contract
Every `PVTSample.timestamp_ns` comes from `JointPodState.header_stamp_ns` (monotonic RX
time). Do NOT mix in wall-clock. Jitter = deviation of inter-sample intervals from the
median period. Quarantine if: p99 jitter > budget, any dropout (>2.5x period), any
backwards interval, or too few samples. Budget defaults target ~100 Hz; recorded into
each file so the dataset is reproducible.

## Atomicity / quarantine
- Ingest only appends in memory. Nothing hits disk until `finalize`.
- Pass -> atomic parquet write to `<out_dir>/<episode_id>.parquet`.
- Fail -> NO episode parquet; a `quarantine/<id>.quarantine.json` sidecar records why.
- Crash mid-write -> at most a `.parquet.part`; readers never see a partial episode.

## Schema
`PVTSample` / `Episode` and `PVT_SCHEMA_VERSION` live in `inhabit_can/pvt.py`. Bump the
version only with a migration in `pvt.MIGRATIONS`; never a silent field change.

## ROS integration (thin adapter, not here)
A `JointPodState` ROS 2 subscriber (Jazzy) converts each message to the `JointPodState`
dataclass — set `header_stamp_ns` from the host monotonic clock at RX — and calls
`recorder.ingest(...)`, then `recorder.finalize()` at episode end. The recorder needs no
ROS; keep that dependency in the subscriber node only.
