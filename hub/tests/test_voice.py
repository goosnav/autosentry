"""Unit tests for the de-escalation VoiceAgent (FR-11/12, SE-2; voice/agent.py).

Pins the dialogue contract with fake STT/LLM/TTS backends (no models, no audio):
- vision context is injected into every prompt, so identical subject speech under
  different ThreatAssessments yields materially different replies (FR-11);
- the SE-2 guardrail blocks illegal-threat / false-weapon-claim generations and
  substitutes a safe, true fallback, logging the blocked text (SE-2, FMEA F16);
- a failing/hung backend degrades to the safe line and never raises into the caller, so
  the parallel alarm chain is never gated (FR-12, FMEA F15);
- every turn (subject + agent) is recorded with role, text, vision context, ts (FR-15).
"""

from __future__ import annotations

from autosentry.config import VoiceConfig
from autosentry.contracts import ThreatAssessment
from autosentry.voice.agent import SAFE_FALLBACK, VoiceAgent


class FakeLLM:
    """Returns a canned reply and records the last user prompt it was given."""

    def __init__(self, reply: str = "Please step back from the door.", raises: bool = False):
        self._reply = reply
        self._raises = raises
        self.last_user: str | None = None
        self.calls = 0

    def generate(self, system: str, user: str, max_tokens: int) -> str:
        self.calls += 1
        self.last_user = user
        if self._raises:
            raise RuntimeError("llm timeout")
        return self._reply


class FakeSTT:
    def __init__(self, text: str = "", raises: bool = False):
        self._text = text
        self._raises = raises

    def transcribe(self, audio: object) -> str:
        if self._raises:
            raise RuntimeError("stt down")
        return self._text


class FakeTTS:
    def __init__(self, raises: bool = False):
        self.spoken: list[str] = []
        self._raises = raises

    def speak(self, text: str) -> None:
        if self._raises:
            raise RuntimeError("tts down")
        self.spoken.append(text)


def _ctx(armed=True, weapon="rifle", intent="advancing toward the door", conf=0.86, zone="front"):
    return ThreatAssessment(
        armed=armed, weapon_type=weapon, intent=intent, confidence=conf,
        description="", zone=zone, ts=7.0,
    )


def _agent(stt=None, llm=None, tts=None):
    return VoiceAgent(
        VoiceConfig(), stt=stt or FakeSTT(), llm=llm or FakeLLM(), tts=tts or FakeTTS()
    )


# --- vision context injection (FR-11) -------------------------------------------------
def test_prompt_carries_vision_context():
    llm = FakeLLM()
    _agent(llm=llm).greet(_ctx(weapon="rifle", intent="advancing toward the door"))
    assert "rifle" in llm.last_user
    assert "advancing toward the door" in llm.last_user
    assert "armed: True" in llm.last_user


def test_same_speech_different_context_changes_prompt():
    # Identical subject utterance, two different assessments -> materially different prompts
    # (and therefore different replies from a real model). FR-11.
    llm = FakeLLM()
    agent = VoiceAgent(VoiceConfig(), stt=FakeSTT("who are you"), llm=llm, tts=FakeTTS())
    agent.respond(object(), _ctx(armed=True, weapon="rifle"))
    armed_prompt = llm.last_user
    agent.respond(object(), _ctx(armed=False, weapon=None, intent="standing at the gate"))
    benign_prompt = llm.last_user
    assert armed_prompt != benign_prompt
    assert "rifle" in armed_prompt and "rifle" not in benign_prompt


# --- guardrails (SE-2) ----------------------------------------------------------------
def test_guardrail_blocks_threat_of_force():
    llm = FakeLLM(reply="Leave now or I will shoot you.")
    agent = _agent(llm=llm)
    turn = agent.greet(_ctx())
    assert turn.text == SAFE_FALLBACK
    assert agent.blocked == ["Leave now or I will shoot you."]  # raw logged for audit


def test_guardrail_blocks_false_weapon_claim():
    agent = _agent(llm=FakeLLM(reply="I have a gun and I'm not afraid to use it."))
    assert agent.greet(_ctx()).text == SAFE_FALLBACK
    assert len(agent.blocked) == 1


def test_safe_reply_passes_through():
    agent = _agent(llm=FakeLLM(reply="You are being recorded. Please leave the property."))
    turn = agent.greet(_ctx())
    assert turn.text == "You are being recorded. Please leave the property."
    assert agent.blocked == []


# --- degradation never gates the alarm chain (FR-12, FMEA F15) ------------------------
def test_llm_failure_degrades_to_safe_line_without_raising():
    agent = _agent(llm=FakeLLM(raises=True))
    turn = agent.greet(_ctx())  # must not raise
    assert turn.text == SAFE_FALLBACK


def test_tts_failure_does_not_raise():
    tts = FakeTTS(raises=True)
    agent = _agent(tts=tts)
    turn = agent.greet(_ctx())  # must not raise
    assert turn.role == "agent"
    assert tts.spoken == []


def test_stt_failure_treated_as_silence():
    llm = FakeLLM()
    agent = _agent(stt=FakeSTT(raises=True), llm=llm)
    agent.respond(object(), _ctx())  # must not raise
    assert "has not spoken yet" in llm.last_user


# --- logging / transcript (FR-15) -----------------------------------------------------
def test_turns_recorded_with_role_and_context():
    tts = FakeTTS()
    agent = VoiceAgent(VoiceConfig(), stt=FakeSTT("don't shoot"), llm=FakeLLM(), tts=tts)
    ctx = _ctx()
    agent.respond(object(), ctx)
    roles = [t.role for t in agent.turns]
    assert roles == ["subject", "agent"]
    assert agent.turns[0].text == "don't shoot"
    assert all(t.vision_context is ctx and t.ts == ctx.ts for t in agent.turns)
    assert tts.spoken == [agent.turns[1].text]
