"""Unit tests for the LoRa air-protocol codec (ICD-3, SR-1).

These are the wire-format and security vectors the firmware must match byte-for-byte:
- round-trip encode/decode,
- HMAC rejects forgery/corruption (a wrong key or flipped bit must not verify),
- the monotonic counter rejects replays per source.
"""

from __future__ import annotations

import struct

import pytest

from autosentry.comms.protocol import (
    HEADER_FMT,
    HEADER_LEN,
    HMAC_LEN,
    VERSION,
    Packet,
    PacketError,
    ReplayError,
    ReplayWindow,
    _sign,
    decode,
    encode,
)
from autosentry.contracts import MsgType

KEY = b"unit-test-preshared-key"
OTHER_KEY = b"a-different-key--------"


def _pkt(counter: int = 1, src: int = 0, dst: int = 0xFF, payload: bytes = b"") -> Packet:
    return Packet(type=MsgType.ALARM, net_id=1, src=src, dst=dst, counter=counter, payload=payload)


def test_round_trip():
    p = _pkt(counter=42, payload=b"\x03\x01")
    raw = encode(p, KEY)
    out = decode(raw, KEY)
    assert out == p


def test_encoded_length():
    raw = encode(_pkt(payload=b"abc"), KEY)
    assert len(raw) == HEADER_LEN + 3 + HMAC_LEN


def test_wrong_key_fails_auth():
    raw = encode(_pkt(), KEY)
    with pytest.raises(PacketError):
        decode(raw, OTHER_KEY)


def test_bit_flip_fails_auth():
    raw = bytearray(encode(_pkt(payload=b"hello"), KEY))
    raw[HEADER_LEN] ^= 0x01  # corrupt the first payload byte
    with pytest.raises(PacketError):
        decode(bytes(raw), KEY)


def test_truncated_packet_rejected():
    with pytest.raises(PacketError):
        decode(b"\x00\x01", KEY)


def test_all_message_types_round_trip():
    for t in MsgType:
        p = Packet(type=t, net_id=2, src=5, dst=7, counter=10, payload=b"\x01")
        assert decode(encode(p, KEY), KEY).type == t


def test_replay_window_accepts_monotonic():
    w = ReplayWindow()
    w.check_and_update(_pkt(counter=1, src=3))
    w.check_and_update(_pkt(counter=2, src=3))
    w.check_and_update(_pkt(counter=5, src=3))  # gaps allowed (lost packets)
    assert w.last_counter(3) == 5


def test_replay_window_rejects_replay():
    w = ReplayWindow()
    w.check_and_update(_pkt(counter=5, src=3))
    with pytest.raises(ReplayError):
        w.check_and_update(_pkt(counter=5, src=3))  # equal -> replay
    with pytest.raises(ReplayError):
        w.check_and_update(_pkt(counter=4, src=3))  # older -> replay


def test_replay_window_is_per_source():
    w = ReplayWindow()
    w.check_and_update(_pkt(counter=9, src=1))
    # A different source with a low counter is independent and must be accepted.
    w.check_and_update(_pkt(counter=1, src=2))
    assert w.last_counter(1) == 9
    assert w.last_counter(2) == 1


def test_counter_out_of_range_rejected():
    with pytest.raises(PacketError):
        encode(_pkt(counter=2**32), KEY)


def test_encode_rejects_unknown_message_type():
    bad = Packet(type="BOGUS", net_id=1, src=0, dst=1, counter=1)  # type: ignore[arg-type]
    with pytest.raises(PacketError):
        encode(bad, KEY)


def test_decode_rejects_unsupported_version():
    # A correctly-signed frame with a bad version byte must still be rejected (the HMAC
    # covers the version, so this proves version checking, not just auth).
    body = struct.pack(HEADER_FMT, VERSION + 1, 1, 1, 0, 1, 7)
    raw = body + _sign(KEY, body)
    with pytest.raises(PacketError):
        decode(raw, KEY)


def test_decode_rejects_unknown_type_code():
    body = struct.pack(HEADER_FMT, VERSION, 99, 1, 0, 1, 7)  # type code 99 is undefined
    raw = body + _sign(KEY, body)
    with pytest.raises(PacketError):
        decode(raw, KEY)
