"""Unit tests for the operator dashboard service (FR-17; dashboard/service.py).

The dashboard is a non-critical read/control surface over a running Hub. These pin its
contract against a real Hub with fakes (no sockets): status reflects per-zone state and
health, the controls route to the same operator actions a human has (FR-14), and the
authority-confirm path is human-only (SE-5). The HTTP adapter is thin glue and exercised by
hand at bring-up; all behavior under test lives in DashboardService.
"""

from __future__ import annotations

import pytest

from autosentry.alarm.controller import AlarmController
from autosentry.app import Hub
from autosentry.config import CaptureConfig, NotifyConfig, Settings
from autosentry.contracts import BBox, Detection, Frame, Level, NodeStatus, ThreatAssessment
from autosentry.dashboard import DashboardService
from autosentry.detection.detector import Detector
from autosentry.notify import Notifier


class FakeBackend:
    def __init__(self, dets):
        self._dets = dets

    def infer(self, image):
        return list(self._dets)


class FakeAssessor:
    def assess(self, tracks, keyframes, zone, ts):
        return ThreatAssessment(
            armed=True, weapon_type="rifle", intent="advancing", confidence=0.95,
            description="long gun at the door", zone=zone, ts=ts,
        )


class FakeSink:
    def on(self): ...
    def off(self): ...
    def test(self): ...


def _det(cls, conf=0.9):
    return Detection(cls=cls, conf=conf, bbox=BBox(0, 0, 10, 20), ts=0.0)


def _frame(zone, ts):
    return Frame(zone=zone, ts=ts, image=object(), seq=int(ts))


def _hub():
    settings = Settings()
    settings.capture = CaptureConfig(sources=["0", "1"], zones=["front", "back"])
    settings.notify = NotifyConfig(queue_path=":memory:")
    hub = Hub(settings, assessor=FakeAssessor(), notifier=Notifier(settings.notify))
    hub.detectors["front"] = Detector(settings.detection, backend=FakeBackend([_det("rifle")]))
    hub.detectors["back"] = Detector(settings.detection, backend=FakeBackend([]))
    hub.alarm = AlarmController(settings.alarm, sink=FakeSink())
    return hub


def _drive_alarm(hub):
    hub.arm("front")
    for i in range(4):
        hub.step("front", _frame("front", float(i)))


def test_status_reports_per_zone_state_and_arming():
    hub = _hub()
    hub.arm("front")
    svc = DashboardService(hub)
    s = svc.status()
    zones = {z["zone"]: z for z in s["zones"]}
    assert set(zones) == {"front", "back"}
    assert zones["front"]["armed"] is True
    assert zones["back"]["armed"] is False
    assert zones["front"]["level"] == Level.NORMAL.value


def test_status_reflects_alarm_and_queues():
    hub = _hub()
    svc = DashboardService(hub)
    _drive_alarm(hub)
    s = svc.status()
    front = next(z for z in s["zones"] if z["zone"] == "front")
    assert front["level"] == Level.ALARM.value
    assert s["pending_notifications"] == 1  # FR-13 owner push enqueued
    assert len(s["pending_authority"]) == 1  # SE-5 recommendation surfaced
    assert s["pending_authority"][0]["confirmed"] is False


def test_arm_disarm_controls_route_to_hub():
    hub = _hub()
    svc = DashboardService(hub)
    svc.arm("back")
    assert "back" in hub.armed_zones
    svc.disarm("back")
    assert "back" not in hub.armed_zones


def test_unknown_zone_is_rejected():
    svc = DashboardService(_hub())
    with pytest.raises(KeyError):
        svc.arm("garage")


def test_test_mode_toggle():
    hub = _hub()
    svc = DashboardService(hub)
    svc.set_test_mode(True)
    assert hub.test_mode is True
    assert svc.status()["test_mode"] is True


def test_panic_forces_alarm_even_when_disarmed():
    hub = _hub()  # both zones disarmed
    svc = DashboardService(hub)
    s = svc.panic("back")
    back = next(z for z in s["zones"] if z["zone"] == "back")
    assert back["level"] == Level.ALARM.value


def test_confirm_authority_is_human_only_and_confirms_the_right_rec():
    hub = _hub()
    svc = DashboardService(hub)
    _drive_alarm(hub)
    assert hub.pending_authority[0].confirmed is False
    s = svc.confirm_authority(0)
    assert hub.pending_authority[0].confirmed is True
    assert s["pending_authority"][0]["confirmed"] is True


def test_confirm_authority_out_of_range_rejected():
    svc = DashboardService(_hub())
    with pytest.raises(KeyError):
        svc.confirm_authority(0)  # nothing pending


def test_status_system_level_is_max_across_zones():
    hub = _hub()
    svc = DashboardService(hub)
    _drive_alarm(hub)  # front -> ALARM, back stays NORMAL
    s = svc.status()
    assert s["system_level"] == Level.ALARM.value
    assert s["armed_count"] == 1
    assert s["zone_count"] == 2


def test_status_surfaces_latest_assessment_per_zone():
    hub = _hub()
    svc = DashboardService(hub)
    _drive_alarm(hub)
    s = svc.status()
    front = next(z for z in s["zones"] if z["zone"] == "front")
    back = next(z for z in s["zones"] if z["zone"] == "back")
    assert front["assessment"]["weapon_type"] == "rifle"
    assert front["assessment"]["armed"] is True
    assert front["assessment"]["intent"] == "advancing"
    assert back["assessment"] is None  # no trigger on the quiet zone


def test_status_reports_node_health():
    hub = _hub()
    svc = DashboardService(hub)
    # inject hub-side node views (FR-8/FR-10): one offline, one online-on-battery
    hub.mesh._nodes[2] = NodeStatus(
        node_id=2, online=False, battery_mv=3700, on_battery=False, last_seen=0.0
    )
    hub.mesh._nodes[5] = NodeStatus(
        node_id=5, online=True, battery_mv=3550, on_battery=True, last_seen=10.0
    )
    nodes = {n["node_id"]: n for n in svc.status()["nodes"]}
    assert nodes[2]["online"] is False
    assert nodes[5]["on_battery"] is True
    assert nodes[5]["battery_mv"] == 3550
    assert [n["node_id"] for n in svc.status()["nodes"]] == [2, 5]  # sorted


def test_events_newest_first_and_limited():
    hub = _hub()
    svc = DashboardService(hub)
    _drive_alarm(hub)
    evs = svc.events(limit=2)
    assert len(evs) <= 2
    # newest-first: the final ALARM event sorts ahead of the earlier transitions
    assert evs[0]["level"] == Level.ALARM.value
