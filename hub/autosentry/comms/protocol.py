"""LoRa air-protocol codec (ICD-3) — authoritative wire format.

Implements signing (HMAC-SHA256 truncated) and anti-replay (per-source monotonic
counter) per requirement SR-1 and docs/COMMS_PROTOCOL.md. Pure stdlib so it is fully
unit-testable on any machine (no radio hardware). The firmware (firmware/alarm_node)
implements the byte-compatible counterpart.

Wire layout (bytes):
    ver(1) | type(1) | net_id(1) | src(1) | dst(1) | counter(4 LE) | payload(n) | hmac(8)

Security properties:
- An attacker without the pre-shared key cannot forge a packet (HMAC).
- A captured packet cannot be replayed (monotonic counter, checked by ReplayWindow).
"""

from __future__ import annotations

import hmac
import struct
from dataclasses import dataclass
from hashlib import sha256

from autosentry.contracts import MsgType

VERSION = 0x01
HEADER_FMT = "<BBBBBI"  # ver, type, net_id, src, dst, counter
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 9
HMAC_LEN = 8
BROADCAST = 0xFF

# Wire codes for MsgType (stable on the air; do not reorder).
_TYPE_TO_CODE = {
    MsgType.ALARM: 1,
    MsgType.ACK: 2,
    MsgType.HEARTBEAT: 3,
    MsgType.HEARTBEAT_ACK: 4,
    MsgType.STATUS: 5,
    MsgType.CONFIG: 6,
    MsgType.TEST: 7,
}
_CODE_TO_TYPE = {v: k for k, v in _TYPE_TO_CODE.items()}


class PacketError(Exception):
    """Malformed packet or failed authentication."""


class ReplayError(PacketError):
    """A packet whose counter is not newer than the last seen for its source."""


@dataclass
class Packet:
    type: MsgType
    net_id: int
    src: int
    dst: int
    counter: int
    payload: bytes = b""


def _sign(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, body, sha256).digest()[:HMAC_LEN]


def encode(pkt: Packet, key: bytes) -> bytes:
    """Serialize and sign a packet."""
    if pkt.type not in _TYPE_TO_CODE:
        raise PacketError(f"unknown message type: {pkt.type}")
    if not (0 <= pkt.counter <= 0xFFFFFFFF):
        raise PacketError("counter out of range")
    header = struct.pack(
        HEADER_FMT,
        VERSION,
        _TYPE_TO_CODE[pkt.type],
        pkt.net_id & 0xFF,
        pkt.src & 0xFF,
        pkt.dst & 0xFF,
        pkt.counter,
    )
    body = header + pkt.payload
    return body + _sign(key, body)


def decode(raw: bytes, key: bytes) -> Packet:
    """Verify and parse a packet. Raises PacketError if auth fails or it's malformed."""
    if len(raw) < HEADER_LEN + HMAC_LEN:
        raise PacketError("packet too short")
    body, tag = raw[:-HMAC_LEN], raw[-HMAC_LEN:]
    if not hmac.compare_digest(tag, _sign(key, body)):
        raise PacketError("HMAC mismatch")  # forged or corrupted — drop + log (SR-1)
    ver, type_code, net_id, src, dst, counter = struct.unpack(HEADER_FMT, body[:HEADER_LEN])
    if ver != VERSION:
        raise PacketError(f"unsupported version: {ver}")
    if type_code not in _CODE_TO_TYPE:
        raise PacketError(f"unknown type code: {type_code}")
    return Packet(
        type=_CODE_TO_TYPE[type_code],
        net_id=net_id,
        src=src,
        dst=dst,
        counter=counter,
        payload=body[HEADER_LEN:],
    )


class ReplayWindow:
    """Tracks the last-seen counter per source to reject replays (SR-1).

    A small forward window is implicitly allowed (any strictly-greater counter is
    accepted), which tolerates lost packets while still rejecting replays.
    """

    def __init__(self) -> None:
        self._last: dict[int, int] = {}

    def check_and_update(self, pkt: Packet) -> None:
        """Raise ReplayError if pkt.counter is not newer than the last seen for pkt.src."""
        last = self._last.get(pkt.src)
        if last is not None and pkt.counter <= last:
            raise ReplayError(f"replay from src={pkt.src}: counter {pkt.counter} <= {last}")
        self._last[pkt.src] = pkt.counter

    def last_counter(self, src: int) -> int | None:
        return self._last.get(src)
