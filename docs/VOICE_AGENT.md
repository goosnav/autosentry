# VOICE_AGENT — De-escalation Agent Detailed Design

**V-Model level:** L4. **Parent:** [ARCHITECTURE.md](ARCHITECTURE.md) §6. **Requirements:** FR-11, FR-12,
PR-8, SE-1, SE-2. **Module:** `hub/autosentry/voice/`.

The voice agent's job is **de-escalation and deterrence through intelligent, vision-aware speech** — not
canned lines. It must never gate or replace the alarm chain (FR-12), and it operates under hard guardrails
(SE-2). Ends with the component test definition.

---

## 1. Loop
```
mic ─► STT (faster-whisper) ─► dialogue manager ─► LLM (local) ─► TTS (Piper) ─► speaker
                                      ▲
                         live ThreatAssessment (vision context, per turn)
```
Runs as an **independent async task** alongside alarm/mesh/notify. If it stalls or is disabled, the alarm
chain is unaffected (FMEA F15).

## 2. Components
- **STT:** faster-whisper (CTranslate2), small/base model; VAD-gated; partials for barge-in.
- **LLM:** small local model (Qwen2.5-3B/7B or Llama-3.2) via Ollama/llama.cpp, quantized to fit alongside
  vision on the Orin (ADR-6, R4). Hard per-turn timeout (FMEA F15).
- **TTS:** Piper (fast, local) for v1; XTTS-v2 as a realism upgrade once PR-8 headroom allows.
- **Dialogue manager:** owns turn-taking, barge-in, context injection, guardrail enforcement, and logging.
- **Provisioning (FR-18):** all three models run on-device and are fetched on first boot if missing —
  faster-whisper into `models/whisper/`, the LLM pulled into the local Ollama server, and the Piper voice
  `.onnx`(+`.json`) into `models/piper/`. Handled by `autosentry/models.py` / `scripts/download_models.py`;
  the backends load the provisioned files (`WhisperModel(download_root=…)`, `piper --model models/piper/…`).

## 3. Intelligence = vision context injection (FR-11)
Every turn, the manager injects the **current `ThreatAssessment`** (from stage-2, reused) into the LLM
prompt — observed weapon, intent, distance/approach, zone. So replies are grounded in what the camera sees:

> *(context: armed=true, weapon=rifle, intent="advancing toward front door", confidence=0.86)*
> → "You're being recorded. Put the rifle down and step back from the door. The police have been alerted."

The agent also consumes the subject's transcribed speech (STT) so it's a real dialogue, not a monologue.

## 4. Persona & policy (system prompt)
- **Persona:** calm, firm, authoritative, non-provoking. Goal order: (1) de-escalate, (2) get the subject to
  leave, (3) buy time and information for the owner.
- **Truthful deterrence:** it may state that the subject is recorded and that the owner/authorities are
  alerted **when true** (those actions do fire in parallel). It must not fabricate claims that undermine
  trust or legality.
- **Multilingual:** detect language from STT and respond in kind when supported.

## 5. Guardrails (SE-2) — hard constraints
The agent shall **never**:
- make illegal threats or threats of physical harm ("I will shoot you"), or claim weapons/capabilities the
  system does not lawfully have;
- use slurs, demographic profiling, or harassing content;
- negotiate away the alarm or instruct the owner/others to take unlawful action;
- impersonate a specific real person or a government official.

Enforcement: a constrained system prompt **plus** an output content-filter pass before TTS; any blocked
generation is replaced with a safe fallback line and **logged** (SE-2, FMEA F16). Every utterance (subject +
agent) is logged with its vision context (FR-15).

## 6. Relationship to the alarm chain (FR-12, SE-1)
- Voice is **additive**, never a precondition. ALARM fires the siren, mesh, and notification **regardless** of
  the dialogue state.
- The agent has **no** control over any physical mechanism beyond the speaker (SE-1) — it cannot unlock,
  trigger, or actuate anything against a person.
- Owner policy may disable voice entirely (some owners won't want it); the rest of the system is unchanged.

## 7. Latency (PR-8)
Target subject-stops-speaking → reply-audio ≤2 s: VAD endpointing, streaming STT partials, short LLM
max-tokens with streaming into Piper, and pre-warmed models. Measure per TPM-10.

## 8. Component test definition (L4 right arm)
- **Context-conditioning (FR-11):** same subject utterance, two different `ThreatAssessment` fixtures ⇒
  materially different prompts (hence replies). `test_voice.py` ☑ (prompt carries weapon/intent/armed; same
  speech under armed vs benign context yields different prompts). On-target reply-quality demo pending models.
- **Guardrails (SE-2):** adversarial generations eliciting threats/false weapon claims ⇒ blocked + safe
  fallback + raw retained in `agent.blocked` and logged. `test_voice.py` ☑. Broader red-team set pending.
- **Non-gating (FR-12):** with voice killed/hung, ALARM still asserts siren. `test_pipeline.py` ☑
  (`test_hung_voice_never_blocks_or_silences_the_siren`) — `Hub._actuate` engages voice only **after** the
  siren latches and wraps it, degrading to `degraded["voice"]` on failure. On-target concurrency demo pending.
- **Latency (PR-8):** measured endpoint→first-audio ≤2 s on-target. ☐ deferred to on-Jetson bench.
- **Logging (FR-15):** every turn recorded with role, text, vision context, timestamp — `VoiceAgent.turns`.
  `test_voice.py` ☑ (`test_turns_recorded_with_role_and_context`).
