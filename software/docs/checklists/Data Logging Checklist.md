# Data Logging Checklist

- [ ] CAN source available (replay, sim, or live socketcan)
- [ ] Bridge node running and publishing JointPodState
- [ ] EpisodeRecorder created with episode_id, output directory, task label
- [ ] Frames ingested (append-only)
- [ ] Bad-checksum frames handled (dropped and counted)
- [ ] Episode finalized
- [ ] Jitter stats measured and logged
- [ ] Jitter within budget (p99 < 2ms, no gaps > 2.5x, no backwards)
- [ ] Parquet file written atomically (no .part file remaining)
- [ ] Read-back matches original samples (round-trip test)
- [ ] Footer metadata present (episode_id, schema_version, jitter_stats)
- [ ] Quarantine works for bad episodes (sidecar JSON, no parquet)
