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
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hub"))

from autosentry.contracts import BBox  # noqa: E402
from autosentry.detection.tracking import iou  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoSentry detection eval")
    ap.add_argument("--set", required=True, help="benchmark dir (YOLO format)")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--max-fn-rate", type=float, default=0.05, help="PR-5 gate")
    args = ap.parse_args(argv)
    # TODO(M1+): load images/labels from --set and run the live Detector to produce preds.
    # The metrics core (evaluate/match_image) is implemented + unit-tested now.
    raise SystemExit(
        f"benchmark loading for '{args.set}' lands with the labeled dataset; "
        "metrics core is tested (see hub/tests/test_eval_detection.py)."
    )


if __name__ == "__main__":
    raise SystemExit(main())
