"""CAN schema v1 codec — single source of truth (mirrors firmware/inc/can_frame.h).

Frame: ID = 0x100 + node_id, DLC 8.
  [0:1] angle_raw_adc  u16 LE | [2:3] angle_millideg i16 LE | [4] node_id | [5] chain_index
  [6]   status_flags   u8     | [7] checksum (XOR of bytes 0..6)
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

PROTO_VERSION = 1
BASE_ID = 0x100

# status_flags bits
ST_ADC_FAULT, ST_SPI_FAULT, ST_CAN_FAULT = 1 << 0, 1 << 1, 1 << 2
ST_MAGNET_OOB, ST_NOT_ENUMERATED, ST_CALIB_INVALID = 1 << 3, 1 << 4, 1 << 5


@dataclass
class State:
    angle_raw_adc: int
    angle_millideg: int
    node_id: int
    chain_index: int
    status_flags: int = 0
    valid: bool = True


def can_id(node_id: int) -> int:
    return BASE_ID + node_id


def _xor7(b: bytes) -> int:
    c = 0
    for x in b:
        c ^= x
    return c


def encode_state(s: State) -> tuple[int, bytes]:
    body = struct.pack(
        "<HhBBB", s.angle_raw_adc & 0xFFFF, s.angle_millideg,
        s.node_id, s.chain_index, s.status_flags,
    )
    return can_id(s.node_id), body + bytes([_xor7(body)])


def decode_state(data: bytes) -> State:
    if len(data) != 8:
        raise ValueError("CAN frame must be 8 bytes")
    raw, millideg, node_id, chain_index, status = struct.unpack("<HhBBB", data[:7])
    return State(raw, millideg, node_id, chain_index, status, valid=_xor7(data[:7]) == data[7])
