"""B6 — golden sim episode fixture: byte-identity + parse-back invariants.

Locks the P-B byte-stability guarantee end-to-end: the committed
``tests/fixtures/pick_place.episode.txt`` must

* stay byte-identical to what ``tests.fixtures.make_sim_fixture`` regenerates (so ANY
  behavioural drift in SimRobot/NoiseSpec/SeededRng, the scenario spec, or the B5
  sim-tactile/sim-frames sources shows up as a loud byte diff, never a silent dataset
  change), and
* parse back into FROZEN ``PVTSample`` rows honouring the episode invariants: tactile
  tokens within the frozen vocabulary, monotonic unique camera frame ids, strictly
  monotonic per-stream timestamps, and the documented ``(timestamp_ns, stream)`` merge
  order.

Regenerate the golden (only after an INTENDED sim-stack change) with::

    cd host
    python -m tests.fixtures.make_sim_fixture
"""
from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import get_type_hints

import pytest

from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample
from sim.scenario import CONTACT_KINDS
from tests.fixtures.make_sim_fixture import (
    FIXTURE_PATH,
    N_PROPRIO_TICKS,
    SCENARIO,
    _quant,
    build_streams,
    merge_rows,
    parse_golden,
    quantize_sample,
    render_golden,
    write_fixture,
)


def _committed_rows() -> list[tuple[str, PVTSample]]:
    """Parse the committed golden bytes (UTF-8, LF) into tagged samples."""
    return parse_golden(FIXTURE_PATH.read_bytes().decode("utf-8"))


def test_quantize_sample_covers_every_float_field() -> None:
    """Drift guard: ``quantize_sample`` canonicalizes EVERY float-typed PVTSample field.

    ``quantize_sample`` hardcodes its field list (explicit, mypy-checkable — the house
    style). If the frozen schema ever gains a float field via a versioned decision record,
    a stale list would silently skip it and the golden would go platform-unstable again.
    This discovers the float fields from the class itself and asserts each one actually
    comes back quantized — behavioral, so it cannot drift alongside the list it guards.
    """
    float_fields = {n for n, t in get_type_hints(PVTSample).items() if t is float}
    assert float_fields  # sanity: the schema has float channels
    raw = 0.12345678912345678  # 17 sig digits — visibly changed by 9-sig-digit quantization
    base = PVTSample(timestamp_ns=1, episode_id="e", chain_index=0, joint_angle=raw)
    # Explicit kwargs (mypy-checkable) seed every KNOWN float field with `raw`; a float
    # field added later arrives at its default here, so the discovery loop below still
    # visits it and fails loud until quantize_sample AND this seeding are updated.
    sample = replace(
        base, joint_velocity=raw, motor_current=raw, estimated_torque=raw
    )
    quantized = quantize_sample(sample)
    for name in sorted(float_fields):
        assert getattr(quantized, name) == _quant(raw), f"unquantized float field: {name}"
        assert getattr(quantized, name) != raw  # the guard really changed the value


# -- byte identity ----------------------------------------------------------------------------


def test_golden_fixture_is_committed() -> None:
    """The golden episode must exist on disk as a committed regression baseline."""
    assert FIXTURE_PATH.exists(), f"missing committed golden {FIXTURE_PATH}"


def test_regenerated_golden_is_byte_identical(tmp_path: Path) -> None:
    """Regenerating the episode is deterministic — byte-identical to the committed copy.

    Runs the generator in-process (same function the CLI entry point calls) into a temp
    file and compares raw bytes. Any drift in the sim stack or the canonical rendering
    changes the bytes and fails loudly; the fix is either reverting the regression or
    consciously regenerating the golden (see module docstring).
    """
    regenerated = write_fixture(tmp_path / "regen.episode.txt")
    assert regenerated.read_bytes() == FIXTURE_PATH.read_bytes()


def test_golden_bytes_are_lf_utf8() -> None:
    """The committed bytes are LF-only UTF-8 (the .gitattributes-pinned canonical form)."""
    raw = FIXTURE_PATH.read_bytes()
    assert b"\r" not in raw, "golden must be LF-only (see fixtures/.gitattributes)"
    text = raw.decode("utf-8")  # raises on a non-UTF-8 golden
    assert text.endswith("\n") and not text.endswith("\n\n")
    # The regeneration one-liner is documented in the header, next to the bytes it rebuilds.
    assert "python -m tests.fixtures.make_sim_fixture" in text


def test_render_golden_matches_committed_text() -> None:
    """The in-memory canonical text (the writer's single source of truth) == committed."""
    assert render_golden() == FIXTURE_PATH.read_bytes().decode("utf-8")


# -- parse-back: the golden is real data, not just stable bytes ------------------------------


def test_golden_parses_back_to_expected_streams() -> None:
    """The golden parses into exactly the CANONICAL samples the sim stack generates.

    Both sides go through the ONE canonicalization (:func:`quantize_sample` — 9-sig-digit
    floats, the platform-stable form the renderer wrote), so this equality holds on any
    libm; comparing against full-precision values would re-introduce the last-ULP skew the
    quantization exists to remove.
    """
    rows = _committed_rows()
    expected = [(name, quantize_sample(s)) for name, s in merge_rows(build_streams())]
    assert rows == expected
    streams = ("proprio", "tactile", "frames")
    counts = {name: sum(1 for s, _ in rows if s == name) for name in streams}
    assert counts["proprio"] == N_PROPRIO_TICKS
    assert counts["tactile"] > 0 and counts["frames"] > 0
    assert {s for s, _ in rows} == {"proprio", "tactile", "frames"}


def test_golden_tactile_tokens_are_frozen_vocabulary() -> None:
    """Every non-None tactile_event is a FROZEN contact token, and only tactile emits them."""
    rows = _committed_rows()
    tokens = {r.tactile_event for s, r in rows if r.tactile_event is not None}
    assert tokens <= set(CONTACT_KINDS)
    assert tokens, "episode must exercise at least one contact token"
    assert all(s == "tactile" for s, r in rows if r.tactile_event is not None)


def test_golden_camera_frame_ids_monotonic_unique() -> None:
    """Frame ids appear only on the frames stream, strictly increasing and unique."""
    rows = _committed_rows()
    tagged = [r.camera_frame_id for s, r in rows if s == "frames"]
    frame_ids = [fid for fid in tagged if fid is not None]
    assert len(frame_ids) == len(tagged), "frames stream must stamp every camera_frame_id"
    assert frame_ids == sorted(frame_ids) and len(set(frame_ids)) == len(frame_ids)
    assert all(r.camera_frame_id is None for s, r in rows if s != "frames")


def test_golden_timestamps_strictly_monotonic_per_stream() -> None:
    """Within each stream, timestamps strictly increase (the one-clock invariant)."""
    rows = _committed_rows()
    for name in ("proprio", "tactile", "frames"):
        stamps = [r.timestamp_ns for s, r in rows if s == name]
        assert all(a < b for a, b in pairwise(stamps))
        assert stamps[0] > 0  # never a zero timestamp


def test_golden_merge_order_is_timestamp_then_stream() -> None:
    """Rows are globally sorted by (timestamp_ns, stream) — the documented tie-break."""
    rows = _committed_rows()
    keys = [(r.timestamp_ns, s) for s, r in rows]
    assert keys == sorted(keys)
    # Co-stamped rows exist (proprio and tactile share an epoch+period), so the stream-name
    # tie-break is actually exercised by this golden, not vacuously true.
    stamps = [k[0] for k in keys]
    assert len(stamps) != len(set(stamps))


def test_golden_rows_carry_schema_and_episode_identity() -> None:
    """Every row carries the frozen schema version and the episode/task identity."""
    for _, r in _committed_rows():
        assert r.schema_version == PVT_SCHEMA_VERSION
        assert r.episode_id == "golden_sim"
        assert r.task_label == SCENARIO.name


# -- parser fail-loud paths -------------------------------------------------------------------


def test_parse_golden_rejects_malformed_token() -> None:
    """A row token with no '=' is a corrupted golden — loud ValueError, not a mis-parse."""
    with pytest.raises(ValueError, match="malformed golden token"):
        parse_golden("stream='proprio' garbage\n")


def test_parse_golden_rejects_non_string_stream() -> None:
    """A non-string stream tag is a corrupted golden — loud ValueError."""
    with pytest.raises(ValueError, match="non-string stream tag"):
        parse_golden("stream=3 timestamp_ns=1 episode_id='e' chain_index=0 joint_angle=0.0\n")
