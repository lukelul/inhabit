"""Tests for inhabit_core.Registry — the generic plugin registry.

Covers the happy path (register/make), the fail-loud guards (unknown name and duplicate
name both -> ValueError with the available names), introspection (available/names), the
optional lazy entry-point discovery (monkeypatched, including the silent-degrade paths),
AND the adapter-registry integration: sim/replay still build working adapters and importing
``adapters`` / ``inhabit_core`` pulls no rclpy (the lazy-import contract).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import pytest

from adapters import make_adapter
from adapters.replay_adapter import ReplayAdapter
from inhabit_can.adapter import RobotState, SimAdapter
from inhabit_core import Registry

# Absolute path to host/ (the package search root) so subprocess cwd is unambiguous
# regardless of where pytest is invoked from.
_HOST_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# A trivial base + plugins to exercise the generic, typed registry.
# ---------------------------------------------------------------------------

@dataclass
class Widget:
    label: str
    size: int = 1


class RedWidget(Widget):
    def __init__(self, size: int = 1) -> None:
        super().__init__(label="red", size=size)


class BlueWidget(Widget):
    def __init__(self, size: int = 1) -> None:
        super().__init__(label="blue", size=size)


def _fresh() -> Registry[Widget]:
    reg: Registry[Widget] = Registry("widget")
    reg.register("red", RedWidget)
    reg.register("blue", BlueWidget)
    return reg


# ---------------------------------------------------------------------------
# register / make happy path
# ---------------------------------------------------------------------------

class TestRegisterMake:
    def test_make_returns_instance(self) -> None:
        reg = _fresh()
        w = reg.make("red")
        assert isinstance(w, RedWidget)
        assert w.label == "red"

    def test_make_forwards_kwargs(self) -> None:
        reg = _fresh()
        w = reg.make("blue", size=7)
        assert isinstance(w, BlueWidget)
        assert w.size == 7

    def test_register_decorator_form(self) -> None:
        reg: Registry[Widget] = Registry("widget")

        @reg.register("green")
        class GreenWidget(Widget):
            def __init__(self) -> None:
                super().__init__(label="green")

        # Decorator returns the class unchanged AND registers it.
        assert GreenWidget(  # type: ignore[call-arg]
        ).label == "green"
        assert reg.make("green").label == "green"

    def test_register_function_factory(self) -> None:
        reg: Registry[Widget] = Registry("widget")
        reg.register("custom", lambda size=3: Widget(label="custom", size=size))
        w = reg.make("custom", size=9)
        assert w.label == "custom"
        assert w.size == 9

    def test_register_call_form_returns_factory(self) -> None:
        # Direct (non-decorator) register returns the factory for convenience.
        reg: Registry[Widget] = Registry("widget")
        ret = reg.register("red", RedWidget)
        assert ret is RedWidget


# ---------------------------------------------------------------------------
# fail-loud guards
# ---------------------------------------------------------------------------

class TestGuards:
    def test_unknown_name_raises_value_error_listing_available(self) -> None:
        reg = _fresh()
        with pytest.raises(ValueError, match=r"Unknown widget 'purple'; available: blue, red"):
            reg.make("purple")

    def test_unknown_name_on_empty_registry_says_none(self) -> None:
        reg: Registry[Widget] = Registry("widget")
        with pytest.raises(ValueError, match=r"available: \(none\)"):
            reg.make("anything")

    def test_duplicate_register_raises_value_error(self) -> None:
        reg = _fresh()
        with pytest.raises(ValueError, match=r"widget 'red' is already registered"):
            reg.register("red", BlueWidget)

    def test_duplicate_register_decorator_form_raises(self) -> None:
        reg = _fresh()
        with pytest.raises(ValueError, match="already registered"):

            @reg.register("blue")
            class Other(Widget):
                def __init__(self) -> None:
                    super().__init__(label="other")


# ---------------------------------------------------------------------------
# introspection
# ---------------------------------------------------------------------------

class TestIntrospection:
    def test_names_sorted(self) -> None:
        assert _fresh().names() == ["blue", "red"]

    def test_available_is_alias_of_names(self) -> None:
        reg = _fresh()
        assert reg.available() == reg.names() == ["blue", "red"]

    def test_contains(self) -> None:
        reg = _fresh()
        assert "red" in reg
        assert "purple" not in reg
        assert 123 not in reg  # non-str never matches

    def test_len(self) -> None:
        assert len(_fresh()) == 2


# ---------------------------------------------------------------------------
# optional entry-point discovery (lazy, monkeypatched, best-effort)
# ---------------------------------------------------------------------------

def _ep(name: str, factory: object) -> metadata.EntryPoint:
    """A real EntryPoint whose .load() returns *factory* (patched below)."""
    ep = metadata.EntryPoint(name=name, value="x:y", group="inhabit.test")
    object.__setattr__(ep, "_loaded", factory)  # carry the factory on the instance
    return ep


class _FakeEntryPoints:
    """Stand-in for the 3.11+ EntryPoints selection result (iterable of EntryPoint)."""

    def __init__(self, eps: list[metadata.EntryPoint]) -> None:
        self._eps = eps

    def __iter__(self) -> object:
        return iter(self._eps)


class TestEntryPointDiscovery:
    def test_discovery_registers_third_party_plugin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        green = _ep("green", None)
        # Make .load() return a real factory (EntryPoint is frozen, so patch the method).
        monkeypatch.setattr(
            metadata.EntryPoint, "load",
            lambda self: (lambda: Widget(label="green")),
        )
        def fake_eps(**kw: object) -> _FakeEntryPoints:
            hit = kw.get("group") == "inhabit.test"
            return _FakeEntryPoints([green] if hit else [])

        monkeypatch.setattr(metadata, "entry_points", fake_eps)
        reg: Registry[Widget] = Registry("widget", entry_point_group="inhabit.test")
        # Discovery is lazy: only triggered on a miss / introspection.
        assert reg.make("green").label == "green"
        assert "green" in reg.names()

    def test_discovery_runs_at_most_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def fake_eps(**kw: object) -> _FakeEntryPoints:
            calls["n"] += 1
            return _FakeEntryPoints([])

        monkeypatch.setattr(metadata, "entry_points", fake_eps)
        reg: Registry[Widget] = Registry("widget", entry_point_group="inhabit.test")
        reg.names()
        reg.names()
        with pytest.raises(ValueError, match="Unknown"):
            reg.make("nope")
        assert calls["n"] == 1  # scanned exactly once despite three lookups

    def test_discovery_disabled_when_no_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**kw: object) -> object:
            raise AssertionError("entry_points must not be called when group is None")

        monkeypatch.setattr(metadata, "entry_points", boom)
        reg: Registry[Widget] = Registry("widget")  # no group
        assert reg.names() == []

    def test_third_party_cannot_clobber_builtin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An entry point named "red" must NOT override the built-in red plugin.
        hostile = _ep("red", None)
        monkeypatch.setattr(
            metadata.EntryPoint, "load",
            lambda self: (lambda: Widget(label="HOSTILE")),
        )
        monkeypatch.setattr(
            metadata, "entry_points", lambda **kw: _FakeEntryPoints([hostile]),
        )
        reg = _fresh()
        reg._entry_point_group = "inhabit.test"  # enable discovery on this instance
        reg._discovered = False
        # names() always runs discovery, so the collision branch (skip, don't clobber)
        # is exercised; "red" must still resolve to the built-in afterwards.
        assert reg.names() == ["blue", "red"]  # hostile "red" skipped, no duplicate
        assert reg.make("red").label == "red"  # built-in wins, not "HOSTILE"

    def test_discovery_degrades_when_metadata_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A broken metadata environment must fall back to built-ins, never crash.
        monkeypatch.setattr(
            metadata, "entry_points",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("metadata exploded")),
        )
        reg = _fresh()
        reg._entry_point_group = "inhabit.test"
        reg._discovered = False
        assert reg.names() == ["blue", "red"]  # survived

    def test_one_bad_plugin_does_not_kill_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bad = _ep("bad", None)
        good = _ep("good", None)

        def load(self: metadata.EntryPoint) -> object:
            if self.name == "bad":
                raise ImportError("bad plugin")
            return lambda: Widget(label="good")

        monkeypatch.setattr(metadata.EntryPoint, "load", load)
        monkeypatch.setattr(metadata, "entry_points", lambda **kw: _FakeEntryPoints([bad, good]))
        reg: Registry[Widget] = Registry("widget", entry_point_group="inhabit.test")
        assert reg.make("good").label == "good"  # good loaded despite bad raising
        assert "bad" not in reg  # the failing one was skipped


# ---------------------------------------------------------------------------
# adapter-registry integration: real plugins still work through the refactor
# ---------------------------------------------------------------------------

class TestAdapterRegistryIntegration:
    def test_sim_adapter_builds_and_works(self) -> None:
        a = make_adapter("sim", dof=4)
        assert isinstance(a, SimAdapter)
        a.connect()
        assert len(a.read_state().joint_angles) == 4
        assert a.capabilities().dof == 4

    def test_replay_adapter_builds_and_works(self) -> None:
        states = [RobotState(joint_angles=[1.0], timestamp_ns=1000)]
        a = make_adapter("replay", states=states)
        assert isinstance(a, ReplayAdapter)
        a.connect()
        assert a.read_state().joint_angles == [1.0]

    def test_unknown_adapter_lists_all_names(self) -> None:
        with pytest.raises(
            ValueError, match=r"available: custom_can, replay, ros2, sim, sim_robot, ur"
        ):
            make_adapter("kuka")


# ---------------------------------------------------------------------------
# lazy-import contract: importing adapters / inhabit_core pulls NO rclpy
# ---------------------------------------------------------------------------

class TestLazyImportContract:
    def _import_pulls_no_rclpy(self, statement: str) -> None:
        # Run in a fresh interpreter so we observe a clean module table, not this
        # session's (some other test may already have imported rclpy).
        code = (
            "import sys\n"
            f"{statement}\n"
            "assert 'rclpy' not in sys.modules, "
            "'lazy-import contract violated: rclpy was imported'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(_HOST_DIR),  # so the `adapters`/`inhabit_core` packages are importable
        )
        assert result.returncode == 0, result.stderr

    def test_import_adapters_no_rclpy(self) -> None:
        self._import_pulls_no_rclpy("import adapters")

    def test_import_inhabit_core_no_rclpy(self) -> None:
        self._import_pulls_no_rclpy("import inhabit_core")

    def test_make_ros2_adapter_does_not_require_rclpy_to_construct(self) -> None:
        # Building the ROS2 adapter must not import rclpy (that happens in connect()).
        code = (
            "import sys\n"
            "from adapters import make_adapter\n"
            "make_adapter('ros2', dof=3)\n"
            "assert 'rclpy' not in sys.modules\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_HOST_DIR)
        )
        assert result.returncode == 0, result.stderr
