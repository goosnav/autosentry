"""Ultralytics YOLO backend (FR-3, PR-1).

The real stage-1 model. Lazy-imports ultralytics so the package and its pure logic import
without the vision extra. On the Jetson, point `config.model` at a TensorRT engine; on dev
machines a `.pt`/ONNX file works. Maps native YOLO results into the `Detection` contract and
normalizes class names to our canonical {person, handgun, rifle, knife}.

This module is exercised by on-hardware/integration runs (it needs real weights), not the
pure unit suite — the Detector's filtering/tracking logic is tested with a fake backend.
"""

from __future__ import annotations

import os

from autosentry.config import DetectionConfig
from autosentry.contracts import BBox, Detection

# Map common label spellings to our canonical classes.
_CLASS_ALIASES = {
    "person": "person",
    "pistol": "handgun",
    "handgun": "handgun",
    "gun": "handgun",
    "rifle": "rifle",
    "long_gun": "rifle",
    "knife": "knife",
}


class YoloBackend:
    """Runs Ultralytics YOLO and returns raw Detections (Detector applies the conf gates)."""

    def __init__(self, config: DetectionConfig) -> None:
        self.cfg = config
        self._model = None

    def _resolve(self, name: str) -> str:
        """Prefer the provisioned weight under models_dir; fall back to the bare name so
        Ultralytics can still auto-fetch it if provisioning was skipped (FR-18)."""
        local = os.path.join(self.cfg.models_dir, name)
        return local if os.path.exists(local) else name

    def _load(self):
        if self._model is None:
            from ultralytics import YOLO  # heavy, lazy

            self._model = YOLO(self._resolve(self.cfg.weapon_model or self.cfg.model))
            if self.cfg.device not in ("auto", ""):
                self._model.to("cuda" if self.cfg.device == "tensorrt" else self.cfg.device)
        return self._model

    def infer(self, image: object) -> list[Detection]:
        model = self._load()
        # verbose=False keeps the hot path quiet; conf=0 here, gating happens in Detector.
        results = model(image, verbose=False)
        out: list[Detection] = []
        for r in results:
            names = r.names
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for b in boxes:
                raw_name = names[int(b.cls)]
                cls = _CLASS_ALIASES.get(str(raw_name).lower())
                if cls is None:
                    continue
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                out.append(
                    Detection(cls=cls, conf=float(b.conf), bbox=BBox(x1, y1, x2, y2), ts=0.0)
                )
        return out
