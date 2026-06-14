"""Unit tests for the stage-1 trigger policy (FR-3, docs/VISION_PIPELINE.md §3)."""

from __future__ import annotations

import time

from autosentry.config import TriggerConfig
from autosentry.contracts import BBox, Track
from autosentry.detection.triggers import TriggerEvaluator


def _track(cls: str, tid: int = 1, first_ts: float = 0.0, last_ts: float = 0.0,
           history: list[BBox] | None = None) -> Track:
    box = BBox(0, 0, 10, 20)
    return Track(
        track_id=tid,
        cls=cls,
        bbox=box,
        first_ts=first_ts,
        last_ts=last_ts,
        history=history if history is not None else [box],
    )


def test_no_tracks_no_trigger():
    ev = TriggerEvaluator(TriggerConfig())
    assert ev.evaluate([], "front", 0.0).fired is False


def test_weapon_class_fires():
    ev = TriggerEvaluator(TriggerConfig())
    res = ev.evaluate([_track("rifle")], "front", 0.0)
    assert res.fired is True
    assert "weapon" in res.reason


def test_benign_person_does_not_fire():
    ev = TriggerEvaluator(TriggerConfig(loiter_s=20.0, approach_px_s=120.0))
    # Present briefly, no movement -> no trigger.
    assert ev.evaluate([_track("person")], "front", 0.0).fired is False


def test_loiter_fires():
    ev = TriggerEvaluator(TriggerConfig(loiter_s=20.0))
    t = _track("person", first_ts=0.0, last_ts=25.0)
    res = ev.evaluate([t], "front", 25.0)
    assert res.fired and res.reason.startswith("loiter")


def test_approach_fires():
    ev = TriggerEvaluator(TriggerConfig(approach_px_s=100.0, loiter_s=999.0))
    # Centroid moves 500px over 1s -> 500 px/s, above the 100 px/s threshold.
    hist = [BBox(0, 0, 10, 10), BBox(0, 500, 10, 510)]
    t = _track("person", first_ts=0.0, last_ts=1.0, history=hist)
    res = ev.evaluate([t], "front", 1.0)
    assert res.fired and res.reason.startswith("approach")


def test_slow_movement_does_not_fire_approach():
    ev = TriggerEvaluator(TriggerConfig(approach_px_s=100.0, loiter_s=999.0))
    hist = [BBox(0, 0, 10, 10), BBox(0, 10, 10, 20)]  # 10px over 1s -> 10 px/s
    t = _track("person", first_ts=0.0, last_ts=1.0, history=hist)
    assert ev.evaluate([t], "front", 1.0).fired is False


def test_loiter_then_sprint_fires_on_recent_window():
    # 60s of near-stationary loiter, then a 400px sprint in the last 2s. Lifetime average is
    # ~400/62 ≈ 6 px/s (below threshold), but the recent window sees ~200 px/s — must fire.
    ev = TriggerEvaluator(
        TriggerConfig(approach_px_s=100.0, loiter_s=999.0, approach_window_s=2.0)
    )
    history = [BBox(0, 0, 10, 10), BBox(1, 1, 11, 11), BBox(0, 400, 10, 410)]
    history_ts = [0.0, 60.0, 62.0]  # last two samples are 2s apart, 400px of motion
    t = Track(
        track_id=1, cls="person", bbox=history[-1],
        first_ts=0.0, last_ts=62.0, history=history, history_ts=history_ts,
    )
    res = ev.evaluate([t], "front", 62.0)
    assert res.fired and res.reason.startswith("approach")


def test_loiter_then_sprint_evades_lifetime_average_proof():
    # Same track WITHOUT timestamps falls back to the lifetime average and does NOT fire —
    # this is the bug the windowed speed fixes (documents the difference explicitly).
    ev = TriggerEvaluator(TriggerConfig(approach_px_s=100.0, loiter_s=999.0))
    history = [BBox(0, 0, 10, 10), BBox(1, 1, 11, 11), BBox(0, 400, 10, 410)]
    t = _track("person", first_ts=0.0, last_ts=62.0, history=history)  # no history_ts
    assert ev.evaluate([t], "front", 62.0).fired is False


def test_restricted_zone_and_time_fires():
    ts = 1_700_000_000.0
    hour = time.localtime(ts).tm_hour  # derive the actual local hour for determinism
    ev = TriggerEvaluator(
        TriggerConfig(loiter_s=999.0, approach_px_s=999.0,
                      restricted_zones=["front"], restricted_hours=[hour])
    )
    res = ev.evaluate([_track("person")], "front", ts)
    assert res.fired and res.reason.startswith("restricted")


def test_restricted_zone_wrong_zone_does_not_fire():
    ts = 1_700_000_000.0
    hour = time.localtime(ts).tm_hour
    ev = TriggerEvaluator(
        TriggerConfig(loiter_s=999.0, approach_px_s=999.0,
                      restricted_zones=["garage"], restricted_hours=[hour])
    )
    assert ev.evaluate([_track("person")], "front", ts).fired is False


def test_weapon_takes_precedence_over_person_signals():
    ev = TriggerEvaluator(TriggerConfig(loiter_s=0.0))  # person would loiter-fire
    res = ev.evaluate([_track("person"), _track("knife", tid=2)], "front", 0.0)
    assert "weapon" in res.reason
