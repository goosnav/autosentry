"""Unit tests for the threat state machine (FR-5) — the safety-critical decision core.

These tests pin the anti-false-positive contract (pillar 3): a single armed frame must
never trip a major alarm, and an alarm must not silently self-clear. The machine takes an
injected clock (`now`) so time-dependent behavior is deterministic.
"""

from __future__ import annotations

from dataclasses import replace

from autosentry.config import StateConfig
from autosentry.contracts import Level, ThreatAssessment
from autosentry.state import StateInputs, StateMachine


def _armed(conf: float, zone: str = "front", ts: float = 0.0) -> ThreatAssessment:
    return ThreatAssessment(armed=True, confidence=conf, zone=zone, ts=ts)


def _cfg(**kw) -> StateConfig:
    base = dict(
        watch_timeout_s=30.0,
        arm_confidence=0.6,
        confirmation_window_s=1.5,
        cooldown_s=60.0,
        latch=True,
    )
    base.update(kw)
    return StateConfig(**base)


def test_starts_normal():
    m = StateMachine("front", _cfg())
    assert m.level == Level.NORMAL


def test_track_present_goes_to_watch():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True), now=0.0)
    assert m.level == Level.WATCH


def test_stage1_trigger_goes_to_suspect():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.0)
    assert m.level == Level.SUSPECT


def test_normal_stays_normal_when_idle():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(), now=0.0)  # no track, no trigger
    assert m.level == Level.NORMAL


def test_watch_escalates_to_suspect_on_trigger():
    # NORMAL -> WATCH -> SUSPECT: the escalation must work from WATCH, not only NORMAL.
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True), now=0.0)
    assert m.level == Level.WATCH
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.5)
    assert m.level == Level.SUSPECT


def test_watch_persists_under_continued_benign_activity():
    # A subject lingering (no trigger) keeps us in WATCH; the idle timer must not fire.
    m = StateMachine("front", _cfg(watch_timeout_s=30.0))
    m.update(StateInputs(track_present=True), now=0.0)
    m.update(StateInputs(track_present=True), now=100.0)  # activity resets the idle clock
    assert m.level == Level.WATCH


def test_suspect_relaxes_to_watch_when_trigger_and_track_clear():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.0)
    assert m.level == Level.SUSPECT
    # Trigger gone but a subject is still tracked -> stay SUSPECT (subject of interest).
    m.update(StateInputs(track_present=True), now=0.5)
    assert m.level == Level.SUSPECT
    # Both trigger and track gone -> de-escalate to WATCH.
    m.update(StateInputs(), now=1.0)
    assert m.level == Level.WATCH


def test_armed_only_path_reaches_threat_without_stage1_trigger():
    # A confident stage-2 armed assessment alone (no cheap trigger) still escalates.
    m = StateMachine("front", _cfg())
    m.update(StateInputs(assessment=_armed(0.9)), now=0.0)
    assert m.level == Level.SUSPECT
    m.update(StateInputs(assessment=_armed(0.9)), now=0.1)
    assert m.level == Level.THREAT


def test_low_confidence_armed_does_not_reach_threat():
    # Below arm_confidence the assessment must not escalate past SUSPECT (PR-4).
    m = StateMachine("front", _cfg())
    inp = StateInputs(track_present=True, stage1_trigger=True, assessment=_armed(0.5))
    m.update(inp, now=0.0)
    assert m.level == Level.SUSPECT


def test_single_armed_frame_does_not_alarm():
    # The core anti-false-positive guarantee: one armed frame -> THREAT, never ALARM.
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.0)
    m.update(StateInputs(track_present=True, assessment=_armed(0.9)), now=0.1)
    assert m.level == Level.THREAT


def test_sustained_armed_confirms_alarm():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.0)
    m.update(StateInputs(track_present=True, assessment=_armed(0.9)), now=0.1)  # -> THREAT
    assert m.level == Level.THREAT
    # Still inside the confirmation window: no alarm yet.
    m.update(StateInputs(track_present=True, assessment=_armed(0.9)), now=1.0)
    assert m.level == Level.THREAT
    # Past the confirmation window with the threat persisting: ALARM.
    m.update(StateInputs(track_present=True, assessment=_armed(0.9)), now=2.0)
    assert m.level == Level.ALARM


def test_threat_deescalates_when_disarmed():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.0)
    m.update(StateInputs(track_present=True, assessment=_armed(0.9)), now=0.1)  # THREAT
    # Disarmed next tick -> drop one level (hysteresis), not straight to NORMAL.
    m.update(StateInputs(track_present=True, stage1_trigger=True), now=0.2)
    assert m.level == Level.SUSPECT


def test_panic_latches_alarm_immediately():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(panic=True), now=0.0)
    assert m.level == Level.ALARM
    # No activity afterward, but the alarm latches (no ack, no cooldown elapsed).
    m.update(StateInputs(), now=5.0)
    assert m.level == Level.ALARM


def test_alarm_latches_until_ack_and_cooldown():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(panic=True), now=0.0)  # ALARM
    m.update(StateInputs(), now=1.0)  # threat-free; clear timer starts
    # Cooldown elapsed but NOT acknowledged -> still latched.
    m.update(StateInputs(), now=100.0)
    assert m.level == Level.ALARM
    # Acknowledge, then let cooldown pass -> clears.
    m.acknowledge()
    m.update(StateInputs(), now=200.0)
    assert m.level == Level.NORMAL


def test_alarm_clears_without_ack_when_latch_disabled():
    m = StateMachine("front", _cfg(latch=False))
    m.update(StateInputs(panic=True), now=0.0)
    m.update(StateInputs(), now=1.0)  # clear timer starts
    m.update(StateInputs(), now=100.0)  # cooled; latch off -> clears without ack
    assert m.level == Level.NORMAL


def test_renewed_threat_resets_cooldown():
    m = StateMachine("front", _cfg())
    m.update(StateInputs(panic=True), now=0.0)  # ALARM
    m.update(StateInputs(), now=1.0)  # clear timer starts at 1.0
    # Threat reappears -> cooldown must restart, alarm stays.
    m.update(StateInputs(stage1_trigger=True), now=2.0)
    m.acknowledge()
    m.update(StateInputs(), now=3.0)  # new clear timer starts at 3.0
    m.update(StateInputs(), now=50.0)  # only 47s since clear -> still latched
    assert m.level == Level.ALARM


def test_watch_times_out_to_normal():
    m = StateMachine("front", _cfg(watch_timeout_s=30.0))
    m.update(StateInputs(track_present=True), now=0.0)  # WATCH
    assert m.level == Level.WATCH
    # Idle past the watch timeout with no activity -> back to NORMAL.
    m.update(StateInputs(), now=31.0)
    assert m.level == Level.NORMAL


def test_state_reports_zone_and_reason():
    m = StateMachine("garage", _cfg())
    st = m.update(StateInputs(track_present=True), now=0.0)
    assert st.zone == "garage"
    assert st.level == Level.WATCH
    assert st.reason  # non-empty human-readable reason

    # `replace` sanity: ThreatState is a plain dataclass carrying the snapshot.
    assert replace(st, reason="x").reason == "x"
