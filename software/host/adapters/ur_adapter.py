"""UR (Universal Robots) adapter — stub for future RTDE integration.

This is a placeholder so the adapter registry is aware of UR robots. Real implementation
will use the UR RTDE interface (port 30004) to read joint state and send servoj commands.
"""
from __future__ import annotations

from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState


class URAdapter(RobotAdapter):
    """Stub adapter for Universal Robots arms (UR3/5/10/16/20/30).

    Parameters
    ----------
    ip:
        Robot controller IP address.
    dof:
        Degrees of freedom (UR arms have 6).
    """

    def __init__(self, *, ip: str = "192.168.1.2", dof: int = 6) -> None:
        # Failure mode: capabilities() is callable on the stub; a non-positive dof
        # would advertise a nonsensical joint count that downstream code trusts.
        if dof <= 0:
            raise ValueError("URAdapter dof must be positive")
        self._ip = ip
        self._dof = dof

    def connect(self) -> None:
        raise NotImplementedError("URAdapter is a stub — RTDE integration not yet implemented")

    def read_state(self) -> RobotState:
        raise NotImplementedError("URAdapter is a stub — RTDE integration not yet implemented")

    def send_command(self, cmd: RobotCommand) -> None:
        raise NotImplementedError("URAdapter is a stub — RTDE integration not yet implemented")

    def capabilities(self) -> Capabilities:
        # Failure mode: advertising force feedback on a non-functional stub makes UR
        # look supported and breaks callers that feature-gate on capabilities. Report
        # False until RTDE-backed force data is actually wired up.
        return Capabilities(dof=self._dof, has_force_feedback=False)
