"""Voice de-escalation agent: STT -> LLM -> TTS, grounded in live vision (FR-11/12).

Speaks to a subject with a calm, authoritative persona, conditioning each reply on the
current ThreatAssessment so it reacts to what the camera sees rather than canned lines.
Two hard constraints govern this module:
- It runs **in parallel** with the alarm + notification and never gates or replaces them
  (FR-12, SE-1). A hung LLM/TTS must never delay or silence the siren (FMEA F15).
- It may only state **true** facts to deter; no fabricated capabilities, no illegal
  threats (SE-2, docs/VOICE_AGENT.md §5).

Heavy deps (faster-whisper, the LLM client, Piper) are lazy-imported in M5.

STATUS: M5 stub — interface + guardrail contract defined.
"""

from __future__ import annotations

from autosentry.config import VoiceConfig
from autosentry.contracts import ThreatAssessment, VoiceTurn

PERSONA = (
    "You are the voice of a home security system speaking to someone on the property. "
    "Be calm, firm, and brief. Your goal is to de-escalate and have the person leave. "
    "State only true facts (recording is active; the owner has been alerted). Never "
    "threaten, never claim weapons or force you do not have, never insult. Keep replies "
    "under two sentences."
)


class VoiceAgent:
    """Local STT->LLM->TTS loop with vision context injected each turn."""

    def __init__(self, config: VoiceConfig) -> None:
        self.cfg = config
        self._stt = None  # faster-whisper (lazy, M5)
        self._tts = None  # Piper (lazy, M5)

    def greet(self, context: ThreatAssessment) -> VoiceTurn:
        """Open the dialogue with a context-grounded line (no subject input yet)."""
        raise NotImplementedError("VoiceAgent.greet lands in M5 (see docs/ROADMAP.md)")

    def respond(self, audio: object, context: ThreatAssessment) -> VoiceTurn:
        """Transcribe subject audio, generate a guarded reply grounded in `context`, speak it.

        M5: STT(audio) -> LLM(PERSONA + context + transcript, capped at max_reply_tokens)
        -> guardrail filter -> TTS. Enforces turn_timeout_s; on timeout the turn is dropped,
        never blocking the critical path (FMEA F15).
        """
        raise NotImplementedError("VoiceAgent.respond lands in M5 (see docs/ROADMAP.md)")
