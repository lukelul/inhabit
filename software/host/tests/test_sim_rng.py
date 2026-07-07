"""Tests for the seeded sim RNG core (P-B/B1) and the seed seam plumbed into ``SimConfig``.

The failure mode under test is **non-portable, non-reproducible fixtures**: if the sim's
randomness were not a single seeded, stdlib-only stream, regenerated goldens could diverge
across machines/CI and back-to-back runs would interfere. So we pin, directly on the RNG
core, the four properties the rest of P-B (B2 SimRobot, B3 noise) and the golden fixtures
rely on:

* same seed => identical draw sequence,
* different seeds => different sequences,
* a fresh instance from the same seed reproduces the sequence exactly (reuse-safe), and
* ``spawn(label)`` gives deterministic, independent per-channel sub-streams.

Sequencing note (B1, not B3): no sample math consumes the RNG yet, so different seeds do
NOT change generated episodes — that test cannot pass until B3 and is deliberately absent.
Instead we assert the generator's **back-compat**: with the default seed its output is
byte-identical (``as_row()`` equality) to the pre-seed behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tools/ lives outside host/; add the repo root so ``tools.dataset`` resolves (mirrors the
# existing sim tests).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim.rng import SeededRng
from tools.dataset.sim_adapter import SimAdapter, SimConfig


def _draws(rng: SeededRng, n: int = 16) -> list[float]:
    """A fixed-order sample of the stream — the sequence identity we compare on."""
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


# -- RNG core: determinism ------------------------------------------------------------


def test_same_seed_converges() -> None:
    """Same seed => byte-identical draw sequence."""
    assert _draws(SeededRng(1234)) == _draws(SeededRng(1234))


def test_different_seed_diverges() -> None:
    """Different seeds => different draw sequences (the streams must not coincide)."""
    assert _draws(SeededRng(1)) != _draws(SeededRng(2))


def test_fresh_instance_reproduces_sequence() -> None:
    """A fresh instance from the same seed replays the sequence — reuse is safe.

    Guards the reproducibility we need when a generator is re-run to regenerate a golden:
    building a new ``SeededRng(seed)`` must not depend on any prior draws or shared state.
    """
    first = _draws(SeededRng(99))
    # Interleave an unrelated stream to prove there is no shared/global RNG state coupling.
    _ = _draws(SeededRng(7), n=50)
    second = _draws(SeededRng(99))
    assert first == second


def test_portable_known_sequence() -> None:
    """Pin the first draws of a fixed seed so a CPython RNG change is caught loudly.

    CPython's Mersenne-Twister stream for a given seed is stable across platforms/versions;
    this is what makes committed goldens diffable. If a future interpreter ever perturbs it,
    this asserts the failure at the seam instead of as a silent golden-diff downstream.
    """
    seq = SeededRng(0)
    got = [round(seq.uniform(0.0, 1.0), 12) for _ in range(3)]
    assert got == [0.844421851525, 0.75795440294, 0.420571580831]


def test_gauss_zero_sigma_is_exact_mu() -> None:
    """``gauss(mu, 0.0)`` returns ``mu`` exactly => a zero-noise config is noise-free."""
    rng = SeededRng(5)
    assert rng.gauss(0.5, 0.0) == 0.5
    assert rng.gauss(-2.0, 0.0) == -2.0


def test_randint_inclusive_range() -> None:
    """``randint`` stays within its inclusive bounds and is seed-reproducible."""
    a = [SeededRng(3).randint(0, 4) for _ in range(1)]
    b = [SeededRng(3).randint(0, 4) for _ in range(1)]
    assert a == b
    assert all(0 <= v <= 4 for v in (SeededRng(k).randint(0, 4) for k in range(20)))


# -- RNG core: spawn (independent per-channel sub-streams) ----------------------------


def test_spawn_is_deterministic_per_label() -> None:
    """Same (seed, label) => same child stream; portable (no process-salted hashing)."""
    parent = SeededRng(42)
    assert _draws(parent.spawn("angle")) == _draws(SeededRng(42).spawn("angle"))


def test_spawn_labels_are_independent() -> None:
    """Distinct labels yield distinct sub-streams, so channels do not couple."""
    parent = SeededRng(42)
    assert _draws(parent.spawn("angle")) != _draws(parent.spawn("velocity"))


def test_spawn_does_not_disturb_parent() -> None:
    """Spawning a child must not advance the parent's own cursor.

    Otherwise deriving a per-channel stream would shift the parent sequence and break
    byte-stability for any code that also draws from the parent.
    """
    parent = SeededRng(8)
    before = _draws(parent, n=4)
    parent2 = SeededRng(8)
    parent2.spawn("noise")  # derive a child, then draw from the parent
    after = _draws(parent2, n=4)
    assert before == after


def test_seed_is_recorded() -> None:
    """The frozen ``seed`` is an immutable record of which stream this is."""
    rng = SeededRng(seed=17)
    assert rng.seed == 17
    with pytest.raises(AttributeError):
        rng.seed = 18  # type: ignore[misc]  # frozen dataclass


# -- Generator back-compat: default seed leaves emitted samples byte-identical ---------


def test_seed_defaults_and_validates() -> None:
    """``SimConfig.seed`` defaults to 0 and rejects a non-int/bool loudly."""
    assert SimConfig().seed == 0
    with pytest.raises(ValueError, match="seed must be an int"):
        SimAdapter().generate_episode(config=SimConfig(seed=True))  # bool is not an int seed


def test_config_rng_is_seeded_and_fresh() -> None:
    """``SimConfig.rng()`` returns a fresh seeded stream each call (replayable)."""
    cfg = SimConfig(seed=123)
    assert _draws(cfg.rng()) == _draws(cfg.rng())  # each call re-derives the same sequence
    assert cfg.rng().seed == 123


def test_generator_output_unchanged_by_seed() -> None:
    """B1 back-compat: threading a seed does NOT change emitted samples yet.

    No sample math consumes the RNG in B1 (noise is B3), so two episodes with different
    seeds are byte-identical (``as_row()`` equality). This is the guard that plumbing the
    seam did not perturb today's golden output — and a canary that must be *inverted* when
    B3 makes the noise seed-dependent.
    """
    cfg_default = SimConfig(n_joints=2, n_samples=30)
    cfg_other_seed = SimConfig(n_joints=2, n_samples=30, seed=999)
    a = SimAdapter(cfg_default).generate_episode(episode_id="det")
    b = SimAdapter(cfg_other_seed).generate_episode(episode_id="det")
    assert [s.as_row() for s in a.samples] == [s.as_row() for s in b.samples]


# -- RNG core: value semantics & boundary validation ----------------------------------


def test_value_identity_is_the_seed() -> None:
    """Two streams with the same seed are equal and hash equal; different seeds differ.

    The private ``Random`` is owned state, excluded from eq/hash — value identity is the
    seed, so a SeededRng can be used as a stable dict key / config value.
    """
    assert SeededRng(7) == SeededRng(7)
    assert hash(SeededRng(7)) == hash(SeededRng(7))
    assert SeededRng(7) != SeededRng(8)


def test_repr_is_byte_stable() -> None:
    """``repr`` must not leak the internal ``Random`` (its process-address repr would make
    a logged fixture non-byte-stable — the very thing this module exists to prevent)."""
    assert repr(SeededRng(7)) == "SeededRng(seed=7)"
    assert "Random" not in repr(SeededRng(7))


@pytest.mark.parametrize("bad", [True, False, 1.5, "7", None])
def test_non_int_seed_rejected_at_the_boundary(bad: object) -> None:
    """The invariant is enforced by the class itself, so a bad seed cannot slip through
    direct construction (bool is an int subclass; a float is a portability smell)."""
    with pytest.raises(ValueError, match="seed must be an int"):
        SeededRng(bad)  # type: ignore[arg-type]
