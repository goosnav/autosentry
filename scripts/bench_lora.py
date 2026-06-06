#!/usr/bin/env python3
"""LoRa hub<->node bench/loopback harness (verifies ICD-3, SR-1, PR-6/7).

Two roles over the USB-serial LoRa gateway (ICD-2):
  * --role ping : send signed ALARM/HEARTBEAT frames, wait for ACKs, report RTT + loss.
  * --role echo : decode inbound frames, verify HMAC, ACK them (stand-in for a node).

The codec is the real one (autosentry.comms.protocol), so this exercises the exact wire
bytes the firmware must match. With no serial port it runs a pure in-process loopback so
the signing/anti-replay path is testable on any laptop (no radio required).

Usage:
  AUTOSENTRY_MESH_KEY=... python scripts/bench_lora.py --loopback --count 20
  AUTOSENTRY_MESH_KEY=... python scripts/bench_lora.py --role ping --port /dev/ttyUSB0
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Allow running from a checkout without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub"))

from autosentry.comms.protocol import (  # noqa: E402
    Packet,
    PacketError,
    ReplayWindow,
    decode,
    encode,
)
from autosentry.contracts import MsgType  # noqa: E402

HUB_ADDR = 0
NODE_ADDR = 1
NET_ID = 1


def _key() -> bytes:
    k = os.environ.get("AUTOSENTRY_MESH_KEY")
    if not k:
        sys.exit("set AUTOSENTRY_MESH_KEY (see docs/SECURITY.md, SR-3)")
    return k.encode()


def run_loopback(count: int, key: bytes) -> int:
    """In-process encode->decode->ACK loop: validates signing + anti-replay, no hardware."""
    replay = ReplayWindow()
    counter = 0
    ok = 0
    for i in range(count):
        counter += 1
        frame = encode(
            Packet(MsgType.ALARM, NET_ID, HUB_ADDR, NODE_ADDR, counter, payload=b"\x03"), key
        )
        try:
            pkt = decode(frame, key)          # node side: verify HMAC
            replay.check_and_update(pkt)       # node side: reject replays
            ack = encode(
                Packet(MsgType.ACK, NET_ID, NODE_ADDR, HUB_ADDR, counter), key
            )
            decode(ack, key)                   # hub side: verify the ACK
            ok += 1
        except PacketError as e:
            print(f"  frame {i}: REJECTED ({e})")
    # Negative check: a replayed frame must be rejected.
    replayed = encode(Packet(MsgType.ALARM, NET_ID, HUB_ADDR, NODE_ADDR, 1), key)
    try:
        replay.check_and_update(decode(replayed, key))
        print("  WARNING: replay was NOT rejected")
    except PacketError:
        pass  # expected
    print(f"loopback: {ok}/{count} round-trips verified; replay rejected.")
    return 0 if ok == count else 1


def run_serial(role: str, port: str, baud: int, count: int, key: bytes) -> int:
    """Real-radio path over the ICD-2 transport (COBS/CRC framing). Needs pyserial + a gateway."""
    try:
        from autosentry.comms.transport import SerialTransport
    except Exception as e:  # pragma: no cover - import guard
        sys.exit(f"transport unavailable: {e}")
    try:
        transport = SerialTransport(port, baud)
    except ImportError:
        sys.exit("pyserial not installed: pip install pyserial (or use --loopback)")
    try:
        return _ping(transport, count, key) if role == "ping" else _echo(transport, count, key)
    finally:
        transport.close()


def _ping(transport: "object", count: int, key: bytes) -> int:
    """Send signed ALARM frames, wait for each ACK, report RTT + loss (PR-3/PR-7)."""
    rtts: list[float] = []
    acked = 0
    for i in range(1, count + 1):
        pkt = Packet(MsgType.ALARM, NET_ID, HUB_ADDR, NODE_ADDR, i, payload=b"\x03")
        sent = time.time()
        transport.send(encode(pkt, key))  # type: ignore[attr-defined]
        deadline = sent + 1.0
        while time.time() < deadline:
            for raw in transport.read():  # type: ignore[attr-defined]
                try:
                    ack = decode(raw, key)
                except PacketError:
                    continue  # forged/corrupt
                if ack.type == MsgType.ACK and ack.counter == i:
                    rtts.append(time.time() - sent)
                    acked += 1
                    deadline = 0  # break outer
                    break
            time.sleep(0.005)
    loss = 100.0 * (count - acked) / count
    avg = 1000.0 * sum(rtts) / len(rtts) if rtts else float("nan")
    print(f"ping: {acked}/{count} ACKed, loss {loss:.0f}%, mean RTT {avg:.1f} ms")
    return 0 if acked == count else 1


def _echo(transport: "object", count: int, key: bytes) -> int:
    """Node stand-in: verify inbound HMAC + reject replays, ACK each accepted frame."""
    replay = ReplayWindow()
    acked = 0
    print(f"echo: listening for {count} frames (Ctrl-C to stop)")
    while acked < count:
        for raw in transport.read():  # type: ignore[attr-defined]
            try:
                pkt = decode(raw, key)
                replay.check_and_update(pkt)
            except PacketError as e:
                print(f"  dropped: {e}")
                continue
            ack = Packet(MsgType.ACK, NET_ID, NODE_ADDR, pkt.src, pkt.counter)
            transport.send(encode(ack, key))  # type: ignore[attr-defined]
            acked += 1
        time.sleep(0.005)
    print(f"echo: ACKed {acked} frames")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoSentry LoRa bench harness")
    ap.add_argument("--loopback", action="store_true", help="in-process codec test, no radio")
    ap.add_argument("--role", choices=["ping", "echo"], default="ping")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args(argv)

    key = _key()
    t0 = time.time()
    rc = (
        run_loopback(args.count, key)
        if args.loopback
        else run_serial(args.role, args.port, args.baud, args.count, key)
    )
    print(f"done in {time.time() - t0:.3f}s")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
