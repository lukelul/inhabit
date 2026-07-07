# host/ — ROS 2 (Jazzy) + data ingestion (Python)

Importable, tested skeleton. Read `host/CLAUDE.md` first.

- `inhabit_can/codec.py` — CAN schema v1 (DONE, tested). Mirrors `firmware/inc/can_frame.h`.
- `inhabit_can/adapter.py` — `RobotAdapter` ABC + `SimAdapter` (pipeline runs with no hardware).
- `inhabit_can/pvt.py` — versioned PVT sample + episode (writer is a TODO).
- `tests/` — run from the **repo root**: `python -m pytest host -q` (123 passing).
  Some tests import repo-root modules (e.g. `tools.calibrate`), so they need the repo
  root on `sys.path`; running from inside `host/` fails at collection.

Next (ros2-integrator): wrap codec in an `inhabit_bridge` rclpy node (socketcan/USB-CAN),
define `inhabit_msgs`, add launch files. (data-pipeline-engineer): episode writer + time-sync.
