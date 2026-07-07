"""CLI entry point: ``python -m tools.can_replay {record,replay}`` (run from repo root).

record: capture live CAN frames from a socketcan interface to a .canlog file.
replay: read a .canlog file and decode each frame via the frozen codec, printing
        decoded state to stdout so the whole stack can be exercised with no board.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure host/ is importable when running from repo root.
_HOST_DIR = Path(__file__).resolve().parents[2] / "host"
if str(_HOST_DIR) not in sys.path:
    sys.path.insert(0, str(_HOST_DIR))


def _cmd_record(args: argparse.Namespace) -> None:
    from transport.file import FileRecorder  # noqa: PLC0415

    if args.interface == "slcan":
        from transport.slcan import SlcanTransport  # noqa: PLC0415

        port = args.channel if args.channel is not None else "/dev/ttyACM0"
        transport = SlcanTransport(port=port, bitrate=args.bitrate)
    else:
        from transport.socketcan import SocketCanTransport  # noqa: PLC0415

        channel = args.channel if args.channel is not None else "can0"
        transport = SocketCanTransport(channel=channel, bitrate=args.bitrate)

    recorder = FileRecorder(args.output)
    count = 0

    iface_channel = port if args.interface == "slcan" else channel
    print(f"Recording [{args.interface}] {iface_channel} -> {args.output}  (Ctrl-C to stop)")
    with transport, recorder:
        while True:
            frame = transport.recv(timeout_s=1.0)
            if frame is not None:
                recorder.write(frame)
                count += 1
                print(f"  [{count}] id=0x{frame.can_id:03X} data={frame.data.hex()} t={frame.rx_monotonic_ns}")


def _cmd_replay(args: argparse.Namespace) -> None:
    from inhabit_can.codec import decode_state  # noqa: PLC0415
    from transport import FileReplayTransport  # noqa: PLC0415

    transport = FileReplayTransport(args.input)

    print(f"Replaying {args.input}")
    with transport:
        while True:
            frame = transport.recv()
            if frame is None:
                break
            st = decode_state(frame.data)
            print(
                f"  id=0x{frame.can_id:03X}  node={st.node_id}  chain={st.chain_index}"
                f"  angle={st.angle_millideg / 1000:.3f} deg"
                f"  raw={st.angle_raw_adc}  flags=0x{st.status_flags:02X}"
                f"  valid={st.valid}"
            )
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tools.can_replay", description="Record / replay .canlog files"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="Capture live CAN frames to a .canlog file")
    rec.add_argument("-o", "--output", default="capture.canlog", help="Output file (default: capture.canlog)")
    rec.add_argument("-c", "--channel", default=None, help="CAN channel: socketcan iface (default: can0) or serial port for slcan (default: /dev/ttyACM0)")
    rec.add_argument("-b", "--bitrate", type=int, default=500_000, help="Bitrate (default: 500000)")
    rec.add_argument(
        "-i", "--interface", default="socketcan", choices=["socketcan", "slcan"],
        help="CAN interface type (default: socketcan)",
    )

    rep = sub.add_parser("replay", help="Replay a .canlog file through the codec")
    rep.add_argument("input", help=".canlog file to replay")

    args = parser.parse_args()
    if args.command == "record":
        _cmd_record(args)
    elif args.command == "replay":
        _cmd_replay(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
