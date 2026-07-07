"""Tests for host/sensors/ — SensorSource ABC, registry, and the sim-proprio plugin.

Headless, zero hardware, stdlib + frozen ``PVTSample`` only. Three concerns:

1. **Determinism** — sim-proprio with the same seed (+ same clock) emits a byte-identical
   sequence; a different seed diverges. This is the hard quality-bar requirement.
2. **A reusable, parametrizable conformance suite** for any ``SensorSource`` (kind
   invariant; ``read`` returns the declared type; metadata present + self-consistent;
   monotonic stamps). A3 will generalize this harness; the builders here are the seam.
3. **Registry** — register/make/unknown→ValueError; ``list_sensor_sources`` sorted and
   includes ``sim-proprio``; the contract version is pinned.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import pytest

import sensors  # for the factory's private _REGISTRY in the contract-version gate test
from inhabit_can.pvt import PVT_SCHEMA_VERSION, PVTSample
from inhabit_core import Registry
from sensors import (
    SENSOR_SOURCE_CONTRACT_VERSION,
    SensorKind,
    SensorMetadata,
    SensorSource,
    SimProprioSource,
    list_sensor_sources,
    make_sensor_source,
)

# ---------------------------------------------------------------------------
# Reusable conformance suite (parametrizable). A SourceBuilder builds a FRESH,
# unopened source each call; the suite owns open/close so it can re-open and
# assert determinism. A3 will lift this into host/tests/conformance/.
# ---------------------------------------------------------------------------

SourceBuilder = Callable[[], SensorSource]


@runtime_checkable
class _Timestamped(Protocol):
    """Structural type for any sample the conformance suite inspects.

    The suite only touches ``timestamp_ns`` on a sample, so binding the sample to this
    Protocol (instead of a raw ``type``) lets the helper read the field type-safely — no
    ``# type: ignore`` — while ``runtime_checkable`` keeps the ``isinstance`` shape check.
    """

    timestamp_ns: int


def assert_sensor_source_conforms(
    build: SourceBuilder,
    *,
    expected_kind: SensorKind,
    sample_type: type[_Timestamped],
) -> None:
    """Assert that ``build()`` produces a conforming :class:`SensorSource`.

    Checks the invariants every sensor source must satisfy, independent of modality:

    * class-level ``kind`` equals ``metadata().kind`` equals ``expected_kind`` (kind
      invariant — readable without opening);
    * ``metadata()`` is a populated :class:`SensorMetadata` reporting the current contract
      version and a non-empty name/device_id;
    * before ``open()``, ``read()`` raises (fail-loud lifecycle);
    * after ``open()``, ``read()`` returns the declared ``sample_type`` (statically known to
      expose ``timestamp_ns`` via the :class:`_Timestamped` protocol) with a monotonic,
      non-decreasing ``timestamp_ns``, and eventually ``None`` (exhaustion);
    * ``stream()`` yields the same number of samples as ``read``-until-``None``;
    * the context-manager protocol opens AND closes — after the ``with`` block the source is
      closed, proven by ``read()`` raising the before-open lifecycle error again.
    """
    # -- kind invariant (no construction-of-instance needed beyond build) --
    src = build()
    assert src.kind is expected_kind
    meta = src.metadata()
    assert isinstance(meta, SensorMetadata)
    assert meta.kind is expected_kind
    assert meta.kind is src.kind
    assert meta.name
    assert meta.device_id
    assert meta.contract_version == SENSOR_SOURCE_CONTRACT_VERSION

    # -- fail-loud: read before open --
    with pytest.raises(RuntimeError):
        src.read()

    # -- read path: declared type + monotonic stamps + exhaustion --
    read_samples: list[_Timestamped] = []
    with src:
        last_ts: int | None = None
        while True:
            s = src.read()
            if s is None:
                break
            assert isinstance(s, sample_type)
            ts = s.timestamp_ns
            if last_ts is not None:
                assert ts >= last_ts, "timestamps must be monotonic non-decreasing"
            last_ts = ts
            read_samples.append(s)
    assert read_samples, "a conforming source must emit at least one sample"

    # -- __exit__ MUST close: after the with-block the source is closed, so the fail-loud
    #    before-open guard fires again. A source that no-ops on close would fail here. --
    with pytest.raises(RuntimeError):
        src.read()

    # -- stream path agrees with read path (count) --
    src2 = build()
    with src2:
        stream_samples = list(src2.stream())
    assert len(stream_samples) == len(read_samples)
    # And src2 is likewise closed after its with-block.
    with pytest.raises(RuntimeError):
        src2.read()


# ---------------------------------------------------------------------------
# sim-proprio conformance (parametrized through the reusable suite)
# ---------------------------------------------------------------------------


def _build_sim_proprio() -> SensorSource:
    return SimProprioSource(seed=7, count=8)


def test_sim_proprio_conforms() -> None:
    assert_sensor_source_conforms(
        _build_sim_proprio, expected_kind=SensorKind.PROPRIO, sample_type=PVTSample
    )


def test_registry_built_source_conforms() -> None:
    """A source obtained via the registry conforms identically (no special-casing)."""
    assert_sensor_source_conforms(
        lambda: make_sensor_source("sim-proprio", seed=3, count=5),
        expected_kind=SensorKind.PROPRIO,
        sample_type=PVTSample,
    )


# ---------------------------------------------------------------------------
# Determinism — the hard requirement
# ---------------------------------------------------------------------------


def _collect(seed: int, count: int = 12) -> list[PVTSample]:
    src = SimProprioSource(seed=seed, count=count, start_ns=1_000, period_ns=5_000_000)
    with src:
        return list(src.stream())


def test_same_seed_is_byte_identical() -> None:
    """Same seed (+ same default clock) => structurally identical sequence."""
    a = _collect(seed=42)
    b = _collect(seed=42)
    assert a == b  # dataclass __eq__ is field-wise; byte-stable for identical inputs
    # And the JSON serialization is byte-identical (true byte-equality, not just ==).
    assert [s.to_json() for s in a] == [s.to_json() for s in b]


def _strip_ts(samples: list[PVTSample]) -> list[PVTSample]:
    """Copy samples with timestamp zeroed — compare the seeded DATA, not the clock."""
    return [dataclasses.replace(s, timestamp_ns=0) for s in samples]


def test_reopen_replays_identical_data() -> None:
    """Re-opening the SAME source re-seeds the RNG => identical sample DATA.

    The default monotonic clock is deliberately NOT rewound by ``open()`` — time only ever
    moves forward (the time-sync invariant), so timestamps advance across re-opens while the
    seeded proprio values replay exactly. We assert the data fields, clock aside.
    """
    src = SimProprioSource(seed=99, count=6, start_ns=0, period_ns=1_000_000)
    with src:
        first = list(src.stream())
    with src:
        second = list(src.stream())
    assert _strip_ts(first) == _strip_ts(second)
    # The clock kept advancing across the re-open (never rewound) — monotonic time.
    assert second[0].timestamp_ns > first[-1].timestamp_ns


def test_different_seed_diverges() -> None:
    """A different seed produces a different sequence (noise actually depends on seed)."""
    a = _collect(seed=1)
    b = _collect(seed=2)
    assert a != b
    # Specifically the angles differ (the seeded noise term is what diverges).
    assert [s.joint_angle for s in a] != [s.joint_angle for s in b]


def test_noise_free_is_pure_sweep_and_deterministic() -> None:
    """noise=0 yields the closed-form sweep, identical across seeds (no RNG dependence)."""
    s0 = SimProprioSource(seed=0, count=5, noise_rad=0.0, start_ns=0, period_ns=1_000_000)
    s1 = SimProprioSource(seed=123, count=5, noise_rad=0.0, start_ns=0, period_ns=1_000_000)
    with s0:
        a = list(s0.stream())
    with s1:
        b = list(s1.stream())
    assert a == b  # no noise => seed is irrelevant => identical


# ---------------------------------------------------------------------------
# Sample shape / clock injection / time-sync contract
# ---------------------------------------------------------------------------


def test_samples_are_pvt_shaped_proprio() -> None:
    """Emitted samples are PVTSample with the frozen schema version and proprio fields."""
    [s] = _collect(seed=5, count=1)
    assert isinstance(s, PVTSample)
    assert s.schema_version == PVT_SCHEMA_VERSION
    # Proprio portion populated; visual/tactile left at defaults (this is a proprio source).
    assert isinstance(s.joint_angle, float)
    assert isinstance(s.joint_velocity, float)
    assert s.camera_frame_id is None
    assert s.tactile_event is None


def test_injected_clock_drives_timestamps() -> None:
    """An injected monotonic clock fully determines timestamps (time-sync contract)."""
    ticks = iter([10, 20, 30, 40])
    src = SimProprioSource(seed=0, count=4, clock_ns=lambda: next(ticks))
    with src:
        stamps = [s.timestamp_ns for s in src.stream()]
    assert stamps == [10, 20, 30, 40]


def test_default_stepping_clock_is_monotonic() -> None:
    """The default clock steps by period_ns from start_ns — reproducible monotonic stamps."""
    src = SimProprioSource(seed=0, count=3, start_ns=1_000, period_ns=500)
    with src:
        stamps = [s.timestamp_ns for s in src.stream()]
    assert stamps == [1_000, 1_500, 2_000]


def test_signal_tracks_injected_clock() -> None:
    """The proprio signal is a function of the INJECTED clock, not an internal index.

    The phase is measured from the first stamp of the open(), so the closed-form sweep
    (noise-free => pure ``amplitude*sin(2*pi*f*t_s)``) must equal the analytic value at the
    clock-derived elapsed time. Two clocks that visit DIFFERENT absolute times but the SAME
    elapsed offsets produce IDENTICAL signal values — proving signal and timestamp share one
    timeline, not two.
    """
    freq, amp = 0.5, 1.0
    # Clock A: starts at 0, samples at elapsed {0, 1e9 ns (1s), 2e9 ns}.
    ticks_a = iter([0, 1_000_000_000, 2_000_000_000])
    # Clock B: same elapsed offsets but shifted to a different absolute origin (500 ns).
    ticks_b = iter([500, 1_000_000_500, 2_000_000_500])

    def build(clock: Callable[[], int]) -> SimProprioSource:
        return SimProprioSource(
            seed=0,
            count=3,
            noise_rad=0.0,  # noise-free => pure closed-form sweep, exactly checkable
            amplitude_rad=amp,
            frequency_hz=freq,
            clock_ns=clock,
        )

    a = build(lambda: next(ticks_a))
    with a:
        sa = list(a.stream())
    b = build(lambda: next(ticks_b))
    with b:
        sb = list(b.stream())

    # Same elapsed offsets => identical signal despite different absolute clock origin.
    assert [s.joint_angle for s in sa] == [s.joint_angle for s in sb]
    # And the signal matches the closed-form sweep evaluated at the clock-derived elapsed t.
    for s, t_s in zip(sa, (0.0, 1.0, 2.0), strict=True):
        assert s.joint_angle == pytest.approx(amp * math.sin(2 * math.pi * freq * t_s))


def test_clock_jump_keeps_signal_and_timestamp_consistent() -> None:
    """A clock that JUMPS advances the signal phase in lockstep with the timestamp.

    If the signal were driven by an internal sample index it would ignore the jump and
    desync from ``timestamp_ns``. Driving it from the clock keeps them on one timeline.
    """
    # Elapsed offsets 0, 0.25s, then a big jump to 5s.
    ticks = iter([0, 250_000_000, 5_000_000_000])
    src = SimProprioSource(
        seed=0, count=3, noise_rad=0.0, amplitude_rad=1.0, frequency_hz=0.5,
        clock_ns=lambda: next(ticks),
    )
    with src:
        samples = list(src.stream())
    for s, t_s in zip(samples, (0.0, 0.25, 5.0), strict=True):
        assert s.joint_angle == pytest.approx(math.sin(2 * math.pi * 0.5 * t_s))


def test_metadata_reports_schema_and_kind() -> None:
    meta = SimProprioSource().metadata()
    assert meta.kind is SensorKind.PROPRIO
    assert meta.name == "sim-proprio"
    assert meta.sample_schema_version == PVT_SCHEMA_VERSION
    assert meta.nominal_rate_hz == pytest.approx(200.0)
    # SensorMetadata is frozen (cheap, inspectable, immutable).
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.kind = SensorKind.VISUAL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Lifecycle / fail-loud
# ---------------------------------------------------------------------------


def test_stream_before_open_raises() -> None:
    src = SimProprioSource(seed=0, count=1)
    with pytest.raises(RuntimeError, match="before open"):
        list(src.stream())


def test_read_before_open_raises() -> None:
    src = SimProprioSource(seed=0, count=1)
    with pytest.raises(RuntimeError, match="before open"):
        src.read()


def test_stream_ends_cleanly_when_closed_mid_iteration() -> None:
    """Closing the source mid-stream ends the generator (StopIteration), not RuntimeError.

    Honors the SensorSource "until exhausted OR closed" contract: a consumer that holds the
    generator across a ``close()`` (e.g. the ``with`` block exits) must see the stream stop,
    NOT a ``read() called before open()`` RuntimeError on the next ``next()``.
    """
    src = SimProprioSource(seed=0, count=100)  # plenty of samples, far from exhaustion
    src.open()
    gen = src.stream()
    first = next(gen)  # consume one sample while open
    assert first is not None
    src.close()  # close mid-iteration
    # The generator must terminate cleanly — StopIteration, never RuntimeError.
    with pytest.raises(StopIteration):
        next(gen)


def test_stream_stops_cleanly_on_with_block_exit() -> None:
    """Same close transition via the context manager: exiting ``with`` stops the stream."""
    src = SimProprioSource(seed=0, count=100)
    with src:
        gen = src.stream()
        assert next(gen) is not None
    # ``__exit__`` closed the source; the held generator now stops cleanly, no RuntimeError.
    with pytest.raises(StopIteration):
        next(gen)


def test_count_zero_emits_nothing() -> None:
    src = SimProprioSource(seed=0, count=0)
    with src:
        assert src.read() is None
        assert list(src.stream()) == []


def test_negative_count_rejected() -> None:
    with pytest.raises(ValueError, match="count must be >= 0"):
        SimProprioSource(count=-1)


def test_non_positive_period_rejected() -> None:
    with pytest.raises(ValueError, match="period_ns must be > 0"):
        SimProprioSource(period_ns=0)


def test_episode_and_task_label_stamped() -> None:
    src = SimProprioSource(
        seed=0, count=2, episode_id="demo_42", chain_index=3, task_label="insert_connector"
    )
    with src:
        samples = list(src.stream())
    assert all(s.episode_id == "demo_42" for s in samples)
    assert all(s.chain_index == 3 for s in samples)
    assert all(s.task_label == "insert_connector" for s in samples)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_list_sensor_sources_sorted_includes_sim_proprio() -> None:
    names = list_sensor_sources()
    assert "sim-proprio" in names
    assert names == sorted(names)


def test_make_sensor_source_returns_sensor_source() -> None:
    src = make_sensor_source("sim-proprio", seed=1, count=3)
    assert isinstance(src, SensorSource)
    assert isinstance(src, SimProprioSource)
    assert src.kind is SensorKind.PROPRIO


def test_make_unknown_raises_valueerror_listing_names() -> None:
    with pytest.raises(ValueError) as exc:
        make_sensor_source("does-not-exist")
    msg = str(exc.value)
    assert "does-not-exist" in msg
    assert "sim-proprio" in msg  # error lists the available names


def test_registry_is_typed_and_duplicate_guarded() -> None:
    """A fresh Registry[SensorSource] register/make round-trips and guards duplicates."""
    reg: Registry[SensorSource] = Registry("sensor source")
    reg.register("sim-proprio", SimProprioSource)
    built = reg.make("sim-proprio", seed=0, count=1)
    assert isinstance(built, SimProprioSource)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("sim-proprio", SimProprioSource)


def test_contract_version_pinned() -> None:
    """The ABC contract version is exported and stamped into metadata."""
    assert SENSOR_SOURCE_CONTRACT_VERSION == 1
    assert SimProprioSource().metadata().contract_version == SENSOR_SOURCE_CONTRACT_VERSION


class _IncompatibleSource(SimProprioSource):
    """A source deliberately built against an incompatible (future) ABC revision.

    Subclasses the real sim source so it is otherwise fully conformant; it only overrides
    :meth:`metadata` to advertise a mismatched ``contract_version``, isolating the factory's
    version gate as the single thing under test.
    """

    def metadata(self) -> SensorMetadata:
        base = super().metadata()
        return dataclasses.replace(
            base, contract_version=SENSOR_SOURCE_CONTRACT_VERSION + 1
        )


def test_make_sensor_source_rejects_incompatible_contract_version() -> None:
    """The factory rejects a plugin whose contract_version != the host's, at the boundary."""
    name = "_incompatible_test_source"
    sensors._REGISTRY.register(name, _IncompatibleSource)
    try:
        with pytest.raises(ValueError) as exc:
            make_sensor_source(name, seed=0, count=1)
        msg = str(exc.value)
        # Error names the offending contract and the expected one (localized, actionable).
        assert str(SENSOR_SOURCE_CONTRACT_VERSION + 1) in msg
        assert str(SENSOR_SOURCE_CONTRACT_VERSION) in msg
    finally:
        # Keep the module-level registry clean for other tests (no leak across tests).
        del sensors._REGISTRY._factories[name]


def test_make_sensor_source_accepts_matching_contract_version() -> None:
    """A source reporting the host's contract_version passes the factory gate unchanged."""
    src = make_sensor_source("sim-proprio", seed=0, count=1)
    assert src.metadata().contract_version == SENSOR_SOURCE_CONTRACT_VERSION
