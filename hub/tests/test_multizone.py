"""M6 integration tests: multi-zone attribution (FR-16), owner-notify wiring (FR-13), and
SE-5 human-confirmed authority escalation — pinned at the Hub seam with fakes.

A threat in one zone must not perturb another (independent detectors + state machines), an
ALARM must enqueue an owner push without gating, and an ALARM must only *recommend*
contacting authorities — never auto-confirm it (SE-5).
"""

from __future__ import annotations

from autosentry.alarm.controller import AlarmController
from autosentry.app import Hub
from autosentry.config import CaptureConfig, NotifyConfig, Settings
from autosentry.contracts import BBox, Detection, Frame, Level, ThreatAssessment
from autosentry.detection.detector import Detector
from autosentry.notify import Notifier


class FakeBackend:
    def __init__(self, dets):
        self._dets = dets

    def infer(self, image):
        return list(self._dets)


class FakeAssessor:
    def __init__(self, armed, confidence):
        self._armed, self._confidence = armed, confidence

    def assess(self, tracks, keyframes, zone, ts):
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
    def __init__(self):
        self.events: list[str] = []

    def on(self):
        self.events.append("on")

    def off(self):
        self.events.append("off")

    def test(self):
        self.events.append("test")


def _det(cls, conf=0.9):
    return Detection(cls=cls, conf=conf, bbox=BBox(0, 0, 10, 20), ts=0.0)


def _frame(zone, ts):
    return Frame(zone=zone, ts=ts, image=object(), seq=int(ts))


def _two_zone_hub():
    settings = Settings()
    settings.capture = CaptureConfig(sources=["0", "1"], zones=["front", "back"])
    settings.notify = NotifyConfig(queue_path=":memory:")
    hub = Hub(
        settings,
        assessor=FakeAssessor(armed=True, confidence=0.95),
        notifier=Notifier(settings.notify),
    )
    # Per-zone detectors with independent scenes: armed threat at "front", empty at "back".
    hub.detectors["front"] = Detector(settings.detection, backend=FakeBackend([_det("rifle")]))
    hub.detectors["back"] = Detector(settings.detection, backend=FakeBackend([]))
    hub.alarm = AlarmController(settings.alarm, sink=FakeSink())
    return hub


# --- multi-zone attribution (FR-16) ---------------------------------------------------
def test_threat_in_one_zone_does_not_affect_the_other():
    hub = _two_zone_hub()
    hub.arm("front")
    hub.arm("back")
    front = back = Level.NORMAL
    for i in range(4):
        front = hub.step("front", _frame("front", float(i))).level
        back = hub.step("back", _frame("back", float(i))).level
    assert front == Level.ALARM  # armed rifle at the front escalates
    assert back == Level.NORMAL  # the empty back zone is unperturbed
    # The ALARM event is attributed to the right zone.
    alarm_evts = [e for e in hub.notifier.events() if e["level"] == "ALARM"]
    assert {e["zone"] for e in alarm_evts} == {"front"}


def test_per_zone_state_machines_are_independent():
    hub = _two_zone_hub()
    assert hub.machines["front"] is not hub.machines["back"]
    assert hub.detectors["front"] is not hub.detectors["back"]


# --- owner notify wiring (FR-13) ------------------------------------------------------
def test_alarm_enqueues_owner_notification():
    hub = _two_zone_hub()
    hub.arm("front")
    for i in range(4):
        hub.step("front", _frame("front", float(i)))
    assert hub.notifier.pending() == 1  # queued (offline default); never gated the alarm
    assert hub.alarm.active is True


# --- SE-5 authority escalation requires human confirmation ----------------------------
def test_alarm_recommends_authority_contact_but_never_auto_confirms():
    hub = _two_zone_hub()
    hub.arm("front")
    for i in range(4):
        hub.step("front", _frame("front", float(i)))
    assert len(hub.pending_authority) == 1
    rec = hub.pending_authority[0]
    assert rec.zone == "front"
    assert rec.confirmed is False  # SE-5: no auto-escalation
    alarm_evt = next(e for e in hub.notifier.events() if e["level"] == "ALARM")
    assert "authority_recommended" in alarm_evt["actions"]


def test_authority_contact_confirmed_only_by_explicit_human_action():
    hub = _two_zone_hub()
    hub.arm("front")
    for i in range(4):
        hub.step("front", _frame("front", float(i)))
    rec = hub.pending_authority[0]
    assert hub.confirm_authority_contact(rec) is True
    assert rec.confirmed is True
