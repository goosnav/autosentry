"""Unit tests for the local AlarmController (FR-6; alarm/controller.py).

Pins the latch/idempotency contract against a fake sink (no GPIO): TRIGGER latches the
siren on and is idempotent, only CLEAR turns it off (a dropped tick can't silence an
active alarm — pillar 3), and TEST pulses without latching.
"""

from __future__ import annotations

from autosentry.alarm.controller import AlarmController
from autosentry.config import AlarmConfig
from autosentry.contracts import Action, AlarmCommand


class FakeSink:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on(self) -> None:
        self.events.append("on")

    def off(self) -> None:
        self.events.append("off")

    def test(self) -> None:
        self.events.append("test")


def _ctl() -> tuple[AlarmController, FakeSink]:
    sink = FakeSink()
    return AlarmController(AlarmConfig(), sink=sink), sink


def test_trigger_latches_on():
    ctl, sink = _ctl()
    ctl.trigger("front")
    assert ctl.active is True
    assert sink.events == ["on"]


def test_trigger_is_idempotent():
    ctl, sink = _ctl()
    ctl.trigger("front")
    ctl.trigger("front")
    ctl.trigger("front")
    assert sink.events == ["on"]  # not re-driven; a repeated TRIGGER never re-pulses
    assert ctl.active is True


def test_only_clear_turns_off():
    ctl, sink = _ctl()
    ctl.trigger("front")
    ctl.clear("front")
    assert ctl.active is False
    assert sink.events == ["on", "off"]


def test_clear_when_inactive_is_noop():
    ctl, sink = _ctl()
    ctl.clear("front")
    assert sink.events == []
    assert ctl.active is False


def test_test_action_pulses_without_latching():
    ctl, sink = _ctl()
    ctl.apply(AlarmCommand(action=Action.TEST, zone="front"))
    assert sink.events == ["test"]
    assert ctl.active is False


def test_arm_is_noop_at_peripheral():
    ctl, sink = _ctl()
    ctl.apply(AlarmCommand(action=Action.ARM, zone="front"))
    assert sink.events == []
    assert ctl.active is False
