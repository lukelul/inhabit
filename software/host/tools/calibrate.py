"""MT6701 calibration utilities — Python mirror of firmware/src/calib.c.

Provides: least-squares linear fit, ADC→millideg conversion, calib CAN frame
codec (0x300 + node_id, 8 bytes, XOR checksum — separate from schema v1 at 0x100).
"""
from __future__ import annotations

import struct
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# --- constants (must match calib.h) ---
CALIB_BASE_ID = 0x300
CALIB_DLC = 8
MT6701_ADC_MAX = 4095  # 12-bit encoder


# --- calibration math ---


def fit_linear_params(samples: Sequence[tuple[int, int]]) -> dict[str, float]:
    """Least-squares linear fit: ADC → millideg.  Mirrors inhabit_calib_fit_linear."""
    if len(samples) < 2:
        raise ValueError("at least two calibration points are required")

    sum_x = sum(x for x, _ in samples)
    sum_y = sum(y for _, y in samples)
    sum_xy = sum(x * y for x, y in samples)
    sum_xx = sum(x * x for x, _ in samples)
    count = len(samples)
    denominator = count * sum_xx - sum_x * sum_x
    if denominator == 0:
        raise ValueError("calibration points must span a non-zero ADC range")

    slope = (count * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / count
    return {"slope": slope, "intercept": intercept}


def _f32(x: float) -> float:
    """Round a Python float to IEEE-754 single precision (C ``float``)."""
    return float(struct.unpack("<f", struct.pack("<f", x))[0])


def adc_to_millideg(raw_adc: int, params: dict[str, float]) -> int:
    """Convert raw ADC to millidegrees.  Mirrors inhabit_calib_adc_to_millideg.

    The C implementation (firmware/src/calib.c) is::

        (int32_t)((float)raw_adc * params->slope + params->intercept)

    so every operand and intermediate is single-precision ``float`` and the final
    cast truncates toward zero. We reproduce that exactly: coerce slope/intercept
    to float32, do the multiply then the add each rounded to float32, then int()
    (which also truncates toward zero). Using Python's native float64 here would
    diverge by 1 LSB at rounding boundaries for steep slopes (e.g. slope=9.999,
    intercept=-32767.4 at raw_adc=1599), so the conversion must run in float32.

    Caveat: the host C *test* binary is 32-bit MinGW and may evaluate the C
    expression in x87 80-bit extended precision, which can itself differ from
    this by 1 LSB at the same boundaries. The single-precision result here is the
    one the real Cortex-M0+ firmware (no x87, no FMA) produces; that is the
    contract we mirror.
    """
    slope = _f32(params["slope"])
    intercept = _f32(params["intercept"])
    product = _f32(_f32(float(raw_adc)) * slope)
    return int(_f32(product + intercept))


def fit_r_squared(samples: Sequence[tuple[int, int]], params: dict[str, float]) -> float:
    """Coefficient of determination (R²) for a linear fit.  1.0 = perfect."""
    if len(samples) < 2:
        return 0.0
    mean_y = sum(y for _, y in samples) / len(samples)
    ss_tot = sum((y - mean_y) ** 2 for _, y in samples)
    if ss_tot == 0.0:
        return 1.0  # all y identical → perfect fit trivially
    ss_res = sum((y - adc_to_millideg(x, params)) ** 2 for x, y in samples)
    return 1.0 - ss_res / ss_tot


# --- calib CAN codec (mirrors firmware pack/unpack at 0x300) ---


def _xor7(b: bytes | bytearray) -> int:
    c = 0
    for x in b[:7]:
        c ^= x
    return c


@dataclass
class CalibTelemetry:
    """Decoded calib telemetry plus a host monotonic RX timestamp.

    ``rx_monotonic_ns`` is a HOST-SIDE field only -- it is NOT part of the CAN
    wire schema (the 0x300 frame is 8 bytes; this struct field is never packed).
    It is read from ``time.monotonic_ns`` at decode (mirroring how CanFrame in
    inhabit_bridge/sources.py stamps received frames) so downstream PVT logging
    can align calib samples with CAN/video/tactile on a single monotonic clock.
    NEVER wall-clock time.
    """

    raw_adc: int
    calibrated_millideg: int
    node_id: int
    chain_index: int
    status_flags: int = 0
    valid: bool = True
    rx_monotonic_ns: int = field(default_factory=time.monotonic_ns)


def calib_can_id(node_id: int) -> int:
    return CALIB_BASE_ID + node_id


def encode_calib(t: CalibTelemetry) -> tuple[int, bytes]:
    """Pack a CalibTelemetry into (can_id, 8-byte frame).  Byte-identical to C.

    Every field is range-validated and raises ``ValueError`` on overflow -- we
    NEVER mask (e.g. ``raw_adc & 0xFFFF``) and silently corrupt a sample. An ADC
    reading above MT6701_ADC_MAX is a sensor/wiring fault that must surface, not
    be truncated into a plausible-but-wrong angle. ``calibrated_millideg`` is
    checked against the int16 wire range up front so the failure is a clear
    ValueError rather than an opaque struct.error.
    """
    if not 0 <= t.raw_adc <= MT6701_ADC_MAX:
        raise ValueError(f"raw_adc out of range [0, {MT6701_ADC_MAX}]: {t.raw_adc}")
    if not -32768 <= t.calibrated_millideg <= 32767:
        raise ValueError(
            f"calibrated_millideg out of int16 range: {t.calibrated_millideg}"
        )
    if not (0 <= t.node_id <= 0xFF and 0 <= t.chain_index <= 0xFF
            and 0 <= t.status_flags <= 0xFF):
        raise ValueError("node_id/chain_index/status_flags must fit in a byte")
    body = struct.pack(
        "<HhBBB",
        t.raw_adc,
        t.calibrated_millideg,
        t.node_id,
        t.chain_index,
        t.status_flags,
    )
    return calib_can_id(t.node_id), body + bytes([_xor7(body)])


def decode_calib(
    data: bytes, clock_ns: Callable[[], int] = time.monotonic_ns
) -> CalibTelemetry:
    """Unpack 8 bytes into CalibTelemetry.  Byte-identical to C.

    Stamps ``rx_monotonic_ns`` from ``clock_ns`` (default ``time.monotonic_ns``)
    at decode -- a host-side monotonic RX time for downstream stream alignment.
    ``clock_ns`` is injectable so tests can assert exact stamps; it must return
    monotonic nanoseconds and NEVER wall-clock time.
    """
    if len(data) != CALIB_DLC:
        raise ValueError(f"calib frame must be {CALIB_DLC} bytes, got {len(data)}")
    raw, millideg, node_id, chain_index, status = struct.unpack("<HhBBB", data[:7])
    return CalibTelemetry(
        raw_adc=raw,
        calibrated_millideg=millideg,
        node_id=node_id,
        chain_index=chain_index,
        status_flags=status,
        valid=_xor7(data[:7]) == data[7],
        rx_monotonic_ns=clock_ns(),
    )
