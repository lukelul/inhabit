"""ArmConfig — the CAD-sourced chain-index / limits table.

Generated once from a :class:`~inhabit_description.urdf.RobotDescription` (via
:func:`from_robot_description`) and then versioned/checked in like any other
schema in this repo (``inhabit_can.codec.PROTO_VERSION`` is the model): regenerate
it when the CAD changes, never hand-edit ``chain_index``/``node_id`` out of sync
with the physical ENUM order (``docs/decisions/0002-ENUM-Protocol.md``).

This is what lets ``adapters.custom_can_adapter.CustomCanAdapter`` and
``sim.robot.SimRobot`` be sized and limited from the real arm's geometry instead
of a bare ``dof`` integer with no travel bounds.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .urdf import RobotDescription

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArmJoint:
    """One joint's CAD-sourced identity, position in the chain, and travel limits."""

    name: str
    chain_index: int
    node_id: int
    axis: tuple[float, float, float]
    lower_rad: float | None
    upper_rad: float | None
    velocity_rad_s: float | None
    effort: float | None


@dataclass(frozen=True)
class ArmConfig:
    """Ordered joint table for one physical arm, base (``chain_index`` 0) -> end effector."""

    robot_name: str
    joints: tuple[ArmJoint, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Failure mode: a config whose chain_index isn't a dense 0..N-1 run in order
        # would silently misalign with the physical ENUM order downstream (the adapter
        # indexes a fixed-size joint_angles list by chain_index). Fail loud at
        # construction, not the first time a frame with a surprising index arrives.
        if not self.joints:
            raise ValueError("ArmConfig requires at least one joint")
        expected = list(range(len(self.joints)))
        actual = [j.chain_index for j in self.joints]
        if actual != expected:
            raise ValueError(f"chain_index must be 0..N-1 in order, got {actual}")

    @property
    def dof(self) -> int:
        return len(self.joints)

    def to_dict(self) -> dict[str, Any]:
        return {
            "robot_name": self.robot_name,
            "schema_version": self.schema_version,
            "joints": [asdict(j) for j in self.joints],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArmConfig:
        joints = tuple(
            ArmJoint(
                name=j["name"],
                chain_index=j["chain_index"],
                node_id=j["node_id"],
                axis=tuple(j["axis"]),
                lower_rad=j["lower_rad"],
                upper_rad=j["upper_rad"],
                velocity_rad_s=j["velocity_rad_s"],
                effort=j["effort"],
            )
            for j in data["joints"]
        )
        return cls(
            robot_name=str(data["robot_name"]),
            joints=joints,
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> ArmConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def from_robot_description(
    desc: RobotDescription,
    *,
    base_node_id: int = 0,
    expected_dof: int | None = None,
) -> ArmConfig:
    """Derive an :class:`ArmConfig` from a parsed URDF chain.

    ``chain_index`` follows URDF root -> tip order, matching the physical ENUM
    order (host seeds index 0 at the base pod; each pod down the chain claims the
    next free index — ``docs/decisions/0002-ENUM-Protocol.md``). ``node_id``
    defaults to ``base_node_id + chain_index``; pass a different ``base_node_id``
    if the physical CAN node IDs were assigned with an offset.

    ``expected_dof`` (e.g. ``6`` or ``7`` for the arm this repo is being prepared
    for) is an optional sanity check: a CAD export with a different actuated-joint
    count raises immediately, rather than silently producing a config for the
    wrong arm.
    """
    if expected_dof is not None and desc.dof != expected_dof:
        raise ValueError(
            f"CAD chain has {desc.dof} actuated joint(s), expected {expected_dof} "
            f"— check the SolidWorks/URDF export before trusting this config"
        )
    joints = tuple(
        ArmJoint(
            name=j.name,
            chain_index=i,
            node_id=base_node_id + i,
            axis=j.axis,
            lower_rad=j.lower,
            upper_rad=j.upper,
            velocity_rad_s=j.velocity,
            effort=j.effort,
        )
        for i, j in enumerate(desc.chain)
    )
    return ArmConfig(robot_name=desc.name, joints=joints)
