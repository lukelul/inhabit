# ADR-0003: MT6701 Analog Calibration

## Status
Accepted

## Context
The MT6701 magnetic encoder provides analog output proportional to angle. The raw ADC value needs conversion to millidegrees, and the mapping may not be perfectly linear due to magnet placement.

## Decision
Linear calibration: `millideg = raw_adc * slope + intercept`. Least-squares fit from calibration samples. Separate CAN ID block (`0x200 + node_id`) for calibration telemetry.

## Failure Mode Prevented
- Uncalibrated raw ADC values treated as angles (meaningless data)
- Calibration parameters overwriting main telemetry (separate CAN ID block)
- Calibration fit failing silently (returns false on insufficient samples or degenerate data)

## Alternatives Considered
1. No calibration (raw ADC only) -- rejected: unusable for ML pipeline without angle conversion
2. Lookup table -- rejected: linear is sufficient for Rev-A; tables add flash usage
3. Polynomial fit -- rejected: overkill for Rev-A analog output; revisit for digital interface

## Consequences
- Positive: simple, fast, low flash usage
- Positive: calibration telemetry provides per-pod visibility
- Trade-off: linear fit may not capture nonlinearity from severe magnet misalignment

## Related Source Files
- `firmware/src/calib.c`, `firmware/inc/calib.h`

## Related Tests
- `firmware/test/test_calib.c`

## Open Questions
- What angular accuracy does the linear fit achieve with a well-positioned magnet? (Measure on hardware)
