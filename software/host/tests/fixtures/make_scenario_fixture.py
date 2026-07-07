"""Deterministic generator for the committed ``pick_place.scenario.json`` golden fixture.

This emits a canonical JSON dump of the built-in :data:`sim.scenario.PICK_PLACE` contact
scenario — the exact bytes B5 and any downstream consumer will parse — so a test can assert
the on-disk golden never silently drifts from the spec that produced it. Regenerate with::

    cd host
    python -m tests.fixtures.make_scenario_fixture

The scenario itself is a *value* (frozen dataclass) whose ``dumps`` uses stdlib :mod:`json`
only (no numpy — a hard P-B invariant), so the bytes are identical on every platform. We
normalize the trailing EOL to a single ``\\n`` after writing (mirroring
``make_sample_canlog``); ``.gitattributes`` pins ``*.scenario.json`` to ``eol=lf`` to match, so
the committed bytes and the byte-identity round-trip test are stable regardless of
``core.autocrlf``.

Frozen contracts are untouched: this only serializes an existing scenario value.
"""
from __future__ import annotations

from pathlib import Path

from sim.scenario import PICK_PLACE, ContactScenario

#: The built-in scenario the golden captures. ``pick_place`` is the canonical happy path
#: (approach -> grasp -> release -> settle); small and hand-checkable.
GOLDEN_SCENARIO: ContactScenario = PICK_PLACE

FIXTURE_PATH = Path(__file__).with_name("pick_place.scenario.json")


def render_golden(scenario: ContactScenario = GOLDEN_SCENARIO) -> str:
    """The canonical JSON text for ``scenario`` plus exactly one trailing newline.

    Single source of truth for both the writer and the byte-identity test, so the expected
    bytes are derived from the spec, never hand-copied. ``dumps`` pins ``indent=2`` and
    insertion order; the trailing newline is added here (POSIX text convention).
    """
    return scenario.dumps() + "\n"


def write_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Write the deterministic golden JSON to ``path`` with an LF EOL on every platform.

    Writing in binary with an explicit ``\\n`` (rather than text mode, which would emit CRLF
    on Windows) keeps the committed bytes platform-independent — the byte-identity regression
    test depends on it.
    """
    path.write_bytes(render_golden().encode("utf-8"))
    return path


if __name__ == "__main__":
    out = write_fixture()
    print(f"wrote {out} ({len(GOLDEN_SCENARIO.phases)} phases, scenario {GOLDEN_SCENARIO.name!r})")
