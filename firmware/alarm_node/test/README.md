# Firmware unit tests (`pio test`)

These are the node-side counterpart to the hub's `pytest` suite. They verify the
**safety-critical** protocol logic — HMAC verification, the wire layout, and the anti-replay
counter (SR-1) — on the host via PlatformIO's `native` test runner, **no radio hardware
required**:

```bash
cd firmware/alarm_node
pio test -e native
```

## Golden cross-implementation vector — `wire_vectors.json`

`wire_vectors.json` is generated from the **authoritative** hub codec
(`hub/autosentry/comms/protocol.py`) by `scripts/gen_wire_vectors.py`, and is pinned on the
hub side by `hub/tests/test_wire_vectors.py`. The firmware MUST reproduce these exact bytes;
if it can't, a real signed ALARM from the hub will never verify on the node.

Current `alarm_broadcast` vector (key `autosentry-golden-vector-key-001`):

| field         | value                                    |
|---------------|------------------------------------------|
| frame_hex     | `01010100ff070000000402` + `4c2395b59e44874d` |
| body (signed) | `01010100ff070000000402`                 |
| hmac_hex      | `4c2395b59e44874d`                        |

The signed body is the frame minus the trailing 8-byte tag; the tag is
`HMAC-SHA256(key, body)[:8]`. Layout: `ver(1) type(1) net_id(1) src(1) dst(1) counter(4 LE)
payload(n) hmac(8)`.

The vector is **data, not code** — both implementations read the same committed file, so
this README's table is only a convenience copy. Always assert against `wire_vectors.json`.

## Test to implement (`test/test_wire_vectors/test_main.cpp`)

Factor the pure protocol functions (`decode_frame`, `encode_frame`, `replay_ok`, `hmac8`)
out of `src/main.cpp` into a host-compilable header (e.g. `src/wire.h`) so the `native`
environment can include them without `Arduino.h`/`RadioLib` (inject the HMAC key instead of
the hardcoded `MESH_KEY`). Then, using Unity:

1. **HMAC reproduction** — `hmac8(key, body, tag)` over the `alarm_broadcast` body yields
   exactly `hmac_hex`. (This is the single most important node test: a wrong HMAC means the
   node ignores every real alarm.)
2. **Verify accepts the golden frame** — `decode_frame()` on `frame_hex` returns `type ==
   MSG_ALARM`, `src == 0`, `dst == 0xFF`, `counter == 7`, payload `04 02`.
3. **Bit-flip rejects** — flip any byte of `frame_hex` ⇒ `decode_frame()` returns false.
4. **Wrong key rejects** — verify with a different key ⇒ false.
5. **Replay rejects** — `replay_ok(src, 7)` then `replay_ok(src, 7)` ⇒ second is false;
   `replay_ok(src, 6)` (older) ⇒ false; `replay_ok(src, 8)` ⇒ true.
6. **Encode round-trips** — `encode_frame()` with the golden fields + counter 7 reproduces
   `frame_hex` byte-for-byte.
7. **ACK carries the ref counter** — `send_ack(MSG_ACK, 7)` produces a frame whose payload is
   the 4-byte LE `07 00 00 00` (so the hub's `decode_ref` matches it). Guards against the
   empty-ACK regression (was C1).

## Gateway role (`AUTOSENTRY_ROLE_GATEWAY`) — ICD-2 framing

The hub-gateway build (`pio run -e hub_gateway`) compiles the `#ifdef AUTOSENTRY_ROLE_GATEWAY`
branch of `main.cpp`: a dumb USB-serial ↔ LoRa modem that COBS+CRC8-frames air bytes to/from
the hub (`comms/transport.py`, ICD-2). Test its framing against the `serial_vectors` in
`wire_vectors.json` (compile the gateway helpers into the `native` env):

8. **CRC8** — `gw_crc8()` over a known body matches the Python `crc8` (poly 0x07, init 0x00).
9. **COBS round-trip** — `gw_cobs_decode(gw_cobs_encode(x)) == x` for payloads with and
   without interior `0x00` bytes, and for a >254-byte run (the 0xFF code-byte split).
10. **SEND decodes** — feeding `serial_send_alarm.frame_hex` (minus the trailing `0x00`) to
    `gw_handle_host_frame` yields `cmd == SEND` and the alarm air bytes; a CRC-corrupted copy
    is rejected (no transmit).
11. **RX framing** — `gw_forward_rx(air, len, -50, 7)` reproduces `serial_rx_alarm.frame_hex`
    byte-for-byte (including the trailing delimiter).

A matching `[env:native]` (with `mbedtls`/a host SHA256 and `test_framework = unity`) is
needed in `platformio.ini`. Until a host with PlatformIO runs this, SR-1's node-side leg is
verified by inspection + the shared golden vector (hub side green); the on-host `pio test`
run closes it fully.
