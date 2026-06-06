"""Unit tests for the detection eval metrics core (PR-4/PR-5; eval_detection.py).

Pins the matching/metrics math (precision, recall, FN-rate, per-class) that the PR-5 gate
depends on. The CLI's dataset loading is out of scope (needs a labeled benchmark).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from eval_detection import Box, evaluate, match_image  # noqa: E402

from autosentry.contracts import BBox  # noqa: E402


def _b(cls: str, x: float = 0.0) -> Box:
    return Box(cls=cls, bbox=BBox(x, 0, x + 10, 10))


def test_perfect_match():
    preds = [_b("person"), _b("rifle", x=100)]
    gts = [_b("person"), _b("rifle", x=100)]
    tp, fp, fn = match_image(preds, gts, iou_thr=0.5)
    assert (tp, fp, fn) == (2, 0, 0)


def test_missed_detection_is_false_negative():
    tp, fp, fn = match_image([_b("person")], [_b("person"), _b("rifle", x=100)], 0.5)
    assert (tp, fp, fn) == (1, 0, 1)


def test_spurious_detection_is_false_positive():
    tp, fp, fn = match_image([_b("person"), _b("knife", x=100)], [_b("person")], 0.5)
    assert (tp, fp, fn) == (1, 1, 0)


def test_class_mismatch_does_not_match():
    tp, fp, fn = match_image([_b("rifle")], [_b("person")], 0.5)
    assert (tp, fp, fn) == (0, 1, 1)


def test_low_iou_does_not_match():
    preds = [Box("person", BBox(0, 0, 10, 10))]
    gts = [Box("person", BBox(50, 50, 60, 60))]  # disjoint
    assert match_image(preds, gts, 0.5) == (0, 1, 1)


def test_aggregate_metrics_and_fn_rate():
    images = [
        ([_b("rifle")], [_b("rifle")]),               # tp
        ([], [_b("rifle")]),                          # fn (missed weapon)
        ([_b("person")], [_b("person")]),             # tp
    ]
    res = evaluate(images, iou_thr=0.5)
    assert res.tp == 2 and res.fn == 1 and res.fp == 0
    assert abs(res.recall - 2 / 3) < 1e-9
    assert res.precision == 1.0
    assert abs(res.fn_rate - 1 / 3) < 1e-9
    assert res.per_class["rifle"] == (1, 0, 1)
    assert res.per_class["person"] == (1, 0, 0)
