"""Unit tests for Detector filtering + track delegation (FR-3), using a fake backend.

The model itself is out of scope here (it needs weights + GPU and is covered by on-hardware
runs); these tests pin the pure logic around it: per-class confidence gating, dropping
classes we don't act on, and that track() produces persistent tracks.
"""

from __future__ import annotations

from autosentry.config import DetectionConfig
from autosentry.contracts import BBox, Detection, Frame
from autosentry.detection.detector import Detector


class FakeBackend:
    def __init__(self, dets: list[Detection]) -> None:
        self._dets = dets

    def infer(self, image: object) -> list[Detection]:
        return list(self._dets)


def _det(cls: str, conf: float, x: float = 0.0) -> Detection:
    return Detection(cls=cls, conf=conf, bbox=BBox(x, 0, x + 10, 20), ts=0.0)


def _frame(ts: float = 0.0) -> Frame:
    return Frame(zone="front", ts=ts, image=object(), seq=0)


def test_keeps_confident_person_and_weapon():
    cfg = DetectionConfig(conf_person=0.4, conf_weapon=0.5)
    det = Detector(cfg, backend=FakeBackend([_det("person", 0.9), _det("rifle", 0.8, x=50)]))
    out = det.detect(_frame())
    assert {d.cls for d in out} == {"person", "rifle"}


def test_drops_low_confidence_per_class_threshold():
    cfg = DetectionConfig(conf_person=0.4, conf_weapon=0.5)
    det = Detector(
        cfg,
        backend=FakeBackend([_det("person", 0.3), _det("rifle", 0.49, x=50)]),
    )
    assert det.detect(_frame()) == []  # both below their class thresholds


def test_ignores_unactioned_classes():
    cfg = DetectionConfig()
    det = Detector(cfg, backend=FakeBackend([_det("car", 0.99), _det("dog", 0.99, x=50)]))
    assert det.detect(_frame()) == []


def test_track_assigns_persistent_ids():
    cfg = DetectionConfig()
    det = Detector(cfg, backend=FakeBackend([_det("person", 0.9)]))
    a = det.track(_frame(ts=0.0))
    b = det.track(_frame(ts=0.1))
    assert a[0].track_id == b[0].track_id  # same detector -> same tracker -> stable id
