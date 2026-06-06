"""M4 tests: arming + test mode + panic (FR-14), graceful degradation (RR-4),
and node power/offline surfacing (FR-10).

These pin the power/reliability guarantees at the Hub seam with fakes: a disarmed zone
sounds nothing, test mode never latches, panic always fires, a faulting subsystem degrades
loudly without crashing or manufacturing a false ALARM, and a node on battery is surfaced.
"""

from __future__ import annotations

from autosentry.alarm.controller import AlarmController
from autosentry.app import Hub
from autosentry.config import NotifyConfig, Settings
from autosentry.contracts import BBox, Detection, Frame, Level, NodeStatus, ThreatAssessment
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


def _hub(dets, assessor=None) -> tuple[Hub, FakeSink]:
    settings = Settings()
    settings.notify = NotifyConfig(queue_path=":memory:")
    detector = Detector(settings.detection, backend=FakeBackend(dets))
    hub = Hub(
        settings,
        detector=detector,
        assessor=assessor or FakeAssessor(armed=True, confidence=0.95),
        notifier=Notifier(settings.notify),
    )
    sink = FakeSink()
    hub.alarm = AlarmController(settings.alarm, sink=sink)
    return hub, sink


def _det(cls, conf=0.9):
    return Detection(cls=cls, conf=conf, bbox=BBox(0, 0, 10, 20), ts=0.0)


def _frame(ts):
    return Frame(zone="default", ts=ts, image=object(), seq=int(ts))


def _drive_to_alarm(hub) -> Level:
    last = Level.NORMAL
    for i in range(4):
        last = hub.step("default", _frame(float(i))).level
    return last


# --- arming (FR-14) -------------------------------------------------------------------
def test_disarmed_zone_reaches_alarm_level_but_sounds_nothing():
    hub, sink = _hub([_det("rifle")])  # Settings() defaults to disarmed
    assert hub.armed_zones == set()
    level = _drive_to_alarm(hub)
    assert level == Level.ALARM  # still tracked + logged
    assert sink.events == []  # but the siren never fired (disarmed)
    assert hub.alarm.active is False
    evt = next(e for e in hub.notifier.events() if e["level"] == "ALARM")
    assert "suppressed_disarmed" in evt["actions"]


def test_armed_zone_fires_siren():
    hub, sink = _hub([_det("rifle")])
    hub.arm("default")
    assert _drive_to_alarm(hub) == Level.ALARM
    assert sink.events == ["on"]
    assert hub.alarm.active is True


# --- test mode (FR-14, OS-8) ----------------------------------------------------------
def test_test_mode_pulses_without_latching():
    hub, sink = _hub([_det("rifle")])
    hub.arm("default")
    hub.set_test_mode(True)
    _drive_to_alarm(hub)
    assert sink.events == ["test"]  # pulse, not a latched "on"
    assert hub.alarm.active is False


# --- panic (FR-14) --------------------------------------------------------------------
def test_panic_forces_alarm_even_when_disarmed():
    hub, sink = _hub([])  # empty scene, disarmed
    state = hub.panic("default", now=0.0)
    assert state.level == Level.ALARM
    assert sink.events == ["on"]  # manual override always fires
    assert hub.alarm.active is True
    evt = next(e for e in hub.notifier.events() if e["level"] == "ALARM")
    assert "local_alarm" in evt["actions"]


# --- graceful degradation (RR-4) ------------------------------------------------------
def test_detector_fault_degrades_without_crashing():
    hub, _ = _hub([_det("person")])

    def boom(frame):
        raise RuntimeError("camera gone")

    hub.detectors["default"].track = boom  # type: ignore[method-assign]
    state = hub.step("default", _frame(0.0))  # must not raise
    assert state.level == Level.NORMAL
    assert "vision" in hub.degraded


def test_assessor_fault_never_manufactures_alarm():
    # A stage-2 that always throws must hold the machine below ALARM (pillar 3): no
    # assessment means SUSPECT->THREAT can't happen.
    class Boom:
        def assess(self, *a, **k):
            raise RuntimeError("vlm timeout")

    hub, sink = _hub([_det("rifle")], assessor=Boom())
    hub.arm("default")
    last = None
    for i in range(10):
        last = hub.step("default", _frame(float(i))).level
        assert last != Level.ALARM
    assert "reasoning" in hub.degraded
    assert sink.events == []


# --- node power / offline surfacing (FR-10) -------------------------------------------
class StubMesh:
    def __init__(self, offline, on_batt):
        self._offline, self._on_batt = offline, on_batt

    def offline_nodes(self):
        return self._offline

    def on_battery_nodes(self):
        return self._on_batt


def test_power_alerts_surface_offline_and_on_battery():
    hub, _ = _hub([])
    offline = [NodeStatus(node_id=5, online=False, battery_mv=0, on_battery=False, last_seen=0.0)]
    on_batt = [NodeStatus(node_id=6, online=True, battery_mv=3200, on_battery=True, last_seen=1.0)]
    hub.mesh = StubMesh(offline, on_batt)  # type: ignore[assignment]
    alerts = hub.power_alerts()
    assert {n.node_id for n in alerts} == {5, 6}
    health = hub.health()
    assert health["offline_nodes"] == [5]
    assert health["on_battery_nodes"] == [6]
