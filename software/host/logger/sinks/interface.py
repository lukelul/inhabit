"""EpisodeSink contract — where an aligned PVT episode goes, behind one stable seam.

A recorded episode is the product; an :class:`EpisodeSink` is the *destination* it is
written to. Core code (a recorder loop, a sim session, a replay harness) never branches
on "are we writing parquet, holding in memory, or quarantining?" — it opens a sink by
name, streams samples into it, and finalizes. New destinations (HDF5, a remote store,
a streaming uploader) become new plugins, never an ``if`` in the hot path.

The failure each lifecycle stage exists to prevent
-------------------------------------------------
* **open** — bind the destination *before* any sample arrives. A sink that lazily
  resolves its output on the first sample can fail half-way through an episode, leaving
  a partially-committed dataset. Opening up front means a bad destination fails loud at
  episode start, not after 10 000 samples are already gone.
* **ingest** — append one sample, append-only. The same data-integrity gates that
  protect :class:`~logger.recorder.EpisodeRecorder` (corrupt-checksum frames, NaN/inf
  joint values) must apply *here* too: a single garbage frame admitted to the timeline
  poisons every model trained on the dataset, and a NaN serialized to parquet silently
  breaks a trainer downstream. A sink may drop/quarantine a bad frame but must NEVER let
  it through unchecked.
* **finalize** — commit *atomically* or quarantine. A half-written episode is worse than
  no episode: it looks complete to a reader but is missing the tail. ``finalize`` is the
  one place a sink either produces a whole, in-budget episode or refuses to (and says
  why). It must be idempotent-safe: calling it twice is a programming error and fails
  loud, not a silent double-write.

Time-sync is first-class
------------------------
Every sample a sink ingests carries ``timestamp_ns`` from the SINGLE monotonic host
clock (``time.monotonic_ns``) that stamps :class:`~inhabit_can.pvt.PVTSample`. A sink
never invents a clock; it measures inter-sample jitter against that one timeline and
(for the durable parquet sink) quarantines an episode whose jitter blows the budget,
because a clock jump silently misaligns the proprio/visual/tactile streams.

Why this is a versioned contract
--------------------------------
:data:`SINK_CONTRACT_VERSION` pins the open/ingest/finalize shape. Bump it ONLY with a
compatibility story for existing sinks — adding a new sink is a new plugin, not a
contract change. This module is the *contract* and nothing else: an ABC, a typed result,
and the context-manager sugar. Concrete sinks live beside it as plugins; importing this
module pulls no heavy or optional dependency (no pyarrow).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any

from inhabit_can.pvt import PVTSample

__all__ = [
    "SINK_CONTRACT_VERSION",
    "EpisodeSink",
    "SinkResult",
]

# Current open/ingest/finalize contract version. Bump ONLY with a migration story for
# existing sinks; a new destination is a new plugin, never a contract break.
SINK_CONTRACT_VERSION = 1


@dataclass(frozen=True, slots=True)
class SinkResult:
    """Outcome of :meth:`EpisodeSink.finalize` — a uniform, plugin-agnostic verdict.

    ``frozen`` because a finalize verdict is append-only evidence: once an episode is
    committed (or quarantined) that fact cannot be quietly rewritten. The fields are the
    intersection every sink can honestly report, so a caller can gate on the result
    without knowing which concrete sink produced it.

    Attributes
    ----------
    episode_id:
        Which episode this verdict is for.
    accepted:
        ``True`` iff the episode was committed to the destination (passed every gate);
        ``False`` iff it was rejected/quarantined. The single boolean a caller branches
        on — *not* "did finalize run", but "is there now a usable episode".
    n_samples:
        Number of samples actually committed (post-drop): the honest episode length.
    reasons:
        Empty iff ``accepted``; otherwise the human-readable rejection reasons (jitter
        over budget, too few samples, clock went backwards, ...). Reproduces the
        recorder's quarantine reasons through the sink layer.
    path:
        Where the result landed, if anywhere: the committed artifact path for an accepted
        durable episode, the quarantine sidecar for a rejected one, or ``None`` for a
        purely in-memory sink that has no on-disk location.
    detail:
        Read-only sink-specific provenance (jitter stats, dropped-frame counts, detector
        version, ...) so timing/label provenance travels with the verdict. Defaults empty.
    """

    episode_id: str
    accepted: bool
    n_samples: int
    reasons: tuple[str, ...] = ()
    path: Path | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ``frozen=True`` only stops re-binding the *attribute*; it does not protect a nested
        # mutable. Sinks build ``detail`` from a plain ``dict``, so without this a caller
        # could still do ``result.detail[k] = v`` after finalize and quietly rewrite the
        # append-only verdict this contract promises. Wrap it in a read-only view (over a
        # private copy, so a reference the caller still holds to the original dict cannot
        # mutate it either). ``object.__setattr__`` is required to assign on a frozen+slots
        # dataclass.
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))


class EpisodeSink(ABC):
    """Destination for one atomic PVT episode: ``open -> ingest* -> finalize``.

    The single contract every sink plugin honours. Core code asks the registry for a
    sink by name (see :func:`logger.sinks.make_episode_sink`) and drives this lifecycle;
    it never imports a concrete sink or branches on its type.

    Lifecycle contract for implementations
    --------------------------------------
    * :meth:`open` is called exactly once, before the first :meth:`ingest`. It binds the
      destination and resets per-episode state. Re-opening an already-open sink is a
      programming error and must fail loud.
    * :meth:`ingest` appends one :class:`~inhabit_can.pvt.PVTSample` (append-only). A sink
      MUST uphold the data-integrity gates: a non-finite (NaN/inf) joint value is never
      admitted to the timeline. Ingesting before :meth:`open` or after :meth:`finalize`
      raises (a sample arriving outside the episode window is a bug, not silent data
      loss).
    * :meth:`finalize` is called exactly once, after the last :meth:`ingest`. It commits
      the episode atomically *or* quarantines it, and returns a :class:`SinkResult`.
      Calling it twice raises rather than double-committing.

    Context-manager sugar
    ---------------------
    A sink is its own context manager so the common path is hard to get wrong::

        with make_episode_sink("parquet-atomic", out_dir=d, episode_id="ep") as sink:
            for sample in stream:
                sink.ingest(sample)
        result = sink.result            # finalize ran on a clean exit

    On a clean ``with`` exit the episode is finalized automatically; on an exception the
    block is abandoned WITHOUT committing (a crashed episode must not produce a
    half-written artifact). The finalize verdict is then available on :attr:`result`.
    """

    #: Registry name of this sink; subclasses override. Used only for messages/provenance.
    name: str = "episode_sink"

    def __init__(self) -> None:
        self._opened = False
        self._finalized = False
        self._result: SinkResult | None = None

    # -- lifecycle ----------------------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """Bind the destination and reset per-episode state. Called once, first.

        Implementations call :meth:`_enter_open` first so every sink rejects a
        double-open identically.
        """

    @abstractmethod
    def ingest(self, sample: PVTSample) -> None:
        """Append one sample to the open episode (append-only).

        Must reject (drop/quarantine) a non-finite joint value rather than admit it — a
        NaN reaching the destination silently breaks any trainer that reads it back.
        """

    @abstractmethod
    def finalize(self) -> SinkResult:
        """Commit the episode atomically or quarantine it; return the verdict. Once."""

    # -- shared lifecycle guards (sinks call these so the rules can't drift) -------------

    def _enter_open(self) -> None:
        """Mark the sink open; fail loud on a double-open. Call at the top of ``open``."""
        if self._opened:
            raise RuntimeError(f"sink {self.name!r} already opened; create a new sink per episode")
        self._opened = True

    def _check_ingestable(self) -> None:
        """Guard an ``ingest`` call: must be open, must not be finalized."""
        if not self._opened:
            raise RuntimeError(f"sink {self.name!r} not opened; call open() before ingest()")
        if self._finalized:
            raise RuntimeError(f"sink {self.name!r} already finalized; open a new episode")

    def _enter_finalize(self) -> None:
        """Guard a ``finalize`` call: must be open, must not be finalized. Call first."""
        if not self._opened:
            raise RuntimeError(f"sink {self.name!r} not opened; nothing to finalize")
        if self._finalized:
            raise RuntimeError(f"sink {self.name!r} already finalized")
        self._finalized = True

    # -- introspection ------------------------------------------------------------------

    @property
    def contract_version(self) -> int:
        """Lifecycle-contract version this sink implements. Pinned to the package."""
        return SINK_CONTRACT_VERSION

    @property
    def result(self) -> SinkResult | None:
        """The :class:`SinkResult` from :meth:`finalize`, or ``None`` if not finalized."""
        return self._result

    # -- context-manager sugar ----------------------------------------------------------

    def __enter__(self) -> EpisodeSink:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Finalize only on a clean exit. If the block raised, the episode is incomplete;
        # abandoning it WITHOUT committing is the whole point of atomicity — a crashed
        # episode must never leave a half-written artifact behind.
        if exc_type is None and not self._finalized:
            self._result = self.finalize()
