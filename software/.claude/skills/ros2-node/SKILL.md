---
name: ros2-node
description: Use when scaffolding or modifying ROS 2 (Jazzy) nodes, packages, messages, launch files, or the robot-adapter interface for the Inhabit host software. Triggers on "ROS2", "rclpy", "node", "publisher", "launch file", "colcon", "msg", "adapter".
---

# ROS 2 Node Scaffolding (Inhabit, Jazzy)

## Conventions
- Distro: **Jazzy** (pin in package.xml comments + CI). Python nodes via `rclpy`.
- Package naming: `inhabit_<thing>` (snake_case). Messages in `inhabit_msgs`.
- Every node: parameterized (no magic constants), launch-file driven, lifecycle-aware if it
  owns hardware. QoS chosen deliberately (sensor data = best-effort + small depth).

## New package (ament_python)
```
ros2 pkg create --build-type ament_python inhabit_bridge \
  --dependencies rclpy inhabit_msgs --license Apache-2.0
```
Wire `entry_points` in setup.py; add a `launch/` dir; keep nodes thin (logic in plain modules
that are unit-testable without a ROS graph).

## Robot adapter interface (the core abstraction)
```python
from abc import ABC, abstractmethod
class RobotAdapter(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def read_state(self) -> "RobotState": ...
    @abstractmethod
    def send_command(self, cmd: "RobotCommand") -> None: ...
    @abstractmethod
    def capabilities(self) -> "Capabilities": ...
```
Implementations: `custom_can`, `ros2`, `ur`, `kuka`, `franka`, `sim`. Core code depends only
on `RobotAdapter` — never `isinstance` a concrete robot.

## Node skeleton
```python
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from inhabit_msgs.msg import JointPodState

class BridgeNode(Node):
    def __init__(self):
        super().__init__('inhabit_bridge')
        self.declare_parameter('can_iface', 'can0')
        self.pub = self.create_publisher(JointPodState, 'joint_pod_state', qos_profile_sensor_data)
        self.timer = self.create_timer(0.001, self._tick)   # 1 kHz
    def _tick(self):
        ...  # drain CAN, decode (can-protocol skill), publish

def main():
    rclpy.init(); n = BridgeNode()
    try: rclpy.spin(n)
    finally: n.destroy_node(); rclpy.shutdown()
```

## Done when
`colcon build` clean · `ros2 launch` brings the node up · params documented · logic unit-tested
off-graph · ruff+mypy clean.
