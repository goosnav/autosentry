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

## ADR-7 — Local operator dashboard: local web UI (loopback-bound)
*Status: Accepted · 2026-06-07*

**Context:** M6 needs an operator surface to show per-zone threat state, recent events, node/health status,
and the FR-14 controls (arm/disarm, panic, test mode) plus the SE-5 authority-contact confirmation
(REQUIREMENTS §FR-17). The dashboard is non-critical (pillar 1) and must not sit on the detection→alarm
path.

**Options:** (a) local web UI served by the hub, (b) minimal text status (logs only) plus a CLI,
(c) require an external always-on host to run the UI.

**Decision:** **Local web UI** served by the hub, opt-in (`dashboard.enabled=false` by default), bound
to loopback (`127.0.0.1`) so it's not reachable from the LAN without explicit operator opt-in. Implemented
in `hub/autosentry/dashboard/server.py` (HTTP) + `hub/autosentry/dashboard/service.py` (Hub projection);
exposed as a single-page UI + JSON API, with POST controls (arm-all/disarm-all/panic/test-mode/confirm-
authority) that route to the Hub. A failure to start the dashboard degrades to `degraded["dashboard"]`
and the pipeline runs headless — never gates the critical path (FR-17, SR-4).

**Consequences:** security review (SR-4) recorded the dashboard as the only inbound network listener; it
is off-path and loopback-bound. Pinned by `test_security` and the SR-4 inspection in
[SECURITY.md §6.2](SECURITY.md). Reconsider if/when richer multi-user/fleet features are added (post-v1).

## ADR-8 — Notification transport: provider-agnostic HTTPS sender
*Status: Accepted · 2026-06-07*

**Context:** FR-13 requires owner notifications on a confirmed threat, queued offline and flushed on
reconnect (ConOps OS-5). v1 is a single-owner product; no multi-tenant / fleet needs yet.

**Options:** (a) hard-bind to a single commercial push provider, (b) provider-agnostic outbound HTTPS
sender with the owner configuring the endpoint, (c) self-hosted webhook only, (d) no notifications (in-app
only).

**Decision:** **Provider-agnostic HTTPS sender** (`hub/autosentry/notify/sender.py`) — the owner configures
their endpoint (commercial provider or self-hosted). Payload is event **metadata only** (event id, zone,
timestamp, threat level, assessment summary, keyframe path) per ICD-6; **no image bytes, no biometric data,
no telemetry** (SE-4). The notifier wraps a durable SQLite outbox that delivers online, queues offline,
flushes oldest-first on reconnect, and stops on failure without dropping (verified by `test_notify`).

**Consequences:** owner install docs need a one-page "configure your push endpoint" guide (planned under
HARDWARE/install). No third-party SDK dependency; no telemetry. If/when professional monitoring-center
integration is added post-v1, revisit the schema to carry the centre's required fields — and re-pass the
five pillars (ADR-4).

## ADR-9 — Weapon-detection dataset/model sourcing & fine-tuning approach
*Status: Open · to record when the labeled benchmark lands*

**Context:** PR-4 (FP rate), PR-5 (weapon FN ≤5%), and SE-3 (bias slices) are gated by the **same**
labeled benchmark. The dataset determines the ceiling of every one of these requirements.

**Open question:** sourcing strategy (open datasets only vs open + collected/augmented site data), fine-
tuning vs out-of-the-box YOLO, hard-negative mining protocol, and stratification. See the Benchmark Dataset
SOW in [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) (added in the v1 verification
rework). **Close this ADR when the SOW is implemented and the dataset is committed under `bench/`.**

## ADR-10 — Multi-hub coordination for larger sites
*Status: Post-v1 · recorded 2026-06-07*

**Context:** R10 (hub SPOF) and the post-v1 roadmap ([ROADMAP.md](ROADMAP.md) "Post-v1") call out multi-hub
for properties too large or too partitioned for a single hub. This is a meaningful design exercise (mesh
topology changes from star to a graph; heartbeat/fail-safe semantics shift; dashboard becomes multi-hub).

**Decision:** Defer to post-v1. v1's star topology + per-node fail-safe is sufficient for a single-hub
property ([ROADMAP.md](ROADMAP.md) v1 acceptance). Reopen the ADR if/when a real site requires it; the
five pillars must still pass (ADR-4, ADR-5).

---

## Open decisions (to record when made)
- ADR-9 — Weapon-detection dataset/model sourcing & fine-tuning approach. Gates PR-4, PR-5, SE-3. See the
  Benchmark Dataset SOW in [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md).
