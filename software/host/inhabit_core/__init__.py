"""inhabit_core — shared plugin-platform primitives.

The reusable building blocks every extension point is built on. Today that is the generic
:class:`Registry`; later phases add the conformance harness and shared contracts here.
Importing this package pulls **no** heavy or optional deps (no rclpy, no pyarrow).
"""
from __future__ import annotations

from inhabit_core.registry import Registry

__all__ = ["Registry"]
