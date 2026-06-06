"""Hub-side LoRa mesh gateway (FR-7..9, SR-1/2).

Bridges the hub's threat decisions to the radio: serializes signed packets with
comms.protocol, ships them over the USB-serial LoRa gateway (ICD-2 transport), collects
ACKs and heartbeats, and maintains a per-node health view (NodeStatus). A node that stops
heartbeating is itself an alarm — silence is never treated as "all clear" (FR-9, FMEA F9).

The wire codec (comms.protocol) and serial framing (comms.transport) are pure and
unit-tested. This layer's retry/heartbeat/health logic is tested against a fake transport;
the real pyserial transport is lazy-built.

STATUS: M3 — broadcast/ACK-retry/poll/heartbeat/offline implemented.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from autosentry.comms import payloads
from autosentry.comms.protocol import (
    BROADCAST,
    Packet,
    PacketError,
    ReplayError,
    ReplayWindow,
    decode,
    encode,
)
from autosentry.comms.transport import Transport
from autosentry.config import CommsConfig
from autosentry.contracts import MsgType, NodeStatus


class MeshGateway:
    """Owns the serial link to the LoRa radio and the per-node health table."""

    def __init__(
        self,
        config: CommsConfig,
        transport: Transport | None = None,
        key: bytes | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = config
        self._transport = transport
        self._key = key
        self._clock = clock
        # Monotonic per-restart counter (anti-replay, SR-1). Persisting across hub restarts
        # is an ops concern (docs/COMMS_PROTOCOL.md §3); in-memory within a run here.
        self._counter = 0
        self._replay = ReplayWindow()
        self._nodes: dict[int, NodeStatus] = {}
        self._acked: set[int] = set()
        self._last_hb = float("-inf")

    # --- wiring -----------------------------------------------------------------------
    def _ensure_transport(self) -> Transport:
        if self._transport is None:
            from autosentry.comms.transport import SerialTransport

            self._transport = SerialTransport(self.cfg.port, self.cfg.baud)
        return self._transport

    def _get_key(self) -> bytes:
        if self._key is None:
            key = os.environ.get(self.cfg.key_env)
            if not key:
                raise RuntimeError(
                    f"mesh key not set: export {self.cfg.key_env} (see docs/SECURITY.md)"
                )
            self._key = key.encode()
        return self._key

    def _next_counter(self) -> int:
        self._counter += 1
        return self._counter

    def _send(self, pkt: Packet) -> None:
        self._ensure_transport().send(encode(pkt, self._get_key()))

    def _packet(self, type: MsgType, dst: int, counter: int, payload: bytes = b"") -> Packet:
        return Packet(
            type=type,
            net_id=self.cfg.net_id,
            src=self.cfg.hub_addr,
            dst=dst,
            counter=counter,
            payload=payload,
        )

    # --- outbound ---------------------------------------------------------------------
    def broadcast_alarm(self, level: int, zone_id: int, pattern: int = 0) -> None:
        """Sign and broadcast an ALARM to all nodes, repeated for reliability (FR-7).

        All repeats share one counter so a node's replay window de-dupes them (it sounds
        once); the next distinct message advances the counter.
        """
        payload = payloads.encode_alarm(payloads.AlarmPayload(level, zone_id, pattern))
        pkt = self._packet(MsgType.ALARM, BROADCAST, self._next_counter(), payload)
        for _ in range(max(1, self.cfg.broadcast_repeats)):
            self._send(pkt)

    def send_command(
        self, type: MsgType, dst: int, payload: bytes = b"", now: float | None = None
    ) -> bool:
        """Send an addressed command and retry until ACKed (FR-8). Returns True if ACKed.

        Each attempt uses a fresh counter; the node ACKs whichever frame it received with
        that counter as `ref_counter`, so a late ACK for an earlier attempt still counts.
        """
        now = self._clock() if now is None else now
        sent_counters: list[int] = []
        for _ in range(self.cfg.retries + 1):
            counter = self._next_counter()
            sent_counters.append(counter)
            self._send(self._packet(type, dst, counter, payload))
            self.poll(now)
            if any(c in self._acked for c in sent_counters):
                return True
        return False

    # --- inbound ----------------------------------------------------------------------
    def poll(self, now: float | None = None) -> list[Packet]:
        """Drain inbound packets, authenticate, reject replays, update node health.

        A frame that fails its HMAC or replays an old counter is dropped (SR-1) and never
        updates state. Returns the accepted packets.
        """
        now = self._clock() if now is None else now
        key = self._get_key()
        accepted: list[Packet] = []
        for raw in self._ensure_transport().read():
            try:
                pkt = decode(raw, key)
            except PacketError:
                continue  # forged/corrupt — drop + (caller logs)
            try:
                self._replay.check_and_update(pkt)
            except ReplayError:
                continue  # captured-and-replayed frame — drop
            self._observe(pkt, now)
            accepted.append(pkt)
        return accepted

    def _observe(self, pkt: Packet, now: float) -> None:
        node = self._nodes.get(pkt.src)
        if node is None:
            node = NodeStatus(
                node_id=pkt.src, online=True, battery_mv=0, on_battery=False, last_seen=now
            )
            self._nodes[pkt.src] = node
        node.online = True
        node.last_seen = now
        if pkt.type in (MsgType.ACK, MsgType.HEARTBEAT_ACK) and len(pkt.payload) >= 4:
            self._acked.add(payloads.decode_ref(pkt.payload))
        elif pkt.type == MsgType.STATUS and len(pkt.payload) >= payloads.STATUS_LEN:
            status = payloads.decode_status(pkt.payload)
            node.battery_mv = status.battery_mv
            node.on_battery = status.on_battery

    # --- heartbeat / liveness ---------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        """Emit a heartbeat at the configured cadence and refresh offline state (FR-9)."""
        now = self._clock() if now is None else now
        if now - self._last_hb >= self.cfg.hb_interval_s:
            self._last_hb = now
            self._send(self._packet(MsgType.HEARTBEAT, BROADCAST, self._next_counter()))
        self.refresh(now)

    def refresh(self, now: float | None = None) -> None:
        """Mark nodes offline after hb_miss_max missed heartbeats (PR-7, ≤30 s)."""
        now = self._clock() if now is None else now
        deadline = self.cfg.hb_interval_s * self.cfg.hb_miss_max
        for node in self._nodes.values():
            if now - node.last_seen > deadline:
                node.online = False

    def node_health(self) -> list[NodeStatus]:
        """Current view of every known node (FR-8)."""
        return list(self._nodes.values())

    def offline_nodes(self) -> list[NodeStatus]:
        """Nodes currently flagged offline/tamper — each is itself an alert (SR-2)."""
        return [n for n in self._nodes.values() if not n.online]

    def on_battery_nodes(self) -> list[NodeStatus]:
        """Online nodes running on battery — a mains-loss alert the owner must see (FR-10)."""
        return [n for n in self._nodes.values() if n.online and n.on_battery]

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
