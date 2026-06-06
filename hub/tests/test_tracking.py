"""Unit tests for the IoU tracker (FR-3) — track-ID continuity across frames.

The contract: a subject keeps its track_id while it persists, a genuinely new subject gets
a fresh id, and a subject gone longer than max_age is dropped. These are the behaviors
downstream loiter/approach logic relies on.
"""

from __future__ import annotations

from autosentry.contracts import BBox, Detection
from autosentry.detection.tracking import IoUTracker, iou


def _det(cls: str, x1: float, y1: float, x2: float, y2: float, conf: float = 0.9) -> Detection:
    return Detection(cls=cls, conf=conf, bbox=BBox(x1, y1, x2, y2), ts=0.0)


def test_iou_identical_is_one():
    b = BBox(0, 0, 10, 10)
    assert iou(b, b) == 1.0


def test_iou_disjoint_is_zero():
    assert iou(BBox(0, 0, 10, 10), BBox(20, 20, 30, 30)) == 0.0


def test_iou_half_overlap():
    # Two 10x10 boxes overlapping in a 5x10 strip: inter=50, union=150 -> 1/3.
    val = iou(BBox(0, 0, 10, 10), BBox(5, 0, 15, 10))
    assert abs(val - (50 / 150)) < 1e-9


def test_same_object_keeps_id():
    tr = IoUTracker(iou_threshold=0.3)
    a = tr.update([_det("person", 0, 0, 10, 20)], ts=0.0)
    # Next frame: slightly shifted but strongly overlapping -> same id.
    b = tr.update([_det("person", 1, 0, 11, 20)], ts=0.1)
    assert len(a) == len(b) == 1
    assert a[0].track_id == b[0].track_id


def test_distinct_objects_get_distinct_ids():
    tr = IoUTracker(iou_threshold=0.3)
    out = tr.update(
        [_det("person", 0, 0, 10, 20), _det("person", 100, 0, 110, 20)], ts=0.0
    )
    assert {t.track_id for t in out} == {1, 2}


def test_new_object_after_gap_gets_new_id():
    tr = IoUTracker(iou_threshold=0.3, max_age=0)
    first = tr.update([_det("person", 0, 0, 10, 20)], ts=0.0)
    tr.update([], ts=0.1)  # object disappears; with max_age=0 it's dropped immediately
    # A new, non-overlapping object -> fresh id, not the recycled one.
    second = tr.update([_det("person", 200, 0, 210, 20)], ts=0.2)
    assert first[0].track_id != second[0].track_id


def test_track_survives_brief_miss_then_rematches():
    tr = IoUTracker(iou_threshold=0.3, max_age=5)
    a = tr.update([_det("person", 0, 0, 10, 20)], ts=0.0)
    tr.update([], ts=0.1)  # one missed frame, within max_age
    b = tr.update([_det("person", 0, 0, 10, 20)], ts=0.2)
    assert a[0].track_id == b[0].track_id


def test_track_dropped_after_max_age():
    tr = IoUTracker(iou_threshold=0.3, max_age=2)
    tr.update([_det("person", 0, 0, 10, 20)], ts=0.0)
    for i in range(3):  # 3 consecutive misses > max_age=2
        tr.update([], ts=1.0 + i)
    # Re-appearing object cannot rematch a dropped track -> new id (id 2).
    out = tr.update([_det("person", 0, 0, 10, 20)], ts=10.0)
    assert out[0].track_id == 2


def test_history_is_capped():
    tr = IoUTracker(iou_threshold=0.0, history=3)
    out = []
    for i in range(6):
        out = tr.update([_det("person", i, 0, 10 + i, 20)], ts=float(i))
    assert len(out[0].history) == 3


def test_first_and_last_ts_tracked():
    tr = IoUTracker(iou_threshold=0.3)
    tr.update([_det("person", 0, 0, 10, 20)], ts=5.0)
    out = tr.update([_det("person", 0, 0, 10, 20)], ts=8.0)
    assert out[0].first_ts == 5.0
    assert out[0].last_ts == 8.0
