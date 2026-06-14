"""Stage-2 reasoner: VLM threat assessment (FR-4).

Invoked only on a stage-1 trigger. Sends keyframes + a structured prompt to a local
VLM (Ollama / llama.cpp) and returns a schema-validated ThreatAssessment. A malformed
or hallucinated response is rejected by the pydantic schema; on timeout we fall back to
a conservative stage-1 decision (FMEA F6/F7, docs/VISION_PIPELINE.md §4).

The VLM transport is a swappable `VLMBackend` so the parse/validate/retry/fallback logic
is unit-testable without a running model. The default Ollama backend is lazy-imported.

STATUS: M2 — assess() implemented (parse + validate + retry + timeout fallback).
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from autosentry.config import ReasoningConfig
from autosentry.contracts import ThreatAssessment, Track

PROMPT = (
    "You are a security threat assessor. Given the image(s), respond with ONLY a JSON "
    "object: {\"armed\": bool, \"weapon_type\": string|null, \"intent\": string, "
    "\"confidence\": number in [0,1], \"description\": string}. Base the assessment on "
    "visible objects and behavior, never on appearance, race, gender, or clothing."
)

def _extract_json_object(text: str) -> str | None:
    """Return the first balanced top-level {...} object in `text`, or None.

    Robust to a model that wraps JSON in prose or markdown fences and to nested objects:
    a greedy regex over-captures trailing prose, a non-greedy one breaks on nesting, so we
    scan brace depth and skip braces inside double-quoted strings (with escape handling).
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class VLMBackend(Protocol):
    """Minimal VLM transport: prompt + keyframes -> raw model text."""

    def generate(self, prompt: str, images: list[object]) -> str: ...


class Assessor:
    """Local VLM client producing schema-validated assessments."""

    def __init__(
        self,
        config: ReasoningConfig,
        backend: VLMBackend | None = None,
        arm_confidence: float | None = None,
    ) -> None:
        self.cfg = config
        self._backend = backend
        # The state machine's arm threshold, so the timeout fallback can stay strictly below
        # it (see conservative_fallback). None → assume the StateConfig default.
        self._arm_confidence = arm_confidence

    def _ensure_backend(self) -> VLMBackend:
        if self._backend is None:
            from autosentry.reasoning.ollama_backend import OllamaBackend

            self._backend = OllamaBackend(self.cfg)
        return self._backend

    def assess(
        self, tracks: list[Track], keyframes: list[object], zone: str, ts: float
    ) -> ThreatAssessment:
        """Return a validated ThreatAssessment, never raising into the pipeline.

        Calls the VLM, parses its JSON into ThreatAssessment (pydantic validates
        bounds/enums), retries once on malformed output, and on any transport failure
        or timeout returns the conservative fallback (FMEA F6/F7). Biasing toward a
        non-silent result is deliberate: a broken stage-2 must never quietly clear a
        threat (pillar 1, pillar 3).
        """
        backend = self._ensure_backend()
        for attempt in range(2):
            try:
                raw = backend.generate(PROMPT, keyframes)
            except Exception:
                return self.conservative_fallback(zone, ts)
            parsed = self._parse(raw, zone, ts)
            if parsed is not None:
                return parsed
            if attempt == 0:
                continue
        return self.conservative_fallback(zone, ts)

    @staticmethod
    def _parse(raw: str, zone: str, ts: float) -> ThreatAssessment | None:
        """Extract and schema-validate a ThreatAssessment from raw model text.

        Returns None on any malformed/out-of-bounds output so the caller can retry or
        fall back; zone/ts are hub-provenance, never taken from the model.
        """
        blob = _extract_json_object(raw or "")
        if blob is None:
            return None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        data.pop("zone", None)
        data.pop("ts", None)
        try:
            return ThreatAssessment(zone=zone, ts=ts, **data)
        except (ValidationError, TypeError):
            return None

    def conservative_fallback(self, zone: str, ts: float) -> ThreatAssessment:
        """Used when the VLM times out/fails: bias toward alerting, never silence (FMEA F6).

        Confidence is held **strictly below the configured arm threshold** so a stage-2
        failure escalates only to SUSPECT (loud, not silent) and can never auto-latch a full
        ALARM on no evidence (pillar 3). Deriving it from `state.arm_confidence` instead of a
        hardcoded 0.5 keeps that guarantee even when an operator tunes the threshold down —
        otherwise lowering arm_confidence to ≤0.5 would silently turn every VLM outage into a
        false alarm. The hub passes its StateConfig in; absent it we assume the 0.6 default.
        """
        arm = self._arm_confidence if self._arm_confidence is not None else 0.6
        # A small margin below the threshold, floored at 0, so armed_now stays False.
        confidence = max(0.0, min(0.5, arm - 0.05))
        return ThreatAssessment(
            armed=True,
            weapon_type=None,
            intent="unconfirmed (stage-2 unavailable)",
            confidence=confidence,
            description="Stage-2 unavailable; conservative fallback engaged.",
            zone=zone,
            ts=ts,
        )
