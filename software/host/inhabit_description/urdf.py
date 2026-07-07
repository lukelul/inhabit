"""Minimal URDF ingestion — the CAD-to-kinematics boundary.

Inhabit does not parse SolidWorks assemblies directly (SLDASM/SLDPRT are a
proprietary binary format). Instead: export the assembly to URDF with the
SW2URDF ("Configuration Publisher") SolidWorks add-in — the standard
ROS-Industrial tool for exactly this job, see ``.claude/skills/cad-import/SKILL.md``
for the exact workflow and frame conventions — then load the resulting URDF here.
URDF is a simple, open XML format; this parser reads only what Inhabit needs (the
kinematic chain + joint limits) via stdlib ``xml.etree``, deliberately not pulling
in the heavier ``urdfpy``/ROS URDF stack as a dependency (PONYTAIL).

Only a single, unbranched serial kinematic chain is supported (root link -> ... ->
tip link), matching Inhabit's daisy-chained joint-pod hardware
(``docs/decisions/0002-ENUM-Protocol.md``). A branching assembly (e.g. a gripper
with two independently actuated fingers) is a real, current gap — this parser
fails loud on a branch rather than silently picking one and mis-numbering the
rest of the chain.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

# Joint types that count as a controllable DOF in the chain. "fixed" joints (e.g. a
# sensor mount or an end-effector bracket) are real URDF joints but contribute zero
# DOF — they're kept in ``joints`` (for completeness) and skipped by ``.chain``.
_ACTUATED_TYPES = frozenset({"revolute", "continuous", "prismatic"})
_ALL_TYPES = _ACTUATED_TYPES | {"fixed"}


@dataclass(frozen=True, slots=True)
class Joint:
    """One parsed ``<joint>`` element."""

    name: str
    type: str
    parent: str
    child: str
    axis: Vec3 = (1.0, 0.0, 0.0)
    origin_xyz: Vec3 = (0.0, 0.0, 0.0)
    origin_rpy: Vec3 = (0.0, 0.0, 0.0)
    lower: float | None = None
    upper: float | None = None
    velocity: float | None = None
    effort: float | None = None

    @property
    def actuated(self) -> bool:
        """``True`` for revolute/continuous/prismatic — ``False`` for fixed."""
        return self.type in _ACTUATED_TYPES


@dataclass(frozen=True, slots=True)
class Link:
    """One parsed ``<link>`` element (name only — Inhabit does not need mesh/inertial)."""

    name: str


@dataclass(frozen=True)
class RobotDescription:
    """A parsed URDF: the serial kinematic chain from root link to tip link.

    ``joints`` is ordered root -> tip and contains EVERY joint on the chain
    (actuated and fixed). ``chain`` is the actuated-only sub-sequence in the same
    order — this is what maps onto Inhabit's per-pod ``chain_index``
    (``docs/decisions/0002-ENUM-Protocol.md``): chain index 0 is the base pod,
    increasing toward the end effector.
    """

    name: str
    links: tuple[Link, ...]
    joints: tuple[Joint, ...]

    @property
    def chain(self) -> tuple[Joint, ...]:
        return tuple(j for j in self.joints if j.actuated)

    @property
    def dof(self) -> int:
        return len(self.chain)


Vec3 = tuple[float, float, float]


def _parse_vec3(text: str | None) -> Vec3:
    """Parse a URDF ``xyz``/``rpy`` attribute (3 whitespace-separated floats)."""
    if text is None:
        return (0.0, 0.0, 0.0)
    parts = [float(x) for x in text.split()]
    if len(parts) != 3:
        raise ValueError(f"expected 3 floats, got {text!r}")
    return (parts[0], parts[1], parts[2])


def _parse_joint(el: ET.Element) -> Joint:
    name = el.get("name")
    jtype = el.get("type")
    if not name or not jtype:
        raise ValueError("<joint> requires name and type attributes")
    if jtype not in _ALL_TYPES:
        raise ValueError(
            f"joint {name!r}: unsupported type {jtype!r} "
            f"(Inhabit chains support {sorted(_ALL_TYPES)})"
        )
    parent_el = el.find("parent")
    child_el = el.find("child")
    if parent_el is None or child_el is None:
        raise ValueError(f"joint {name!r} is missing <parent>/<child>")
    parent = parent_el.get("link")
    child = child_el.get("link")
    if not parent or not child:
        raise ValueError(f"joint {name!r} <parent>/<child> is missing a link attribute")

    axis_el = el.find("axis")
    axis = _parse_vec3(axis_el.get("xyz")) if axis_el is not None else (1.0, 0.0, 0.0)

    origin_el = el.find("origin")
    origin_xyz = _parse_vec3(origin_el.get("xyz") if origin_el is not None else None)
    origin_rpy = _parse_vec3(origin_el.get("rpy") if origin_el is not None else None)

    lower = upper = velocity = effort = None
    limit_el = el.find("limit")
    if limit_el is not None:
        lower = float(limit_el.get("lower", "0"))
        upper = float(limit_el.get("upper", "0"))
        velocity = float(limit_el.get("velocity", "0")) or None
        effort = float(limit_el.get("effort", "0")) or None
    elif jtype in ("revolute", "prismatic"):
        # Failure mode: a revolute/prismatic joint with no <limit> silently becomes an
        # unbounded joint downstream (SimRobot/firmware would have no travel bound to
        # honour). URDF requires <limit> for these types too — fail loud here instead
        # of discovering it as a missing attribute three modules away.
        raise ValueError(f"joint {name!r} is {jtype!r} and requires a <limit> element")

    return Joint(
        name=name,
        type=jtype,
        parent=parent,
        child=child,
        axis=axis,
        origin_xyz=origin_xyz,
        origin_rpy=origin_rpy,
        lower=lower,
        upper=upper,
        velocity=velocity,
        effort=effort,
    )


def parse_urdf(text: str) -> RobotDescription:
    """Parse URDF XML text into a :class:`RobotDescription` (a single serial chain).

    Raises ``ValueError`` (with a specific, actionable message) on anything that
    would make the chain ambiguous: an unsupported joint type, a joint missing its
    required ``<limit>``, more than one child joint on a link (a branch), more or
    fewer than one root link, a cycle, or a link the chain never reaches.
    """
    root = ET.fromstring(text)
    if root.tag != "robot":
        raise ValueError(f"expected a <robot> root element, got <{root.tag}>")
    robot_name = root.get("name", "unnamed")

    links = tuple(Link(name=el.get("name", "")) for el in root.findall("link"))
    if not links:
        raise ValueError("URDF defines no <link> elements")
    link_names = {link.name for link in links}

    joints_by_parent: dict[str, list[Joint]] = {}
    child_names: set[str] = set()
    for el in root.findall("joint"):
        j = _parse_joint(el)
        if j.parent not in link_names or j.child not in link_names:
            raise ValueError(f"joint {j.name!r} references an undeclared link")
        joints_by_parent.setdefault(j.parent, []).append(j)
        child_names.add(j.child)

    # Failure mode: a branching tree (>1 child joint from the same parent link) would
    # silently pick one branch below and mis-assign chain_index to the wrong physical
    # pod for the rest. Fail loud instead — a gripper/branching end-effector is a real,
    # documented gap (see the cad-import skill), not something to guess through.
    for parent, kids in joints_by_parent.items():
        if len(kids) > 1:
            raise ValueError(
                f"link {parent!r} has {len(kids)} child joints "
                f"({[k.name for k in kids]}) — only a single serial chain is "
                f"supported (branching end-effectors are not yet supported)"
            )

    roots = [link.name for link in links if link.name not in child_names]
    if len(roots) != 1:
        raise ValueError(
            f"expected exactly one root link (a link with no parent joint), found {roots}"
        )
    root_link = roots[0]

    ordered: list[Joint] = []
    current = root_link
    visited = {current}
    while current in joints_by_parent:
        j = joints_by_parent[current][0]
        if j.child in visited:
            raise ValueError(f"cycle detected in kinematic chain at joint {j.name!r}")
        ordered.append(j)
        visited.add(j.child)
        current = j.child

    if len(visited) != len(links):
        stray = link_names - visited
        raise ValueError(
            f"link(s) {sorted(stray)} are not connected to the root chain "
            f"(check for a stray/duplicate link in the SolidWorks export)"
        )

    return RobotDescription(name=robot_name, links=links, joints=tuple(ordered))


def load_urdf(path: str | Path) -> RobotDescription:
    """Load and parse a URDF file (as produced by SW2URDF from the SolidWorks assembly)."""
    return parse_urdf(Path(path).read_text(encoding="utf-8"))
