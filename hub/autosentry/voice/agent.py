"""Voice de-escalation agent: STT -> LLM -> TTS, grounded in live vision (FR-11/12).

Speaks to a subject with a calm, authoritative persona, conditioning each reply on the
current ThreatAssessment so it reacts to what the camera sees rather than canned lines.
Two hard constraints govern this module:
- It runs **in parallel** with the alarm + notification and never gates or replaces them
  (FR-12, SE-1). A hung LLM/TTS must never delay or silence the siren (FMEA F15) — every
  backend call is wrapped so a failure degrades to a safe spoken line, never an exception
  into the caller.
- It may only state **true** facts to deter; no fabricated capabilities, no illegal
  threats (SE-2, docs/VOICE_AGENT.md §5). A guardrail filter runs on every generation
  before TTS; a blocked utterance is replaced by SAFE_FALLBACK and logged.

The three transports (STT, LLM, TTS) are swappable Protocols so the dialogue logic is
unit-testable without a model; the default faster-whisper / Ollama / Piper backends are
lazy-imported.

STATUS: M5 — greet()/respond() implemented (context injection + guardrails + logging).
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from autosentry.config import VoiceConfig
from autosentry.contracts import ThreatAssessment, VoiceTurn

log = logging.getLogger("autosentry.voice")

PERSONA = (
    "You are the voice of a home security system speaking to someone on the property. "
    "Be calm, firm, and brief. Your goal is to de-escalate and have the person leave. "
    "State only true facts (recording is active; the owner has been alerted). Never "
    "threaten, never claim weapons or force you do not have, never insult. Keep replies "
    "under two sentences."
)

# Spoken when the LLM fails/times out or its output is blocked by the guardrail. True,
# non-provoking, and within the system's lawful capabilities (SE-2, docs/VOICE_AGENT.md §5).
SAFE_FALLBACK = (
    "You are on private property and are being recorded. Please leave the area now."
)

# SE-2 output filter: illegal threats of force and false weapon/capability claims. A match
# means the generation is unsafe and is dropped in favor of SAFE_FALLBACK. Conservative by
# design — over-blocking degrades to a safe true line, never to a harmful one.
_BANNED = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi(?:'?ll| will| am going to|'?m going to)\b[^.?!]*\b"
        r"(?:shoot|kill|hurt|harm|beat|attack|stab|destroy)\b",
        r"\b(?:shoot|kill|hurt|harm|stab|beat)\s+you\b",
        r"\bi(?:'?ve| have| am holding|'?m holding| own| carry)\b[^.?!]*\b"
        r"(?:gun|rifle|weapon|knife|firearm|pistol|taser)\b",
        r"\bi(?:'?m| am)\s+armed\b",
    )
]


class STTBackend(Protocol):
    """Speech-to-text: subject audio -> transcript text."""

    def transcribe(self, audio: object) -> str: ...


class LLMBackend(Protocol):
    """Local LLM: (system persona, user prompt) -> reply text."""

    def generate(self, system: str, user: str, max_tokens: int) -> str: ...


class TTSBackend(Protocol):
    """Text-to-speech: render the reply to the speaker."""

    def speak(self, text: str) -> None: ...


class VoiceAgent:
    """Local STT->LLM->TTS loop with vision context injected each turn."""

    def __init__(
        self,
        config: VoiceConfig,
        stt: STTBackend | None = None,
        llm: LLMBackend | None = None,
        tts: TTSBackend | None = None,
    ) -> None:
        self.cfg = config
        self._stt = stt
        self._llm = llm
        self._tts = tts
        # Full dialogue transcript with per-turn vision context (FR-15). Both the subject's
        # speech and the agent's replies are recorded for audit.
        self.turns: list[VoiceTurn] = []
        # Raw LLM generations the guardrail rejected, kept for audit (SE-2, FMEA F16).
        self.blocked: list[str] = []

    # --- public dialogue API ----------------------------------------------------------
    def greet(self, context: ThreatAssessment) -> VoiceTurn:
        """Open the dialogue with a context-grounded line (no subject input yet)."""
        reply = self._generate(context, subject_text="")
        return self._speak_turn(reply, context)

    def respond(self, audio: object, context: ThreatAssessment) -> VoiceTurn:
        """Transcribe subject audio, generate a guarded reply grounded in `context`, speak it.

        STT(audio) -> LLM(PERSONA + context + transcript, capped at max_reply_tokens) ->
        guardrail filter -> TTS. Any backend failure (incl. timeout) degrades to a safe
        spoken line; this method never raises into the caller, so the alarm chain that
        runs alongside it is never blocked (FR-12, FMEA F15).
        """
        transcript = self._transcribe(audio)
        if transcript:
            self._record(VoiceTurn("subject", transcript, context, context.ts))
        reply = self._generate(context, subject_text=transcript)
        return self._speak_turn(reply, context)

    # --- internals --------------------------------------------------------------------
    def _transcribe(self, audio: object) -> str:
        try:
            return self._ensure_stt().transcribe(audio).strip()
        except Exception as e:
            log.warning("STT failed, treating turn as silence: %s", e)
            return ""

    def _generate(self, context: ThreatAssessment, subject_text: str) -> str:
        """Build the context-grounded prompt, call the LLM, and guardrail the result."""
        prompt = self._build_prompt(context, subject_text)
        try:
            raw = self._ensure_llm().generate(PERSONA, prompt, self.cfg.max_reply_tokens)
        except Exception as e:
            log.warning("LLM failed, using safe fallback: %s", e)
            return SAFE_FALLBACK
        return self._guard(raw)

    @staticmethod
    def _build_prompt(context: ThreatAssessment, subject_text: str) -> str:
        """Inject the live ThreatAssessment so the reply is grounded in what the camera sees.

        This is the intelligence of the agent (FR-11): identical subject speech under
        different vision contexts yields materially different prompts, hence replies.
        """
        weapon = context.weapon_type or "none observed"
        ctx = (
            f"Live camera assessment — armed: {context.armed}; weapon: {weapon}; "
            f"intent: {context.intent or 'unknown'}; confidence: {context.confidence:.2f}; "
            f"zone: {context.zone}."
        )
        if context.description:
            ctx += f" Scene: {context.description}"
        said = (
            f'The person said: "{subject_text}"'
            if subject_text
            else "The person has not spoken yet."
        )
        return f"{ctx}\n{said}\nRespond now."

    def _guard(self, text: str) -> str:
        """SE-2 content filter: block illegal threats / false capability claims (§5).

        Empty or unsafe generations are replaced by SAFE_FALLBACK; the raw blocked text is
        logged and retained for audit so a misbehaving model is observable, never silent.
        """
        candidate = (text or "").strip()
        if not candidate:
            return SAFE_FALLBACK
        if any(pat.search(candidate) for pat in _BANNED):
            self.blocked.append(candidate)
            log.warning("guardrail blocked an unsafe generation; using safe fallback")
            return SAFE_FALLBACK
        return candidate

    def _speak_turn(self, text: str, context: ThreatAssessment) -> VoiceTurn:
        """Render the reply (TTS failure is non-critical) and record the agent turn."""
        try:
            self._ensure_tts().speak(text)
        except Exception as e:
            log.warning("TTS failed, reply not voiced: %s", e)
        turn = VoiceTurn("agent", text, context, context.ts)
        self._record(turn)
        return turn

    def _record(self, turn: VoiceTurn) -> None:
        self.turns.append(turn)

    # --- lazy default backends --------------------------------------------------------
    def _ensure_stt(self) -> STTBackend:
        if self._stt is None:
            from autosentry.voice.backends import WhisperSTT

            self._stt = WhisperSTT(self.cfg)
        return self._stt

    def _ensure_llm(self) -> LLMBackend:
        if self._llm is None:
            from autosentry.voice.backends import OllamaLLM

            self._llm = OllamaLLM(self.cfg)
        return self._llm

    def _ensure_tts(self) -> TTSBackend:
        if self._tts is None:
            from autosentry.voice.backends import PiperTTS

            self._tts = PiperTTS(self.cfg)
        return self._tts
