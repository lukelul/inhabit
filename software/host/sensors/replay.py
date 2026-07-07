"""``replay`` — deterministic playback of a recorded proprioceptive sample sequence.

The sensor-source analogue of ``adapters.replay_adapter.ReplayAdapter`` and
``transport`` ``FileReplayTransport``: it faithfully re-emits a caller-provided sequence of
:class:`~inhabit_can.pvt.PVTSample` rows through the :class:`SensorSource` interface, so a
recorded proprio stream can drive the same ingestion path a live source would — no hardware,
no ROS, stdlib-only. It is a reusable building block (P-C alignment tests, P-E QA, P-H
session replay), not a throwaway.

Failure mode it prevents
------------------------
A replay source is only trustworthy if it *cannot* mutate the recording out from under a
consumer and *cannot* smuggle a time-sync-poisoning recording downstream. Two guards, taken
straight from :class:`ReplayAdapter`:

* **Recording poisoning.** Zero/negative/NaN or backwards ``timestamp_ns`` silently corrupts
  the first-class time-sync contract (jitter math, episode alignment). We reject such a
  recording at construction with a loud :class:`ValueError` — the recording must be clean
  before it ever streams. (An empty recording is legal; it simply exhausts immediately.)
* **Aliasing.** :meth:`read` returns an INDEPENDENT copy, and the constructor snapshots its
  input, so a consumer that mutates a returned sample can never corrupt the stored recording —
  replay stays byte-identical across runs and re-opens (the determinism bar in
  ``MASTER_PLAN.md``). A *shallow* ``copy.copy`` suffices because ``PVTSample`` is an
  all-immutable-scalar dataclass (int/float/str/None) — a consumer can only rebind fields on
  its own copy, never mutate a shared sub-object — so we avoid ``deepcopy``'s per-sample
  recursion cost on the replay hot path. (Revisit if the frozen schema ever gains a mutable
  field, which is itself a versioned decision.)

This source IMPORTS the frozen :class:`PVTSample`/``PVT_SCHEMA_VERSION`` to shape/type its
output but never edits them; it replays whatever proprio recording it is handed and stamps
:meth:`metadata` with the schema version those samples already carry.

Time-sync contract
------------------
Unlike a live source, ``replay`` does NOT read a clock: the recorded ``timestamp_ns`` values
ARE the timeline (they were captured against the one monotonic host clock upstream). It only
enforces that they are positive and non-decreasing — the same invariant the ingesting clock
guarantees — so downstream jitter/alignment code sees a recording indistinguishable from a
live capture. Being event/recording-driven, it declares ``nominal_rate_hz=None``.
"""
from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from copy import copy
from itertools import pairwise

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample

from .interface import SensorKind, SensorMetadata, SensorSource


class ReplaySource(SensorSource):
    """Play back a pre-recorded sequence of :class:`PVTSample` rows as a proprio source.

    Faithfully replays whatever proprioceptive recording it is given: it does not synthesize,
    resample, or re-stamp — the recorded ``timestamp_ns`` values are the timeline. This makes
    it the deterministic fixture for alignment (P-C), QA (P-E), and session replay (P-H).

    Parameters
    ----------
    samples:
        Ordered recording to replay. May be empty (exhausts immediately). Every sample's
        ``timestamp_ns`` must be positive, finite, and non-decreasing (the host time-sync
        contract); otherwise construction raises :class:`ValueError`. Snapshotted on
        construction so later caller mutations cannot corrupt the recording.
    device_id:
        Logical device identity advertised in :meth:`metadata` (informational; the replay
        does not depend on it).
    """

    #: This source feeds the proprioceptive modality — it replays ``PVTSample`` proprio rows.
    kind = SensorKind.PROPRIO

    def __init__(
        self,
        samples: Sequence[PVTSample] = (),
        *,
        device_id: str = "replay",
    ) -> None:
        # Failure mode: zero/backwards host timestamps silently corrupt the first-class
        # time-sync contract downstream (jitter math, episode alignment). Reject non-positive
        # and non-monotonic recordings up front — mirrors ReplayAdapter. Empty is allowed.
        timestamps = [s.timestamp_ns for s in samples]
        if any(ts <= 0 for ts in timestamps):
            raise ValueError("ReplaySource requires positive host timestamps")
        # NaN compares False against everything, so a NaN stamp would slip past the ``<=``
        # and the pairwise monotonicity check; reject non-finite stamps explicitly.
        if any(not math.isfinite(ts) for ts in timestamps):
            raise ValueError("ReplaySource requires finite host timestamps")
        if any(curr < prev for prev, curr in pairwise(timestamps)):
            raise ValueError("ReplaySource timestamps must be non-decreasing")
        # Snapshot so caller mutations (and our returned copies) can never corrupt the
        # recording — replay must stay deterministic across runs and re-opens. Shallow copy
        # is enough: PVTSample is all immutable scalars (see class docstring).
        self._samples: list[PVTSample] = [copy(s) for s in samples]
        self._device_id = device_id
        self._index = 0
        self._open = False

    def __len__(self) -> int:
        """Number of recorded samples — useful for progress bars and batching."""
        return len(self._samples)

    # -- metadata -----------------------------------------------------------------------

    def metadata(self) -> SensorMetadata:
        return SensorMetadata(
            kind=self.kind,
            name="replay",
            device_id=self._device_id,
            sample_schema_version=PVT_SCHEMA_VERSION,
            nominal_rate_hz=None,  # event/recording-driven — no fixed period to declare
        )

    # -- lifecycle ----------------------------------------------------------------------

    def open(self) -> None:
        # Rewind the cursor so each open() replays the identical recording from the start —
        # determinism survives reuse (mirrors ReplayAdapter.connect / SimProprioSource.open).
        self._index = 0
        self._open = True

    def close(self) -> None:
        self._open = False

    # -- sample production --------------------------------------------------------------

    def read(self) -> PVTSample | None:
        """Return the next sample as an INDEPENDENT copy, or ``None`` once exhausted.

        The copy is a contract requirement: a caller mutating the returned sample must not be
        able to corrupt the stored recording, so a subsequent re-open replays byte-identically.
        """
        if not self._open:
            raise RuntimeError("ReplaySource.read() called before open()")
        if self._index >= len(self._samples):
            return None
        sample = copy(self._samples[self._index])
        self._index += 1
        return sample

    def stream(self) -> Iterator[PVTSample]:
        """Yield samples until the recording is exhausted OR the source is closed.

        Honors the :class:`SensorSource` "until exhausted or closed" contract: a mid-stream
        ``close()`` (e.g. exiting a ``with`` block while a consumer holds the generator) ends
        the generator cleanly instead of calling :meth:`read` after close and raising. The
        loop re-checks ``self._open`` each iteration, so close transitions terminate it.
        Streaming is exactly read-until-``None``, so the two paths agree.
        """
        if not self._open:
            raise RuntimeError("ReplaySource.stream() called before open()")
        while self._open:
            sample = self.read()
            if sample is None:
                return
            yield sample


__all__ = ["ReplaySource"]
