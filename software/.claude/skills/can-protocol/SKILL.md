---
name: can-protocol
description: Use when defining, encoding, decoding, or extending Inhabit CAN messages on either side (STM32 firmware or Python host). Triggers on "CAN message", "frame", "payload", "byte layout", "0x100", "schema", "decode telemetry", "node id".
---

# Inhabit CAN Protocol

## Schema v1 (frozen — do not break)
```
ID: 0x100 + node_id            # 11-bit standard IDs; node_id in 0..0x6FF range budget
DLC: 8
byte 0-1: angle_raw_adc   uint16 LE
byte 2-3: angle_millideg  int16  LE   # signed; wrap handled host-side
byte 4:   node_id         uint8
byte 5:   chain_index     uint8
byte 6:   status_flags    uint8       # bit0 adc_fault, bit1 spi_fault, bit2 can_fault,
                                       # bit3 magnet_oob, bit4 not_enumerated, bit5 calib_invalid
byte 7:   checksum         uint8       # XOR of bytes 0..6
```

## Extending the protocol (the right way)
- New telemetry ⇒ **new CAN ID**, never repurposed bytes in 0x100+node_id.
- Suggested ID blocks: 0x100+ state · 0x200+ extended telemetry (vel, current) ·
  0x300+ tactile/contact events · 0x700+ host→pod commands (enum seed, calib, reset).
- Bump a `proto_version` constant in both firmware and host on any change; log mismatches.

## Reference codecs
Firmware (C) and host (Python) MUST agree byte-for-byte. Keep a single doc as truth (this file).
```python
import struct
def encode_state(raw, millideg, node_id, chain_index, status):
    b = struct.pack('<HhBBB', raw & 0xFFFF, millideg, node_id, chain_index, status)
    chk = 0
    for x in b: chk ^= x
    return (0x100 + node_id), b + bytes([chk])

def decode_state(can_id, data):
    assert len(data) == 8
    chk = 0
    for x in data[:7]: chk ^= x
    valid = (chk == data[7])
    raw, millideg, node_id, chain_index, status = struct.unpack('<HhBBB', data[:7])
    return dict(node_id=node_id, chain_index=chain_index, angle_millideg=millideg,
                raw=raw, status=status, valid=valid)
```

## Test it
Round-trip property test: `decode_state(*encode_state(...))` recovers inputs and `valid==True`.
Inject a bit flip ⇒ `valid==False`. Add these to host/tests before trusting live data.
