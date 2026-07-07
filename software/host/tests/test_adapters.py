"""Tests for robot protocol adapters (replay, UR stub, SimAdapter, factory, interface contract)."""
from __future__ import annotations

import pytest

from adapters import list_adapters, make_adapter
from adapters.replay_adapter import ReplayAdapter
from adapters.ros2_adapter import ROS2Adapter
from adapters.ur_adapter import URAdapter
from inhabit_can.adapter import RobotAdapter, RobotCommand, RobotState, SimAdapter

# ---------------------------------------------------------------------------
# SimAdapter (ships with adapter.py — confirm it satisfies the contract)
# ---------------------------------------------------------------------------

class TestSimAdapter:
    def test_interface_compliance(self) -> None:
        assert issubclass(SimAdapter, RobotAdapter)

    def test_connect_and_read(self) -> None:
        a = SimAdapter(dof=3)
        a.connect()
        s = a.read_state()
        assert len(s.joint_angles) == 3
        assert all(v == 0.0 for v in s.joint_angles)

    def test_send_command_updates_state(self) -> None:
        a = SimAdapter(dof=2)
        a.connect()
        a.send_command(RobotCommand(joint_targets=[1.0, 2.0]))
        s = a.read_state()
        assert s.joint_angles == [1.0, 2.0]

    def test_capabilities(self) -> None:
        a = SimAdapter(dof=7)
        c = a.capabilities()
        assert c.dof == 7
        assert c.has_force_feedback is False


# ---------------------------------------------------------------------------
# ReplayAdapter
# ---------------------------------------------------------------------------

class TestReplayAdapter:
    def _states(self, n: int = 5) -> list[RobotState]:
        # Positive, strictly increasing host timestamps (i + 1 -> never zero).
        return [
            RobotState(joint_angles=[float(i)], timestamp_ns=(i + 1) * 1000)
            for i in range(n)
        ]

    def test_interface_compliance(self) -> None:
        assert issubclass(ReplayAdapter, RobotAdapter)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            ReplayAdapter([])

    def test_sequential_playback(self) -> None:
        states = self._states(3)
        a = ReplayAdapter(states)
        a.connect()
        assert a.read_state().joint_angles == [0.0]
        assert a.read_state().joint_angles == [1.0]
        assert a.read_state().joint_angles == [2.0]

    def test_holds_last_state(self) -> None:
        states = self._states(2)
        a = ReplayAdapter(states)
        a.connect()
        a.read_state()  # 0
        a.read_state()  # 1
        assert a.read_state().joint_angles == [1.0]  # still 1
        assert a.read_state().joint_angles == [1.0]  # still 1

    def test_connect_resets(self) -> None:
        states = self._states(2)
        a = ReplayAdapter(states)
        a.connect()
        a.read_state()  # 0
        a.read_state()  # 1
        a.connect()  # reset
        assert a.read_state().joint_angles == [0.0]

    def test_send_command_is_noop(self) -> None:
        a = ReplayAdapter(self._states(1))
        a.connect()
        a.send_command(RobotCommand(joint_targets=[99.0]))
        assert a.read_state().joint_angles == [0.0]  # unchanged

    def test_capabilities_dof_from_states(self) -> None:
        states = [RobotState(joint_angles=[1.0, 2.0, 3.0], timestamp_ns=42_000)]
        a = ReplayAdapter(states)
        assert a.capabilities().dof == 3

    def test_capabilities_dof_override_matches(self) -> None:
        # A matching override is accepted and capabilities() stays truthful.
        states = [RobotState(joint_angles=[1.0, 2.0, 3.0], timestamp_ns=42_000)]
        a = ReplayAdapter(states, dof=3)
        assert a.capabilities().dof == 3

    def test_capabilities_dof_override_mismatch_raises(self) -> None:
        # capabilities().dof must not lie about the replayed state width.
        states = [RobotState(joint_angles=[1.0], timestamp_ns=42_000)]
        with pytest.raises(ValueError, match="must match the recorded joint count"):
            ReplayAdapter(states, dof=6)

    def test_zero_timestamp_raises(self) -> None:
        # A zero host timestamp poisons downstream time-alignment; reject it.
        states = [RobotState(joint_angles=[1.0], timestamp_ns=0)]
        with pytest.raises(ValueError, match="positive host timestamps"):
            ReplayAdapter(states)

    def test_negative_timestamp_raises(self) -> None:
        states = [RobotState(joint_angles=[1.0], timestamp_ns=-5)]
        with pytest.raises(ValueError, match="positive host timestamps"):
            ReplayAdapter(states)

    def test_backwards_timestamp_raises(self) -> None:
        # Non-monotonic host clock breaks episode alignment / jitter math.
        states = [
            RobotState(joint_angles=[0.0], timestamp_ns=2_000),
            RobotState(joint_angles=[1.0], timestamp_ns=1_000),
        ]
        with pytest.raises(ValueError, match="timestamps must be monotonic"):
            ReplayAdapter(states)

    def test_equal_timestamps_allowed(self) -> None:
        # Non-decreasing is the contract; duplicate ticks are valid, not an error.
        states = [
            RobotState(joint_angles=[0.0], timestamp_ns=1_000),
            RobotState(joint_angles=[1.0], timestamp_ns=1_000),
        ]
        a = ReplayAdapter(states)
        a.connect()
        assert a.read_state().joint_angles == [0.0]
        assert a.read_state().joint_angles == [1.0]

    def test_mixed_dof_raises(self) -> None:
        states = [
            RobotState(joint_angles=[1.0, 2.0], timestamp_ns=1_000),
            RobotState(joint_angles=[3.0], timestamp_ns=2_000),
        ]
        with pytest.raises(ValueError, match="same joint count"):
            ReplayAdapter(states)

    def test_preserves_timestamp(self) -> None:
        states = [
            RobotState(joint_angles=[0.0], timestamp_ns=111),
            RobotState(joint_angles=[1.0], timestamp_ns=222),
        ]
        a = ReplayAdapter(states)
        a.connect()
        assert a.read_state().timestamp_ns == 111
        assert a.read_state().timestamp_ns == 222

    def test_does_not_mutate_input(self) -> None:
        original = [RobotState(joint_angles=[1.0], timestamp_ns=42_000)]
        a = ReplayAdapter(original)
        a.connect()
        # Mutating a returned state must not corrupt the source recording or later reads.
        s = a.read_state()
        s.joint_angles[0] = 999.0
        s.timestamp_ns = -1
        assert len(original) == 1  # list not consumed
        assert original[0].joint_angles == [1.0]  # source unchanged
        assert original[0].timestamp_ns == 42_000
        assert a.read_state().joint_angles == [1.0]  # replay unaffected

    def test_len(self) -> None:
        states = self._states(7)
        a = ReplayAdapter(states)
        assert len(a) == 7

    def test_nan_joint_angle_rejected(self) -> None:
        states = [RobotState(joint_angles=[float("nan")], timestamp_ns=1_000)]
        with pytest.raises(ValueError, match="non-finite"):
            ReplayAdapter(states)

    def test_inf_joint_angle_rejected(self) -> None:
        states = [RobotState(joint_angles=[float("inf")], timestamp_ns=1_000)]
        with pytest.raises(ValueError, match="non-finite"):
            ReplayAdapter(states)


# ---------------------------------------------------------------------------
# URAdapter (stub)
# ---------------------------------------------------------------------------

class TestURAdapter:
    def test_interface_compliance(self) -> None:
        assert issubclass(URAdapter, RobotAdapter)

    def test_connect_raises(self) -> None:
        a = URAdapter(ip="10.0.0.1")
        with pytest.raises(NotImplementedError, match="stub"):
            a.connect()

    def test_read_state_raises(self) -> None:
        a = URAdapter()
        with pytest.raises(NotImplementedError, match="stub"):
            a.read_state()

    def test_send_command_raises(self) -> None:
        a = URAdapter()
        with pytest.raises(NotImplementedError, match="stub"):
            a.send_command(RobotCommand(joint_targets=[0.0] * 6))

    def test_capabilities_no_force_until_implemented(self) -> None:
        # Stub must not advertise force feedback it cannot deliver.
        a = URAdapter(dof=6)
        c = a.capabilities()
        assert c.dof == 6
        assert c.has_force_feedback is False

    def test_non_positive_dof_raises(self) -> None:
        # capabilities().dof must be a sane joint count even on the stub.
        with pytest.raises(ValueError, match="dof must be positive"):
            URAdapter(dof=0)


# ---------------------------------------------------------------------------
# ROS2Adapter (importable without rclpy — rclpy is imported lazily in connect())
# ---------------------------------------------------------------------------

class TestROS2Adapter:
    def test_interface_compliance(self) -> None:
        assert issubclass(ROS2Adapter, RobotAdapter)

    def test_connect_is_idempotent(self) -> None:
        # Failure mode: a second connect() would orphan the old node and leave
        # duplicate subscriptions/publishers on the bus. With a node already set,
        # connect() must short-circuit without importing rclpy or recreating it.
        a = ROS2Adapter()
        sentinel = object()
        a._node = sentinel  # type: ignore[assignment]
        a.connect()  # must not raise (no rclpy needed) and must not replace _node
        assert a._node is sentinel

    def test_fallback_state_has_timestamp(self) -> None:
        # First read before any callback must still carry a monotonic host timestamp.
        a = ROS2Adapter(dof=4)
        s = a.read_state()
        assert len(s.joint_angles) == 4
        assert s.timestamp_ns > 0

    def test_non_positive_dof_raises(self) -> None:
        # A non-positive dof yields garbage state vectors / capability.
        with pytest.raises(ValueError, match="dof must be positive"):
            ROS2Adapter(dof=0)

    def test_read_state_returns_independent_copy(self) -> None:
        # Failure mode: caller mutates returned state and corrupts internal
        # adapter state, poisoning every subsequent read in the ML loop.
        a = ROS2Adapter(dof=2)
        s1 = a.read_state()
        s1.joint_angles[0] = 999.0
        s2 = a.read_state()
        assert s2.joint_angles[0] != 999.0  # internal state not corrupted

    def test_nan_positions_dropped(self) -> None:
        # Simulate a callback with NaN — adapter should keep last valid state.
        a = ROS2Adapter(dof=2)
        original = a.read_state()

        class FakeMsg:
            position: tuple[float, ...] = (float("nan"), 1.0)

        a._on_joint_state(FakeMsg())  # type: ignore[arg-type]
        after = a.read_state()
        # NaN frame was dropped; state unchanged from fallback.
        assert after.joint_angles == original.joint_angles

    def test_inf_positions_dropped(self) -> None:
        a = ROS2Adapter(dof=2)
        original = a.read_state()

        class FakeMsg:
            position: tuple[float, ...] = (1.0, float("inf"))

        a._on_joint_state(FakeMsg())  # type: ignore[arg-type]
        after = a.read_state()
        assert after.joint_angles == original.joint_angles


# ---------------------------------------------------------------------------
# make_adapter factory
# ---------------------------------------------------------------------------

class TestMakeAdapter:
    def test_sim(self) -> None:
        a = make_adapter("sim", dof=3)
        assert isinstance(a, SimAdapter)
        assert a.capabilities().dof == 3

    def test_replay(self) -> None:
        states = [RobotState(joint_angles=[1.0], timestamp_ns=1000)]
        a = make_adapter("replay", states=states)
        assert isinstance(a, ReplayAdapter)

    def test_ros2(self) -> None:
        a = make_adapter("ros2", dof=4)
        assert isinstance(a, ROS2Adapter)

    def test_ur(self) -> None:
        a = make_adapter("ur", ip="10.0.0.1")
        assert isinstance(a, URAdapter)

    def test_unknown_raises(self) -> None:
        # make_adapter is now built on inhabit_core.Registry, which raises ValueError
        # (listing the available names) on an unknown plugin name.
        with pytest.raises(ValueError, match=r"Unknown adapter.*available"):
            make_adapter("kuka")

    def test_list_adapters(self) -> None:
        names = list_adapters()
        assert isinstance(names, list)
        assert names == sorted(names)  # alphabetical
        # ``sim_robot`` = the P-B/B2 non-stub sim adapter (sim.SimRobotAdapter).
        # ``custom_can`` = the Rev-A / N-pod daisy chain adapter (adapters.custom_can_adapter).
        assert set(names) == {"custom_can", "replay", "ros2", "sim", "sim_robot", "ur"}
