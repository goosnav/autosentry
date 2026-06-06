"""Component tests for MeshGateway against a fake transport (FR-7/8/9, SR-1, PR-7).

No radio hardware: a FakeTransport captures the air bytes the gateway emits and lets a
test inject inbound frames (including forged/replayed ones). This pins the safety-relevant
behavior — signed broadcast, ACK-gated retry, replay/forgery rejection, and the
"silence is an alarm" offline detection — without leaving the bench.
"""

from __future__ import annotations

from autosentry.comms import payloads
from autosentry.comms.gateway import MeshGateway
from autosentry.comms.protocol import Packet, decode, encode
from autosentry.config import CommsConfig
from autosentry.contracts import MsgType

KEY = b"unit-test-mesh-key"
NODE = 2


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.inbox: list[bytes] = []
        self.on_send = None  # optional callback(air_bytes) to simulate a node reply

    def send(self, air: bytes) -> None:
        self.sent.append(air)
        if self.on_send is not None:
            self.on_send(air)

    def read(self) -> list[bytes]:
        out, self.inbox = self.inbox, []
        return out

    def close(self) -> None:
        pass


def _gateway(cfg: CommsConfig | None = None) -> tuple[MeshGateway, FakeTransport]:
    cfg = cfg or CommsConfig()
    transport = FakeTransport()
    gw = MeshGateway(cfg, transport=transport, key=KEY)
    return gw, transport


def _node_frame(type: MsgType, counter: int, payload: bytes = b"", net_id: int = 1) -> bytes:
    """Craft a signed node->hub frame as the radio would deliver it."""
    return encode(
        Packet(type=type, net_id=net_id, src=NODE, dst=0, counter=counter, payload=payload), KEY
    )


# --- broadcast (FR-7) -----------------------------------------------------------------
def test_broadcast_alarm_repeats_and_signs():
    cfg = CommsConfig(broadcast_repeats=3)
    gw, t = _gateway(cfg)
    gw.broadcast_alarm(level=4, zone_id=1, pattern=0)
    assert len(t.sent) == 3
    pkts = [decode(raw, KEY) for raw in t.sent]
    assert all(p.type == MsgType.ALARM for p in pkts)
    assert all(p.dst == 0xFF for p in pkts)  # BROADCAST
    # All repeats share one counter so a node de-dupes them (sounds once).
    assert len({p.counter for p in pkts}) == 1
    alarm = payloads.decode_alarm(pkts[0].payload)
    assert (alarm.level, alarm.zone_id) == (4, 1)


# --- addressed command + ACK retry (FR-8) ---------------------------------------------
def test_send_command_returns_true_when_acked():
    gw, t = _gateway()

    def reply(air: bytes) -> None:
        sent = decode(air, KEY)
        t.inbox.append(
            _node_frame(MsgType.ACK, counter=100, payload=payloads.encode_ref(sent.counter))
        )

    t.on_send = reply
    assert gw.send_command(MsgType.CONFIG, dst=NODE, now=0.0) is True
    assert len(t.sent) == 1  # acked on the first attempt, no retries


def test_send_command_retries_then_fails_without_ack():
    cfg = CommsConfig(retries=2)
    gw, t = _gateway(cfg)
    assert gw.send_command(MsgType.CONFIG, dst=NODE, now=0.0) is False
    assert len(t.sent) == 3  # retries + 1 attempts, all unacked


# --- inbound auth / replay (SR-1) -----------------------------------------------------
def test_poll_drops_forged_hmac():
    gw, t = _gateway()
    forged = encode(Packet(MsgType.STATUS, net_id=1, src=NODE, dst=0, counter=1), b"wrong-key")
    t.inbox.append(forged)
    assert gw.poll(now=0.0) == []
    assert gw.node_health() == []  # forged frame never touched node state


def test_poll_rejects_replayed_counter():
    gw, t = _gateway()
    t.inbox.append(_node_frame(MsgType.STATUS, counter=5, payload=_status_bytes()))
    assert len(gw.poll(now=0.0)) == 1
    t.inbox.append(_node_frame(MsgType.STATUS, counter=5, payload=_status_bytes()))
    assert gw.poll(now=1.0) == []  # same counter -> replay, dropped


# --- node health / status (FR-8, FR-10) -----------------------------------------------
def _status_bytes() -> bytes:
    return payloads.encode_status(
        payloads.StatusPayload(battery_mv=3700, on_battery=True, siren_active=False, fw_ver=1)
    )


def test_status_updates_node_battery():
    gw, t = _gateway()
    t.inbox.append(_node_frame(MsgType.STATUS, counter=1, payload=_status_bytes()))
    gw.poll(now=0.0)
    node = gw.node_health()[0]
    assert node.node_id == NODE
    assert node.online is True
    assert node.battery_mv == 3700
    assert node.on_battery is True


def test_on_battery_nodes_surfaced_only_while_online():
    gw, t = _gateway()
    t.inbox.append(_node_frame(MsgType.STATUS, counter=1, payload=_status_bytes()))
    gw.poll(now=0.0)
    assert [n.node_id for n in gw.on_battery_nodes()] == [NODE]  # online + on battery
    gw.refresh(now=1000.0)  # node goes silent -> offline, no longer "on battery" alert
    assert gw.on_battery_nodes() == []
    assert [n.node_id for n in gw.offline_nodes()] == [NODE]


# --- heartbeat / offline detection (FR-9, PR-7) ---------------------------------------
def test_tick_emits_heartbeat_at_cadence():
    cfg = CommsConfig(hb_interval_s=5.0)
    gw, t = _gateway(cfg)
    gw.tick(now=0.0)
    assert len(t.sent) == 1
    hb = decode(t.sent[0], KEY)
    assert hb.type == MsgType.HEARTBEAT and hb.dst == 0xFF
    gw.tick(now=1.0)  # within the interval -> no new heartbeat
    assert len(t.sent) == 1
    gw.tick(now=6.0)  # past the interval -> a second heartbeat
    assert len(t.sent) == 2


def test_node_goes_offline_after_missed_heartbeats():
    cfg = CommsConfig(hb_interval_s=5.0, hb_miss_max=3)
    gw, t = _gateway(cfg)
    t.inbox.append(_node_frame(MsgType.STATUS, counter=1, payload=_status_bytes()))
    gw.poll(now=0.0)
    assert gw.offline_nodes() == []
    gw.refresh(now=10.0)  # < 5*3 deadline, still online
    assert gw.offline_nodes() == []
    gw.refresh(now=16.0)  # > 15s deadline -> offline (silence is itself an alarm)
    offline = gw.offline_nodes()
    assert len(offline) == 1 and offline[0].node_id == NODE


def test_counter_advances_across_distinct_messages():
    gw, t = _gateway()
    gw.broadcast_alarm(level=1, zone_id=0)
    gw.tick(now=0.0)
    counters = [decode(raw, KEY).counter for raw in t.sent]
    # alarm repeats share a counter; the heartbeat must use a strictly newer one.
    assert counters[-1] > counters[0]
    assert len(set(counters)) >= 2


def test_send_uses_fresh_counter_each_attempt():
    cfg = CommsConfig(retries=2)
    gw, t = _gateway(cfg)
    gw.send_command(MsgType.CONFIG, dst=NODE, now=0.0)
    counters = [decode(raw, KEY).counter for raw in t.sent]
    assert len(set(counters)) == len(counters)  # all distinct
    assert counters == sorted(counters)  # strictly increasing
