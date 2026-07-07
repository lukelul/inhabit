"""Generic, typed plugin registry — the foundation of the plugin-everything platform.

Every extension point in the Inhabit data engine (robot adapters, transports, sensor
sources, event detectors, exporters, episode sinks) is a *plugin* selected by name from a
:class:`Registry`. Core code never branches on concrete type; it asks the registry for an
instance by name. New capability = a new registration, never a breaking ``if``.

Design rules (PONYTAIL: the simplest correct thing):

* **Typed.** ``Registry[T]`` binds a base type so ``make`` returns ``T`` and mypy-strict
  understands the construction site.
* **Fail loud.** Duplicate names and unknown names raise ``ValueError`` with the available
  names in the message — never a silent overwrite or a bare ``KeyError``.
* **Lazy third-party discovery.** An optional ``importlib.metadata`` entry-point group lets
  external packages (P-M marketplace) register plugins without editing this repo. Discovery
  is *opt-in per lookup*, runs at most once, and **degrades silently** if the group is empty
  or the metadata API is unavailable — a missing third-party plugin must never break the
  first-party engine.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import metadata
from typing import Generic, TypeVar, overload

__all__ = ["Registry"]

T = TypeVar("T")
# A factory is anything callable that returns a T (a class, or a function). We keep the
# argument types open (``...``) on purpose: each plugin defines its own constructor kwargs,
# which ``make`` forwards verbatim. The *return* type stays pinned to T.
Factory = Callable[..., T]


class Registry(Generic[T]):
    """A name -> factory map for plugins of a single base type ``T``.

    Parameters
    ----------
    kind:
        Human-readable label for the extension point (e.g. ``"adapter"``), used only in
        error messages so an unknown-name failure says *which* registry it came from.
    entry_point_group:
        Optional ``importlib.metadata`` entry-point group (e.g.
        ``"inhabit.adapters"``). When set, the first lookup that misses the built-in
        names triggers a one-time, best-effort scan of that group so third-party packages
        can contribute plugins. Leave ``None`` to disable discovery entirely.
    """

    def __init__(self, kind: str = "plugin", *, entry_point_group: str | None = None) -> None:
        self._kind = kind
        self._entry_point_group = entry_point_group
        self._factories: dict[str, Factory[T]] = {}
        # Entry-point discovery is lazy and runs at most once; this guards re-scans.
        self._discovered = False

    # -- registration -------------------------------------------------------------------

    @overload
    def register(self, name: str, factory: Factory[T]) -> Factory[T]: ...
    @overload
    def register(self, name: str) -> Callable[[Factory[T]], Factory[T]]: ...

    def register(
        self, name: str, factory: Factory[T] | None = None
    ) -> Factory[T] | Callable[[Factory[T]], Factory[T]]:
        """Register *factory* under *name*.

        Usable two ways::

            registry.register("sim", SimAdapter)        # direct call

            @registry.register("sim")                   # decorator
            class SimAdapter(...): ...

        A duplicate *name* raises ``ValueError`` rather than silently overwriting an
        existing plugin (a silent clobber is how two packages fight over a name and the
        loser vanishes at runtime).
        """
        if factory is None:
            # Decorator form: return a one-shot decorator that registers then returns the
            # original object unchanged (so the decorated class/func is still usable).
            def decorator(f: Factory[T]) -> Factory[T]:
                self._register(name, f)
                return f

            return decorator
        self._register(name, factory)
        return factory

    def _register(self, name: str, factory: Factory[T]) -> None:
        if name in self._factories:
            raise ValueError(
                f"{self._kind} {name!r} is already registered; "
                f"registered: {self._format_names()}"
            )
        self._factories[name] = factory

    # -- construction -------------------------------------------------------------------

    def make(self, name: str, **kwargs: object) -> T:
        """Construct the plugin registered as *name*, forwarding ``**kwargs``.

        Unknown *name* raises ``ValueError`` listing the available names. Built-in names are
        tried first; only on a miss do we run (once) the optional entry-point discovery, so
        importing the package never eagerly imports third-party plugins.
        """
        factory = self._factories.get(name)
        if factory is None:
            self._maybe_discover()
            factory = self._factories.get(name)
        if factory is None:
            raise ValueError(
                f"Unknown {self._kind} {name!r}; available: {self._format_names()}"
            )
        return factory(**kwargs)

    # -- introspection ------------------------------------------------------------------

    def names(self) -> list[str]:
        """Sorted registered names (runs discovery once so the list is complete)."""
        self._maybe_discover()
        return sorted(self._factories)

    # ``available`` is an alias for ``names`` — both spellings appear across the codebase
    # and docs; keep them identical so neither surprises a caller.
    def available(self) -> list[str]:
        """Alias for :meth:`names`."""
        return self.names()

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._factories

    def __len__(self) -> int:
        return len(self._factories)

    # -- entry-point discovery (lazy, best-effort) --------------------------------------

    def _maybe_discover(self) -> None:
        """Scan the entry-point group once, if configured. Never raises.

        Third-party plugins are a *bonus*: a broken or absent metadata environment must
        degrade to "just the built-ins", not crash the engine. Any failure here is
        swallowed deliberately. A third-party name that collides with a built-in is
        skipped (built-ins win) rather than raising, so a hostile package can't break us.
        """
        if self._discovered or self._entry_point_group is None:
            return
        # Set the flag first: even if discovery raises, we must not retry on every lookup.
        self._discovered = True
        try:
            for ep in self._iter_entry_points(self._entry_point_group):
                if ep.name in self._factories:
                    continue  # built-ins and earlier plugins win; no clobber, no error.
                try:
                    factory = ep.load()
                except Exception:
                    continue
                self._factories[ep.name] = factory
        except Exception:
            return

    @staticmethod
    def _iter_entry_points(group: str) -> Iterable[metadata.EntryPoint]:
        """Yield entry points for *group*.

        We target Python 3.11+, where ``entry_points(group=...)`` returns an
        ``EntryPoints`` already filtered to the group — the single supported API shape.
        """
        return tuple(metadata.entry_points(group=group))

    # -- helpers ------------------------------------------------------------------------

    def _format_names(self) -> str:
        return ", ".join(sorted(self._factories)) or "(none)"
