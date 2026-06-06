"""Unit tests for the stage-2 Assessor (FR-4; reasoning/assessor.py).

Pins the parse/validate/retry/fallback contract with a fake VLM backend (no model, no
HTTP). The key safety properties: malformed/out-of-bounds output is rejected, a failing
or timing-out backend yields the conservative fallback (never silence — FMEA F6/F7), and
zone/ts are hub provenance and cannot be spoofed by the model.
"""

from __future__ import annotations

from autosentry.config import ReasoningConfig
from autosentry.reasoning.assessor import Assessor

_GOOD = '{"armed": true, "weapon_type": "rifle", "intent": "advancing", "confidence": 0.86, "description": "long gun"}'  # noqa: E501


class FakeBackend:
    """Returns a queued sequence of raw responses; optionally raises."""

    def __init__(self, *responses: str, raises: bool = False) -> None:
        self._responses = list(responses)
        self._raises = raises
        self.calls = 0

    def generate(self, prompt: str, images: list[object]) -> str:
        self.calls += 1
        if self._raises:
            raise RuntimeError("backend down")
        return self._responses.pop(0)


def _assessor(backend: FakeBackend) -> Assessor:
    return Assessor(ReasoningConfig(), backend=backend)


def test_valid_json_parses_to_assessment():
    a = _assessor(FakeBackend(_GOOD)).assess([], [object()], "front", 12.0)
    assert a.armed is True
    assert a.weapon_type == "rifle"
    assert a.confidence == 0.86
    assert a.zone == "front" and a.ts == 12.0


def test_json_embedded_in_prose_is_extracted():
    raw = 'Sure! Here is the assessment: ' + _GOOD + ' Hope that helps.'
    a = _assessor(FakeBackend(raw)).assess([], [object()], "front", 0.0)
    assert a.armed is True and a.weapon_type == "rifle"


def test_malformed_then_valid_uses_retry():
    b = FakeBackend("not json at all", _GOOD)
    a = _assessor(b).assess([], [object()], "front", 0.0)
    assert b.calls == 2
    assert a.weapon_type == "rifle"


def test_malformed_twice_falls_back_conservative():
    b = FakeBackend("nope", "still nope")
    a = _assessor(b).assess([], [object()], "z", 5.0)
    assert b.calls == 2
    assert a.armed is True and a.confidence == 0.5
    assert "unavailable" in a.intent


def test_backend_failure_falls_back_immediately():
    b = FakeBackend(raises=True)
    a = _assessor(b).assess([], [object()], "z", 5.0)
    assert b.calls == 1  # no pointless retry on a hard transport failure
    assert a.armed is True and a.confidence == 0.5


def test_out_of_bounds_confidence_is_rejected():
    # confidence > 1 violates the schema -> both attempts rejected -> fallback
    bad = '{"armed": true, "confidence": 1.7}'
    a = _assessor(FakeBackend(bad, bad)).assess([], [object()], "z", 0.0)
    assert a.confidence == 0.5  # the fallback, not the bogus 1.7


def test_model_cannot_spoof_zone_or_ts():
    spoof = '{"armed": false, "confidence": 0.1, "zone": "attacker", "ts": 999}'
    a = _assessor(FakeBackend(spoof)).assess([], [object()], "front", 7.0)
    assert a.zone == "front" and a.ts == 7.0
