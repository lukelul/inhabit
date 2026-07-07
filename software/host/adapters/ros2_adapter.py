"""ROS 2 (Jazzy) adapter — bridges joint_state topics to the RobotAdapter interface.

Imports rclpy lazily so the module stays importable (and testable) without a ROS
install. The actual node interaction happens only inside connect().
"""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState

if TYPE_CHECKING:  # pragma: no cover
    from rclpy.node import Node
    from sensor_msgs.msg import JointState


class ROS2Adapter(RobotAdapter):
    """Subscribe to ``/joint_states`` and publish ``/joint_commands``.

    Parameters
    ----------
    joint_state_topic:
        Topic name carrying ``sensor_msgs/JointState`` (default ``/joint_states``).
    joint_command_topic:
        Topic name for outgoing joint targets (default ``/joint_commands``).
    dof:
        Expected degrees of freedom. Caps/pads state vectors to this length.
    """

    def __init__(
        self,
        *,
        joint_state_topic: str = "/joint_states",
        joint_command_topic: str = "/joint_commands",
        dof: int = 6,
    ) -> None:
        # Failure mode: a non-positive dof yields empty/garbage state vectors and a
        # meaningless capability that downstream buffer sizing trusts. Reject it.
        if dof <= 0:
            raise ValueError("ROS2Adapter dof must be positive")
        self._js_topic = joint_state_topic
        self._cmd_topic = joint_command_topic
        self._dof = dof
        self._node: Node | None = None
        # Failure mode: read_state() can fire before the first callback. Seed the
        # fallback with a monotonic host timestamp so the very first sample still
        # honours the timestamp contract (no zero-timestamp samples ever leave here).
        self._last_state: RobotState = RobotState(
            joint_angles=[0.0] * dof,
            timestamp_ns=time.monotonic_ns(),
        )
        self._pub: object = None  # type: ignore[assignment]  # rclpy Publisher

    def connect(self) -> None:
        # Failure mode: a second connect() would allocate a fresh node/pub and
        # orphan the old ones, leaving duplicate subscriptions/publishers alive on
        # the bus. Make connect() idempotent — a no-op once already connected.
        if self._node is not None:
            return

        import rclpy  # noqa: PLC0415
        from rclpy.node import Node  # noqa: PLC0415
        from rclpy.qos import (  # noqa: PLC0415
            QoSProfile,
            QoSReliabilityPolicy,
            qos_profile_sensor_data,
        )
        from sensor_msgs.msg import JointState  # noqa: PLC0415

        if not rclpy.ok():
            rclpy.init()

        self._node = Node("inhabit_ros2_adapter")  # type: ignore[assignment]
        # Failure mode: a bare depth inherits RELIABLE durability, so we silently
        # drop connection to best-effort SensorDataQoS /joint_states publishers (the
        # common case) and read stale state. Request the sensor-data profile, which
        # is compatible with both reliable and best-effort offers.
        self._node.create_subscription(
            JointState, self._js_topic, self._on_joint_state, qos_profile_sensor_data
        )
        # Commands must not be dropped: publish RELIABLE with a small queue.
        command_qos = QoSProfile(depth=10, reliability=QoSReliabilityPolicy.RELIABLE)
        self._pub = self._node.create_publisher(JointState, self._cmd_topic, command_qos)

    def _on_joint_state(self, msg: JointState) -> None:
        positions = list(msg.position)[: self._dof]
        while len(positions) < self._dof:
            positions.append(0.0)
        # Failure mode: a misbehaving robot publishes NaN/inf positions that
        # silently propagate through the ML pipeline, producing garbage training
        # data. Reject non-finite values at the boundary — the robot must fix its
        # output, not the data pipeline.
        if not all(math.isfinite(p) for p in positions):
            return  # drop frame; _last_state stays valid
        self._last_state = RobotState(
            joint_angles=positions,
            timestamp_ns=time.monotonic_ns(),
        )

    def read_state(self) -> RobotState:
        if self._node is not None:
            rclpy = __import__("rclpy")
            rclpy.spin_once(self._node, timeout_sec=0.0)
        # Failure mode: returning the same mutable object means a caller that
        # mutates joint_angles (e.g. normalizing in-place) silently corrupts the
        # adapter's internal state and every subsequent read. RobotState holds a
        # list (mutable) + an int (immutable), so a shallow copy is sufficient
        # and cheaper than deepcopy for high-frequency ML polling loops.
        s = self._last_state
        return RobotState(joint_angles=list(s.joint_angles), timestamp_ns=s.timestamp_ns)

    def send_command(self, cmd: RobotCommand) -> None:
        if self._pub is None or self._node is None:
            return
        from sensor_msgs.msg import JointState  # noqa: PLC0415

        msg = JointState()
        msg.position = list(cmd.joint_targets)
        self._pub.publish(msg)  # type: ignore[attr-defined]

    def capabilities(self) -> Capabilities:
        return Capabilities(dof=self._dof, has_force_feedback=False)
