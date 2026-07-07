from __future__ import annotations

import pytest

from tools.calibrate import (
    CALIB_BASE_ID,
    MT6701_ADC_MAX,
    CalibTelemetry,
    adc_to_millideg,
    calib_can_id,
    decode_calib,
    encode_calib,
    fit_linear_params,
    fit_r_squared,
)

# --- linear fit ---


def test_fit_linear_params_and_conversion() -> None:
    samples = [(1000, 0), (2000, 1500), (3000, 3000)]
    params = fit_linear_params(samples)
    assert abs(params["slope"] - 1.5) < 1e-9
    assert abs(params["intercept"] + 1500.0) < 1e-9
    assert adc_to_millideg(2000, params) == 1500
    assert adc_to_millideg(3000, params) == 3000


def test_fit_two_points_full_range() -> None:
    """int16_t millideg caps at 32767; test realistic sub-range."""
    samples = [(0, -10000), (MT6701_ADC_MAX, 10000)]
    params = fit_linear_params(samples)
    assert adc_to_millideg(0, params) == -10000
    assert abs(adc_to_millideg(MT6701_ADC_MAX, params) - 10000) <= 1


def test_fit_rejects_single_point() -> None:
    with pytest.raises(ValueError, match="at least two"):
        fit_linear_params([(1000, 0)])


def test_fit_rejects_degenerate() -> None:
    with pytest.raises(ValueError, match="non-zero ADC range"):
        fit_linear_params([(2000, 100), (2000, 200)])


def test_r_squared_perfect() -> None:
    samples = [(0, 0), (1000, 1500), (2000, 3000)]
    params = fit_linear_params(samples)
    assert fit_r_squared(samples, params) > 0.9999


def test_r_squared_imperfect() -> None:
    samples = [(0, 0), (1000, 1400), (2000, 3000), (3000, 4600)]
    params = fit_linear_params(samples)
    r2 = fit_r_squared(samples, params)
    assert 0.99 < r2 < 1.0


def test_r_squared_single_point_is_zero() -> None:
    """Fewer than two points has no defined R²; return 0.0 (not a crash)."""
    assert fit_r_squared([(1000, 0)], {"slope": 1.0, "intercept": 0.0}) == 0.0


def test_r_squared_all_y_identical_is_perfect() -> None:
    """Zero total variance in y → trivially perfect fit (R²=1.0)."""
    samples = [(0, 500), (1000, 500), (2000, 500)]
    assert fit_r_squared(samples, {"slope": 0.0, "intercept": 500.0}) == 1.0


# --- calib CAN codec ---


def test_calib_can_id() -> None:
    assert calib_can_id(0) == CALIB_BASE_ID
    assert calib_can_id(3) == 0x303
    assert calib_can_id(255) == CALIB_BASE_ID + 255


def test_encode_decode_roundtrip() -> None:
    t = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    can_id, data = encode_calib(t)
    assert can_id == 0x303
    assert len(data) == 8

    decoded = decode_calib(data)
    assert decoded.raw_adc == t.raw_adc
    assert decoded.calibrated_millideg == t.calibrated_millideg
    assert decoded.node_id == t.node_id
    assert decoded.chain_index == t.chain_index
    assert decoded.status_flags == 0
    assert decoded.valid is True


def test_encode_decode_extremes() -> None:
    t = CalibTelemetry(
        raw_adc=4095, calibrated_millideg=32767,
        node_id=255, chain_index=255, status_flags=0xFF,
    )
    _, data = encode_calib(t)
    decoded = decode_calib(data)
    assert decoded.raw_adc == 4095
    assert decoded.calibrated_millideg == 32767
    assert decoded.status_flags == 0xFF
    assert decoded.valid is True


def test_negative_millideg() -> None:
    t = CalibTelemetry(raw_adc=0, calibrated_millideg=-1500, node_id=0, chain_index=0)
    _, data = encode_calib(t)
    decoded = decode_calib(data)
    assert decoded.calibrated_millideg == -1500
    assert decoded.valid is True


def test_corrupt_checksum_rejected() -> None:
    t = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    _, data = encode_calib(t)
    corrupted = bytearray(data)
    corrupted[7] ^= 0x01
    decoded = decode_calib(bytes(corrupted))
    assert decoded.valid is False


def test_corrupt_payload_rejected() -> None:
    t = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    _, data = encode_calib(t)
    corrupted = bytearray(data)
    corrupted[0] ^= 0xFF
    decoded = decode_calib(bytes(corrupted))
    assert decoded.valid is False


def test_wrong_length_rejected() -> None:
    with pytest.raises(ValueError, match="8 bytes"):
        decode_calib(b"\x00" * 7)


# --- field-range validation (no silent truncation) ---


def test_encode_rejects_out_of_range_adc() -> None:
    """raw_adc > MT6701_ADC_MAX must raise, never be masked with & 0xFFFF."""
    t = CalibTelemetry(raw_adc=MT6701_ADC_MAX + 1, calibrated_millideg=0,
                       node_id=0, chain_index=0)
    with pytest.raises(ValueError, match="raw_adc out of range"):
        encode_calib(t)
    # a 16-bit value that would alias to a valid ADC under & 0xFFFF must still fail
    t2 = CalibTelemetry(raw_adc=0x10000 + 100, calibrated_millideg=0,
                        node_id=0, chain_index=0)
    with pytest.raises(ValueError, match="raw_adc out of range"):
        encode_calib(t2)


def test_encode_rejects_out_of_range_millideg() -> None:
    """calibrated_millideg outside int16 must raise a clear ValueError."""
    t = CalibTelemetry(raw_adc=2048, calibrated_millideg=40000,
                       node_id=0, chain_index=0)
    with pytest.raises(ValueError, match="calibrated_millideg out of int16 range"):
        encode_calib(t)
    t2 = CalibTelemetry(raw_adc=2048, calibrated_millideg=-40000,
                        node_id=0, chain_index=0)
    with pytest.raises(ValueError, match="calibrated_millideg out of int16 range"):
        encode_calib(t2)


def test_encode_rejects_out_of_byte_range_fields() -> None:
    """node_id/chain_index/status_flags above a byte must raise, not wrap."""
    with pytest.raises(ValueError, match="must fit in a byte"):
        encode_calib(CalibTelemetry(raw_adc=0, calibrated_millideg=0,
                                    node_id=256, chain_index=0))
    with pytest.raises(ValueError, match="must fit in a byte"):
        encode_calib(CalibTelemetry(raw_adc=0, calibrated_millideg=0,
                                    node_id=0, chain_index=0, status_flags=300))


def test_encode_accepts_int16_boundaries() -> None:
    """Exact int16 extremes must encode/decode cleanly (boundary, not overflow)."""
    for md in (-32768, 32767):
        _, data = encode_calib(
            CalibTelemetry(raw_adc=0, calibrated_millideg=md, node_id=0, chain_index=0)
        )
        assert decode_calib(data).calibrated_millideg == md


# --- host monotonic RX timestamp (stream-alignment contract) ---


def test_decode_stamps_monotonic_rx_with_injected_clock() -> None:
    """decode_calib stamps rx_monotonic_ns from the injected clock at decode."""
    _, data = encode_calib(
        CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    )
    decoded = decode_calib(data, clock_ns=lambda: 123_456_789)
    assert decoded.rx_monotonic_ns == 123_456_789


def test_decode_default_clock_is_monotonic_positive() -> None:
    """Default clock is time.monotonic_ns: positive and non-decreasing across decodes."""
    _, data = encode_calib(
        CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    )
    first = decode_calib(data).rx_monotonic_ns
    second = decode_calib(data).rx_monotonic_ns
    assert first > 0
    assert second >= first


def test_rx_monotonic_default_factory_distinct_instances() -> None:
    """Each CalibTelemetry built without an explicit stamp gets its own RX time."""
    a = CalibTelemetry(raw_adc=0, calibrated_millideg=0, node_id=0, chain_index=0)
    b = CalibTelemetry(raw_adc=0, calibrated_millideg=0, node_id=0, chain_index=0)
    assert a.rx_monotonic_ns > 0 and b.rx_monotonic_ns > 0
    assert b.rx_monotonic_ns >= a.rx_monotonic_ns


def test_rx_monotonic_not_packed_into_wire_frame() -> None:
    """rx_monotonic_ns is host-side only: it must not change the 8-byte wire frame."""
    t1 = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3,
                        chain_index=1, rx_monotonic_ns=1)
    t2 = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3,
                        chain_index=1, rx_monotonic_ns=9_999_999)
    assert encode_calib(t1)[1] == encode_calib(t2)[1] == GOLDEN_BYTES


# --- adc_to_millideg float32 parity with the C implementation ---


def test_adc_to_millideg_uses_float32_arithmetic() -> None:
    """Python conversion runs in float32 (matches the C float cast), not float64.

    slope=9.999, intercept=-32767.4 at raw_adc=1599 is a known boundary where
    float64 truncates to -16778 but single-precision (the firmware contract)
    gives -16779. Asserting the float32 result locks the parity.
    """
    params = {"slope": 9.999, "intercept": -32767.4}
    assert adc_to_millideg(1599, params) == -16779
    assert adc_to_millideg(3599, params) == 3218


def test_adc_to_millideg_exact_slope_unaffected() -> None:
    """Exactly-representable slopes are identical in float32 and float64."""
    params = {"slope": 1.5, "intercept": -1500.0}
    assert adc_to_millideg(1000, params) == 0
    assert adc_to_millideg(2000, params) == 1500
    assert adc_to_millideg(3000, params) == 3000


# --- C↔Python golden-byte parity ---
# tx = {raw_adc=2048, millideg=1234, node=3, chain=1, flags=0}
# LE: 2048=0x0800, 1234=0x04D2
_CKSUM = 0x00 ^ 0x08 ^ 0xD2 ^ 0x04 ^ 0x03 ^ 0x01 ^ 0x00
GOLDEN_BYTES = bytes([0x00, 0x08, 0xD2, 0x04, 0x03, 0x01, 0x00, _CKSUM])


def test_golden_frame_parity_with_c() -> None:
    """Encode in Python, assert byte-identical to the C golden frame in test_calib.c."""
    t = CalibTelemetry(raw_adc=2048, calibrated_millideg=1234, node_id=3, chain_index=1)
    _, data = encode_calib(t)
    assert data == GOLDEN_BYTES, f"Python produced {data.hex()}, expected {GOLDEN_BYTES.hex()}"


def test_golden_frame_decode() -> None:
    decoded = decode_calib(GOLDEN_BYTES)
    assert decoded.raw_adc == 2048
    assert decoded.calibrated_millideg == 1234
    assert decoded.node_id == 3
    assert decoded.chain_index == 1
    assert decoded.status_flags == 0
    assert decoded.valid is True
