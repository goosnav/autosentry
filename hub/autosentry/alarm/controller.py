"""Local siren + strobe control (ICD-4, FR-6).

Drives the powered siren and strobe wired to the hub (GPIO/relay or USB-audio). This is
a *critical-path* output: it must fire within PR-3 (≤1 s of ALARM) and must not depend on
the network, the VLM, or the voice agent. The hardware is behind a swappable `AlarmSink`
so the latch/idempotency logic is unit-testable; the default GPIO sink lazy-imports
Jetson.GPIO so this module imports cleanly on any dev machine.

STATUS: M2 — apply() implemented (ARM/TRIGGER/CLEAR/TEST + hardware latch).
"""

from __future__ import annotations

from typing import Protocol

from autosentry.config import AlarmConfig
from autosentry.contracts import Action, AlarmCommand


class AlarmSink(Protocol):
    """The physical siren/strobe surface (GPIO lines or USB-audio)."""

    def on(self) -> None: ...
    def off(self) -> None: ...
    def test(self) -> None: ...


class AlarmController:
    """Owns the local siren/strobe. One instance per hub."""

    def __init__(self, config: AlarmConfig, sink: AlarmSink | None = None) -> None:
        self.cfg = config
        self._sink = sink
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def _ensure_sink(self) -> AlarmSink:
        if self._sink is None:
            from autosentry.alarm.gpio_sink import GpioSink

            self._sink = GpioSink(self.cfg)
        return self._sink

    def apply(self, command: AlarmCommand) -> None:
        """Execute an alarm command (ARM/TRIGGER/CLEAR/TEST).

        TRIGGER is idempotent and latches the sink on until an explicit CLEAR, so a
        dropped tick can never silence an active alarm (FR-6, pillar 3). CLEAR is the only
        path that turns the siren off.
        """
        sink = self._ensure_sink()
        if command.action is Action.TRIGGER:
            if not self._active:
                sink.on()
                self._active = True
        elif command.action is Action.CLEAR:
            if self._active:
                sink.off()
                self._active = False
        elif command.action is Action.TEST:
            sink.test()
        # ARM is a no-op at the peripheral level; arming policy lives in the state machine.

    def trigger(self, zone: str) -> None:
        """Convenience: sound the local alarm for a zone."""
        self.apply(AlarmCommand(action=Action.TRIGGER, zone=zone))

    def clear(self, zone: str) -> None:
        """Convenience: silence the local alarm for a zone (after ack + cooldown)."""
        self.apply(AlarmCommand(action=Action.CLEAR, zone=zone))
