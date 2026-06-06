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
import re
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

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


class VLMBackend(Protocol):
    """Minimal VLM transport: prompt + keyframes -> raw model text."""

    def generate(self, prompt: str, images: list[object]) -> str: ...


class Assessor:
    """Local VLM client producing schema-validated assessments."""

    def __init__(self, config: ReasoningConfig, backend: VLMBackend | None = None) -> None:
        self.cfg = config
        self._backend = backend

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
        match = _JSON_OBJ.search(raw or "")
        if match is None:
            return None
        try:
            data = json.loads(match.group(0))
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

    @staticmethod
    def conservative_fallback(zone: str, ts: float) -> ThreatAssessment:
        """Used when the VLM times out/fails: bias toward alerting, never silence (FMEA F6).

        Confidence is deliberately below the default arm threshold so a fallback holds the
        machine at SUSPECT (loud, not silent) without latching a full ALARM on no evidence.
        """
        return ThreatAssessment(
            armed=True,
            weapon_type=None,
            intent="unconfirmed (stage-2 unavailable)",
            confidence=0.5,
            description="Stage-2 unavailable; conservative fallback engaged.",
            zone=zone,
            ts=ts,
        )
