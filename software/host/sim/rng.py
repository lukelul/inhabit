"""Seeded, portable RNG core for the synthetic PVT engine.

Failure mode this prevents: **non-portable, non-reproducible fixtures.** If the sim drew
from the process-global :func:`random.random` (or numpy), every regenerated golden episode
could differ across machines, CI runners, and Python builds, and two "identical" runs in
the same process would interfere through shared RNG state. That silently rots the whole
P-B byte-stability guarantee — the point of the simulator is a byte-stable dataset you can
diff. So randomness in the sim flows through exactly ONE object seeded with an ``int``.

P-B determinism invariant (see ``MASTER_TASK_QUEUE.md`` §"Invariants for every P-B task"):

* **Stdlib-only.** Wraps :class:`random.Random`; **NO numpy** (house style / hard P-B
  invariant). CPython's Mersenne-Twister stream for a given seed is documented as stable
  across platforms and versions, so ``SeededRng(7)`` yields the identical sequence on
  win32/py3.13 dev and Ubuntu/py3.11 CI — which is what makes committed goldens diffable.
* **One seed in, one stream out.** Same seed => identical draw sequence; different seeds
  diverge; a fresh instance from the same seed reproduces the sequence exactly.

Scope (PONYTAIL — the leanest core that works): a thin, well-typed wrapper plus the few
draw helpers B3 (per-channel proprio noise) will obviously reach for, and :meth:`spawn` so
independent noise channels get *independent, still-deterministic* sub-streams without
manual bookkeeping. No speculative distributions, no state serialisation — YAGNI until a
later task actually needs them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

__all__ = ["SeededRng"]


@dataclass(frozen=True, slots=True)
class SeededRng:
    """A seeded, portable random stream — the ONE randomness source for the sim.

    Wraps a private :class:`random.Random` so no draw ever touches the process-global RNG
    (whose state is shared, order-dependent, and therefore non-reproducible). Construct with
    an integer ``seed``; the same seed always produces the same sequence, a fresh instance
    re-derives it exactly, and different seeds diverge — the properties B2/B3 and the golden
    fixtures rely on.

    The dataclass is ``frozen`` so ``seed`` is an immutable record of *which* stream this is —
    two ``SeededRng(7)`` compare equal and ``repr`` is a byte-stable ``SeededRng(seed=7)``
    (the private :class:`random.Random`, which carries the mutable draw cursor and a
    process-address ``repr``, is excluded from init/repr/eq/hash so it can never leak into a
    logged fixture or break value equality). Value identity is the seed; the ``Random`` is
    owned implementation state.
    """

    seed: int
    # Owned implementation state, not part of the value: excluded from the constructor, repr,
    # equality, and hash. Set in __post_init__ so each instance owns its OWN Random — a shared
    # field default would couple every SeededRng's cursor and destroy reproducibility, and a
    # Random in repr/eq would leak a process address and make SeededRng(7) != SeededRng(7).
    _rng: Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Enforce the invariant at the RNG boundary itself (not only in SimConfig): the seed
        # must be a real int. bool is an int subclass, and a float seed is accepted by
        # random.Random but is a portability smell — reject both up front, loud, so a bad seed
        # can't slip through direct construction or SimConfig.rng().
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError(f"SeededRng seed must be an int (got {type(self.seed).__name__})")
        # frozen dataclass: bypass the blocked setattr to install the private Random from seed.
        object.__setattr__(self, "_rng", Random(self.seed))

    def uniform(self, low: float, high: float) -> float:
        """Draw a float uniformly from ``[low, high]`` (advances the stream)."""
        return self._rng.uniform(low, high)

    def gauss(self, mu: float, sigma: float) -> float:
        """Draw a Gaussian ``N(mu, sigma)`` sample (advances the stream).

        The natural primitive for bounded per-channel sensor noise in B3; ``sigma == 0``
        returns ``mu`` exactly (a zero-noise config reproduces the noise-free path).
        """
        return self._rng.gauss(mu, sigma)

    def randint(self, low: int, high: int) -> int:
        """Draw an int uniformly from the inclusive range ``[low, high]``."""
        return self._rng.randint(low, high)

    def spawn(self, label: str) -> SeededRng:
        """Derive an independent child stream keyed by ``label``.

        Failure mode this prevents: **cross-channel RNG coupling.** If every noise channel
        (angle/velocity/current/torque) drew from one shared stream, adding or reordering a
        single channel would shift every *other* channel's draws and break byte-stability.
        Each child is seeded deterministically from ``(self.seed, label)`` via
        :func:`hash`-free arithmetic on the label bytes, so:

        * the same ``(seed, label)`` always yields the same child stream (portable — we do
          NOT use the process-salted builtin ``hash``), and
        * distinct labels yield distinct, independent streams.

        This lets B3 give each channel its own reproducible sub-stream without hand-tuning
        offsets.
        """
        # Fold the label into the seed with a fixed, salt-free scheme (str hashing in CPython
        # is randomised per process — unusable for reproducibility). FNV-1a over the UTF-8
        # bytes is small, stdlib-free, and identical on every machine.
        child_seed = self.seed
        h = 0x811C9DC5
        for byte in label.encode("utf-8"):
            h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
        return SeededRng(child_seed ^ h)
