"""Golden wire-vector pin for the LoRa codec (ICD-3, SR-1).

The behavior tests in `test_comms_protocol.py` encode *then* decode, so they pass even if the
encoder silently drifts (a changed struct format, byte order, or HMAC truncation) — both
directions move together. This test pins the **exact committed bytes** in
`firmware/alarm_node/test/wire_vectors.json` so any such drift fails loudly, and so the hub
and the ESP32 firmware are provably checking against one identical artifact (the firmware
test reproduces the same frame_hex/hmac_hex).
"""

from __future__ import annotations

import json
from pathlib import Path

from autosentry.comms.protocol import HMAC_LEN, Packet, _sign, decode, encode
from autosentry.contracts import MsgType

_VECTORS = (
    Path(__file__).resolve().parents[2] / "firmware" / "alarm_node" / "test" / "wire_vectors.json"
)


def _load() -> dict:
    return json.loads(_VECTORS.read_text())


def test_vector_file_exists_and_is_populated():
    data = _load()
    assert data["hmac_len"] == HMAC_LEN
    assert len(data["vectors"]) >= 2


def test_encoder_reproduces_each_golden_frame():
    data = _load()
    key = data["key_utf8"].encode()
    for v in data["vectors"]:
        pkt = Packet(
            type=MsgType[v["type"]],
            net_id=v["net_id"],
            src=v["src"],
            dst=v["dst"],
            counter=v["counter"],
            payload=bytes.fromhex(v["payload_hex"]),
        )
        raw = encode(pkt, key)
        assert raw.hex() == v["frame_hex"], f"{v['name']}: frame drifted from the golden vector"
        assert raw[-HMAC_LEN:].hex() == v["hmac_hex"], f"{v['name']}: HMAC tag drifted"


def test_golden_frames_decode_back_to_their_fields():
    data = _load()
    key = data["key_utf8"].encode()
    for v in data["vectors"]:
        out = decode(bytes.fromhex(v["frame_hex"]), key)
        assert out.type == MsgType[v["type"]]
        assert out.src == v["src"] and out.dst == v["dst"]
        assert out.counter == v["counter"]
        assert out.payload == bytes.fromhex(v["payload_hex"])


def test_recorded_hmac_matches_independent_sign():
    # Recompute the tag straight from _sign over the body — independent of encode()'s framing.
    data = _load()
    key = data["key_utf8"].encode()
    for v in data["vectors"]:
        frame = bytes.fromhex(v["frame_hex"])
        body = frame[:-HMAC_LEN]
        assert _sign(key, body).hex() == v["hmac_hex"], f"{v['name']}: _sign disagrees"
