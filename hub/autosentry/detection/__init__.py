"""Stage-1 detection + tracking + trigger policy (FR-3, PR-1). See docs/VISION_PIPELINE.md."""

from autosentry.detection.detector import Detector
from autosentry.detection.tracking import IoUTracker, iou
from autosentry.detection.triggers import TriggerEvaluator, TriggerResult

__all__ = ["Detector", "IoUTracker", "TriggerEvaluator", "TriggerResult", "iou"]
