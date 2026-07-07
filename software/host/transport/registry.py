"""Transport registry — name -> :class:`CanTransport` factory.

Built on the generic :class:`inhabit_core.Registry`, so transports share one plugin
mechanism with adapters (``host/adapters``), exporters, sensor sources, and every
other Inhabit extension point. Select a backend by name instead of importing concrete
classes::

    from transport import make_transport
    t = make_transport("inmem")            # or "file", path=...; "socketcan"; "slcan"

Registered built-ins:
  * ``file``      — :class:`FileReplayTransport` (replay a ``.canlog``; needs ``path=``)
  * ``socketcan`` — :class:`SocketCanTransport` (Linux socketcan via python-can)
  * ``slcan``     — :class:`SlcanTransport` (USB-CAN serial dongle, any OS)
  * ``inmem``     — :class:`InMemTransport` (zero-dependency loopback queue)

Lazy-import contract: ``socketcan`` / ``slcan`` import their heavyweight deps
(``python-can`` / ``pyserial``) only inside ``open()``, so registering the classes
here — and importing this module — pulls **no** hardware libraries. ``entry_point_group``
lets third-party packages ship transports (P-M marketplace) via ``inhabit.transports``
entry points, discovered lazily and degrading silently when none are installed.
"""
from __future__ import annotations

from typing import Any

from inhabit_core import Registry

from .file import FileReplayTransport
from .inmem import InMemTransport
from .interface import CanTransport
from .slcan import SlcanTransport
from .socketcan import SocketCanTransport

_REGISTRY: Registry[CanTransport] = Registry(
    "transport", entry_point_group="inhabit.transports"
)
# Register the classes directly — each constructor is cheap and pulls no hardware deps
# (socketcan/slcan defer python-can/pyserial to open()).
_REGISTRY.register("file", FileReplayTransport)
_REGISTRY.register("socketcan", SocketCanTransport)
_REGISTRY.register("slcan", SlcanTransport)
_REGISTRY.register("inmem", InMemTransport)


def make_transport(name: str, **kwargs: Any) -> CanTransport:
    """Create a :class:`CanTransport` by name, forwarding ``**kwargs`` to its constructor.

    Raises ``ValueError`` listing the available names if *name* is unknown.
    """
    return _REGISTRY.make(name, **kwargs)


def list_transports() -> list[str]:
    """Return sorted names of all registered transports.

    Delegates to :meth:`Registry.names` (which runs entry-point discovery once so
    third-party transports are included); ``Registry`` deliberately exposes no
    ``__iter__``, so never iterate it directly.
    """
    return _REGISTRY.names()
