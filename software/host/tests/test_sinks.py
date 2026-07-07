"""Tests for host/logger/sinks/ — EpisodeSink ABC, registry, parquet-atomic + inmem.

Headless, deterministic, no hardware. Covers (A7 DoD):
  * parquet sink round-trip: ingest seeded samples -> finalize -> read back -> assert-equal;
  * inmem sink: ingest -> finalize -> samples present;
  * the PR #25 data-integrity gates STILL trigger THROUGH the new sink layer:
      - corrupt-checksum frames quarantined (via the JointPodState path the parquet sink wraps),
      - non-monotonic / backwards-clock episode quarantined,
      - NaN/inf joint value rejected (never reaches parquet/inmem);
  * registry register / make / unknown -> ValueError / duplicate-guard;
  * list_episode_sinks sorted and includes both built-ins;
  * a parametrized conformance-style suite over EVERY registered sink (open/ingest/finalize
    invariants + context-manager + double-open/finalize guards). A3 generalizes this later.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from inhabit_can.pvt import PVT_SCHEMA_VERSION, JointPodState, PVTSample
from inhabit_core import Registry
from logger import (
    SINK_CONTRACT_VERSION,
    EpisodeRecorder,
    EpisodeSink,
    InMemorySink,
    ParquetAtomicSink,
    QuarantineError,
    SinkResult,
    list_episode_sinks,
    make_episode_sink,
    read_episode,
)

PERIOD_NS = 10_000_000  # 100 Hz, matches the recorder's documented budget

# --- helpers ---------------------------------------------------------------


def _sample(
    i: int,
    *,
    stamp_ns: int | None = None,
    episode_id: str = "ep",
    angle: float | None = None,
) -> PVTSample:
    """A clean, periodic PVT row at 100 Hz with a deterministic angle."""
    return PVTSample(
        timestamp_ns=i * PERIOD_NS if stamp_ns is None else stamp_ns,
        episode_id=episode_id,
        chain_index=3,
        joint_angle=math.sin(i / 10.0) if angle is None else angle,
        joint_velocity=0.01 * i,
        motor_current=0.1,
        task_label="insert_connector",
    )


def _clean_samples(n: int, *, episode_id: str = "ep") -> list[PVTSample]:
    return [_sample(i, episode_id=episode_id) for i in range(n)]


# --- parquet-atomic: round-trip -------------------------------------------


def test_parquet_sink_roundtrip(tmp_path: Path) -> None:
    """ingest seeded samples -> finalize -> read back -> structural + numerical equality."""
    samples = _clean_samples(50, episode_id="demo_round")
    sink = make_episode_sink(
        "parquet-atomic", out_dir=tmp_path, episode_id="demo_round", task_label="insert_connector"
    )
    sink.open()
    for s in samples:
        sink.ingest(s)
    result = sink.finalize()

    assert result.accepted is True
    assert result.path is not None and result.path.exists()
    assert result.n_samples == 50
    assert result.reasons == ()

    episode_out, meta = read_episode(result.path)
    assert episode_out.episode_id == "demo_round"
    assert episode_out.task_label == "insert_connector"
    assert len(episode_out) == 50
    for a, b in zip(samples, episode_out.samples, strict=True):
        assert a.timestamp_ns == b.timestamp_ns
        assert a.chain_index == b.chain_index
        assert a.joint_angle == pytest.approx(b.joint_angle, rel=0, abs=0)
        assert a.episode_id == b.episode_id
        assert a.task_label == b.task_label
        assert a.schema_version == b.schema_version == PVT_SCHEMA_VERSION
    # provenance travels in the footer (the recorder stamped it; the sink preserved it)
    assert meta["episode_id"] == "demo_round"
    assert meta["jitter_stats"]["n_samples"] == 50
    assert meta["contact_detector_version"]


def test_parquet_sink_context_manager_finalizes(tmp_path: Path) -> None:
    """A clean `with` block finalizes automatically and the verdict is on .result."""
    with make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="cm_ep") as sink:
        for s in _clean_samples(30, episode_id="cm_ep"):
            sink.ingest(s)
    assert sink.result is not None
    assert sink.result.accepted is True
    assert (tmp_path / "cm_ep.parquet").exists()


def test_parquet_sink_exception_in_block_writes_nothing(tmp_path: Path) -> None:
    """An exception inside `with` abandons the episode WITHOUT committing a half-write."""
    with pytest.raises(RuntimeError, match="boom"):
        with make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="crash_ep") as sink:
            for s in _clean_samples(10, episode_id="crash_ep"):
                sink.ingest(s)
            raise RuntimeError("boom")
    assert sink.result is None  # finalize never ran
    assert not (tmp_path / "crash_ep.parquet").exists()  # nothing in the dataset


# --- inmem: round-trip -----------------------------------------------------


def test_inmem_sink_collects_samples() -> None:
    sink = make_episode_sink("inmem", episode_id="m0", task_label="grasp")
    sink.open()
    samples = _clean_samples(7, episode_id="m0")
    for s in samples:
        sink.ingest(s)
    result = sink.finalize()

    assert result.accepted is True
    assert result.n_samples == 7
    assert result.path is None  # purely in-memory, no on-disk location
    assert isinstance(sink, InMemorySink)
    assert sink.samples == samples
    assert sink.episode is not None
    assert sink.episode.episode_id == "m0"
    assert sink.episode.task_label == "grasp"
    assert len(sink.episode) == 7


def test_inmem_sink_samples_property_is_a_copy() -> None:
    sink = InMemorySink(episode_id="m1")  # concrete type: exercises the read-back accessors
    sink.open()
    sink.ingest(_sample(0, episode_id="m1"))
    sink.finalize()
    got = sink.samples
    got.clear()  # mutating the returned list must not touch the sink's buffer
    assert len(sink.samples) == 1


# --- #25 gates STILL trigger THROUGH the sink layer ------------------------


def test_nan_joint_value_rejected_by_parquet_sink(tmp_path: Path) -> None:
    """A NaN joint value must NEVER reach parquet: the recorder's gate fires via the sink.

    The dropped frame leaves a one-period time hole; the recorder honestly surfaces that as
    a jitter dropout and quarantines the episode (it does not paper over missing data). The
    point proven here: the NaN never lands in the dataset AND the gate is reachable through
    the new sink seam.
    """
    sink = make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="nan_ep")
    sink.open()
    for i in range(20):
        angle = float("nan") if i == 5 else math.sin(i / 10.0)
        sink.ingest(_sample(i, episode_id="nan_ep", angle=angle))
    result = sink.finalize()
    assert result.detail["dropped_nonfinite"] == 1  # the NaN was caught at the door
    assert result.n_samples == 19  # excluded from the committed timeline
    # the hole is surfaced (honest), so the episode is quarantined, not silently exported
    assert result.accepted is False
    assert not (tmp_path / "nan_ep.parquet").exists()


def test_inf_joint_value_rejected_keeps_episode_clean(tmp_path: Path) -> None:
    """An inf on a sample we can afford to lose without a timing hole: episode still exports,
    proving the gate drops the bad value without corrupting the rest of the dataset."""
    sink = make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="inf_ep")
    sink.open()
    # 40 clean samples, then one extra inf with a timestamp that does NOT create a gap
    for i in range(40):
        sink.ingest(_sample(i, episode_id="inf_ep"))
    sink.ingest(_sample(40, episode_id="inf_ep", angle=float("inf")))  # dropped, no gap created
    result = sink.finalize()
    assert result.detail["dropped_nonfinite"] == 1
    assert result.n_samples == 40
    assert result.accepted is True  # the inf was dropped; the rest is a clean in-budget episode
    episode_out, _ = read_episode(result.path)  # type: ignore[arg-type]
    assert all(math.isfinite(s.joint_angle) for s in episode_out.samples)


def test_nan_rejected_by_inmem_sink() -> None:
    """The NaN/inf gate is a property of the data contract, not the backend: inmem drops too."""
    sink = make_episode_sink("inmem", episode_id="m_nan")
    sink.open()
    sink.ingest(_sample(0, episode_id="m_nan", angle=float("nan")))
    sink.ingest(_sample(1, episode_id="m_nan", angle=1.0))
    sink.ingest(_sample(2, episode_id="m_nan", angle=float("-inf")))
    result = sink.finalize()
    assert result.n_samples == 1
    assert result.detail["dropped_nonfinite"] == 2
    assert isinstance(sink, InMemorySink)
    assert all(math.isfinite(s.joint_angle) for s in sink.samples)


def test_backwards_clock_quarantined_through_parquet_sink(tmp_path: Path) -> None:
    """A non-monotonic (backwards) clock blows the budget and is quarantined via the sink.

    Nothing lands in the dataset dir; only a quarantine sidecar documents why. This is the
    #25 monotonic-clock gate proven reachable through the EpisodeSink layer.
    """
    sink = make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="back_ep")
    sink.open()
    stamps = [0, PERIOD_NS, PERIOD_NS // 2, 3 * PERIOD_NS]  # third interval goes backwards
    for i, t in enumerate(stamps):
        sink.ingest(_sample(i, stamp_ns=t, episode_id="back_ep"))
    result = sink.finalize()
    assert result.accepted is False
    assert any("backwards" in r for r in result.reasons)
    assert not (tmp_path / "back_ep.parquet").exists()
    sidecar = tmp_path / "quarantine" / "back_ep.quarantine.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any("backwards" in r for r in payload["reasons"])


def test_over_budget_jitter_quarantined_through_parquet_sink(tmp_path: Path) -> None:
    sink = make_episode_sink("parquet-atomic", out_dir=tmp_path, episode_id="jit_ep")
    sink.open()
    for i in range(40):
        wobble = 5_000_000 if i % 2 else 0  # 5 ms spike >> 2 ms p99 budget
        sink.ingest(_sample(i, stamp_ns=i * PERIOD_NS + wobble, episode_id="jit_ep"))
    result = sink.finalize()
    assert result.accepted is False
    assert any("jitter p99" in r for r in result.reasons)
    assert not (tmp_path / "jit_ep.parquet").exists()


def test_corrupt_checksum_quarantined_through_recorder_wrapped_by_sink(tmp_path: Path) -> None:
    """The corrupt-checksum gate is a JointPodState concept; prove it still fires in the
    EXACT recorder the parquet sink wraps.

    ``checksum_valid`` does not exist on a PVTSample (it is enforced upstream, on the raw
    decoded-CAN frame). The parquet sink delegates to EpisodeRecorder, so a corrupt frame
    fed on the JointPodState path is still dropped and the episode's hole still quarantines
    it — the gate the sink relies on is intact, not weakened.
    """
    rec = EpisodeRecorder("csum_ep", tmp_path)
    for i in range(20):
        rec.ingest(
            JointPodState(
                node_id=3,
                chain_index=3,
                angle_raw_adc=1000 + i,
                angle_millideg=i,
                angle_rad=math.sin(i / 10.0),
                status_flags=0,
                checksum_valid=(i != 5),  # one corrupt frame
                schema_version=1,
                header_stamp_ns=i * PERIOD_NS,
            )
        )
    result = rec.finalize()
    assert rec.drop_counts["dropped_checksum"] == 1  # the gate caught the corrupt frame
    assert result.stats.n_samples == 19  # excluded from the timeline


def test_recorder_ingest_sample_nan_gate_is_unconditional(tmp_path: Path) -> None:
    """The additive ingest_sample seam the sink uses must reject NaN exactly like ingest()."""
    rec = EpisodeRecorder("seam_ep", tmp_path)
    rec.ingest_sample(_sample(0, episode_id="seam_ep", angle=float("nan")))
    rec.ingest_sample(_sample(1, episode_id="seam_ep", angle=1.0))
    assert rec.drop_counts["dropped_nonfinite"] == 1
    assert len(rec.episode) == 1


def test_recorder_ingest_sample_rebinds_foreign_provenance(tmp_path: Path) -> None:
    """A sample carrying a foreign episode_id/task_label is re-stamped to THIS recorder.

    The recorder is the single authority for an episode's provenance — ``ingest`` always
    stamps episode_id/task_label from the recorder, so ``ingest_sample`` must not let a
    mis-wired or reused row persist with mismatched metadata in the wrong file. The stored
    row carries the recorder's values; the caller's own object is left untouched (copy, not
    in-place mutation).
    """
    rec = EpisodeRecorder("right_ep", tmp_path, task_label="right_task")
    foreign = _sample(0, episode_id="WRONG_ep")  # _sample stamps task_label="insert_connector"
    rec.ingest_sample(foreign)

    stored = rec.episode.samples[0]
    assert stored.episode_id == "right_ep"
    assert stored.task_label == "right_task"
    assert stored.timestamp_ns == foreign.timestamp_ns  # payload untouched, only provenance
    assert stored.joint_angle == foreign.joint_angle
    # the caller's object must not have been mutated in place
    assert foreign.episode_id == "WRONG_ep"
    assert foreign.task_label == "insert_connector"


def test_recorder_ingest_sample_matching_provenance_kept_verbatim(tmp_path: Path) -> None:
    """When metadata already matches, the exact sample object is appended (no needless copy)."""
    rec = EpisodeRecorder("match_ep", tmp_path, task_label="insert_connector")
    s = _sample(0, episode_id="match_ep")  # task_label="insert_connector" matches
    rec.ingest_sample(s)
    assert rec.episode.samples[0] is s


# --- registry --------------------------------------------------------------


def test_make_unknown_sink_raises_listing_builtins() -> None:
    with pytest.raises(ValueError) as exc:
        make_episode_sink("does_not_exist")
    assert "parquet-atomic" in str(exc.value)
    assert "inmem" in str(exc.value)


def test_list_episode_sinks_sorted_includes_builtins() -> None:
    names = list_episode_sinks()
    assert names == sorted(names)
    assert "parquet-atomic" in names
    assert "inmem" in names


def test_registry_register_make_roundtrip() -> None:
    """A fresh registry registers, makes, and guards duplicates — the A1 contract."""
    reg: Registry[EpisodeSink] = Registry("episode sink")
    reg.register("inmem", InMemorySink)
    assert isinstance(reg.make("inmem", episode_id="x"), InMemorySink)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("inmem", InMemorySink)


def test_registry_unknown_on_empty() -> None:
    reg: Registry[EpisodeSink] = Registry("episode sink")
    with pytest.raises(ValueError, match="Unknown episode sink"):
        reg.make("inmem")


# --- SinkResult immutability -----------------------------------------------


def test_sink_result_detail_is_immutable() -> None:
    """A finalize verdict is append-only evidence: its nested ``detail`` cannot be rewritten.

    ``frozen=True`` alone leaves the nested dict mutable; the contract wraps it in a
    read-only view so a caller cannot quietly rewrite ``result.detail[...]`` after finalize.
    """
    result = SinkResult(
        episode_id="ep", accepted=True, n_samples=1, detail={"dropped_nonfinite": 0}
    )
    assert result.detail["dropped_nonfinite"] == 0
    with pytest.raises(TypeError):
        result.detail["dropped_nonfinite"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        del result.detail["dropped_nonfinite"]  # type: ignore[attr-defined]
    assert result.detail["dropped_nonfinite"] == 0  # unchanged


def test_sink_result_detail_copies_source_dict() -> None:
    """Mutating the dict a caller passed in must not leak into the frozen verdict."""
    source = {"dropped_nonfinite": 0}
    result = SinkResult(episode_id="ep", accepted=True, n_samples=1, detail=source)
    source["dropped_nonfinite"] = 99  # mutate the original after construction
    assert result.detail["dropped_nonfinite"] == 0  # the view is over a private copy


def test_sink_result_attribute_is_frozen() -> None:
    """The frozen dataclass still rejects rebinding a top-level attribute."""
    result = SinkResult(episode_id="ep", accepted=True, n_samples=1)
    with pytest.raises(AttributeError):
        result.accepted = False  # type: ignore[misc]


# --- conformance-style suite over the BUILT-IN sinks -----------------------
# A3 generalizes this into the shared harness; here we assert the EpisodeSink
# lifecycle invariants every plugin must satisfy.
#
# Pin the parametrization to the known built-ins, NOT ``list_episode_sinks()``:
# that helper also returns lazily-discovered third-party entry-point sinks, and
# ``_make_sink`` only knows how to construct these two. Driving the suite off the
# live registry would make it environment-dependent — an external plugin (or one
# needing constructor kwargs this helper does not know) could break the suite
# before it tests any repo code. The built-in set is the contract we own here.
BUILTIN_SINKS = ("parquet-atomic", "inmem")


def _make_sink(name: str, tmp_path: Path) -> EpisodeSink:
    """Construct a registered sink with whatever kwargs it needs, by name."""
    if name == "parquet-atomic":
        return make_episode_sink(name, out_dir=tmp_path, episode_id="conf_ep")
    if name == "inmem":
        return make_episode_sink(name, episode_id="conf_ep")
    raise AssertionError(f"unhandled built-in sink {name!r}; add its constructor here")


@pytest.fixture(params=BUILTIN_SINKS)
def sink(request: pytest.FixtureRequest, tmp_path: Path) -> EpisodeSink:
    return _make_sink(request.param, tmp_path)


def test_builtin_sinks_are_registered() -> None:
    """The built-ins the conformance suite pins are actually in the live registry."""
    registered = list_episode_sinks()
    for name in BUILTIN_SINKS:
        assert name in registered


def test_conformance_is_episode_sink(sink: EpisodeSink) -> None:
    assert isinstance(sink, EpisodeSink)


def test_conformance_contract_version_matches(sink: EpisodeSink) -> None:
    assert sink.contract_version == SINK_CONTRACT_VERSION


def test_conformance_open_ingest_finalize_returns_result(sink: EpisodeSink) -> None:
    sink.open()
    for s in _clean_samples(30, episode_id="conf_ep"):
        sink.ingest(s)
    result = sink.finalize()
    assert isinstance(result, SinkResult)
    assert result.episode_id == "conf_ep"
    assert result.n_samples == 30
    assert sink.result is result  # the verdict is cached on the sink


def test_conformance_ingest_before_open_raises(sink: EpisodeSink) -> None:
    with pytest.raises(RuntimeError, match="not opened"):
        sink.ingest(_sample(0, episode_id="conf_ep"))


def test_conformance_double_open_raises(sink: EpisodeSink) -> None:
    sink.open()
    with pytest.raises(RuntimeError, match="already opened"):
        sink.open()


def test_conformance_ingest_after_finalize_raises(sink: EpisodeSink) -> None:
    sink.open()
    for s in _clean_samples(2, episode_id="conf_ep"):
        sink.ingest(s)
    sink.finalize()
    with pytest.raises(RuntimeError, match="already finalized"):
        sink.ingest(_sample(99, episode_id="conf_ep"))


def test_conformance_double_finalize_raises(sink: EpisodeSink) -> None:
    sink.open()
    for s in _clean_samples(2, episode_id="conf_ep"):
        sink.ingest(s)
    sink.finalize()
    with pytest.raises(RuntimeError, match="already finalized"):
        sink.finalize()


def test_conformance_finalize_before_open_raises(sink: EpisodeSink) -> None:
    with pytest.raises(RuntimeError, match="not opened"):
        sink.finalize()


def test_conformance_nan_never_admitted(sink: EpisodeSink) -> None:
    """No registered sink — disk or memory — admits a non-finite joint value.

    The generic contract is only the SHARED behaviour: a NaN sample is not admitted, so
    exactly the one finite sample is committed (``n_samples == 1``). It deliberately does
    NOT assert ``detail["dropped_nonfinite"]`` — ``SinkResult.detail`` is documented as
    sink-specific and may be empty, so a plugin must not be forced to expose that key to
    pass conformance. The drop-count provenance is asserted in the built-in sink tests
    (:func:`test_nan_joint_value_rejected_by_parquet_sink`,
    :func:`test_nan_rejected_by_inmem_sink`) that exercise the concrete implementations.
    """
    sink.open()
    sink.ingest(_sample(0, episode_id="conf_ep", angle=float("nan")))
    sink.ingest(_sample(1, episode_id="conf_ep", angle=1.0))
    result = sink.finalize()
    assert result.n_samples == 1


def test_conformance_context_manager_clean_exit_finalizes(sink: EpisodeSink) -> None:
    with sink:
        for s in _clean_samples(30, episode_id="conf_ep"):
            sink.ingest(s)
    assert sink.result is not None
    assert sink.result.n_samples == 30


# --- direct-construction sanity (no registry) ------------------------------


def test_parquet_atomic_sink_direct_strict_raises_on_quarantine(tmp_path: Path) -> None:
    """strict=True surfaces the recorder's QuarantineError through the sink finalize."""
    sink = ParquetAtomicSink(out_dir=tmp_path, episode_id="strict_ep", strict=True)
    sink.open()
    sink.ingest(_sample(0, episode_id="strict_ep"))  # one sample -> too few -> quarantine
    with pytest.raises(QuarantineError):
        sink.finalize()
