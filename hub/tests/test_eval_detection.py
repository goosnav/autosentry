"""Unit tests for the detection eval metrics core (PR-4/PR-5; eval_detection.py).

Pins the matching/metrics math (precision, recall, FN-rate, per-class) that the PR-5 gate
depends on. The CLI's dataset loading is out of scope (needs a labeled benchmark).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from eval_detection import (  # noqa: E402
    Box,
    check_gates,
    discover_pairs,
    evaluate,
    ground_truth_boxes,
    load_names,
    match_image,
    parse_label_file,
    weapon_fn_rate,
    yolo_to_bbox,
)

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


# --- PR-4/PR-5 acceptance gates (docs/VISION_PIPELINE.md §7) ---------------------------
def test_weapon_fn_rate_ignores_person_misses():
    # Two missed persons must NOT count against the weapon FN gate (PR-5 is weapon-present).
    images = [
        ([], [_b("person")]),               # missed person — not a weapon miss
        ([], [_b("person", x=20)]),         # missed person — not a weapon miss
        ([_b("rifle", x=100)], [_b("rifle", x=100)]),  # weapon hit
    ]
    res = evaluate(images, iou_thr=0.5)
    assert weapon_fn_rate(res) == 0.0  # every weapon was found


def test_weapon_fn_rate_counts_missed_weapons():
    images = [
        ([_b("rifle")], [_b("rifle")]),     # tp
        ([], [_b("knife", x=100)]),         # missed weapon
    ]
    res = evaluate(images, iou_thr=0.5)
    assert abs(weapon_fn_rate(res) - 0.5) < 1e-9  # 1 of 2 weapons missed


def test_gates_pass_when_clean():
    images = [([_b("rifle")], [_b("rifle")])]
    report = check_gates(evaluate(images), max_fn_rate=0.05, benign_major_alarms=0)
    assert report.passed is True
    assert report.failures == []


def test_pr5_gate_fails_on_missed_weapon():
    images = [([_b("rifle")], [_b("rifle")]), ([], [_b("rifle", x=100)])]  # 50% FN
    report = check_gates(evaluate(images), max_fn_rate=0.05)
    assert report.passed is False
    assert any("PR-5" in f for f in report.failures)


def test_pr4_gate_fails_on_benign_major_alarm():
    images = [([_b("person")], [_b("person")])]  # detection-clean
    report = check_gates(evaluate(images), benign_major_alarms=1)
    assert report.passed is False
    assert any("PR-4" in f for f in report.failures)


# --- YOLO-format dataset loading (the loader is pure; the detector run is not tested here) ---
def test_load_names_default_and_from_file(tmp_path):
    assert load_names(None)[0] == "person"
    f = tmp_path / "names.txt"
    f.write_text("person\nrifle\n")
    assert load_names(str(f)) == ["person", "rifle"]


def test_parse_label_file(tmp_path):
    f = tmp_path / "img1.txt"
    f.write_text("0 0.5 0.5 0.2 0.4\n2 0.1 0.1 0.05 0.05\n")
    rows = parse_label_file(str(f))
    assert rows[0] == (0, 0.5, 0.5, 0.2, 0.4)
    assert rows[1][0] == 2
    assert parse_label_file(str(tmp_path / "missing.txt")) == []  # missing -> empty


def test_yolo_to_bbox_converts_to_pixels():
    b = yolo_to_bbox(0.5, 0.5, 0.2, 0.4, width=100, height=200)
    assert (b.x1, b.y1, b.x2, b.y2) == (40.0, 60.0, 60.0, 140.0)


def test_ground_truth_boxes_maps_class_ids(tmp_path):
    lbl = tmp_path / "a.txt"
    lbl.write_text("2 0.5 0.5 0.5 0.5\n")  # class 2 -> "rifle" in the default names
    boxes = ground_truth_boxes(str(lbl), ["person", "handgun", "rifle", "knife"], 100, 100)
    assert len(boxes) == 1 and boxes[0].cls == "rifle"


def test_discover_pairs_images_labels_layout(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    (tmp_path / "images" / "a.jpg").write_bytes(b"x")
    (tmp_path / "images" / "b.png").write_bytes(b"x")
    (tmp_path / "labels" / "a.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    pairs = discover_pairs(str(tmp_path))
    assert len(pairs) == 2
    assert pairs[0][0].endswith("a.jpg") and pairs[0][1].endswith("a.txt")


def test_discover_pairs_flat_layout(tmp_path):
    (tmp_path / "x.jpg").write_bytes(b"x")
    (tmp_path / "x.txt").write_text("")
    pairs = discover_pairs(str(tmp_path))
    assert len(pairs) == 1 and pairs[0][1].endswith("x.txt")


def test_discover_pairs_empty_dir(tmp_path):
    assert discover_pairs(str(tmp_path)) == []
