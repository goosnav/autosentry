"""Integration test for the M1+M2 pipeline (Hub.step): detect -> track -> trigger ->
stage-2 -> state -> local alarm + audit log.

Exercises the wired vision core with fake backends (no camera, no model, no GPIO) and pins
the key safety properties at the system seam:
- stage-1 evidence with stage-2 *unavailable* can raise concern (SUSPECT) but can NEVER
  reach a latched ALARM (pillar 3 / PR-4);
- a *confirmed* armed assessment that persists across the confirmation window does reach
  ALARM and fires the local siren (FR-6), and the event is audited (FR-15).
"""

from __future__ import annotations

from autosentry.alarm.controller import AlarmController
from autosentry.app import Hub
from autosentry.config import NotifyConfig, Settings
from autosentry.contracts import BBox, Detection, Frame, Level, ThreatAssessment
from autosentry.detection.detector import Detector
from autosentry.notify.notifier import Notifier


class FakeBackend:
    def __init__(self, dets: list[Detection]) -> None:
        self._dets = dets

    def infer(self, image: object) -> list[Detection]:
        return list(self._dets)


class FakeAssessor:
    """Stands in for stage-2: returns a fixed assessment for every call."""

    def __init__(self, armed: bool, confidence: float) -> None:
        self._armed = armed
        self._confidence = confidence

    def assess(self, tracks, keyframes, zone: str, ts: float) -> ThreatAssessment:
        return ThreatAssessment(
            armed=self._armed,
            weapon_type="rifle" if self._armed else None,
            intent="test",
            confidence=self._confidence,
            description="",
            zone=zone,
            ts=ts,
        )


class FakeSink:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on(self) -> None:
        self.events.append("on")

    def off(self) -> None:
        self.events.append("off")

    def test(self) -> None:
        self.events.append("test")


def _hub(dets: list[Detection], assessor=None) -> tuple[Hub, FakeSink]:
    settings = Settings()  # single zone "default"
    settings.notify = NotifyConfig(queue_path=":memory:")  # audit log -> memory, no file
    detector = Detector(settings.detection, backend=FakeBackend(dets))
    hub = Hub(
        settings,
        detector=detector,
        assessor=assessor or FakeAssessor(armed=False, confidence=0.0),
        notifier=Notifier(settings.notify),
    )
    sink = FakeSink()
    hub.alarm = AlarmController(settings.alarm, sink=sink)  # no GPIO in tests
    return hub, sink


def _frame(ts: float) -> Frame:
    return Frame(zone="default", ts=ts, image=object(), seq=int(ts))


def _det(cls: str, conf: float) -> Detection:
    return Detection(cls=cls, conf=conf, bbox=BBox(0, 0, 10, 20), ts=0.0)


def test_benign_person_reaches_watch_only():
    hub, _ = _hub([_det("person", 0.9)])
    state = hub.step("default", _frame(0.0))
    assert state.level == Level.WATCH


def test_weapon_escalates_to_suspect():
    hub, _ = _hub([_det("rifle", 0.9)])  # unarmed stage-2 -> holds at SUSPECT
    state = hub.step("default", _frame(0.0))
    assert state.level == Level.SUSPECT


def test_stage2_unavailable_never_alarms():
    # Sustained weapon detections with stage-2 returning the conservative fallback
    # (armed but confidence below the arm threshold): the machine must hold at SUSPECT
    # and never latch ALARM — the core anti-false-positive guarantee (pillar 3).
    hub, sink = _hub([_det("rifle", 0.9)], assessor=FakeAssessor(armed=True, confidence=0.5))
    last = None
    for i in range(50):
        last = hub.step("default", _frame(float(i)))
        assert last.level != Level.ALARM
        assert last.level != Level.THREAT
    assert last.level == Level.SUSPECT
    assert sink.events == []  # siren never fired


def test_confirmed_threat_reaches_alarm_and_fires_siren():
    # A high-confidence armed assessment that persists across the confirmation window
    # escalates SUSPECT -> THREAT -> ALARM and drives the local siren (FR-6).
    hub, sink = _hub([_det("rifle", 0.9)], assessor=FakeAssessor(armed=True, confidence=0.95))
    hub.arm("default")  # actuation requires an armed zone (FR-14)
    levels = [hub.step("default", _frame(float(i))).level for i in range(4)]
    assert levels[0] == Level.SUSPECT
    assert Level.THREAT in levels
    assert levels[-1] == Level.ALARM
    assert hub.alarm.active is True
    assert sink.events == ["on"]
    # FR-15: the ALARM transition is audited with the action taken.
    events = hub.notifier.events()
    assert any(e["level"] == "ALARM" for e in events)
    alarm_evt = next(e for e in events if e["level"] == "ALARM")
    assert "local_alarm" in alarm_evt["actions"]


def test_alarm_clears_and_silences_siren_on_return_to_normal():
    # Leaving ALARM silences the siren and audits the action (FR-6); only an explicit
    # CLEAR turns the latched siren off.
    hub, sink = _hub([_det("rifle", 0.9)], assessor=FakeAssessor(armed=True, confidence=0.95))
    hub.arm("default")  # actuation requires an armed zone (FR-14)
    for i in range(4):
        hub.step("default", _frame(float(i)))
    assert hub.alarm.active is True
    actions = hub._actuate("default", Level.ALARM, Level.NORMAL)
    assert actions == ["alarm_cleared"]
    assert hub.alarm.active is False
    assert sink.events == ["on", "off"]


def test_empty_scene_stays_normal():
    hub, _ = _hub([])
    assert hub.step("default", _frame(0.0)).level == Level.NORMAL
