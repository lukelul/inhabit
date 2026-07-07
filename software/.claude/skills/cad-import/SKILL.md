---
name: cad-import
description: Use when bringing a SolidWorks arm assembly (6/7-DOF CAD) into the Inhabit host software as a real kinematic chain — exporting to URDF, generating an ArmConfig, or wiring it into custom_can/SimRobot. Triggers on "SolidWorks assembly", "URDF", "arm CAD", "DOF arm", "import the arm", "arm_config".
---

# CAD Import (SolidWorks arm -> Inhabit ArmConfig)

## The boundary: we do not parse SolidWorks files

`SLDASM`/`SLDPRT` are proprietary binary formats. Inhabit's host software never reads
them directly. Instead there is one supported path:

```
SolidWorks assembly  --[SW2URDF add-in]-->  URDF (+ STL meshes)  --[inhabit_description]-->  ArmConfig
```

**SW2URDF** (`ros/solidworks_urdf_exporter` on GitHub, installer `sw2urdfSetup.exe`,
requires SolidWorks 2018 SP5+) is the standard ROS-Industrial add-in for exactly this
job: it walks the assembly's mates and reference geometry and writes a URDF describing
the same serial chain, plus one STL mesh per link. This repo has SolidWorks 2025
installed, which satisfies the add-in's minimum version.

Do not attempt to write a native SolidWorks parser, and do not hand-author the URDF
from the SLDASM — both are reinventing what SW2URDF already does correctly.

## Step 1 — export the assembly with SW2URDF

1. Install the add-in (`sw2urdfSetup.exe`, run as administrator — it registers a COM
   add-in and needs write access to `Program Files`).
2. Open the arm assembly in SolidWorks with the add-in enabled (Tools menu ->
   Export as URDF / Configuration Publisher).
3. Walk the wizard link-by-link, **base link first, end effector last** — this
   determines URDF joint order, which becomes `chain_index` on the Inhabit side
   (`docs/decisions/0002-ENUM-Protocol.md`: chain_index 0 = base pod, increasing
   toward the tip). Getting this order wrong silently mismatches the CAD-side config
   against the physical ENUM order later.
4. For each joint, set:
   - **type** = `revolute` for every rotating joint pod (Inhabit's MT6701 + MCP2515
     joint is a single-axis rotary sensor — `continuous`/`prismatic` are supported by
     the parser but don't match Rev-A hardware today; a `fixed` joint is fine for a
     non-actuated mount, e.g. a sensor bracket or the end-effector base).
   - **axis** = the physical rotation axis of that joint pod's shaft, in the joint's
     own local frame (Z is the SW2URDF default convention — pick whatever the wizard
     gives you, but be consistent, since the parser stores whatever axis is present).
   - **limit** (`lower`/`upper` in radians, `velocity`, `effort`) — **required** for
     every `revolute`/`prismatic` joint; the Inhabit URDF parser rejects an actuated
     joint with no `<limit>` (an unbounded joint is a real failure mode — nothing
     downstream would know the pod's travel range).
5. Export. You get one `.urdf` file and a `meshes/` folder of per-link STL files.
6. A branching assembly (e.g. a two-finger gripper at the tip) is **not supported
   yet** — `inhabit_description.urdf.parse_urdf` fails loud with "only a single
   serial chain is supported" rather than silently picking one branch. If the arm
   has a gripper, export the 6/7-DOF arm chain only and treat the gripper as a
   separate, later problem.

## Step 2 — turn the URDF into an ArmConfig

```bash
cd host
python -m tools.urdf_import path/to/arm.urdf --describe                 # sanity check first
python -m tools.urdf_import path/to/arm.urdf --expected-dof 6 \
    -o inhabit_description/data/arm_config.json
```

`--expected-dof` (6 or 7, matching the physical arm) is a hard gate: a CAD export
with the wrong actuated-joint count is rejected here, at import time, rather than
silently producing a config for the wrong arm three modules downstream. `--describe`
prints the parsed chain (name/axis/limits per joint) with no file written — use it
first to eyeball that base->tip order and axes look right before trusting the output.

Commit the resulting `arm_config.json` like any other schema artifact (CAN schema v1,
PVT sample schema): regenerate it when the CAD changes, never hand-edit
`chain_index`/`node_id` out of sync with the physical ENUM order.

## Step 3 — wire it into the software

```python
from inhabit_description.arm_config import ArmConfig
from adapters import make_adapter

cfg = ArmConfig.load("inhabit_description/data/arm_config.json")
adapter = make_adapter("custom_can", arm_config=cfg)   # real bus, or SimSource default
assert adapter.capabilities().dof == cfg.dof
```

- **`adapters.custom_can_adapter.CustomCanAdapter`** — the Rev-A / N-pod daisy chain
  as one `RobotAdapter`. Pass `arm_config=cfg` to size `dof` and joint order from the
  CAD instead of a bare integer; omit it to keep the old bare-`dof` behaviour (today's
  single/dual-pod bench setup with no CAD yet).
- **`sim.robot.SimRobot`/`SimRobotAdapter`** — pass `dof=cfg.dof` to simulate the same
  joint count as the real arm with zero hardware (the simulator does not yet consume
  per-joint limits from `ArmConfig` — that's the next gap to close if the sim needs to
  respect real travel limits, not just joint count).

## Key files

| File | Role |
|---|---|
| `host/inhabit_description/urdf.py` | Stdlib URDF parser -> `RobotDescription` (fails loud on branches/cycles/missing limits) |
| `host/inhabit_description/arm_config.py` | `RobotDescription` -> `ArmConfig` (chain_index/node_id/limits table, JSON round-trip) |
| `host/tools/urdf_import/__main__.py` | `python -m tools.urdf_import` CLI |
| `host/adapters/custom_can_adapter.py` | `CustomCanAdapter` — the real/sim CAN chain as one `RobotAdapter` |
| `docs/sdk/ROBOT_SDK_MAPPING.md` §4.5 | `custom_can` adapter capability matrix entry |
| `docs/decisions/0002-ENUM-Protocol.md` | Why `chain_index` order matters (the physical ENUM protocol this mirrors) |

## Failure modes this pipeline guards against

- **Wrong joint count silently accepted** — `expected_dof` / `--expected-dof` fails
  loud on a CAD export with the wrong actuated-joint count.
- **Branching chain silently flattened to one path** — the parser rejects any link
  with more than one child joint instead of guessing which branch is "the" chain.
- **Unbounded joint travel** — a `revolute`/`prismatic` joint with no `<limit>` is
  rejected at parse time, not discovered later as a missing attribute.
- **CAD chain order drifting from the physical ENUM order** — `chain_index` is
  assigned strictly from URDF root-to-tip order and validated dense/ordered by
  `ArmConfig.__post_init__`; cross-check it against the real bring-up's ENUM order
  during hardware bring-up (`pcb-bringup` skill), don't assume they match without
  checking.
