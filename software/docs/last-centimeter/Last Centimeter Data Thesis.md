# Last Centimeter Data Thesis

## The Problem: Why Robots Fail During Contact

Robots trained on egocentric video demonstrations fail at the moment of contact. The "last centimeter" -- when the gripper touches the object, when force matters, when occlusion hides what's happening -- is where all current approaches break down.

**Why:**
- Passive egocentric cameras can't see through the gripper
- Video doesn't capture force, friction, slip, or vibration
- Demonstration datasets lack ground truth for the contact phase
- Robot foundation models are trained on data that stops being useful exactly when it matters most

---

## Why Passive Egocentric Data Is Insufficient

Egocentric video from a wrist camera captures:
- Approach trajectory (useful)
- Pre-grasp alignment (useful)
- **Contact moment** (occluded by the gripper itself)
- **In-grasp manipulation** (occluded, no force info)
- **Slip, recovery, insertion** (invisible to cameras)

The data that matters most is exactly the data that cameras can't capture.

---

## Action-Labeled Tactile Data

The solution: record **what the robot feels** during contact, synchronized with what it sees and where its joints are.

### PVT Triplet
- **P** (Proprioceptive): joint angles, velocities, motor currents, torque estimates
- **V** (Visual): wrist/scene/depth cameras, timestamped to the same clock
- **T** (Tactile): force, vibration, acoustic contact signatures, slip events

The key insight: the tactile stream must be **action-labeled** -- each sample records what the human was doing (the task label) and what the robot was feeling (the contact event).

---

## Active-Tactile Synchronization

"Active-tactile" means the tactile data is recorded during **active human demonstration**, not passive observation. The human controls the robot, the robot feels the contact, and the data pipeline records both.

Synchronization requirement: all three streams (P, V, T) share ONE monotonic host clock. Jitter between streams must be within budget. If it's not, the episode is quarantined.

---

## Contact Signatures

Different manipulation events produce distinct sensor signatures:

| Event | Motor Current | Vibration | Acoustic | Force |
|-------|--------------|-----------|----------|-------|
| `contact_start` | Step increase | Impulse | Click/tap | Sudden load |
| `slip` | Oscillation | High-freq burst | Scrape | Fluctuating |
| `impact` | Spike | Sharp transient | Bang | Peak |
| `release` | Drop | Settling | Quiet | Unload |

These are the `tactile_event` labels in `PVTSample`.

---

## MEMS Microphone Hypothesis

A MEMS microphone mounted near the contact surface can detect acoustic signatures of contact events:
- Contact initiation (tap/click)
- Sliding (scrape sound)
- Slip (frequency shift)
- Material properties (hard vs. soft impact sound)

**Advantages:**
- Very cheap ($0.30-$1.00)
- Small form factor
- High bandwidth (can capture transient events)
- Complementary to force/current sensing

**Hypothesis to test:** A MEMS mic + motor current monitoring together provide reliable contact event detection for common manipulation tasks (pick, place, insert, turn, push, pull).

---

## Motor Current / Contact Correlation

Motor current changes during contact:
- Free motion: smooth, predictable current draw
- Contact: sudden load increase
- Stall: current limit
- Slip: oscillating current

This is available "for free" from the motor driver (no extra sensor). Combined with acoustic data, it provides a robust contact detector without expensive force/torque sensors.

---

## Vibration and Acoustic Features

Frequency-domain features from vibration/acoustic sensors:
- Power spectral density changes during contact
- Frequency peaks characteristic of material stiffness
- Transient detection (onset of contact)
- Sustained vibration patterns (sliding, rotating)

These features are low-dimensional enough to include in PVT samples without excessive data volume.

---

## Experimental Plan

### Phase 1: Baseline (Current)
- Proprioceptive-only episodes from CAN telemetry
- Establish jitter budget and episode quality metrics
- Verify end-to-end pipeline: record -> export -> read-back

### Phase 2: Motor Current Contact Detection
- Add motor current sensing to Rev-C pod
- Correlate current spikes with known contact events
- Develop threshold-based contact detector
- Label episodes with detected events

### Phase 3: MEMS Microphone Integration
- Mount MEMS mic near contact surface on future sensor board
- Record acoustic data synchronized with motor current
- Compare acoustic vs. current detection accuracy
- Develop multi-modal contact classifier

### Phase 4: Visual Synchronization
- Add camera frame timestamps to PVT pipeline
- Align video frames with contact events
- Verify cross-stream jitter is within budget

### Phase 5: Full PVT Episodes
- Record synchronized proprioceptive + visual + tactile demonstrations
- Export ML-ready datasets with contact labels
- Evaluate training improvements on manipulation benchmarks

---

## Future Sensor Stack

| Sensor | Purpose | Integration Point |
|--------|---------|-------------------|
| MEMS microphone | Acoustic contact detection | Future sensor board |
| Motor current ADC | Load/contact monitoring | Rev-C motor driver |
| Vibration sensor (accelerometer) | Impact/slip detection | Future sensor board |
| Strain gauge / FSR | Direct force measurement | Contact surface |
| Temperature sensor | Thermal contact | TBD |

---

## What Data to Collect

For each manipulation task:
- Multiple demonstrations with varying objects, forces, speeds
- Known-outcome episodes (success and failure)
- Labeled contact events (manual annotation initially, then detector-labeled)
- Baseline episodes with no contact (free motion reference)
- Per-pod calibration data

---

## What Success Looks Like

1. A ML model trained on PVT data performs better on contact-rich tasks than one trained on video-only data
2. Contact event detection is reliable enough to auto-label episodes (>90% agreement with human labels)
3. The pipeline produces enough labeled data per hour of demonstration to be practical (target: TBD episodes/hour)
4. Cross-robot transfer: data from Inhabit pods on one arm improves policy on a different arm
