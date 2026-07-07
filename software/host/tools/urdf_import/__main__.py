"""CLI: URDF (SW2URDF export) -> Inhabit ArmConfig JSON.

Usage:
    python -m tools.urdf_import path/to/arm.urdf -o inhabit_description/data/arm_config.json
    python -m tools.urdf_import path/to/arm.urdf --expected-dof 6 --node-base 0 -o arm_config.json
    python -m tools.urdf_import path/to/arm.urdf --describe   # print the chain, no output file

``--expected-dof`` is a sanity check, not a requirement: pass ``6`` or ``7`` (or
whatever the CAD assembly's actuated-joint count should be) so a bad export is
rejected here, at import time, instead of silently producing a config for the
wrong arm three steps downstream.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inhabit_description.arm_config import from_robot_description
from inhabit_description.urdf import load_urdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.urdf_import",
        description="Convert a SolidWorks-exported URDF into an Inhabit ArmConfig.",
    )
    parser.add_argument("urdf", type=Path, help="Path to the exported .urdf file")
    parser.add_argument(
        "--expected-dof", type=int, default=None,
        help="Reject the CAD export unless it has exactly this many actuated joints (e.g. 6 or 7)",
    )
    parser.add_argument(
        "--node-base", type=int, default=0,
        help="CAN node_id of the base pod (default 0); node_id = node_base + chain_index",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="ArmConfig JSON output path"
    )
    parser.add_argument(
        "--describe", action="store_true",
        help="Print the parsed chain (name, axis, limits) and exit without writing a file",
    )
    args = parser.parse_args(argv)

    if not args.describe and args.output is None:
        parser.error("-o/--output is required unless --describe is given")

    try:
        desc = load_urdf(args.urdf)
        cfg = from_robot_description(
            desc, base_node_id=args.node_base, expected_dof=args.expected_dof
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.describe:
        print(f"robot: {cfg.robot_name}  dof: {cfg.dof}")
        for j in cfg.joints:
            limits = (
                f"[{j.lower_rad:.3f}, {j.upper_rad:.3f}] rad"
                if j.lower_rad is not None and j.upper_rad is not None
                else "(no limit)"
            )
            print(
                f"  chain_index={j.chain_index} node_id={j.node_id} {j.name!r} "
                f"axis={j.axis} limits={limits}"
            )
        return 0

    cfg.save(args.output)
    print(f"wrote {cfg.dof}-DOF ArmConfig for {cfg.robot_name!r} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
