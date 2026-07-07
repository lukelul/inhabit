"""inhabit_bridge — CAN <-> ROS 2 bridge for smart joint pods (ROS 2 Jazzy).

The ROS-independent core lives in ``conversion`` and ``sources`` so the
codec-facing logic is unit-testable as plain Python without a ROS install.
The ROS 2 node wiring lives in ``bridge_node`` (imported lazily; requires rclpy).
"""
from .conversion import PodFields, fields_from_frame

__all__ = ["PodFields", "fields_from_frame"]
