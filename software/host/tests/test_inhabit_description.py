"""Tests for inhabit_description: URDF ingestion + ArmConfig derivation."""
from __future__ import annotations

from pathlib import Path

import pytest

from inhabit_description.arm_config import ArmConfig, ArmJoint, from_robot_description
from inhabit_description.urdf import load_urdf, parse_urdf


def _serial_chain_urdf(n: int, *, name: str = "test_arm", fixed_tip: bool = False) -> str:
    """A synthetic n-revolute-joint serial chain, matching an SW2URDF export shape."""
    n_links = n + 1 + (1 if fixed_tip else 0)
    links = "".join(f'<link name="link{i}"/>' for i in range(n_links))
    joints = "".join(
        f'<joint name="joint{i}" type="revolute">'
        f'<parent link="link{i}"/><child link="link{i + 1}"/>'
        f'<axis xyz="0 0 1"/>'
        f'<origin xyz="0 0 0.1" rpy="0 0 0"/>'
        f'<limit lower="-3.14" upper="3.14" velocity="2.0" effort="10.0"/>'
        f"</joint>"
        for i in range(n)
    )
    if fixed_tip:
        joints += (
            f'<joint name="tip_mount" type="fixed">'
            f'<parent link="link{n}"/><child link="link{n + 1}"/>'
            f"</joint>"
        )
    return f'<robot name="{name}">{links}{joints}</robot>'


class TestParseUrdf:
    def test_6dof_chain(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6))
        assert desc.dof == 6
        assert [j.name for j in desc.chain] == [f"joint{i}" for i in range(6)]
        assert all(j.type == "revolute" for j in desc.chain)

    def test_7dof_chain(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(7))
        assert desc.dof == 7

    def test_fixed_joint_not_counted_as_dof(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6, fixed_tip=True))
        assert desc.dof == 6  # the fixed tip mount is a joint, but not actuated
        assert len(desc.joints) == 7
        assert desc.joints[-1].type == "fixed"
        assert not desc.joints[-1].actuated

    def test_load_urdf_from_file(self, tmp_path: Path) -> None:
        p = tmp_path / "arm.urdf"
        p.write_text(_serial_chain_urdf(6), encoding="utf-8")
        desc = load_urdf(p)
        assert desc.dof == 6

    def test_non_robot_root_raises(self) -> None:
        with pytest.raises(ValueError, match="robot"):
            parse_urdf("<not_a_robot/>")

    def test_no_links_raises(self) -> None:
        with pytest.raises(ValueError, match="no <link>"):
            parse_urdf('<robot name="empty"></robot>')

    def test_unsupported_joint_type_raises(self) -> None:
        urdf = (
            '<robot name="bad">'
            '<link name="a"/><link name="b"/>'
            '<joint name="j0" type="floating">'
            '<parent link="a"/><child link="b"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="unsupported type"):
            parse_urdf(urdf)

    def test_revolute_missing_limit_raises(self) -> None:
        urdf = (
            '<robot name="bad">'
            '<link name="a"/><link name="b"/>'
            '<joint name="j0" type="revolute">'
            '<parent link="a"/><child link="b"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="requires a <limit>"):
            parse_urdf(urdf)

    def test_branching_chain_raises(self) -> None:
        urdf = (
            '<robot name="bad">'
            '<link name="a"/><link name="b"/><link name="c"/>'
            '<joint name="j0" type="revolute">'
            '<parent link="a"/><child link="b"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j1" type="revolute">'
            '<parent link="a"/><child link="c"/>'
            '<limit lower="-1" upper="1"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="child joints"):
            parse_urdf(urdf)

    def test_no_root_link_raises(self) -> None:
        # Every link is somebody's child (a 3-link ring) -> zero roots.
        urdf = (
            '<robot name="bad">'
            '<link name="a"/><link name="b"/><link name="c"/>'
            '<joint name="j0" type="revolute"><parent link="a"/><child link="b"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j1" type="revolute"><parent link="b"/><child link="c"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j2" type="revolute"><parent link="c"/><child link="a"/>'
            '<limit lower="-1" upper="1"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="exactly one root"):
            parse_urdf(urdf)

    def test_disconnected_link_raises(self) -> None:
        # "a" is the only real root (b/c/d form their own disjoint cycle, so none of
        # them present as a second root) -- exercises the "reachable link count"
        # guard specifically, distinct from both the root-count and cycle checks.
        urdf = (
            '<robot name="bad">'
            '<link name="a"/><link name="b"/><link name="c"/><link name="d"/>'
            '<joint name="j0" type="revolute"><parent link="b"/><child link="c"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j1" type="revolute"><parent link="c"/><child link="d"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j2" type="revolute"><parent link="d"/><child link="b"/>'
            '<limit lower="-1" upper="1"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="not connected"):
            parse_urdf(urdf)

    def test_cycle_raises(self) -> None:
        # Single root "r"; the tail loops back onto an already-visited link "b"
        # without any link having more than one child joint (so the branch check
        # does not fire first) -- exercises the dedicated cycle-detection path.
        urdf = (
            '<robot name="bad">'
            '<link name="r"/><link name="a"/><link name="b"/><link name="c"/>'
            '<joint name="j0" type="revolute"><parent link="r"/><child link="a"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j1" type="revolute"><parent link="a"/><child link="b"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j2" type="revolute"><parent link="b"/><child link="c"/>'
            '<limit lower="-1" upper="1"/></joint>'
            '<joint name="j3" type="revolute"><parent link="c"/><child link="b"/>'
            '<limit lower="-1" upper="1"/></joint>'
            "</robot>"
        )
        with pytest.raises(ValueError, match="cycle detected"):
            parse_urdf(urdf)


class TestFromRobotDescription:
    def test_chain_index_and_node_id(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6))
        cfg = from_robot_description(desc)
        assert cfg.dof == 6
        assert [j.chain_index for j in cfg.joints] == list(range(6))
        assert [j.node_id for j in cfg.joints] == list(range(6))
        assert [j.name for j in cfg.joints] == [f"joint{i}" for i in range(6)]

    def test_base_node_id_offset(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(3))
        cfg = from_robot_description(desc, base_node_id=10)
        assert [j.node_id for j in cfg.joints] == [10, 11, 12]

    def test_limits_carried_through(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6))
        cfg = from_robot_description(desc)
        assert cfg.joints[0].lower_rad == pytest.approx(-3.14)
        assert cfg.joints[0].upper_rad == pytest.approx(3.14)
        assert cfg.joints[0].velocity_rad_s == pytest.approx(2.0)

    def test_expected_dof_mismatch_raises(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6))
        with pytest.raises(ValueError, match="expected 7"):
            from_robot_description(desc, expected_dof=7)

    def test_expected_dof_match_ok(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(7))
        cfg = from_robot_description(desc, expected_dof=7)
        assert cfg.dof == 7


class TestArmConfig:
    def test_requires_at_least_one_joint(self) -> None:
        with pytest.raises(ValueError, match="at least one joint"):
            ArmConfig(robot_name="empty", joints=())

    def test_chain_index_must_be_dense_and_ordered(self) -> None:
        joints = (
            ArmJoint(
                name="j0", chain_index=0, node_id=0, axis=(0, 0, 1),
                lower_rad=None, upper_rad=None, velocity_rad_s=None, effort=None,
            ),
            ArmJoint(
                name="j1", chain_index=2, node_id=1, axis=(0, 0, 1),
                lower_rad=None, upper_rad=None, velocity_rad_s=None, effort=None,
            ),
        )
        with pytest.raises(ValueError, match="chain_index must be"):
            ArmConfig(robot_name="bad", joints=joints)

    def test_round_trip_dict(self) -> None:
        desc = parse_urdf(_serial_chain_urdf(6))
        cfg = from_robot_description(desc)
        back = ArmConfig.from_dict(cfg.to_dict())
        assert back == cfg

    def test_round_trip_file(self, tmp_path: Path) -> None:
        desc = parse_urdf(_serial_chain_urdf(7))
        cfg = from_robot_description(desc)
        p = tmp_path / "arm_config.json"
        cfg.save(p)
        back = ArmConfig.load(p)
        assert back == cfg
        assert back.dof == 7
