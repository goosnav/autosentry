"""Unit tests for type-specific mesh payload codecs (ICD-3 §4).

Round-trips each payload and pins the little-endian byte layout that the firmware
(firmware/alarm_node/src/main.cpp) must match byte-for-byte.
"""

from __future__ import annotations

from autosentry.comms import payloads


def test_alarm_round_trip():
    p = payloads.AlarmPayload(level=4, zone_id=7, pattern=2)
    assert payloads.decode_alarm(payloads.encode_alarm(p)) == p


def test_alarm_layout_is_three_little_endian_bytes():
    raw = payloads.encode_alarm(payloads.AlarmPayload(level=3, zone_id=1, pattern=0))
    assert raw == bytes([3, 1, 0])
    assert len(raw) == payloads.ALARM_LEN == 3


def test_ref_round_trip():
    assert payloads.decode_ref(payloads.encode_ref(0xDEADBEEF)) == 0xDEADBEEF


def test_ref_is_little_endian_u32():
    assert payloads.encode_ref(1) == bytes([1, 0, 0, 0])


def test_heartbeat_round_trip():
    assert payloads.decode_heartbeat(payloads.encode_heartbeat(123456)) == 123456


def test_status_round_trip():
    s = payloads.StatusPayload(battery_mv=3700, on_battery=True, siren_active=False, fw_ver=2)
    assert payloads.decode_status(payloads.encode_status(s)) == s


def test_status_layout():
    raw = payloads.encode_status(
        payloads.StatusPayload(battery_mv=0x0102, on_battery=True, siren_active=False, fw_ver=9)
    )
    # battery_mv little-endian u16, then three bytes
    assert raw == bytes([0x02, 0x01, 1, 0, 9])
    assert len(raw) == payloads.STATUS_LEN


def test_decode_tolerates_trailing_bytes():
    # A decoder must read only its own field width and ignore any extra trailing bytes.
    raw = payloads.encode_ref(42) + b"\xff\xff"
    assert payloads.decode_ref(raw) == 42
