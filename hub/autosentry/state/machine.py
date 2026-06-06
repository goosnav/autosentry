"""Threat state machine — converts noisy detections into a stable threat level.

Implements FR-5: NORMAL -> WATCH -> SUSPECT -> THREAT -> ALARM with hysteresis, a
confirmation window, and a cooldown, plus a manual panic override (FR-14). This is
the safety-critical decision core; it is deterministic and clock-injectable so it can
be exhaustively unit-tested (docs/VERIFICATION_AND_VALIDATION.md, FR-5 row).

Design notes:
- A single armed frame must NOT trip a major alarm: SUSPECT->THREAT requires a stage-2
  armed assessment, and THREAT->ALARM requires it to *persist* for the confirmation
  window. This is the core anti-false-positive mechanism (PR-4, pillar 3).
- De-escalation drops one level at a time (hysteresis) to avoid flicker.
- ALARM latches (when configured) until the threat is gone for the cooldown period AND
  the owner acknowledges — alarms don't silently self-clear.
"""

from __future__ import annotations

from dataclasses import dataclass

from autosentry.config import StateConfig
from autosentry.contracts import Level, ThreatAssessment, ThreatState


@dataclass
class StateInputs:
    """One tick of evidence fed to the machine."""

    track_present: bool = False  # any subject currently tracked in the zone
    stage1_trigger: bool = False  # weapon/loiter/approach/restricted-zone trigger (FR-3)
    assessment: ThreatAssessment | None = None  # stage-2 result, if produced this tick (FR-4)
    panic: bool = False  # manual panic override (FR-14)


class StateMachine:
    """Per-zone threat state machine."""

    def __init__(self, zone: str, config: StateConfig | None = None) -> None:
        self.zone = zone
        self.cfg = config or StateConfig()
        self._level = Level.NORMAL
        self._since = 0.0
        self._reason = "init"
        self._last_activity = 0.0
        self._threat_since: float | None = None  # entered THREAT at
        self._clear_since: float | None = None  # threat-free since (for cooldown)
        self._acked = False

    @property
    def level(self) -> Level:
        return self._level

    def acknowledge(self) -> None:
        """Owner acknowledges an active alarm; required (with cooldown) to clear a latch."""
        self._acked = True

    def state(self) -> ThreatState:
        return ThreatState(
            level=self._level, zone=self.zone, since=self._since, reason=self._reason
        )

    def _set(self, level: Level, now: float, reason: str) -> None:
        if level != self._level:
            self._since = now
            if level == Level.THREAT:
                self._threat_since = now
            elif level in (Level.NORMAL, Level.WATCH):
                self._threat_since = None
            if level == Level.ALARM:
                self._acked = False
                self._clear_since = None
            elif level == Level.NORMAL:
                self._clear_since = None
        self._level = level
        self._reason = reason

    def update(self, inputs: StateInputs, now: float) -> ThreatState:
        """Advance the machine by one tick and return the resulting state."""
        # Panic overrides everything and latches ALARM (FR-14).
        if inputs.panic:
            self._set(Level.ALARM, now, "manual panic")
            return self.state()

        armed_now = (
            inputs.assessment is not None
            and inputs.assessment.armed
            and inputs.assessment.confidence >= self.cfg.arm_confidence
        )
        suspicious = inputs.stage1_trigger
        activity = inputs.track_present or suspicious or armed_now
        if activity:
            self._last_activity = now

        idle = (now - self._last_activity) >= self.cfg.watch_timeout_s

        if self._level == Level.NORMAL:
            if suspicious or armed_now:
                self._set(Level.SUSPECT, now, "stage-1 trigger")
            elif inputs.track_present:
                self._set(Level.WATCH, now, "subject present")

        elif self._level == Level.WATCH:
            if suspicious or armed_now:
                self._set(Level.SUSPECT, now, "stage-1 trigger")
            elif not activity and idle:
                self._set(Level.NORMAL, now, "watch timeout")

        elif self._level == Level.SUSPECT:
            if armed_now:
                self._set(Level.THREAT, now, "stage-2 armed assessment")
            elif not suspicious and not inputs.track_present:
                self._set(Level.WATCH, now, "trigger cleared")

        elif self._level == Level.THREAT:
            if armed_now:
                assert self._threat_since is not None
                if (now - self._threat_since) >= self.cfg.confirmation_window_s:
                    self._set(Level.ALARM, now, "threat confirmed")
            else:
                self._set(Level.SUSPECT, now, "threat de-escalated")

        elif self._level == Level.ALARM:
            threat_active = armed_now or suspicious
            if threat_active:
                self._clear_since = None
            elif self._clear_since is None:
                self._clear_since = now
            cooled = (
                self._clear_since is not None
                and (now - self._clear_since) >= self.cfg.cooldown_s
            )
            clearable = self._acked or not self.cfg.latch
            if cooled and clearable:
                self._set(Level.NORMAL, now, "alarm cleared")

        return self.state()
