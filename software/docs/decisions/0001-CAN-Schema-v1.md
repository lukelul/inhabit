# ADR-0001: CAN Schema v1

## Status
Accepted (FROZEN)

## Context
The smart joint pod needs to transmit telemetry over CAN bus. The frame format must be identical in firmware (C) and host (Python) and must never change silently.

## Decision
8-byte CAN frame at ID `0x100 + node_id`:
- [0:1] angle_raw_adc (uint16 LE)
- [2:3] angle_millideg (int16 LE)
- [4] node_id (uint8)
- [5] chain_index (uint8)
- [6] status_flags (uint8)
- [7] checksum (XOR of bytes 0..6)

New telemetry uses new CAN ID blocks, never repurposed bytes.

## Failure Mode Prevented
Schema drift between firmware and host causing data corruption. Byte repurposing breaking backward compatibility.

## Alternatives Considered
1. Protobuf/CBOR over CAN -- rejected: too much overhead for 8-byte frames
2. Variable-length frames -- rejected: DLC=8 is simplest, all controllers handle it
3. CRC instead of XOR -- rejected: XOR is cheapest for 7 bytes; CRC adds complexity for minimal gain at this size

## Consequences
- Positive: identical pack/unpack in C and Python, tested together
- Positive: simple, deterministic, fits in single CAN frame
- Trade-off: limited to 7 data bytes before the checksum byte. Future telemetry needs separate CAN IDs.

## Related Source Files
- `firmware/inc/can_frame.h`
- `firmware/src/can_frame.c`
- `host/inhabit_can/codec.py`

## Related Tests
- `firmware/test/test_can_frame.c`
- `host/tests/test_codec.py`

## Related Benchmarks
- BENCHMARKS.md item 3 (frozen contracts untouched)

## Open Questions
- None (frozen)
