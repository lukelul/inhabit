"""inhabit_description — the CAD-to-kinematics boundary.

Ingests a URDF exported from a SolidWorks assembly (see
``.claude/skills/cad-import/SKILL.md`` for the export workflow and frame
conventions) and turns it into an :class:`~inhabit_description.arm_config.ArmConfig`
— the ordered joint/limit table that ``adapters.custom_can_adapter.CustomCanAdapter``
and ``sim.robot.SimRobot`` can be sized/limited from, instead of a bare DOF integer.
"""
from __future__ import annotations

from .arm_config import ArmConfig, ArmJoint, from_robot_description
from .urdf import Joint, Link, RobotDescription, load_urdf, parse_urdf

__all__ = [
    "ArmConfig",
    "ArmJoint",
    "Joint",
    "Link",
    "RobotDescription",
    "from_robot_description",
    "load_urdf",
    "parse_urdf",
]
