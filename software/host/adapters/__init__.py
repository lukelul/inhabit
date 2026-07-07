"""Robot protocol adapters — swappable plugins behind RobotAdapter.

Use ``make_adapter(name, **kwargs)`` to get a configured adapter by name instead of
importing concrete classes directly. The factory is built on the generic
:class:`inhabit_core.Registry`, so adapters share one registration mechanism with every
other extension point (transports, exporters, ...).

Lazy-import contract: importing this package must pull **no** rclpy. ``sim`` and ``replay``
are zero-dependency and registered directly; ``ros2`` and ``ur`` are registered behind
factory functions that import their modules only when an instance is actually built.
"""
from __future__ import annotations

from typing import Any

from inhabit_can.adapter import (
    Capabilities,
    RobotAdapter,
    RobotCommand,
    RobotState,
    SimAdapter,
)
from inhabit_core import Registry

from .replay_adapter import ReplayAdapter

# One registry for all robot adapters. ``entry_point_group`` lets third-party packages
# ship adapters (P-M marketplace) by advertising ``inhabit.adapters`` entry points; it is
# discovered lazily and degrades silently when none are installed.
_REGISTRY: Registry[RobotAdapter] = Registry("adapter", entry_point_group="inhabit.adapters")

# Zero-dependency adapters: register the classes directly.
_REGISTRY.register("sim", SimAdapter)
_REGISTRY.register("replay", ReplayAdapter)


# ``sim_robot`` — the P-B/B2 non-stub simulation adapter (``sim.SimRobotAdapter``): a
# configurable DOF + pluggable trajectory driver with monotonic, non-zero timestamps and
# independent-copy reads (fixing the two ``sim`` reference-stub gaps). Registered behind a
# lazy factory so importing ``host/adapters`` pulls in ``sim`` only when an instance is built
# — matching the heavyweight-adapter pattern and keeping the adapter package import cheap.
@_REGISTRY.register("sim_robot")
def _make_sim_robot(**kwargs: Any) -> RobotAdapter:
    from sim.robot import SimRobotAdapter  # noqa: PLC0415

    return SimRobotAdapter(**kwargs)


# ROS 2 / UR are registered behind factory functions so their modules import only when an
# instance is requested. ros2_adapter imports rclpy lazily (inside connect()), but routing
# it through a factory keeps the import off the package-import path and matches the same
# lazy pattern we will reuse for every heavyweight adapter.
@_REGISTRY.register("ros2")
def _make_ros2(**kwargs: Any) -> RobotAdapter:
    from .ros2_adapter import ROS2Adapter  # noqa: PLC0415

    return ROS2Adapter(**kwargs)


@_REGISTRY.register("ur")
def _make_ur(**kwargs: Any) -> RobotAdapter:
    from .ur_adapter import URAdapter  # noqa: PLC0415

    return URAdapter(**kwargs)


# custom_can — the Rev-A / N-pod daisy chain as one robot (docs/sdk/ROBOT_SDK_MAPPING.md
# §4.5). Zero-dependency (its default source is the in-process SimSource), but routed
# through a lazy factory anyway to match the one pattern every heavyweight adapter uses.
@_REGISTRY.register("custom_can")
def _make_custom_can(**kwargs: Any) -> RobotAdapter:
    from .custom_can_adapter import CustomCanAdapter  # noqa: PLC0415

    return CustomCanAdapter(**kwargs)


def list_adapters() -> list[str]:
    """Return sorted names of all registered adapters."""
    # ``Registry`` intentionally exposes no ``__iter__`` (introspection goes through the
    # public ``names()``/``available()`` API); ``names()`` already returns a sorted list
    # and runs entry-point discovery once so third-party adapters are included.
    return _REGISTRY.names()


def make_adapter(name: str, **kwargs: Any) -> RobotAdapter:
    """Create a :class:`RobotAdapter` by name.

    Raises ``ValueError`` listing the available names if *name* is unknown.
    """
    return _REGISTRY.make(name, **kwargs)


__all__ = [
    "Capabilities",
    "RobotAdapter",
    "RobotCommand",
    "RobotState",
    "list_adapters",
    "make_adapter",
]
