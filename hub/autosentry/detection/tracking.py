"""Multi-object tracker — assigns persistent track IDs across frames (FR-3).

A portable, dependency-free IoU/greedy-association tracker so downstream logic can reason
over a subject's behavior across *time*, not a single frame (loiter, approach). On the
Jetson the production path is Ultralytics' ByteTrack; this implementation is the dev/CI
tracker and the contract both must satisfy: a subject keeps the same `track_id` while it
persists, gets a fresh ID when it's new, and is dropped after it's been missing too long.

Pure stdlib — fully unit-testable without a camera or model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autosentry.contracts import BBox, Detection, Track


def iou(a: BBox, b: BBox) -> float:
    """Intersection-over-union of two boxes; 0.0 if they don't overlap."""
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


@dataclass
class _Tracked:
    track: Track
    misses: int = 0


@dataclass
class IoUTracker:
    """Greedy IoU tracker. One instance per zone (track IDs are zone-local)."""

    iou_threshold: float = 0.3
    max_age: int = 30  # frames a track may go unmatched before being dropped
    history: int = 30  # bbox history length per track

    _next_id: int = field(default=1, init=False)
    _tracked: list[_Tracked] = field(default_factory=list, init=False)

    def update(self, detections: list[Detection], ts: float) -> list[Track]:
        """Associate detections to existing tracks; return the tracks present this frame."""
        # Greedy association: highest-IoU pairs first, each track/detection used once.
        pairs: list[tuple[float, int, int]] = []
        for ti, t in enumerate(self._tracked):
            for di, d in enumerate(detections):
                score = iou(t.track.bbox, d.bbox)
                if score >= self.iou_threshold:
                    pairs.append((score, ti, di))
        pairs.sort(key=lambda p: p[0], reverse=True)

        matched_t: set[int] = set()
        matched_d: set[int] = set()
        present: list[Track] = []
        for _score, ti, di in pairs:
            if ti in matched_t or di in matched_d:
                continue
            matched_t.add(ti)
            matched_d.add(di)
            present.append(self._advance(self._tracked[ti], detections[di], ts))

        # Age out unmatched existing tracks; drop those past max_age.
        survivors: list[_Tracked] = []
        for ti, t in enumerate(self._tracked):
            if ti in matched_t:
                survivors.append(t)
                continue
            t.misses += 1
            if t.misses <= self.max_age:
                survivors.append(t)
        self._tracked = survivors

        # Unmatched detections become new tracks.
        for di, d in enumerate(detections):
            if di not in matched_d:
                present.append(self._spawn(d, ts))

        return present

    def _advance(self, t: _Tracked, d: Detection, ts: float) -> Track:
        t.misses = 0
        tr = t.track
        tr.bbox = d.bbox
        tr.cls = d.cls
        tr.last_ts = ts
        tr.history.append(d.bbox)
        if len(tr.history) > self.history:
            tr.history = tr.history[-self.history :]
        return tr

    def _spawn(self, d: Detection, ts: float) -> Track:
        tr = Track(
            track_id=self._next_id,
            cls=d.cls,
            bbox=d.bbox,
            first_ts=ts,
            last_ts=ts,
            history=[d.bbox],
        )
        self._next_id += 1
        self._tracked.append(_Tracked(track=tr))
        return tr
