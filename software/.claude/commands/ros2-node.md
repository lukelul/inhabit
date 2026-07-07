---
description: Scaffold a new ROS 2 (Jazzy) node/package following Inhabit conventions
---
Use the `ros2-node` skill and `ros2-integrator` agent. Scaffold the package/node described in
$ARGUMENTS: ament_python package, thin node + testable logic module, launch file, deliberate QoS,
params (no magic constants). If it touches a robot, route through RobotAdapter. Pin Jazzy.
