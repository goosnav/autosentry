"""Unit tests for the FR-15 audit event log (notify/notifier.py).

Verifies every alarm-relevant event is persisted with timestamp, zone, level, the stage-2
assessment, and the actions taken — the auditable record STK-6 requires.
"""

from __future__ import annotations

import json

from autosentry.config import NotifyConfig
from autosentry.contracts import Level, ThreatAssessment, ThreatState


def _notifier():
    from autosentry.notify.notifier import Notifier

    return Notifier(NotifyConfig(queue_path=":memory:"))


def _state(level: Level, ts: float) -> ThreatState:
    return ThreatState(level=level, zone="front", since=ts, reason="test")


def _assessment(ts: float) -> ThreatAssessment:
    return ThreatAssessment(
        armed=True, weapon_type="rifle", intent="advancing", confidence=0.9,
        description="long gun", zone="front", ts=ts,
    )


def test_event_persisted_with_assessment_and_actions():
    n = _notifier()
    n.log_event(_state(Level.ALARM, 3.0), _assessment(3.0), ["local_alarm"])
    rows = n.events()
    assert len(rows) == 1
    row = rows[0]
    assert row["zone"] == "front"
    assert row["level"] == "ALARM"
    assert row["ts"] == 3.0
    assert json.loads(row["actions"]) == ["local_alarm"]
    assert json.loads(row["assessment"])["weapon_type"] == "rifle"


def test_event_without_assessment_stores_null():
    n = _notifier()
    n.log_event(_state(Level.WATCH, 1.0), None, [])
    row = n.events()[0]
    assert row["assessment"] is None
    assert json.loads(row["actions"]) == []


def test_event_records_keyframe_paths():
    n = _notifier()
    n.log_event(_state(Level.ALARM, 3.0), _assessment(3.0), ["local_alarm"],
                ["keyframes/front-7-3.000.jpg"])
    row = n.events()[0]
    assert json.loads(row["keyframes"]) == ["keyframes/front-7-3.000.jpg"]


def test_keyframes_default_to_empty_list():
    n = _notifier()
    n.log_event(_state(Level.WATCH, 1.0), None, [])
    assert json.loads(n.events()[0]["keyframes"]) == []


def test_events_are_ordered():
    n = _notifier()
    n.log_event(_state(Level.WATCH, 1.0), None, [])
    n.log_event(_state(Level.SUSPECT, 2.0), None, [])
    n.log_event(_state(Level.ALARM, 3.0), _assessment(3.0), ["local_alarm"])
    levels = [r["level"] for r in n.events()]
    assert levels == ["WATCH", "SUSPECT", "ALARM"]


def test_recent_events_is_newest_first_and_limited():
    n = _notifier()
    for i, lvl in enumerate([Level.WATCH, Level.SUSPECT, Level.THREAT, Level.ALARM]):
        n.log_event(_state(lvl, float(i)), None, [])
    recent = n.recent_events(limit=2)
    assert [r["level"] for r in recent] == ["ALARM", "THREAT"]  # newest first, bounded


def test_recent_events_handles_fewer_rows_than_limit():
    n = _notifier()
    n.log_event(_state(Level.WATCH, 1.0), None, [])
    assert len(n.recent_events(limit=50)) == 1
