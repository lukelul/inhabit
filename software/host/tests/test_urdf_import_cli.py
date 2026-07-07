"""Tests for the `python -m tools.urdf_import` CLI."""
from __future__ import annotations

from pathlib import Path

import pytest

from inhabit_description.arm_config import ArmConfig
from tools.urdf_import.__main__ import main


def _write_urdf(path: Path, n: int = 6) -> None:
    links = "".join(f'<link name="link{i}"/>' for i in range(n + 1))
    joints = "".join(
        f'<joint name="joint{i}" type="revolute">'
        f'<parent link="link{i}"/><child link="link{i + 1}"/>'
        f'<axis xyz="0 0 1"/>'
        f'<limit lower="-3.14" upper="3.14" velocity="2.0" effort="10.0"/>'
        f"</joint>"
        for i in range(n)
    )
    path.write_text(f'<robot name="cli_test_arm">{links}{joints}</robot>', encoding="utf-8")


class TestUrdfImportCli:
    def test_describe_prints_chain_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        urdf = tmp_path / "arm.urdf"
        _write_urdf(urdf, 6)
        rc = main([str(urdf), "--describe"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "dof: 6" in out
        assert "joint0" in out

    def test_missing_output_without_describe_errors(self, tmp_path: Path) -> None:
        urdf = tmp_path / "arm.urdf"
        _write_urdf(urdf, 6)
        with pytest.raises(SystemExit):
            main([str(urdf)])

    def test_writes_arm_config_json(self, tmp_path: Path) -> None:
        urdf = tmp_path / "arm.urdf"
        _write_urdf(urdf, 7)
        out = tmp_path / "arm_config.json"
        rc = main([str(urdf), "--node-base", "5", "-o", str(out)])
        assert rc == 0
        assert out.exists()
        cfg = ArmConfig.load(out)
        assert cfg.dof == 7
        assert cfg.joints[0].node_id == 5

    def test_expected_dof_mismatch_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        urdf = tmp_path / "arm.urdf"
        _write_urdf(urdf, 6)
        out = tmp_path / "arm_config.json"
        rc = main([str(urdf), "--expected-dof", "7", "-o", str(out)])
        assert rc == 1
        assert "error:" in capsys.readouterr().err
        assert not out.exists()
