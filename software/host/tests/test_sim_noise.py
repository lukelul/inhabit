"""Property + contract tests for B3 seeded proprio noise (``sim.robot.NoiseSpec``).

The failure mode under test is **unbounded / non-reproducible / cross-coupled noise**: noise that
wanders past a documented bound (unrealistic outliers that poison P-C alignment / P-D detection),
that differs run-to-run (non-diffable goldens), or where one channel's noise shifts another's draws
(reordering/adding a channel breaks byte-stability). B3's contract, pinned here:

* **zero-noise ≡ B2** — the default (all-zero) config is byte-identical to the noise-free path;
* **bounded** — every noisy value stays within ``±clamp_sigmas·sigma`` of its clean value;
* **per-channel independent** — raising one channel's sigma leaves other channels byte-identical;
* **deterministic** — same (seed, noise) => identical output; different seed (noise ON) => diverges;
* noise is **proprio-only** — the monotonic timestamp clock is never perturbed.
"""
from __future__ import annotations

import pytest

from sim.robot import NO_NOISE, NOISE_CHANNELS, NoiseSpec, SimRobot

# A non-trivial noise config: every channel active, distinct sigmas so a cross-channel leak
# would be visible.
_NOISY = NoiseSpec(
    joint_angle_sigma=0.05,
    joint_velocity_sigma=0.1,
    motor_current_sigma=0.02,
    estimated_torque_sigma=0.03,
    clamp_sigmas=3.0,
)


def _channel(sample: object, name: str) -> float:
    return float(getattr(sample, name))


# -- zero-noise back-compat (hard requirement) -------------------------------------------------


def test_default_is_no_noise() -> None:
    """The default SimRobot has noise disabled (so it is byte-identical to B2)."""
    assert SimRobot().noise is NO_NOISE
    assert not NO_NOISE.enabled


def test_zero_noise_is_byte_identical_regardless_of_seed() -> None:
    """With zero noise the seed cannot matter — output is the clean B2 trajectory for any seed.

    An explicit all-zero NoiseSpec must reproduce the default (NO_NOISE) output exactly, and two
    different seeds must be byte-identical (the RNG is never drawn from when disabled)."""
    default = SimRobot(dof=3, seed=1).generate(30)
    explicit_zero = SimRobot(dof=3, seed=1, noise=NoiseSpec()).generate(30)
    other_seed = SimRobot(dof=3, seed=999, noise=NoiseSpec()).generate(30)
    assert [s.as_row() for s in explicit_zero] == [s.as_row() for s in default]
    assert [s.as_row() for s in other_seed] == [s.as_row() for s in default]


# -- determinism (noise ON) --------------------------------------------------------------------


def test_noise_same_seed_converges() -> None:
    """Same (seed, noise) => byte-identical output across two fresh robots."""
    a = SimRobot(dof=3, seed=7, noise=_NOISY).generate(40)
    b = SimRobot(dof=3, seed=7, noise=_NOISY).generate(40)
    assert [s.as_row() for s in a] == [s.as_row() for s in b]


def test_noise_on_different_seed_diverges() -> None:
    """The inverse of B2's canary: with noise ON, different seeds DO change the output."""
    a = SimRobot(dof=3, seed=1, noise=_NOISY).generate(40)
    b = SimRobot(dof=3, seed=2, noise=_NOISY).generate(40)
    assert [s.as_row() for s in a] != [s.as_row() for s in b]


def test_noise_sample_at_is_pure() -> None:
    """Noise draw is keyed on (seed, channel, index, joint) — not call order — so sample_at is
    pure: repeated calls for the same cell return the identical noisy value."""
    robot = SimRobot(dof=2, seed=5, noise=_NOISY)
    assert robot.sample_at(9, 1).as_row() == robot.sample_at(9, 1).as_row()


# -- bounded (the key B3 property) -------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 42, 12345])
def test_noise_stays_within_clamp_bound(seed: int) -> None:
    """Every noisy channel value is within ``±clamp_sigmas·sigma`` of its clean value.

    Compare a noisy robot against the clean (zero-noise) robot of the same config, cell by cell;
    the per-channel deviation must never exceed the documented clamp — no fat-tail outliers."""
    clean = SimRobot(dof=4, seed=seed).generate(60)
    noisy = SimRobot(dof=4, seed=seed, noise=_NOISY).generate(60)
    assert len(clean) == len(noisy)
    eps = 1e-9
    for c, n in zip(clean, noisy, strict=True):
        for name in NOISE_CHANNELS:
            bound = _NOISY.sigma(name) * _NOISY.clamp_sigmas
            assert abs(_channel(n, name) - _channel(c, name)) <= bound + eps, name


# -- per-channel independence ------------------------------------------------------------------


def test_per_channel_independence() -> None:
    """Raising one channel's sigma leaves every OTHER channel byte-identical.

    Each channel draws from its own spawn(channel) sub-stream, so adding motor_current noise must
    not shift joint_angle/joint_velocity/estimated_torque draws."""
    only_angle = NoiseSpec(joint_angle_sigma=0.05)
    angle_and_current = NoiseSpec(joint_angle_sigma=0.05, motor_current_sigma=0.02)
    a = SimRobot(dof=3, seed=3, noise=only_angle).generate(30)
    b = SimRobot(dof=3, seed=3, noise=angle_and_current).generate(30)
    for sa, sb in zip(a, b, strict=True):
        # Untouched channels are identical; only motor_current differs.
        assert _channel(sa, "joint_angle") == _channel(sb, "joint_angle")
        assert _channel(sa, "joint_velocity") == _channel(sb, "joint_velocity")
        assert _channel(sa, "estimated_torque") == _channel(sb, "estimated_torque")
    # motor_current actually changed for at least one sample (sanity: the knob does something).
    assert any(
        _channel(sa, "motor_current") != _channel(sb, "motor_current")
        for sa, sb in zip(a, b, strict=True)
    )


# -- noise never touches the clock -------------------------------------------------------------


def test_noise_does_not_perturb_timestamps() -> None:
    """Noise is proprio-only: the monotonic timestamp clock is identical with/without noise."""
    clean = SimRobot(dof=2, seed=8).generate(20)
    noisy = SimRobot(dof=2, seed=8, noise=_NOISY).generate(20)
    assert [s.timestamp_ns for s in noisy] == [s.timestamp_ns for s in clean]


# -- fail-loud validation ----------------------------------------------------------------------


@pytest.mark.parametrize("channel", list(NOISE_CHANNELS))
def test_negative_sigma_rejected(channel: str) -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        NoiseSpec(**{f"{channel}_sigma": -0.1})


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_non_positive_clamp_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="clamp_sigmas must be > 0"):
        NoiseSpec(clamp_sigmas=bad)
