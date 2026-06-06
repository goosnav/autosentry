"""Stage-1 detector: YOLO + tracker (FR-3, PR-1).

Per-frame person/weapon detection plus persistent track IDs so downstream logic can reason
over behavior across time (docs/VISION_PIPELINE.md §2). The model call is isolated behind a
small `Backend` protocol: the real backend lazy-loads Ultralytics YOLO (TensorRT on Jetson,
ONNX/torch elsewhere), while the surrounding logic — class filtering, confidence gating,
track association — is pure and unit-tested with a fake backend.

STATUS: M1 — detection-filtering + tracking implemented; YOLO backend lazy-loaded.
"""

from __future__ import annotations

from typing import Protocol

from autosentry.config import DetectionConfig
from autosentry.contracts import Detection, Frame, Track
from autosentry.detection.tracking import IoUTracker
from autosentry.detection.triggers import PERSON_CLASS, WEAPON_CLASSES


class Backend(Protocol):
    """Runs a model on one image and returns raw detections (pre-filter)."""

    def infer(self, image: object) -> list[Detection]: ...


class Detector:
    """Wraps the stage-1 model + tracker. On Jetson, prefer the TensorRT engine."""

    def __init__(
        self,
        config: DetectionConfig,
        backend: Backend | None = None,
        tracker: IoUTracker | None = None,
    ) -> None:
        self.cfg = config
        self._backend = backend  # lazily built on first use if None
        self._tracker = tracker or IoUTracker(
            iou_threshold=config.track_iou,
            max_age=config.track_max_age,
            history=config.track_history,
        )

    def _ensure_backend(self) -> Backend:
        if self._backend is None:
            from autosentry.detection.yolo_backend import YoloBackend

            self._backend = YoloBackend(self.cfg)
        return self._backend

    def _keep(self, d: Detection) -> bool:
        """Confidence gate per class (weapons and persons have separate thresholds)."""
        if d.cls in WEAPON_CLASSES:
            return d.conf >= self.cfg.conf_weapon
        if d.cls == PERSON_CLASS:
            return d.conf >= self.cfg.conf_person
        return False  # ignore everything we don't act on (FR-3 keys on person + weapons)

    def detect(self, frame: Frame) -> list[Detection]:
        """Run the detector on one frame and return kept detections."""
        raw = self._ensure_backend().infer(frame.image)
        return [d for d in raw if self._keep(d)]

    def track(self, frame: Frame) -> list[Track]:
        """Run detection + tracking, returning persistent tracks for the frame."""
        return self._tracker.update(self.detect(frame), frame.ts)
