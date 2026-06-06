# DECISIONS — Trade Studies & Architecture Decision Records

**Crosscutting SE process (Decision Analysis).** Each record states the decision, the options weighed, the
criteria, and the rationale. Append-only: supersede rather than delete, so the reasoning history survives.

Format: **ADR-n — Title** · *Status* · *Date* · Context → Options → Decision → Consequences.

---

## ADR-1 — Compute platform: NVIDIA Jetson Orin
*Status: Accepted · 2026-06-06*

**Context:** The hub must run real-time vision (+ optionally LLM/voice) at the edge, on battery, with GPIO for
radio/alarm, fully offline (pillars 1, 4; PR-1, RR-3).

**Options:** (a) Jetson Orin NX/Nano, (b) Mac Mini (Apple Silicon), (c) x86 mini-PC + discrete GPU,
(d) abstract over all three.

**Criteria:** edge-AI throughput/watt, batteryability, GPIO/peripheral access, power draw, dev ergonomics,
cost.

**Decision:** **Jetson Orin NX 16GB** as the production hub (Orin Nano Super 8GB budget; AGX Orin if running
all models concurrently at max quality). TensorRT throughput per watt, GPIO, and easy battery backup win for
an edge security node. Mac Mini noted as an excellent *dev* box and possible central "brain" for heavier LLM
work post-v1; software stays portable (Python) so that remains open.

**Consequences:** vision uses TensorRT; models must be sized to the Orin's memory/thermal envelope (risk R4).
Voice + VLM concurrency on one Orin NX is tight — model selection in [VOICE_AGENT.md](VOICE_AGENT.md) /
[VISION_PIPELINE.md](VISION_PIPELINE.md) accounts for it; a 2-box split is the fallback.

## ADR-2 — Alarm-mesh radio: LoRa (SX1262/RFM95)
*Status: Accepted · 2026-06-06*

**Context:** Nodes must be triggered reliably across a property **without depending on the router or mains**,
and survive an intruder cutting infrastructure (STK-2/4, SR-2).

**Options:** (a) LoRa sub-GHz, (b) ESP-NOW (2.4 GHz, ESP32-native), (c) Wi-Fi/MQTT, (d) Zigbee/Thread,
(e) plain 433 MHz OOK.

**Criteria:** range, wall penetration, infrastructure-independence, jam resistance, power, build simplicity,
security.

**Decision:** **LoRa** backbone. Sub-GHz range + penetration cover a property; spread-spectrum resists casual
jamming; no router needed. Wi-Fi/MQTT rejected (router/mains dependency — fails pillar 1). ESP-NOW kept as a
documented budget alternative for short-range nodes (shorter range, worse penetration). 433 MHz OOK rejected
(no practical auth, poor robustness).

**Consequences:** custom application protocol with HMAC + monotonic counter + ACK + heartbeat (ICD-3,
[COMMS_PROTOCOL.md](COMMS_PROTOCOL.md)). Low bandwidth is fine — we send tiny control frames, not media.
Region band (915/868 MHz) is a deployment parameter.

## ADR-3 — Two-tier vision (fast detector + triggered VLM)
*Status: Accepted · 2026-06-06*

**Context:** A single model can't be both fast enough every frame and reliable enough to avoid false alarms
(pillar 3; PR-1, PR-4, PR-5).

**Options:** (a) single light detector, (b) single heavy VLM every frame, (c) two-tier: YOLO every frame +
VLM only on trigger.

**Decision:** **Two-tier.** YOLO+ByteTrack at frame rate for cheap continuous detection and temporal
behavior; a VLM second opinion only when stage-1 triggers, to crush false positives and produce the scene
description the voice agent reuses.

**Consequences:** more moving parts and a defined trigger policy (config-driven). VLM failures must fall back
safely (FMEA F6/F7). This is the central reliability mechanism for PR-4/PR-5.

## ADR-4 — Local-first, no cloud in the critical path
*Status: Accepted · 2026-06-06*

**Context:** Must work with power/internet cut; must protect privacy (pillars 1, 4; STK-2, SE-4).

**Decision:** All detection/decision/alarm logic runs on-device. Cloud/notifications are **best-effort and
off the critical path** (ICD-6). No biometric identity database in v1.

**Consequences:** owner remote features are limited to notifications + a local dashboard in v1; richer
fleet/cloud features are explicitly post-v1 and must each re-pass the five pillars.

## ADR-5 — Never autonomous physical force
*Status: Accepted (immutable) · 2026-06-06*

**Context:** This is a defensive forewarning system, not a weapon (pillar 2; SE-1; STK-6).

**Decision:** No interface to any mechanism that applies physical force to a person will exist in the
codebase or hardware. Response is limited to alarms, light, voice, and notification.

**Consequences:** verified by inspection (SE-1) at every milestone; PRs adding such capability are rejected on
principle. This decision is **not** subject to revision.

## ADR-6 — Voice stack: faster-whisper + local LLM + Piper
*Status: Accepted (revisitable) · 2026-06-06*

**Context:** Need intelligent, vision-aware, low-latency speech, fully local (FR-11, PR-8).

**Options (TTS):** Piper (fast, light, slightly robotic) vs XTTS-v2/Coqui (more natural, heavier).
**Options (LLM):** Qwen2.5-3B/7B vs Llama-3.2 (sizes vs Orin budget).

**Decision:** **faster-whisper** (STT) + a small local **LLM** (Qwen2.5/Llama-3.2, quantized) + **Piper**
(TTS) for v1; XTTS-v2 flagged as a realism upgrade once latency/headroom allow. "Intelligence" comes from
injecting live vision context into the LLM prompt, not from canned lines.

**Consequences:** revisit TTS quality after measuring PR-8 and Orin headroom alongside vision.

---

## Open decisions (to record when made)
- ADR-7 — Local web dashboard vs minimal status UI (M6).
- ADR-8 — Notification transport (self-hosted vs provider) (M6).
- ADR-9 — Weapon-detection dataset/model sourcing & fine-tuning approach (M1/M2; see VISION_PIPELINE.md).
- ADR-10 — Multi-hub coordination for larger sites (post-v1).
