---
name: pvt-data-logger
description: Use when building or modifying the ML data pipeline — recording PVT (proprioceptive-visual-tactile) episodes, time synchronization, contact-event detection, schema, or ML-ready export. Triggers on "data logger", "episode", "PVT", "training data", "time sync", "contact event", "export", "lerobot", "dataset".
---

# PVT Data Logger (the business layer)

The hardware exists to produce this. Quality of the dataset > quantity. The wedge is the
**last centimeter**: contact, occlusion, force, friction, recovery.

## Canonical sample
```json
{
  "timestamp": "monotonic_ns",
  "device_id": "joint_pod_03",
  "chain_index": 3,
  "joint_angle": 1.284,
  "joint_velocity": 0.032,
  "motor_current": 0.42,
  "estimated_torque": 0.18,
  "operator_input": {},
  "robot_state": {},
  "camera_frame_id": "frame_184920",
  "tactile_event": "contact_start",
  "audio_embedding": {},
  "task_label": "insert_connector",
  "episode_id": "demo_000421",
  "schema_version": 1
}
```

## Non-negotiables
1. **Time sync first.** Pick ONE monotonic host clock. Stamp every stream (CAN, video frames,
   tactile/audio) against it. Measure and log jitter; reject episodes whose jitter exceeds budget.
2. **Episodes are atomic.** An episode = aligned multi-stream window + labels. Write append-only,
   then index. A half-written episode is quarantined, not exported.
3. **Schema versioned.** Never silently change fields. Add `schema_version`; provide migrations.
4. **Contact-event detection is a labeled signal**, not decoration. Derive `contact_start/slip/
   impact/release` from current spikes + vibration/audio + velocity discontinuity; store the
   detector version so labels are reproducible.

## Export targets
- lerobot-style episodes / parquet / HDF5 — whatever the training stack ingests directly.
- Round-trip test: write → read → assert structural + numerical equality (within tol).

## Last-centimeter sensor experiments (Phase 6)
MEMS/contact mic near end-effector + motor-current correlation + IMU. Goal: detect and
classify contact/failure acoustically and electrically where cameras are occluded. Treat as
an experiment: log raw + features + ground-truth labels so detectors can be trained/evaluated.
