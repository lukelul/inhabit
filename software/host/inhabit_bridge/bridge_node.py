"""ROS 2 (Jazzy) node: CAN frames -> JointPodState.

Reads raw CAN frames from a :class:`~inhabit_bridge.sources.CanSource`, decodes
them via the FROZEN codec, and publishes ``inhabit_msgs/JointPodState``.

Time-sync (first-class)
-----------------------
The receive timestamp is read from a SINGLE MONOTONIC clock (``time.monotonic_ns``)
at the instant each frame leaves the source -- NEVER wall clock. That nanosecond
value is written verbatim into ``header.stamp`` (sec + nanosec split). Because it
is monotonic, ``header.stamp`` is a stable anchor that downstream PVT logging uses
to align CAN, video, and tactile streams. Consumers must treat the stamp as a
monotonic host clock, not POSIX/UTC time.

Bad-checksum policy
-------------------
Frames whose codec checksum fails are STILL PUBLISHED, with
``checksum_valid=False``, and a throttled warning is logged. Rationale: the data
pipeline (Track 3) must see dropouts/corruption to compute link quality and to
quarantine episodes; silently dropping frames would hide bus faults
(root CLAUDE.md: "fail loud"). Downstream filters on ``checksum_valid``.

This module imports rclpy and inhabit_msgs lazily (inside functions) so the
ROS-independent parts of the package remain importable without a ROS install.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inhabit_bridge.conversion import PodFields, fields_from_frame
from inhabit_bridge.sources import CanFrame, CanSource, ReplaySource, SimSource
from inhabit_bridge.transport_source import TransportSource

if TYPE_CHECKING:  # pragma: no cover - typing only, not imported at runtime in tests
    from rclpy.node import Node as _NodeBase
else:
    _NodeBase = object


_NS_PER_SEC = 1_000_000_000


def stamp_from_monotonic_ns(monotonic_ns: int) -> tuple[int, int]:
    """Split a monotonic-ns timestamp into (sec, nanosec) for builtin Time.

    Pure helper (no ROS) so the time-sync math is unit-testable.
    """
    return monotonic_ns // _NS_PER_SEC, monotonic_ns % _NS_PER_SEC


def build_message(frame: CanFrame, msg_cls: Any, frame_id: str = "joint_pod") -> Any:
    """Construct a JointPodState message from a received CAN frame.

    ``msg_cls`` is injected (the generated ``inhabit_msgs.msg.JointPodState``)
    so this function carries no hard ROS import and stays testable with a stub.
    Returns the populated message; raises ``ValueError`` if the frame payload is
    not 8 bytes (propagated from the codec).
    """
    fields: PodFields = fields_from_frame(frame.data)
    sec, nanosec = stamp_from_monotonic_ns(frame.rx_monotonic_ns)

    msg = msg_cls()
    msg.header.stamp.sec = sec
    msg.header.stamp.nanosec = nanosec
    msg.header.frame_id = frame_id
    msg.node_id = fields.node_id
    msg.chain_index = fields.chain_index
    msg.angle_raw_adc = fields.angle_raw_adc
    msg.angle_millideg = fields.angle_millideg
    msg.angle_rad = fields.angle_rad
    msg.status_flags = fields.status_flags
    msg.checksum_valid = fields.checksum_valid
    msg.schema_version = fields.schema_version
    return msg


def _make_source(name: str, channel: str, path: str = "") -> CanSource:
    """Resolve a source by name. One interface, swappable implementations.

    ``file`` and ``socketcan`` are backed by host/transport (file replay and
    Linux socketcan respectively), exposed through :class:`TransportSource` so the
    transport layer is a first-class bridge input. ``replay``/``sim`` remain the
    in-memory/synthetic sources. Decoding always happens downstream in the frozen
    codec -- never re-implemented here.
    """
    name = name.lower()
    if name == "replay":
        # Empty replay by default; real captures are loaded by callers/tests.
        return ReplaySource([])
    if name == "sim":
        return SimSource(num_pods=2, count=100)
    if name == "file":
        if not path:
            raise ValueError("source='file' requires a 'path' to a .canlog recording")
        from transport.file import FileReplayTransport  # noqa: PLC0415

        # File replay is finite: stop when the recording is exhausted.
        return TransportSource(FileReplayTransport(path), stop_on_none=True)
    if name == "socketcan":
        from transport.socketcan import SocketCanTransport  # noqa: PLC0415

        # Live bus: a None recv is a timeout, not end-of-stream -- keep reading.
        return TransportSource(SocketCanTransport(channel=channel), stop_on_none=False)
    if name == "slcan":
        from transport.slcan import SlcanTransport  # noqa: PLC0415

        # SLCAN over USB-serial: same live-bus semantics as socketcan.
        return TransportSource(SlcanTransport(port=channel), stop_on_none=False)
    raise ValueError(f"unknown can source '{name}' (expected sim|replay|file|socketcan|slcan)")


def _make_node() -> _NodeBase:
    """Construct the rclpy node (lazy ROS imports)."""
    from rclpy.node import Node  # noqa: PLC0415
    from rclpy.qos import (  # noqa: PLC0415
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )

    from inhabit_msgs.msg import JointPodState  # type: ignore[attr-defined]  # noqa: PLC0415

    class CanBridgeNode(Node):  # type: ignore[misc, valid-type]
        """Pulls frames from a CanSource on a worker thread and publishes them."""

        def __init__(self) -> None:
            super().__init__("inhabit_can_bridge")

            # Parameters (documented in README / launch file).
            self.declare_parameter("source", "sim")
            self.declare_parameter("channel", "can0")
            self.declare_parameter("path", "")
            self.declare_parameter("frame_id", "joint_pod")
            self.declare_parameter("topic", "joint_pod_state")

            source_name = str(self.get_parameter("source").value)
            channel = str(self.get_parameter("channel").value)
            path = str(self.get_parameter("path").value)
            self._frame_id = str(self.get_parameter("frame_id").value)
            topic = str(self.get_parameter("topic").value)

            # QoS: sensor-style telemetry. BEST_EFFORT + small KEEP_LAST depth
            # matches a high-rate CAN stream where the freshest sample wins and
            # occasional loss is acceptable; VOLATILE since late joiners do not
            # need historical pod state.
            qos = QoSProfile(
                history=HistoryPolicy.KEEP_LAST,
                depth=10,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )
            self._pub = self.create_publisher(JointPodState, topic, qos)
            self._msg_cls = JointPodState
            self._source = _make_source(source_name, channel, path)

            self.get_logger().info(
                f"inhabit_can_bridge: source={source_name} topic={topic} "
                f"frame_id={self._frame_id} (stamp=monotonic host RX clock)"
            )

            import threading  # noqa: PLC0415

            self._stop = threading.Event()
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._source.open()
            self._worker.start()

        def _run(self) -> None:
            try:
                for frame in self._source.frames():
                    if self._stop.is_set():
                        break
                    self._publish(frame)
            except Exception as exc:  # log loud, do not crash the executor
                self.get_logger().error(f"CAN source error: {exc!r}")

        def _publish(self, frame: CanFrame) -> None:
            try:
                msg = build_message(frame, self._msg_cls, self._frame_id)
            except ValueError as exc:
                self.get_logger().warning(f"dropping malformed frame: {exc}")
                return
            if not msg.checksum_valid:
                # Fail loud, but still publish so Track 3 sees corruption.
                self.get_logger().warning(
                    f"checksum FAIL node_id={msg.node_id} chain_index={msg.chain_index} "
                    "(publishing with checksum_valid=False)",
                    throttle_duration_sec=1.0,
                )
            self._pub.publish(msg)

        def destroy_node(self) -> bool:
            self._stop.set()
            self._source.close()
            return bool(super().destroy_node())

    return CanBridgeNode()


def main(args: list[str] | None = None) -> None:
    """Console entry point: spin the CAN bridge node (requires a ROS env)."""
    import rclpy  # noqa: PLC0415

    rclpy.init(args=args)
    node = _make_node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
