"""Unit tests for ICD-2 serial framing: CRC8, COBS, frame/unframe.

The pure framing layer is what guarantees we never mistake a corrupt or truncated
serial read for a valid command. SerialTransport itself is hardware and not unit-tested.
"""

from __future__ import annotations

import pytest

from autosentry.comms.transport import (
    CMD_SEND,
    DELIMITER,
    cobs_decode,
    cobs_encode,
    crc8,
    frame,
    unframe,
)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x00",
        b"\x00\x00\x00",
        b"hello",
        bytes(range(256)),
        b"\x01" * 600,  # forces a 0xFF COBS block split
        bytes([0]) * 600,
    ],
)
def test_cobs_round_trip(data):
    encoded = cobs_encode(data)
    assert DELIMITER not in encoded  # the whole point: no interior zero byte
    assert cobs_decode(encoded) == data


def test_crc8_known_vector():
    # CRC-8 poly 0x07, init 0x00 over "123456789" is the canonical 0xF4.
    assert crc8(b"123456789") == 0xF4


def test_frame_unframe_round_trip():
    air = b"\x01\x02\x03payload"
    encoded = frame(CMD_SEND, air)
    assert encoded[-1] == DELIMITER
    cmd, data = unframe(encoded[:-1])  # unframe takes the body without the delimiter
    assert cmd == CMD_SEND
    assert data == air


def test_unframe_rejects_crc_corruption():
    encoded = bytearray(frame(CMD_SEND, b"abcd")[:-1])
    encoded[-1] ^= 0xFF  # flip the CRC byte (still a valid COBS code region)
    with pytest.raises(ValueError):
        unframe(bytes(encoded))


def test_unframe_rejects_short_frame():
    with pytest.raises(ValueError):
        unframe(cobs_encode(b"\x01"))  # too short to hold cmd|len|crc


def test_cobs_decode_rejects_zero_code_byte():
    with pytest.raises(ValueError):
        cobs_decode(b"\x00")
