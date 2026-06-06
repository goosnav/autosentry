"""Stage-1 -> stage-2 trigger policy (FR-3, docs/VISION_PIPELINE.md §3).

Stage-2 (the VLM) is expensive, so cheap signals decide when it's worth running. A track
fires a trigger when *any* condition holds (all thresholds in config):
  * a weapon class is associated with the track,
  * a person loiters in the zone longer than `loiter_s`,
  * a person is in a restricted zone during a restricted hour,
  * a person approaches faster than `approach_px_s`.

The output (a bool + human-readable reason) becomes the state machine's `stage1_trigger`.
Pure logic over Track[] — no model, fully unit-testable.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from autosentry.config import TriggerConfig
from autosentry.contracts import Track

# Stage-1 weapon classes (extensible; person uses COCO, weapons need a fine-tuned head).
WEAPON_CLASSES = frozenset({"handgun", "rifle", "knife", "weapon"})
PERSON_CLASS = "person"


@dataclass
class TriggerResult:
    fired: bool
    reason: str = ""
    track_id: int | None = None


class TriggerEvaluator:
    """Evaluates the stage-1 trigger policy for a zone. Stateless across frames."""

    def __init__(self, config: TriggerConfig) -> None:
        self.cfg = config

    def evaluate(self, tracks: list[Track], zone: str, ts: float) -> TriggerResult:
        """Return the first firing trigger across all tracks (weapon checked first)."""
        # Weapons dominate: check every track for a weapon association before behavior.
        for t in tracks:
            if t.cls in WEAPON_CLASSES:
                return TriggerResult(True, f"weapon:{t.cls}", t.track_id)

        restricted_zone = zone in self.cfg.restricted_zones
        hour = time.localtime(ts).tm_hour
        restricted_time = hour in self.cfg.restricted_hours

        for t in tracks:
            if t.cls != PERSON_CLASS:
                continue
            dwell = t.last_ts - t.first_ts
            if dwell >= self.cfg.loiter_s:
                return TriggerResult(True, f"loiter:{dwell:.0f}s", t.track_id)
            if restricted_zone and restricted_time:
                return TriggerResult(True, f"restricted:{zone}@{hour:02d}h", t.track_id)
            speed = self._approach_speed(t)
            if speed >= self.cfg.approach_px_s:
                return TriggerResult(True, f"approach:{speed:.0f}px/s", t.track_id)

        return TriggerResult(False)

    def _approach_speed(self, t: Track) -> float:
        """Average centroid speed (px/s) over the track's history — an approach proxy.

        Refined on hardware to "closing speed toward a configured entry"; magnitude of
        motion is the M1 proxy and is what we threshold on.
        """
        dt = t.last_ts - t.first_ts
        if dt <= 0.0 or len(t.history) < 2:
            return 0.0
        first, last = t.history[0], t.history[-1]
        dist = math.hypot(last.cx - first.cx, last.cy - first.cy)
        return dist / dt
