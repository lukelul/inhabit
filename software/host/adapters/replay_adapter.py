"""Replay adapter — feeds a recorded sequence of RobotStates through the adapter interface.

Useful for offline ML pipeline testing and deterministic integration tests. No hardware,
no ROS. States are consumed in order; once exhausted, the last state is returned forever.
"""
from __future__ import annotations

import math
from copy import deepcopy
from itertools import pairwise

from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState


class ReplayAdapter(RobotAdapter):
    """Play back a pre-recorded list of :class:`RobotState` snapshots.

    Parameters
    ----------
    states:
        Ordered snapshots to replay. Must contain at least one entry, all with
        the same joint count and positive, non-decreasing ``timestamp_ns``
        (the host time-sync contract).
    dof:
        Reported degrees of freedom. Optional; must equal the recorded joint
        count if given (it only documents intent — it cannot reshape the data).
    """

    def __init__(self, states: list[RobotState], *, dof: int | None = None) -> None:
        if not states:
            raise ValueError("ReplayAdapter requires at least one state")
        # Failure mode: a mixed-length recording silently replays inconsistent
        # vectors and breaks downstream code that sizes buffers from a fixed DOF.
        # Require every state to share the first state's joint count.
        state_dof = len(states[0].joint_angles)
        if any(len(state.joint_angles) != state_dof for state in states):
            raise ValueError("All replay states must have the same joint count")
        # Failure mode: zero/backwards host timestamps silently corrupt the
        # first-class time-sync contract downstream (jitter math, episode
        # alignment). Reject non-positive and non-monotonic recordings up front.
        timestamps = [state.timestamp_ns for state in states]
        if any(ts <= 0 for ts in timestamps):
            raise ValueError("ReplayAdapter requires positive host timestamps")
        if any(curr < prev for prev, curr in pairwise(timestamps)):
            raise ValueError("ReplayAdapter timestamps must be monotonic")
        # Failure mode: NaN/inf joint angles silently propagate through the ML
        # pipeline, producing garbage training data that's hard to diagnose.
        # Reject at the recording boundary — the recording must be clean.
        for i, s in enumerate(states):
            if not all(math.isfinite(a) for a in s.joint_angles):
                raise ValueError(f"State {i} contains non-finite joint angles")
        # Failure mode: a dof override that disagrees with the recorded width makes
        # capabilities().dof lie. The frozen RobotAdapter contract requires dof to be
        # truthful so core code can size buffers without special-casing the adapter.
        if dof is not None and dof != state_dof:
            raise ValueError("ReplayAdapter dof must match the recorded joint count")
        # Snapshot so caller mutations (and our returned copies) can never corrupt
        # the recording — replay must stay deterministic.
        self._states = [deepcopy(state) for state in states]
        self._index = 0
        self._dof = state_dof

    def __len__(self) -> int:
        """Number of recorded states — useful for ML progress bars and batching."""
        return len(self._states)

    def connect(self) -> None:
        self._index = 0

    def read_state(self) -> RobotState:
        state = deepcopy(self._states[self._index])
        if self._index < len(self._states) - 1:
            self._index += 1
        return state

    def send_command(self, cmd: RobotCommand) -> None:
        pass  # replay is read-only

    def capabilities(self) -> Capabilities:
        return Capabilities(dof=self._dof, has_force_feedback=False)
