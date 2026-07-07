"""RobotAdapter conformance — every registered adapter must satisfy these invariants."""
from __future__ import annotations

import pytest

from adapters import list_adapters, make_adapter
from inhabit_can.adapter import Capabilities, RobotAdapter, RobotCommand, RobotState

_ADAPTER_CONFIG: dict[str, dict[str, object]] = {
    "sim": {},
    # P-B/B2 non-stub sim: full contract (monotonic non-zero timestamps + independent-copy
    # reads + command reflection), so it satisfies every conformance invariant with no skips.
    "sim_robot": {},
    "replay": {
        "states": [RobotState(joint_angles=[0.1, 0.2], timestamp_ns=1_000_000)],
        "_skip_command_test": "replay adapter is read-only; send_command is a no-op by design",
    },
    "ros2": {"_skip": "requires rclpy (not installed in CI)"},
    "ur": {"_skip": "URAdapter is an unimplemented stub"},
    # Rev-A pods are sensor-only (root CLAUDE.md): send_command is a documented no-op,
    # same reason "replay" skips the command-reflection test.
    "custom_can": {
        "_skip_command_test": "Rev-A pods are sensor-only; send_command is a no-op by design",
    },
}


@pytest.fixture(params=list_adapters(), ids=lambda n: f"adapter:{n}")
def adapter(request: pytest.FixtureRequest) -> RobotAdapter:
    cfg = _ADAPTER_CONFIG.get(request.param, {})
    if cfg.get("_skip"):
        pytest.skip(str(cfg["_skip"]))
    kwargs = {k: v for k, v in cfg.items() if not k.startswith("_")}
    return make_adapter(request.param, **kwargs)


class TestAdapterConformance:
    def test_is_robot_adapter(self, adapter: RobotAdapter) -> None:
        assert isinstance(adapter, RobotAdapter)

    def test_connect_is_idempotent(self, adapter: RobotAdapter) -> None:
        adapter.connect()
        adapter.connect()

    def test_read_state_returns_robot_state(self, adapter: RobotAdapter) -> None:
        adapter.connect()
        state = adapter.read_state()
        assert isinstance(state, RobotState)
        assert isinstance(state.joint_angles, list)
        assert isinstance(state.timestamp_ns, int)

    def test_capabilities_positive_dof(self, adapter: RobotAdapter) -> None:
        caps = adapter.capabilities()
        assert isinstance(caps, Capabilities)
        assert caps.dof > 0

    def test_dof_matches_state_length(self, adapter: RobotAdapter) -> None:
        adapter.connect()
        assert len(adapter.read_state().joint_angles) == adapter.capabilities().dof

    def test_send_command_accepted(self, adapter: RobotAdapter) -> None:
        adapter.connect()
        dof = adapter.capabilities().dof
        adapter.send_command(RobotCommand(joint_targets=[0.0] * dof))

    def test_state_reflects_command(
        self, adapter: RobotAdapter, request: pytest.FixtureRequest,
    ) -> None:
        name = request.node.callspec.id.split(":")[-1]
        cfg = _ADAPTER_CONFIG.get(name, {})
        if cfg.get("_skip_command_test"):
            pytest.skip(str(cfg["_skip_command_test"]))
        adapter.connect()
        dof = adapter.capabilities().dof
        targets = [float(i) * 0.1 for i in range(dof)]
        adapter.send_command(RobotCommand(joint_targets=targets))
        state = adapter.read_state()
        assert len(state.joint_angles) == dof
        for i, (actual, target) in enumerate(
            zip(state.joint_angles, targets, strict=True)
        ):
            assert abs(actual - target) < 1e-6, f"joint {i}: {actual} vs {target}"
