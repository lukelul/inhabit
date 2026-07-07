"""RobotAdapter — the one interface every robot speaks through. Core code never branches
on robot type; it only calls these methods. Add new robots as new adapters, not new ifs."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RobotState:
    joint_angles: list[float] = field(default_factory=list)
    timestamp_ns: int = 0


@dataclass
class RobotCommand:
    joint_targets: list[float] = field(default_factory=list)


@dataclass
class Capabilities:
    dof: int = 0
    has_force_feedback: bool = False


class RobotAdapter(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def read_state(self) -> RobotState: ...
    @abstractmethod
    def send_command(self, cmd: RobotCommand) -> None: ...
    @abstractmethod
    def capabilities(self) -> Capabilities: ...


class SimAdapter(RobotAdapter):
    """Zero-hardware adapter so the pipeline runs end-to-end before any robot exists."""
    def __init__(self, dof: int = 6) -> None:
        self._dof = dof
        self._state = RobotState(joint_angles=[0.0] * dof)

    def connect(self) -> None:  # nothing to connect
        return None

    def read_state(self) -> RobotState:
        return self._state

    def send_command(self, cmd: RobotCommand) -> None:
        self._state = RobotState(joint_angles=list(cmd.joint_targets))

    def capabilities(self) -> Capabilities:
        return Capabilities(dof=self._dof, has_force_feedback=False)
