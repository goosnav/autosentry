"""ICD-2 — Hub ↔ LoRa radio gateway serial transport.

The gateway is a dumb radio modem: the hub hands it already-signed air bytes (ICD-3) and it
transmits them; inbound air bytes come back as RX events. The local wire is COBS-framed with
a 1-byte command type, a length, and a CRC8 over the frame, delimited by 0x00 (COBS
guarantees no interior zero byte, so 0x00 is an unambiguous frame boundary).

Pure framing (cobs/crc8/frame/unframe) is unit-tested here; `SerialTransport` lazy-imports
pyserial so the package imports without it.

Frame body (before COBS): cmd(1) | len(1) | data(len) | crc8(1)
  - host→gw  SEND(0x01): data = air bytes to transmit.
  - gw→host  RX(0x02):   data = rssi(int8) | snr(int8) | air bytes received.
"""

from __future__ import annotations

from typing import Protocol

CMD_SEND = 0x01
CMD_RX = 0x02
DELIMITER = 0x00


def crc8(data: bytes) -> int:
    """CRC-8 (poly 0x07, init 0x00) — matches the gateway firmware."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    """Consistent Overhead Byte Stuffing — output contains no 0x00 bytes (canonical)."""
    out = bytearray([0])  # placeholder for the first code byte
    code_idx = 0
    code = 1
    for b in data:
        if b == 0:
            out[code_idx] = code
            code_idx = len(out)
            out.append(0)
            code = 1
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_idx] = code
                code_idx = len(out)
                out.append(0)
                code = 1
    out[code_idx] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """Inverse of cobs_encode."""
    out = bytearray()
    idx = 0
    n = len(data)
    while idx < n:
        code = data[idx]
        if code == 0:
            raise ValueError("malformed COBS frame (zero code byte)")
        idx += 1
        for _ in range(code - 1):
            if idx >= n:
                raise ValueError("malformed COBS frame (truncated block)")
            out.append(data[idx])
            idx += 1
        if code < 0xFF and idx < n:
            out.append(0)
    return bytes(out)


def frame(cmd: int, data: bytes) -> bytes:
    """Build a delimited, COBS-encoded frame with a CRC8."""
    body = bytes([cmd & 0xFF, len(data) & 0xFF]) + data
    body += bytes([crc8(body)])
    return cobs_encode(body) + bytes([DELIMITER])


def unframe(encoded: bytes) -> tuple[int, bytes]:
    """Decode one COBS frame (without the trailing delimiter) -> (cmd, data).

    Raises ValueError on a CRC mismatch or a malformed/short frame.
    """
    body = cobs_decode(encoded)
    if len(body) < 3:
        raise ValueError("frame too short")
    cmd, length = body[0], body[1]
    data = body[2:-1]
    if len(data) != length:
        raise ValueError("length mismatch")
    if crc8(body[:-1]) != body[-1]:
        raise ValueError("CRC mismatch")
    return cmd, data


class Transport(Protocol):
    """What MeshGateway needs from the radio link."""

    def send(self, air: bytes) -> None: ...
    def read(self) -> list[bytes]: ...
    def close(self) -> None: ...


class SerialTransport:
    """pyserial-backed ICD-2 transport. Lazy-imports pyserial; not unit-tested (hardware)."""

    def __init__(self, port: str, baud: int = 115200, timeout_s: float = 0.1) -> None:
        import serial  # lazy, optional

        self._ser = serial.Serial(port, baud, timeout=timeout_s)
        self._buf = bytearray()

    def send(self, air: bytes) -> None:
        self._ser.write(frame(CMD_SEND, air))

    def read(self) -> list[bytes]:
        """Drain available bytes, return air payloads from any complete RX frames."""
        self._buf.extend(self._ser.read(256))
        out: list[bytes] = []
        while DELIMITER in self._buf:
            chunk, _, rest = bytes(self._buf).partition(bytes([DELIMITER]))
            self._buf = bytearray(rest)
            if not chunk:
                continue
            try:
                cmd, data = unframe(chunk)
            except ValueError:
                continue  # dropped/corrupt frame — CRC caught it
            if cmd == CMD_RX and len(data) >= 2:
                out.append(data[2:])  # strip rssi, snr
        return out

    def close(self) -> None:
        self._ser.close()
