"""host.sim — the seeded, hardware-free synthetic PVT engine (Phase P-B).

Everything under this package is **deterministic and stdlib-only** (no numpy — a hard P-B
invariant), so the whole PVT pipeline is exercisable with zero hardware and the committed
golden fixtures stay byte-stable across machines and CI.

B1 lands the shared seam the rest of P-B consumes: :class:`SeededRng`, the ONE randomness
source. B2 (:class:`SimRobot`), B3 (proprio noise), and B4 (contact scenarios) draw
exclusively from it so every run is reproducible.

B2 adds :class:`SimRobot` — the configurable, seeded synthetic joint robot (DOF + pluggable
:data:`Trajectory` models, monotonic ``timestamp_ns``, independent-copy reads) — and
:class:`SimRobotAdapter`, which exposes it behind the FROZEN ``RobotAdapter``.

B4 adds :class:`ContactScenario` — the validated, serializable last-centimeter contact
script B5 drives onto the FROZEN ``PVTSample.tactile_event`` / ``camera_frame_id`` timeline.
"""
from __future__ import annotations

from sim.rng import SeededRng
from sim.robot import (
    TRAJECTORIES,
    SimRobot,
    SimRobotAdapter,
    Trajectory,
    TrajectoryParams,
    hold,
    ramp,
    sine,
    trajectory,
)
from sim.scenario import (
    CONTACT_KINDS,
    EXAMPLE_SCENARIOS,
    NONCONTACT_KINDS,
    PHASE_KINDS,
    PICK_PLACE,
    SLIP_RECOVERY,
    ContactPhase,
    ContactScenario,
    example_scenario,
)

__all__ = [
    "CONTACT_KINDS",
    "EXAMPLE_SCENARIOS",
    "NONCONTACT_KINDS",
    "PHASE_KINDS",
    "PICK_PLACE",
    "SLIP_RECOVERY",
    "TRAJECTORIES",
    "ContactPhase",
    "ContactScenario",
    "SeededRng",
    "SimRobot",
    "SimRobotAdapter",
    "Trajectory",
    "TrajectoryParams",
    "example_scenario",
    "hold",
    "ramp",
    "sine",
    "trajectory",
]
