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


def test_keyframe_captured_for_triggering_event(tmp_path):
    # FR-15: a stage-1 trigger persists the frame and records its path in the audit row.
    hub, _ = _hub([_det("rifle", 0.9)])
    hub.settings.notify.keyframe_dir = str(tmp_path)
    written: list = []

    def fake_writer(image, path):
        written.append((image, path))
        return True

    hub._keyframe_writer = fake_writer  # type: ignore[assignment]
    hub.step("default", _frame(0.0))  # rifle -> stage-1 fires -> SUSPECT transition
    assert len(written) == 1
    evt = next(e for e in hub.notifier.events() if e["level"] == "SUSPECT")
    import json
    assert json.loads(evt["keyframes"]) == [written[0][1]]


def test_keyframe_write_failure_never_breaks_the_pipeline(tmp_path):
    # Pillar 1: a failing keyframe encode degrades to no-keyframe, never an exception.
    hub, _ = _hub([_det("rifle", 0.9)])
    hub.settings.notify.keyframe_dir = str(tmp_path)

    def boom(image, path):
        raise OSError("disk full")

    hub._keyframe_writer = boom  # type: ignore[assignment]
    hub.step("default", _frame(0.0))  # must not raise
    import json
    evt = next(e for e in hub.notifier.events() if e["level"] == "SUSPECT")
    assert json.loads(evt["keyframes"]) == []


# --- voice is additive, never gates the alarm (FR-12, SE-1) ---------------------------
class _RecordingVoice:
    def __init__(self, raises: bool = False):
        self.greeted = 0
        self._raises = raises

    def greet(self, context):
        self.greeted += 1
        if self._raises:
            raise RuntimeError("llm hung")
        from autosentry.contracts import VoiceTurn

        return VoiceTurn("agent", "Please leave the property.", context, context.ts)


def test_voice_engages_on_alarm_with_vision_context():
    hub, sink = _hub([_det("rifle", 0.9)], assessor=FakeAssessor(armed=True, confidence=0.95))
    hub.arm("default")
    voice = _RecordingVoice()
    hub.voice = voice  # type: ignore[assignment]
    for i in range(4):
        hub.step("default", _frame(float(i)))
    assert hub.alarm.active is True
    assert voice.greeted == 1  # engaged once on ALARM entry, grounded in the assessment
    alarm_evt = next(e for e in hub.notifier.events() if e["level"] == "ALARM")
    assert "voice_engaged" in alarm_evt["actions"]


def test_hung_voice_never_blocks_or_silences_the_siren():
    # FR-12 / FMEA F15: a broken voice agent degrades loudly but the siren still fires.
    hub, sink = _hub([_det("rifle", 0.9)], assessor=FakeAssessor(armed=True, confidence=0.95))
    hub.arm("default")
    hub.voice = _RecordingVoice(raises=True)  # type: ignore[assignment]
    for i in range(4):
        hub.step("default", _frame(float(i)))  # must not raise
    assert hub.alarm.active is True
    assert sink.events == ["on"]  # siren fired despite the voice failure
    assert "voice" in hub.degraded
    alarm_evt = next(e for e in hub.notifier.events() if e["level"] == "ALARM")
    assert "local_alarm" in alarm_evt["actions"]
    assert "voice_engaged" not in alarm_evt["actions"]
