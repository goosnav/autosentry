"""Unit tests for owner notifications: durable queue + flush (FR-13, OS-5; notify/notifier.py).

A notification must survive an internet outage and be delivered when the link returns, and
must never block or gate the alarm (ICD-6, pillar 1). These pin the queue/flush contract
with a fake sender that can be toggled offline — no network, no push provider.
"""

from __future__ import annotations

from autosentry.config import NotifyConfig
from autosentry.contracts import Level, ThreatAssessment, ThreatState
from autosentry.notify.notifier import Notifier


class FakeSender:
    """Captures delivered notifications; raises while offline or once `fail_after` is hit."""

    def __init__(self, online: bool = True, fail_after: int | None = None) -> None:
        self.online = online
        self.fail_after = fail_after  # deliver this many, then fail (flaky link)
        self.delivered: list[int] = []

    def send(self, note) -> None:
        if not self.online:
            raise RuntimeError("network down")
        if self.fail_after is not None and len(self.delivered) >= self.fail_after:
            raise RuntimeError("link dropped mid-flush")
        self.delivered.append(note.event_id)


def _notifier(sender: FakeSender, enabled: bool = True) -> Notifier:
    return Notifier(NotifyConfig(queue_path=":memory:", enabled=enabled), sender=sender)


def _state(level: Level = Level.ALARM, ts: float = 1.0) -> ThreatState:
    return ThreatState(level=level, zone="front", since=ts, reason="confirmed")


def _assessment() -> ThreatAssessment:
    return ThreatAssessment(
        armed=True, weapon_type="rifle", intent="advancing", confidence=0.9,
        description="long gun at the door", zone="front", ts=1.0,
    )


def test_notify_delivers_when_online():
    s = FakeSender(online=True)
    n = _notifier(s)
    n.notify(_state(), _assessment())
    assert len(s.delivered) == 1
    assert n.pending() == 0


def test_notify_queues_when_offline():
    s = FakeSender(online=False)
    n = _notifier(s)
    n.notify(_state(), _assessment())
    assert s.delivered == []  # nothing left the box
    assert n.pending() == 1  # but it's durably queued


def test_queued_notifications_flush_on_reconnect():
    s = FakeSender(online=False)
    n = _notifier(s)
    n.notify(_state(ts=1.0), _assessment())
    n.notify(_state(ts=2.0), _assessment())
    assert n.pending() == 2
    s.online = True  # link returns
    sent = n.flush()
    assert sent == 2
    assert n.pending() == 0
    assert s.delivered == [1, 2]  # oldest-first ordering preserved


def test_flush_preserves_order_and_stops_on_failure():
    # If delivery fails mid-drain (flaky link), the failed item and all later items stay
    # queued and ordered — none are dropped.
    s = FakeSender(online=False)
    n = _notifier(s)
    n.notify(_state(ts=1.0), _assessment())  # queued (offline)
    n.notify(_state(ts=2.0), _assessment())  # queued
    assert n.pending() == 2
    s.online = True
    s.fail_after = 1  # first delivers, second fails
    assert n.flush() == 1
    assert s.delivered == [1]
    assert n.pending() == 1


def test_disabled_notify_still_queues_but_does_not_send():
    s = FakeSender(online=True)
    n = _notifier(s, enabled=False)  # owner push turned off
    n.notify(_state(), _assessment())
    assert s.delivered == []
    assert n.pending() == 1  # retained for audit / later enablement


def test_summary_falls_back_to_state_reason_without_assessment():
    s = FakeSender(online=True)
    n = _notifier(s)
    n.notify(_state(), None)
    assert s.delivered == [1]
