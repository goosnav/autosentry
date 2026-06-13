#!/usr/bin/env python3
"""Generate the golden cross-implementation wire vectors (ICD-3, SR-1).

The hub codec `hub/autosentry/comms/protocol.py` is the **authoritative** wire format; the
ESP32 firmware (`firmware/alarm_node`) must reproduce these exact bytes. This script emits a
frozen JSON artifact (`firmware/alarm_node/test/wire_vectors.json`) containing, for a fixed
key and packet, the full signed frame and its truncated HMAC tag in hex.

Both sides pin to it: `hub/tests/test_wire_vectors.py` asserts the live encoder still
produces these bytes (catching silent encoder drift that round-trip tests cannot), and the
firmware test asserts its parser/HMAC reproduces them.

Run only on an intentional, ICD-documented format change:
    python scripts/gen_wire_vectors.py        # rewrites the JSON in place
"""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub"))

from autosentry.comms.protocol import HEADER_FMT, HMAC_LEN, Packet, encode  # noqa: E402
from autosentry.comms.transport import CMD_RX, CMD_SEND, frame  # noqa: E402
from autosentry.contracts import MsgType  # noqa: E402

KEY = b"autosentry-golden-vector-key-001"

_OUT = os.path.join(
    os.path.dirname(__file__), "..", "firmware", "alarm_node", "test", "wire_vectors.json"
)

# (name, packet) — the safety-critical ALARM broadcast and a node heartbeat.
_CASES = [
    (
        "alarm_broadcast",
        Packet(MsgType.ALARM, net_id=1, src=0, dst=0xFF, counter=7, payload=bytes([4, 2])),
    ),
    (
        "node_heartbeat",
        Packet(
            MsgType.HEARTBEAT, net_id=1, src=1, dst=0, counter=100, payload=struct.pack("<I", 3600)
        ),
    ),
]


def build() -> dict:
    vectors = []
    for name, pkt in _CASES:
        raw = encode(pkt, KEY)
        vectors.append(
            {
                "name": name,
                "type": pkt.type.value if hasattr(pkt.type, "value") else str(pkt.type),
                "net_id": pkt.net_id,
                "src": pkt.src,
                "dst": pkt.dst,
                "counter": pkt.counter,
                "payload_hex": pkt.payload.hex(),
                "frame_hex": raw.hex(),
                "hmac_hex": raw[-HMAC_LEN:].hex(),
            }
        )
    # ICD-2 serial framing (COBS + CRC8). The gateway firmware must reproduce these exactly:
    # a SEND frame carrying the alarm air bytes, and an RX frame carrying rssi/snr + air.
    alarm_air = bytes.fromhex(vectors[0]["frame_hex"])
    send_frame = frame(CMD_SEND, alarm_air)
    rx_payload = bytes([0xCE, 0x07]) + alarm_air  # rssi=-50 (0xCE), snr=7, then air
    rx_frame = frame(CMD_RX, rx_payload)
    serial_vectors = [
        {
            "name": "serial_send_alarm",
            "cmd": CMD_SEND,
            "data_hex": alarm_air.hex(),
            "frame_hex": send_frame.hex(),  # includes trailing 0x00 delimiter
        },
        {
            "name": "serial_rx_alarm",
            "cmd": CMD_RX,
            "rssi": -50,
            "snr": 7,
            "data_hex": rx_payload.hex(),
            "frame_hex": rx_frame.hex(),
        },
    ]

    return {
        "_README": (
            "Golden cross-implementation wire vectors. ICD-3 (vectors[]) is the LoRa air "
            "format signed by hub/autosentry/comms/protocol.py; ICD-2 (serial_vectors[]) is "
            "the COBS+CRC8 host↔gateway framing from comms/transport.py. Both are "
            "authoritative on the hub side; firmware/alarm_node MUST reproduce frame_hex "
            "byte-for-byte. Regenerate via scripts/gen_wire_vectors.py only on an "
            "intentional, ICD-documented format change."
        ),
        "key_utf8": KEY.decode(),
        "header_fmt": HEADER_FMT,
        "hmac_len": HMAC_LEN,
        "vectors": vectors,
        "serial_vectors": serial_vectors,
    }


def main() -> int:
    data = build()
    with open(os.path.normpath(_OUT), "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"wrote {len(data['vectors'])} vectors -> {os.path.normpath(_OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
