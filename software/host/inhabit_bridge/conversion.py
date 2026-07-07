"""ROS-independent conversion: raw CAN frame -> JointPodState field values.

This module is the single mapping point from the FROZEN CAN codec
(:mod:`inhabit_can.codec`) onto the approved ``JointPodState`` message. It is
deliberately free of any ROS imports so it can be unit-tested as plain Python
and so the field mapping is auditable in one place.

The ROS node (``bridge_node``) only adds the ``header`` (with a monotonic
stamp) and copies these fields onto the generated message type.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from inhabit_can.codec import PROTO_VERSION, State, decode_state

# millidegrees -> radians. millideg / 1000 -> degrees; * pi / 180 -> radians.
_MILLIDEG_TO_RAD = math.pi / 180.0 / 1000.0


@dataclass(frozen=True)
class PodFields:
    """Flat, ROS-independent mirror of the JointPodState payload (no header).

    Track 3 (data / PVTSample) can map these fields directly. ``angle_rad`` is
    the derived convenience value; ``checksum_valid`` is ``State.valid`` from
    the codec; ``schema_version`` equals the codec ``PROTO_VERSION``.
    """

    node_id: int
    chain_index: int
    angle_raw_adc: int
    angle_millideg: int
    angle_rad: float
    status_flags: int
    checksum_valid: bool
    schema_version: int


def fields_from_state(state: State) -> PodFields:
    """Map a decoded codec :class:`State` onto :class:`PodFields`."""
    return PodFields(
        node_id=state.node_id,
        chain_index=state.chain_index,
        angle_raw_adc=state.angle_raw_adc,
        angle_millideg=state.angle_millideg,
        angle_rad=state.angle_millideg * _MILLIDEG_TO_RAD,
        status_flags=state.status_flags,
        checksum_valid=state.valid,
        schema_version=PROTO_VERSION,
    )


def fields_from_frame(data: bytes) -> PodFields:
    """Decode an 8-byte CAN payload via the frozen codec and map to fields.

    Raises ``ValueError`` (from the codec) if ``data`` is not 8 bytes. A frame
    with a bad checksum decodes successfully with ``checksum_valid=False``.
    """
    return fields_from_state(decode_state(data))
