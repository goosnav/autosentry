"""Unit tests for the ICD-7 data contracts (IR-4).

The contracts are the seams between subsystems; ThreatAssessment in particular is the
schema that rejects a malformed/hallucinated VLM response (FR-4, FMEA F7), so its bounds
must be enforced.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from autosentry.contracts import (
    BBox,
    Level,
    MsgType,
    ThreatAssessment,
)


def test_bbox_center():
    b = BBox(x1=0.0, y1=0.0, x2=10.0, y2=20.0)
    assert b.cx == 5.0
    assert b.cy == 10.0


def test_bbox_is_frozen():
    b = BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0)
    with pytest.raises(FrozenInstanceError):
        b.x1 = 5.0  # type: ignore[misc]


def test_assessment_accepts_valid():
    a = ThreatAssessment(armed=True, confidence=0.9, zone="front", ts=1.0)
    assert a.armed is True
    assert a.weapon_type is None  # optional default


def test_assessment_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        ThreatAssessment(armed=True, confidence=1.5, zone="front", ts=1.0)
    with pytest.raises(ValidationError):
        ThreatAssessment(armed=False, confidence=-0.1, zone="front", ts=1.0)


def test_assessment_requires_zone_and_ts():
    with pytest.raises(ValidationError):
        ThreatAssessment(armed=True, confidence=0.5)  # type: ignore[call-arg]


def test_enums_are_strings():
    # str-Enum membership keeps wire/logging values stable and human-readable.
    assert Level.ALARM == "ALARM"
    assert MsgType.HEARTBEAT == "HEARTBEAT"
