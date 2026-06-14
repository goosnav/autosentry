#!/usr/bin/env python3
"""Detection evaluation harness (PR-4, PR-5, TPM-4/5; docs/VISION_PIPELINE.md §7).

Computes per-class precision/recall and the false-negative rate on a labeled benchmark,
plus a false-positive proxy on the benign suite (OS-2). The matching/metrics core is pure
and unit-tested; the CLI loads a YOLO-format benchmark and prints a report. CI gates on
FN-rate (PR-5) and on any major-alarm trigger in the benign suite (PR-4).

Usage:
  python scripts/eval_detection.py --set bench/        # run the labeled benchmark
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub"))

from autosentry.contracts import BBox  # noqa: E402
from autosentry.detection.tracking import iou  # noqa: E402

# Default class-id → name map (Ultralytics YOLO label files index classes by integer). Override
# with a --names file (one class name per line, in index order). Index 0 is COCO `person`.
_DEFAULT_NAMES = ["person", "handgun", "rifle", "knife"]
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")


@dataclass(frozen=True)
class Box:
    cls: str
    bbox: BBox


@dataclass
class EvalResult:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    per_class: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # cls -> (tp,fp,fn)

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def fn_rate(self) -> float:
        denom = self.tp + self.fn
        return self.fn / denom if denom else 0.0


def match_image(preds: list[Box], gts: list[Box], iou_thr: float) -> tuple[int, int, int]:
    """Greedy class-aware matching for one image -> (tp, fp, fn)."""
    candidates: list[tuple[float, int, int]] = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            if p.cls == g.cls:
                score = iou(p.bbox, g.bbox)
                if score >= iou_thr:
                    candidates.append((score, pi, gi))
    candidates.sort(key=lambda c: c[0], reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    tp = 0
    for _score, pi, gi in candidates:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        tp += 1
    fp = len(preds) - len(used_p)
    fn = len(gts) - len(used_g)
    return tp, fp, fn


# Weapon classes the PR-5 false-negative gate is computed over (docs/VISION_PIPELINE.md §2).
WEAPON_CLASSES = ("handgun", "rifle", "knife")


@dataclass
class GateReport:
    """Pass/fail of the CI acceptance gates with human-readable reasons (PR-4, PR-5)."""

    passed: bool
    failures: list[str] = field(default_factory=list)


def weapon_fn_rate(res: EvalResult, weapon_classes: tuple[str, ...] = WEAPON_CLASSES) -> float:
    """False-negative rate restricted to weapon classes — the PR-5 measure (weapon-present).

    A missed weapon is the safety-critical error (PR-5/TPM-5); person misses don't count
    against this gate. Returns 0.0 when the benchmark contains no weapon ground truth.
    """
    tp = fn = 0
    for cls in weapon_classes:
        if cls in res.per_class:
            ctp, _cfp, cfn = res.per_class[cls]
            tp += ctp
            fn += cfn
    denom = tp + fn
    return fn / denom if denom else 0.0


def check_gates(
    res: EvalResult,
    *,
    max_fn_rate: float = 0.05,
    benign_major_alarms: int = 0,
) -> GateReport:
    """Apply the CI acceptance gates (docs/VISION_PIPELINE.md §7).

    - **PR-5:** the weapon-present false-negative rate must be ≤ `max_fn_rate` (default 5%).
    - **PR-4:** the benign suite must produce **zero** major-alarm triggers (OS-2).

    Pure and side-effect-free so CI and tests share one source of truth for "is this build
    safe to ship". A non-empty `failures` list means the gate fails.
    """
    failures: list[str] = []
    wfn = weapon_fn_rate(res)
    if wfn > max_fn_rate:
        failures.append(f"PR-5: weapon false-negative rate {wfn:.3f} > {max_fn_rate:.3f}")
    if benign_major_alarms > 0:
        failures.append(
            f"PR-4: benign suite produced {benign_major_alarms} major-alarm trigger(s) (must be 0)"
        )
    return GateReport(passed=not failures, failures=failures)


def evaluate(images: list[tuple[list[Box], list[Box]]], iou_thr: float = 0.5) -> EvalResult:
    """Aggregate (preds, gts) over a benchmark into overall + per-class metrics."""
    res = EvalResult()
    acc: dict[str, list[int]] = {}
    for preds, gts in images:
        tp, fp, fn = match_image(preds, gts, iou_thr)
        res.tp += tp
        res.fp += fp
        res.fn += fn
        for cls in {b.cls for b in preds} | {b.cls for b in gts}:
            cp = [b for b in preds if b.cls == cls]
            cg = [b for b in gts if b.cls == cls]
            ctp, cfp, cfn = match_image(cp, cg, iou_thr)
            slot = acc.setdefault(cls, [0, 0, 0])
            slot[0] += ctp
            slot[1] += cfp
            slot[2] += cfn
    res.per_class = {c: (v[0], v[1], v[2]) for c, v in acc.items()}
    return res


# --- YOLO-format dataset loading (pure; the detector run is the only heavy step) ---------
def load_names(path: str | None) -> list[str]:
    """Class names in index order — from a --names file (one per line) or the default map."""
    if path and os.path.exists(path):
        with open(path) as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    return list(_DEFAULT_NAMES)


def parse_label_file(path: str) -> list[tuple[int, float, float, float, float]]:
    """Read a YOLO label file → [(cls_id, cx, cy, w, h)] (normalized). Missing file → []."""
    rows: list[tuple[int, float, float, float, float]] = []
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 5:
                continue
            c, cx, cy, w, h = parts[:5]
            rows.append((int(float(c)), float(cx), float(cy), float(w), float(h)))
    return rows


def yolo_to_bbox(cx: float, cy: float, w: float, h: float, width: int, height: int) -> BBox:
    """Normalized YOLO center-box → pixel BBox (so GT and detector preds share units)."""
    return BBox(
        x1=(cx - w / 2.0) * width,
        y1=(cy - h / 2.0) * height,
        x2=(cx + w / 2.0) * width,
        y2=(cy + h / 2.0) * height,
    )


def discover_pairs(root: str) -> list[tuple[str, str]]:
    """Find (image, label) pairs. Supports `<root>/images/` + `<root>/labels/` (Ultralytics)
    and a flat `<root>/*.jpg` + `<root>/*.txt` layout. Sorted for deterministic runs."""
    img_dir = os.path.join(root, "images")
    lbl_dir = os.path.join(root, "labels")
    if os.path.isdir(img_dir) and os.path.isdir(lbl_dir):
        images = [
            p for p in glob.glob(os.path.join(img_dir, "*")) if p.lower().endswith(_IMAGE_EXTS)
        ]
        return sorted(
            (img, os.path.join(lbl_dir, os.path.splitext(os.path.basename(img))[0] + ".txt"))
            for img in images
        )
    images = [p for p in glob.glob(os.path.join(root, "*")) if p.lower().endswith(_IMAGE_EXTS)]
    return sorted((img, os.path.splitext(img)[0] + ".txt") for img in images)


def ground_truth_boxes(label_path: str, names: list[str], width: int, height: int) -> list[Box]:
    """Convert a YOLO label file into pixel-space Box[] using the class-name map."""
    out: list[Box] = []
    for cls_id, cx, cy, w, h in parse_label_file(label_path):
        if 0 <= cls_id < len(names):
            out.append(Box(cls=names[cls_id], bbox=yolo_to_bbox(cx, cy, w, h, width, height)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoSentry detection eval (PR-4/PR-5)")
    ap.add_argument("--set", required=True, help="benchmark dir (YOLO format: images/ + labels/)")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--max-fn-rate", type=float, default=0.05, help="PR-5 weapon FN gate")
    ap.add_argument("--names", default=None, help="class-names file (one per line, index order)")
    ap.add_argument("--config", default=None, help="hub config.yaml (for the detector weights)")
    args = ap.parse_args(argv)

    pairs = discover_pairs(args.set)
    if not pairs:
        raise SystemExit(f"no image/label pairs under {args.set!r} (expected images/ + labels/)")
    names = load_names(args.names)

    # Heavy step (lazy): load the configured detector + read each image. Imported here so the
    # pure loaders above stay unit-testable without cv2/ultralytics.
    import cv2  # noqa: PLC0415

    from autosentry.config import Settings, load_settings
    from autosentry.contracts import Frame
    from autosentry.detection.detector import Detector

    settings = load_settings(args.config) if args.config else Settings()
    detector = Detector(settings.detection)

    images: list[tuple[list[Box], list[Box]]] = []
    for seq, (img_path, lbl_path) in enumerate(pairs):
        image = cv2.imread(img_path)
        if image is None:
            print(f"  skip (unreadable): {img_path}")
            continue
        height, width = image.shape[:2]
        gts = ground_truth_boxes(lbl_path, names, width, height)
        frame = Frame(zone="eval", ts=float(seq), image=image, seq=seq)
        preds = [Box(cls=d.cls, bbox=d.bbox) for d in detector.detect(frame)]  # stage-1 (FR-3)
        images.append((preds, gts))

    res = evaluate(images, iou_thr=args.iou)
    report = check_gates(res, max_fn_rate=args.max_fn_rate)
    print(f"images={len(images)} precision={res.precision:.3f} recall={res.recall:.3f} "
          f"weapon_fn_rate={weapon_fn_rate(res):.3f}")
    for cls, (tp, fp, fn) in sorted(res.per_class.items()):
        print(f"  {cls:10s} tp={tp} fp={fp} fn={fn}")
    if report.passed:
        print("GATE: PASS (PR-4/PR-5)")
        return 0
    for f in report.failures:
        print(f"GATE FAIL: {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
