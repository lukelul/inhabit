"""Tests for CustomCanAdapter — the Rev-A / N-pod daisy chain as one RobotAdapter."""
from __future__ import annotations

import pytest

from adapters import make_adapter
from adapters.custom_can_adapter import CustomCanAdapter
from inhabit_bridge.sources import ReplaySource, SimSource
from inhabit_can.adapter import RobotAdapter, RobotCommand
from inhabit_can.codec import State, encode_state
from inhabit_description.arm_config import ArmConfig, ArmJoint


def _arm_config(dof: int) -> ArmConfig:
    joints = tuple(
        ArmJoint(
            name=f"joint{i}", chain_index=i, node_id=i, axis=(0.0, 0.0, 1.0),
            lower_rad=-3.14, upper_rad=3.14, velocity_rad_s=2.0, effort=10.0,
        )
        for i in range(dof)
    )
    return ArmConfig(robot_name="test_arm", joints=joints)


class TestCustomCanAdapter:
    def test_interface_compliance(self) -> None:
        assert issubclass(CustomCanAdapter, RobotAdapter)

    def test_default_zero_hardware(self) -> None:
        # No source, no arm_config -- must still work end to end (SimSource fallback).
        a = CustomCanAdapter(dof=4)
        a.connect()
        state = a.read_state()
        assert len(state.joint_angles) == 4
        assert state.timestamp_ns > 0

    def test_bad_dof_raises(self) -> None:
        with pytest.raises(ValueError, match="dof must be"):
            CustomCanAdapter(dof=0)

    def test_connect_is_idempotent(self) -> None:
        a = CustomCanAdapter(dof=2)
        a.connect()
        a.connect()  # must not re-open / raise

    def test_read_before_connect_raises(self) -> None:
        a = CustomCanAdapter(dof=2)
        with pytest.raises(RuntimeError, match="before connect"):
            a.read_state()

    def test_send_command_is_documented_noop(self) -> None:
        # Sensor-only Rev-A (root CLAUDE.md): commanding must not force the readback
        # to the commanded targets -- read_state only ever reflects decoded CAN frames.
        a = CustomCanAdapter(dof=3)
        a.connect()
        a.send_command(RobotCommand(joint_targets=[1.0, 1.0, 1.0]))  # must not raise
        state = a.read_state()
        assert state.joint_angles != [1.0, 1.0, 1.0]

    def test_capabilities_dof(self) -> None:
        a = CustomCanAdapter(dof=5)
        assert a.capabilities().dof == 5
        assert a.capabilities().has_force_feedback is False

    def test_decodes_real_frames_by_chain_index(self) -> None:
        # Two pods; feed one frame for chain_index 1 with a known angle and confirm it
        # lands in the right slot while chain_index 0 stays at its initial value.
        _, data = encode_state(
            State(angle_raw_adc=0, angle_millideg=20_000, node_id=1, chain_index=1)
        )
        source = ReplaySource([(0x101, data)])
        a = CustomCanAdapter(dof=2, source=source)
        a.connect()
        state = a.read_state()
        assert state.joint_angles[0] == 0.0
        assert state.joint_angles[1] == pytest.approx(20.0 * 3.141592653589793 / 180.0)

    def test_corrupt_frame_does_not_update_state(self) -> None:
        _, good = encode_state(
            State(angle_raw_adc=0, angle_millideg=10_000, node_id=0, chain_index=0)
        )
        corrupt = good[:7] + bytes([good[7] ^ 0xFF])  # flip the checksum byte
        source = ReplaySource([(0x100, corrupt)])
        a = CustomCanAdapter(dof=1, source=source)
        a.connect()
        state = a.read_state()
        assert state.joint_angles[0] == 0.0  # corrupt frame ignored, not trusted

    def test_out_of_range_chain_index_does_not_crash(self) -> None:
        _, data = encode_state(
            State(angle_raw_adc=0, angle_millideg=1_000, node_id=9, chain_index=9)
        )
        source = ReplaySource([(0x109, data)])
        a = CustomCanAdapter(dof=2, source=source)
        a.connect()
        state = a.read_state()  # must not raise (chain_index 9 is out of range for dof=2)
        assert len(state.joint_angles) == 2

    def test_arm_config_sizes_dof_and_ignores_dof_kwarg(self) -> None:
        cfg = _arm_config(6)
        a = CustomCanAdapter(arm_config=cfg, dof=99)
        assert a.capabilities().dof == 6

    def test_registered_in_factory(self) -> None:
        a = make_adapter("custom_can", dof=3)
        assert isinstance(a, CustomCanAdapter)
        assert a.capabilities().dof == 3

    def test_custom_source_frames_are_exhausted_gracefully(self) -> None:
        # A finite SimSource: reading past its frame budget must raise StopIteration,
        # not silently loop or hang -- the caller (a ROS node / recorder loop) owns
        # deciding what "no more frames" means for a live vs. replay run.
        a = CustomCanAdapter(dof=1, source=SimSource(num_pods=1, count=1))
        a.connect()
        a.read_state()
        with pytest.raises(StopIteration):
            a.read_state()
