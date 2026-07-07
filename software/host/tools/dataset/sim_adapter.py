"""SimAdapter — synthetic episode generator for testing the PVT data pipeline.

Produces realistic-looking PVT episodes (sinusoidal joint motion, configurable
noise/jitter) without any hardware. Imports PVTSample FROZEN from inhabit_can.pvt.

Determinism (P-B invariant): randomness flows through exactly ONE seeded stream,
:class:`sim.rng.SeededRng`, built from ``SimConfig.seed`` (stdlib ``random.Random``, **no
numpy**). Prevents non-portable, non-byte-stable fixtures across machines/CI. In B1 the
seed is *plumbed but not yet consumed* by the sample math — the sweep is still the pure
closed-form ``math.sin`` — so the default-config output is byte-identical to before; B3
starts drawing per-channel noise from this stream.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from inhabit_can.pvt import Episode, PVTSample
from sim.rng import SeededRng


@dataclass
class SimConfig:
    """Parameters for a synthetic episode."""

    n_joints: int = 3
    n_samples: int = 100
    frequency_hz: float = 100.0
    amplitude_rad: float = 1.0
    phase_offsets: list[float] = field(default_factory=list)
    task_label: str | None = "sim_reach"
    start_ns: int = 1_000_000_000
    # Seeds the ONE synthetic RNG stream (see ``sim.rng.SeededRng``). Defaulted so existing
    # callers/goldens are unaffected; in B1 it is plumbed but not consumed, so changing it
    # does NOT change emitted samples yet (noise lands in B3). Type-checked in ``validate``.
    seed: int = 0

    def rng(self) -> SeededRng:
        """Fresh seeded RNG for this config — the single randomness source for generation.

        Each call returns a NEW stream built from ``seed`` so a generator can re-run and
        replay the identical sequence (reproducibility survives reuse). Reserved for B3's
        per-channel noise; unused by today's pure ``math.sin`` sweep.
        """
        return SeededRng(self.seed)

    def validate(self) -> None:
        """Reject invalid configs before sample generation.

        Failure modes guarded: ``frequency_hz <= 0`` would raise an opaque
        ``ZeroDivisionError`` at the period computation, and a non-empty
        ``phase_offsets`` shorter than ``n_joints`` would raise ``IndexError``
        mid-loop. Fail fast with a clear message instead.
        """
        if self.n_joints < 0 or self.n_samples < 0:
            raise ValueError("n_joints and n_samples must be non-negative")
        # ``random.Random`` accepts any int seed, but a bool (``isinstance(True, int)``) or a
        # float slips past mypy at a call site and gives a surprising/non-reproducible seed.
        # Fail loud so fixtures stay portable.
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an int (bool is not accepted)")
        if self.frequency_hz <= 0:
            raise ValueError("frequency_hz must be greater than 0")
        if int(1e9 / self.frequency_hz) < 1:
            raise ValueError("frequency_hz must yield at least 1 ns between samples")
        if self.phase_offsets and len(self.phase_offsets) != self.n_joints:
            raise ValueError("phase_offsets must be empty or match n_joints")


class SimAdapter:
    """Generate synthetic PVT episodes for pipeline testing.

    Each call to ``generate_episode`` produces an ``Episode`` with deterministic,
    sinusoidal joint trajectories — no hardware required.
    """

    def __init__(self, config: SimConfig | None = None) -> None:
        self.config = config or SimConfig()

    def generate_episode(
        self,
        episode_id: str | None = None,
        config: SimConfig | None = None,
    ) -> Episode:
        cfg = config or self.config
        cfg.validate()
        eid = episode_id or f"sim_{uuid.uuid4().hex[:8]}"
        episode = Episode(episode_id=eid, task_label=cfg.task_label)

        # The ONE seeded randomness source for this episode. Built here so the seam is live
        # for B3's per-channel noise; deliberately NOT drawn from in B1 (no ``rng.*`` call
        # below), so with the default seed the emitted samples are byte-identical to before.
        _rng = cfg.rng()  # plumbed for B3's noise; deliberately unused (leading _) in B1.

        period_ns = int(1e9 / cfg.frequency_hz)
        phases = cfg.phase_offsets or [
            i * math.pi / max(cfg.n_joints, 1) for i in range(cfg.n_joints)
        ]

        for i in range(cfg.n_samples):
            t_ns = cfg.start_ns + i * period_ns
            t_sec = i / cfg.frequency_hz
            for j in range(cfg.n_joints):
                angle = cfg.amplitude_rad * math.sin(2 * math.pi * 0.5 * t_sec + phases[j])
                # Simple finite-difference velocity (rad/s)
                if i > 0:
                    prev_angle = cfg.amplitude_rad * math.sin(
                        2 * math.pi * 0.5 * (i - 1) / cfg.frequency_hz + phases[j]
                    )
                    velocity = (angle - prev_angle) * cfg.frequency_hz
                else:
                    velocity = 0.0

                episode.add(
                    PVTSample(
                        timestamp_ns=t_ns,
                        episode_id=eid,
                        chain_index=j,
                        joint_angle=angle,
                        joint_velocity=velocity,
                        task_label=cfg.task_label,
                    )
                )
        return episode
