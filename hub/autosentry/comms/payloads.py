"""Type-specific mesh payloads (ICD-3 §4 / docs/COMMS_PROTOCOL.md §4).

The packet header + HMAC live in comms.protocol; this module owns the *payload* bytes for
each MsgType. Layouts are little-endian to match the header and the firmware
(firmware/alarm_node/src/main.cpp) byte-for-byte. The Python codec is the golden reference.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_ALARM_FMT = "<BBB"  # level, zone_id, pattern
_REF_FMT = "<I"  # ref_counter (ACK / HEARTBEAT_ACK)
_UPTIME_FMT = "<I"  # uptime_s (HEARTBEAT)
_STATUS_FMT = "<HBBB"  # battery_mv, on_battery, siren_active, fw_ver

ALARM_LEN = struct.calcsize(_ALARM_FMT)
STATUS_LEN = struct.calcsize(_STATUS_FMT)


@dataclass(frozen=True)
class AlarmPayload:
    level: int
    zone_id: int
    pattern: int


@dataclass(frozen=True)
class StatusPayload:
    battery_mv: int
    on_battery: bool
    siren_active: bool
    fw_ver: int


def encode_alarm(p: AlarmPayload) -> bytes:
    return struct.pack(_ALARM_FMT, p.level & 0xFF, p.zone_id & 0xFF, p.pattern & 0xFF)


def decode_alarm(payload: bytes) -> AlarmPayload:
    level, zone_id, pattern = struct.unpack(_ALARM_FMT, payload[:ALARM_LEN])
    return AlarmPayload(level=level, zone_id=zone_id, pattern=pattern)


def encode_ref(ref_counter: int) -> bytes:
    """ACK / HEARTBEAT_ACK payload: the counter of the frame being acknowledged."""
    return struct.pack(_REF_FMT, ref_counter & 0xFFFFFFFF)


def decode_ref(payload: bytes) -> int:
    return int(struct.unpack(_REF_FMT, payload[:4])[0])


def encode_heartbeat(uptime_s: int) -> bytes:
    return struct.pack(_UPTIME_FMT, uptime_s & 0xFFFFFFFF)


def decode_heartbeat(payload: bytes) -> int:
    return int(struct.unpack(_UPTIME_FMT, payload[:4])[0])


def encode_status(s: StatusPayload) -> bytes:
    return struct.pack(
        _STATUS_FMT, s.battery_mv & 0xFFFF, int(s.on_battery), int(s.siren_active), s.fw_ver & 0xFF
    )


def decode_status(payload: bytes) -> StatusPayload:
    battery_mv, on_battery, siren_active, fw_ver = struct.unpack(_STATUS_FMT, payload[:STATUS_LEN])
    return StatusPayload(
        battery_mv=battery_mv,
        on_battery=bool(on_battery),
        siren_active=bool(siren_active),
        fw_ver=fw_ver,
    )
