"""Custom-CAN adapter — Inhabit's own daisy-chained joint-pod chain as one robot.

Closes the ``custom_can`` gap tracked in ``docs/sdk/ROBOT_SDK_MAPPING.md`` §4.5: the
CAN->host data path already existed (``inhabit_bridge``/``transport``/``inhabit_can.codec``)
but no ``RobotAdapter`` presented the chain as one robot. Wraps a :class:`CanSource`
(``SimSource`` for zero-hardware demos/tests, ``SocketCanSource`` for the real bus) and
decodes frames with the frozen CAN schema v1 codec.

Rev-A pods are sensor-only (root ``CLAUDE.md``): ``send_command`` is a documented no-op,
matching ``ReplayAdapter``'s read-only convention -- this is not an oversight, it is what
"sensor node, no actuation" means today.
"""
from __future__ import annotations

import math
import time
from collections.abc import Iterator

from inhabit_bridge.sources import CanFrame, CanSource, SimSource
from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState
from inhabit_can.codec import decode_state
from inhabit_description.arm_config import ArmConfig

_DEG_TO_RAD = math.pi / 180.0


class CustomCanAdapter(RobotAdapter):
    """The Rev-A / N-pod daisy chain, presented as one :class:`RobotAdapter`.

    Parameters
    ----------
    source:
        A :class:`CanSource` yielding raw frames. Defaults to a zero-hardware
        ``SimSource`` sized to ``dof`` pods, so the adapter is exercisable (and
        conformance-testable) with no configuration and no hardware. Pass a
        ``SocketCanSource`` for the real bus.
    arm_config:
        Optional CAD-sourced :class:`ArmConfig` (``inhabit_description``) giving the
        authoritative chain length, joint order, and travel limits. When given,
        ``dof`` is ``len(arm_config.joints)`` and the ``dof`` constructor argument is
        ignored. When omitted, the adapter falls back to a bare ``dof``-pod chain
        with no CAD-sourced limits -- exactly today's Rev-A single/dual-pod bench
        setup, before any CAD exists for it.
    dof:
        Fallback chain length when no ``arm_config`` is given. Ignored if
        ``arm_config`` is set.
    """

    def __init__(
        self,
        *,
        source: CanSource | None = None,
        arm_config: ArmConfig | None = None,
        dof: int = 6,
    ) -> None:
        if arm_config is not None:
            self._dof = arm_config.dof
        else:
            if dof < 1:
                raise ValueError(f"dof must be >= 1, got {dof}")
            self._dof = dof
        self._arm_config = arm_config
        self._source = source if source is not None else SimSource(num_pods=self._dof, count=1000)
        self._angles = [0.0] * self._dof
        self._timestamp_ns = 0
        self._frame_iter: Iterator[CanFrame] | None = None

    def connect(self) -> None:
        # Idempotent (the frozen contract): a second connect() while already open is a
        # no-op rather than re-opening the transport underneath an in-flight iterator.
        if self._frame_iter is not None:
            return
        self._source.open()
        self._frame_iter = self._source.frames()
        # Never a zero timestamp before the first frame arrives (the frozen contract).
        self._timestamp_ns = time.monotonic_ns()

    def read_state(self) -> RobotState:
        if self._frame_iter is None:
            raise RuntimeError("CustomCanAdapter.read_state() called before connect()")
        frame = next(self._frame_iter)
        state = decode_state(frame.data)
        # A bad checksum or an out-of-range chain_index is a real hardware fault
        # (status_flags/wiring) -- surface it by simply not updating that joint's
        # angle rather than trusting corrupt data, matching the "fail loud, don't
        # silently corrupt a sample" rule (can-protocol skill).
        if state.valid and 0 <= state.chain_index < self._dof:
            self._angles[state.chain_index] = state.angle_millideg / 1000.0 * _DEG_TO_RAD
        self._timestamp_ns = frame.rx_monotonic_ns
        return RobotState(joint_angles=list(self._angles), timestamp_ns=self._timestamp_ns)

    def send_command(self, cmd: RobotCommand) -> None:
        pass  # Rev-A pods are sensor-only; no actuation exists to command (root CLAUDE.md).

    def capabilities(self) -> Capabilities:
        return Capabilities(dof=self._dof, has_force_feedback=False)
