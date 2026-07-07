"""Deterministic generator for the committed ``pick_place.episode.txt`` golden sim episode.

This emits a SMALL, hand-checkable canonical **text row dump** of one scripted synthetic
episode driving the full deterministic sim stack B2-B5 built: seeded+noisy ``SimRobot``
proprio, scenario-driven ``sim-tactile`` tactile events, and scenario-driven ``sim-frames``
camera frame ids — all three streams tagged and merged onto ONE monotonic timeline. It is
the byte-exact regression baseline proving the whole stack stays reproducible across
machines/Python builds (the core P-B guarantee). Regenerate with::

    cd host
    python -m tests.fixtures.make_sim_fixture

Format: canonical text rows, NOT parquet. Parquet bytes are pyarrow-version-fragile
(metadata/encoder drift would break byte-identity on every dependency bump), so the golden
is a plain LF-terminated UTF-8 text file: ``#`` header comments, then one line per
:class:`~inhabit_can.pvt.PVTSample` as ``stream=<repr> <col>=<repr> ...`` with columns in
the FROZEN :data:`~inhabit_can.pvt.SAMPLE_COLUMNS` order. Float channels are quantized to
9 significant digits (:func:`_quant` — below the ~15-digit cross-libm agreement of
``math.sin``/``gauss``, so the bytes are identical on Windows AND Linux) then rendered with
``repr()`` and parsed back with :func:`ast.literal_eval`, so :func:`parse_golden`
reconstructs the exact canonical (:func:`quantize_sample`) values byte-for-byte.
``.gitattributes`` pins ``*.episode.txt`` to ``eol=lf`` so the committed bytes survive any
checkout's ``core.autocrlf``.

Merge order: rows are sorted by ``(timestamp_ns, stream_name)`` — timestamp order with the
stream name as the stable tie-break — so co-stamped samples from different modalities land
in one documented, deterministic order (no dict-order or insertion-order dependence).

Determinism: stdlib-only (NO numpy, NO pyarrow), no wall clock — the sensor sources use
their deterministic stepping clocks and ``SimRobot`` stamps ``start_ns + i*period_ns``.
Frozen contracts (``PVTSample``/``SAMPLE_COLUMNS``, contact tokens) are imported, never
reimplemented.
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from inhabit_can.pvt import SAMPLE_COLUMNS, PVTSample
from sensors.sim_scenario import SimFramesSource, SimTactileSource
from sim.robot import NoiseSpec, SimRobot
from sim.scenario import PICK_PLACE, ContactScenario

#: The committed scenario the episode is scripted by — the canonical happy path (B4's
#: golden, mirrored on disk as ``pick_place.scenario.json``). Total timeline: 1.8 s.
SCENARIO: ContactScenario = PICK_PLACE

#: The ONE seed for the episode. Feeds ``SimRobot``'s ``SeededRng`` (proprio noise) and is
#: passed to the scenario sources for constructor symmetry (they are fully scripted today).
SEED = 7

#: Shared epoch for all three streams (> 0 — never a zero timestamp). Sharing one epoch
#: makes co-stamped rows across modalities, so the merge tie-break is actually exercised.
START_NS = 1_000_000_000

#: Stream periods. Proprio and tactile tick together at 50 Hz (every proprio stamp collides
#: with a tactile stamp => tie-break on every tick); frames run at 25 Hz (collides with both
#: every other tick). Slow-ish rates keep the committed golden a few hundred lines.
PROPRIO_PERIOD_NS = 20_000_000  # 50 Hz
TACTILE_PERIOD_NS = 20_000_000  # 50 Hz
FRAME_PERIOD_NS = 40_000_000  # 25 Hz

#: Proprio ticks: exactly the scenario timeline at the proprio rate, so all three streams
#: cover the same [0, total_duration) window (the scenario sources self-exhaust there).
N_PROPRIO_TICKS = round(SCENARIO.total_duration_s * 1e9) // PROPRIO_PERIOD_NS

#: Identity stamped onto every row.
EPISODE_ID = "golden_sim"
TASK_LABEL = SCENARIO.name

#: Per-channel proprio noise (B3): small, non-zero sigmas on every channel so the golden
#: actually locks the seeded noise path (all-zero noise would silently stop covering it).
NOISE = NoiseSpec(
    joint_angle_sigma=0.01,
    joint_velocity_sigma=0.02,
    motor_current_sigma=0.005,
    estimated_torque_sigma=0.004,
)

FIXTURE_PATH = Path(__file__).with_name("pick_place.episode.txt")


def build_streams() -> list[tuple[str, list[PVTSample]]]:
    """Generate the three tagged streams, each strictly monotonic in ``timestamp_ns``.

    Single source of truth for the episode content: the writer, the byte-identity test, and
    the parse-back invariants all derive from this. Returned in a fixed literal order
    (proprio, tactile, frames) — the merge re-orders by timestamp anyway.
    """
    robot = SimRobot(
        dof=1,  # one joint => one row per tick => per-stream stamps stay strictly monotonic
        trajectory="sine",
        seed=SEED,
        noise=NOISE,
        start_ns=START_NS,
        period_ns=PROPRIO_PERIOD_NS,
        episode_id=EPISODE_ID,
        task_label=TASK_LABEL,
    )
    proprio = robot.generate(N_PROPRIO_TICKS)
    tactile_src = SimTactileSource(
        scenario=SCENARIO,
        seed=SEED,
        episode_id=EPISODE_ID,
        task_label=TASK_LABEL,
        start_ns=START_NS,
        period_ns=TACTILE_PERIOD_NS,
    )
    with tactile_src:  # keep the concrete type: its stream() yields PVTSample, not object
        tactile = list(tactile_src.stream())
    frames_src = SimFramesSource(
        scenario=SCENARIO,
        seed=SEED,
        episode_id=EPISODE_ID,
        task_label=TASK_LABEL,
        start_ns=START_NS,
        period_ns=FRAME_PERIOD_NS,
    )
    with frames_src:
        frames = list(frames_src.stream())
    return [("proprio", proprio), ("tactile", tactile), ("frames", frames)]


def merge_rows(streams: list[tuple[str, list[PVTSample]]]) -> list[tuple[str, PVTSample]]:
    """Tag and merge the streams in ``(timestamp_ns, stream_name)`` order.

    Timestamp order first (the one-timeline invariant); the stream NAME is the documented,
    stable tie-break for co-stamped rows — deterministic and machine-independent, unlike
    insertion order or object identity.
    """
    tagged = [(name, s) for name, samples in streams for s in samples]
    tagged.sort(key=lambda row: (row[1].timestamp_ns, row[0]))
    return tagged


def _quant(value: float) -> float:
    """Quantize a float to 9 significant digits — the cross-platform canonical value.

    Failure mode this prevents: **platform-libm last-ULP drift.** ``math.sin``/``gauss``
    agree across libms to ~15 significant digits but may differ in the final ULP, so a
    full-precision ``repr()`` golden regenerated on Windows differed from the Linux/CI one
    by one trailing digit. Rounding to 9 significant digits (far below the ~15-digit
    agreement) yields the bit-identical double — and therefore the identical shortest
    ``repr()`` — on every platform. Idempotent: quantizing a quantized value is a no-op.
    """
    return float(f"{value:.9g}")


def quantize_sample(sample: PVTSample) -> PVTSample:
    """The canonical (platform-stable) form of a sample: float channels quantized.

    ONE canonicalization shared by the renderer and the parse-back comparison, so the
    committed bytes and the in-memory expectation can never disagree about precision.
    Explicit field list (not reflection) so mypy verifies the frozen float channels.
    """
    return replace(
        sample,
        joint_angle=_quant(sample.joint_angle),
        joint_velocity=_quant(sample.joint_velocity),
        motor_current=_quant(sample.motor_current),
        estimated_torque=_quant(sample.estimated_torque),
    )


def render_row(stream: str, sample: PVTSample) -> str:
    """One canonical line: ``stream=<repr>`` then every FROZEN column as ``name=<repr>``.

    Values are rendered from :func:`quantize_sample` — floats rounded to 9 significant
    digits (platform-stable, see :func:`_quant`) then ``repr()``'d (shortest round-tripping
    form), so :func:`ast.literal_eval` inverts every value exactly on any platform. Column
    order is :data:`SAMPLE_COLUMNS` — frozen, never dict order.
    """
    row = quantize_sample(sample).as_row()
    parts = [f"stream={stream!r}"] + [f"{c}={row[c]!r}" for c in SAMPLE_COLUMNS]
    return " ".join(parts)


def render_golden() -> str:
    """The full canonical text: ``#`` header (with the regeneration one-liner) + rows + LF.

    Single source of truth for the on-disk bytes; the byte-identity test compares this
    directly against the committed file.
    """
    streams = build_streams()
    rows = merge_rows(streams)
    counts = " ".join(f"{name}={len(samples)}" for name, samples in streams)
    header = [
        "# Inhabit golden sim episode — canonical PVT row dump (byte-exact regression "
        "baseline).",
        "# regenerate: cd host && python -m tests.fixtures.make_sim_fixture",
        f"# scenario={SCENARIO.name!r} seed={SEED} start_ns={START_NS} "
        f"duration_s={SCENARIO.total_duration_s!r}",
        f"# periods_ns: proprio={PROPRIO_PERIOD_NS} tactile={TACTILE_PERIOD_NS} "
        f"frames={FRAME_PERIOD_NS}",
        f"# rows={len(rows)} ({counts}); order: (timestamp_ns, stream); "
        "values: repr() of 9-sig-digit-quantized floats",
    ]
    lines = header + [render_row(stream, sample) for stream, sample in rows]
    return "\n".join(lines) + "\n"


def parse_golden(text: str) -> list[tuple[str, PVTSample]]:
    """Invert :func:`render_golden`: the tagged, ordered ``PVTSample`` rows of a dump.

    Skips ``#`` header/comment lines; each row line is ``key=<python literal>`` tokens
    (values never contain spaces — the ids/labels/tokens in the episode are space-free by
    construction). Values are rebuilt with :func:`ast.literal_eval` (exact for repr'd
    floats/ints/strings/None) and fed through :meth:`PVTSample.from_row` so schema
    migrations apply exactly as they would on a real read-back path.
    """
    rows: list[tuple[str, PVTSample]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        # Explicit value type: tokens parse to arbitrary literals (int/float/str/None), so the
        # dict holds ``object``; from_row takes Mapping[str, Any], and the stream tag is
        # isinstance-narrowed to str below — keeps the loop assignments type-safe.
        fields: dict[str, object] = {}
        for token in line.split(" "):
            key, sep, value = token.partition("=")
            if not sep:
                raise ValueError(f"malformed golden token {token!r} in line {line!r}")
            fields[key] = ast.literal_eval(value)
        stream = fields.pop("stream")
        if not isinstance(stream, str):
            raise ValueError(f"golden row has non-string stream tag {stream!r}")
        rows.append((stream, PVTSample.from_row(fields)))
    return rows


def write_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Write the deterministic golden dump to ``path`` with LF EOLs on every platform.

    Binary write with explicit ``\\n`` (mirroring ``make_scenario_fixture``) so text-mode
    CRLF on Windows can never leak into the committed bytes; ``.gitattributes`` pins
    ``*.episode.txt`` to ``eol=lf`` to match.
    """
    path.write_bytes(render_golden().encode("utf-8"))
    return path


if __name__ == "__main__":
    out = write_fixture()
    n_rows = len(parse_golden(out.read_text(encoding="utf-8")))
    print(f"wrote {out} ({n_rows} rows, scenario {SCENARIO.name!r}, seed {SEED})")
