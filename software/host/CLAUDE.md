# host/ — ROS 2 + data ingestion (Python)

Scope: everything off-board — ROS 2 nodes, CAN bridge, robot adapters, PVT logger.
Inherits root CLAUDE.md.

## Layout (target)
```
host/
  inhabit_bridge/      CAN<->ROS2 bridge node (socketcan / USB-CAN)
  inhabit_msgs/        custom ROS 2 messages (JointPodState, PVTSample, ...)
  inhabit_description/ CAD (SolidWorks->URDF) ingestion -> ArmConfig (see cad-import skill)
  adapters/            robot protocol plugins (custom_can, ros2, ur, kuka, franka, sim)
  logger/              episode recorder, time-sync, ML export
  viz/                 live joint-angle / virtual-arm visualization
  tests/
```

## Hard rules
- **One adapter interface.** Every robot speaks through `RobotAdapter` (connect, read_state,
  send_command, capabilities). Never branch on robot type in core code.
- **Time sync is first-class.** All samples carry a monotonic host timestamp; align CAN,
  video, and tactile to a common clock. Document the sync method and measured jitter.
- **Schema versioning.** PVTSample and CAN parsing carry a version field. Migrations, not breaks.
- Type hints everywhere. `ruff` + `mypy` clean. ROS 2 = **Jazzy** (pin it).
- Exports are ML-ready (lerobot-style episodes / parquet / HDF5), not ad-hoc CSV.

## Definition of done
Node launches via launch file · message schema versioned · time-sync jitter measured &
logged · export round-trips (write → read → assert equal) · tests green.
