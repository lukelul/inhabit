"""Launch the Inhabit CAN bridge node (ROS 2 Jazzy).

Headless default: source='sim' synthesizes valid pod frames with zero hardware.
Switch to 'socketcan' (with channel) on a real Linux/Jazzy bus, 'file' (with
path) to replay a recorded ``.canlog`` through host/transport with no hardware,
or 'replay' to feed a captured frame list programmatically.

The 'file' and 'socketcan' sources are backed by host/transport (file replay and
Linux socketcan), wired in behind the bridge's CanSource interface.

Examples
--------
    ros2 launch inhabit_bridge bridge.launch.py
    ros2 launch inhabit_bridge bridge.launch.py source:=socketcan channel:=can0
    ros2 launch inhabit_bridge bridge.launch.py source:=file path:=/data/run.canlog
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    source = LaunchConfiguration("source")
    channel = LaunchConfiguration("channel")
    path = LaunchConfiguration("path")
    topic = LaunchConfiguration("topic")
    frame_id = LaunchConfiguration("frame_id")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "source",
                default_value="sim",
                description="CAN source: sim | replay | file | socketcan",
            ),
            DeclareLaunchArgument(
                "channel",
                default_value="can0",
                description="socketcan channel (only used when source:=socketcan)",
            ),
            DeclareLaunchArgument(
                "path",
                default_value="",
                description="path to a .canlog recording (required when source:=file)",
            ),
            DeclareLaunchArgument(
                "topic",
                default_value="joint_pod_state",
                description="Output JointPodState topic name",
            ),
            DeclareLaunchArgument(
                "frame_id",
                default_value="joint_pod",
                description="header.frame_id for published messages",
            ),
            Node(
                package="inhabit_bridge",
                executable="bridge_node",
                name="inhabit_can_bridge",
                output="screen",
                parameters=[
                    {
                        "source": source,
                        "channel": channel,
                        "path": path,
                        "topic": topic,
                        "frame_id": frame_id,
                    }
                ],
            ),
        ]
    )
