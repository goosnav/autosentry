# ARCHITECTURE — System Architecture

**V-Model level:** L3 (left arm). **Parent:** [REQUIREMENTS.md](REQUIREMENTS.md). **Verified by:** Subsystem
Integration & Test (L3 right arm). **Interfaces:** [INTERFACES.md](INTERFACES.md) (ICD-1..7).

This document is the architectural baseline: components, data flow, the threat state machine, deployment, and
the key design decisions and why they satisfy the requirements.

---

## 1. Context diagram

```
        ┌─────────────────────────────────────────────────────────────────────┐
        │                         AutoSentry SITE                              │
        │                                                                     │
  light │   ┌──────────┐   video    ┌───────────────────────────────────┐     │
  ───────►  │ camera(s)│ ─────────► │              HUB                  │     │  LoRa 915/868 MHz
  scene │   │ UVC/CSI/ │  ICD-1     │          (Jetson Orin NX)         │ ◄──────────────────────┐
        │   │ RTSP     │            │                                   │     │   signed + ACK +    │
        │   └──────────┘            │  capture→detect→reason→state→...  │     │   heartbeat (ICD-3) │
        │                          │     │        │       │     │      │     │                     │
        │   ┌──────────┐  audio    │     ▼        ▼       ▼     ▼      │     │   ┌───────────────┐ │
        │   │ mic +    │ ◄────────► │  siren/strobe  voice  LoRa-gw  notify│   │ │ ALARM NODE ×N │ │
        │   │ speaker  │  ICD-4/7   │   (ICD-4)    (voice) (ICD-2)  (ICD-6)│   │ │ ESP32+LoRa+   │ │
        │   └──────────┘            └───────────────────────────────────┘     │ │ siren+strobe  │ │
        │                                          │ owner notify (best-effort)│ │ batt+mains    │ │
        └──────────────────────────────────────────┼──────────────────────────┘ └───────────────┘ │
                                                    ▼                                               │
                                          owner phone / dashboard  ◄────── (off-site, non-critical) ┘
```

The **critical path** (camera → detect → reason → state → siren/mesh) is entirely on-device. Owner
notification and any cloud/dashboard are explicitly **non-critical** and off the critical path (pillar 1).

## 2. Hub component model (`hub/autosentry/`)

| Module | Responsibility | Key reqs | Interface |
|--------|----------------|----------|-----------|
| `capture/` | Open camera(s), deliver frames with zone + timestamp; auto-reconnect. | FR-1, FR-16, ER-2 | ICD-1 → `Frame` |
| `detection/` | Stage-1 YOLO + ByteTrack: per-frame detections + persistent track IDs. | FR-3, PR-1 | `Frame` → `Detection[]`,`Track[]` |
| `reasoning/` | Stage-2 VLM, invoked only on a trigger; schema-validated assessment. | FR-4, SE-3 | `Track[]`+keyframes → `ThreatAssessment` |
| `state/` | Threat state machine: fuse stage-1 triggers + stage-2 assessments into a stable `ThreatState`. | FR-5, FR-14 | → `ThreatState` |
| `alarm/` | Drive local siren + strobe on ALARM; manage active/cleared. | FR-6 | ICD-4, `AlarmCommand` |
| `comms/` | LoRa gateway over serial: encode/sign/broadcast, collect ACKs, run heartbeats, track node health. | FR-7,8,9,10; SR-1,2 | ICD-2/3, `MeshMessage` |
| `voice/` | STT→LLM→TTS de-escalation, conditioned on vision context; parallel to alarm. | FR-11,12; SE-2 | ICD-7, `VoiceTurn` |
| `notify/` | Owner push; offline queue + flush. | FR-13, SE-5 | ICD-6 |
| `contracts.py` | The typed data models every boundary uses. | IR-4 | **ICD-7** |
| `config.py` | pydantic-settings + `config.yaml`: all thresholds/zones/keys. | FR-5, FR-16 | — |
| `app.py` | Supervisor: wires the pipeline, runs the async loop, owns watchdog + degraded-mode logic. | FR-2; RR-1,4 | — |

### Dataflow contract (ICD-7, summarized)
```
Frame ──► detection ──► (Detection[], Track[]) ──► state ──► trigger? ──► reasoning ──► ThreatAssessment
                                                     │                                        │
                                                     └────────────── state machine ◄──────────┘
                                                                          │
                                                ┌─────────────────────────┼───────────────────────┐
                                                ▼                         ▼                        ▼
                                          AlarmCommand              MeshMessage                VoiceTurn / Notify
                                          (alarm/)                  (comms/)                   (voice/, notify/)
```

## 3. Two-tier vision (why it exists)

False positives are a product-killing bug (pillar 3, PR-4). A single model is either too slow (if heavy) or
too trigger-happy (if light). So:

- **Stage-1 (every frame, cheap):** Ultralytics YOLO (v8/v11) on TensorRT, ~15–30 FPS. Detects persons +
  weapon classes. **ByteTrack** gives each subject a persistent ID so the state machine reasons over
  *behavior across time* (approach speed, loitering, weapon persistence) rather than a single noisy frame.
- **Stage-2 (only on trigger, expensive):** a vision-language model (Qwen2-VL / Llama-3.2-Vision via Ollama
  or llama.cpp) receives a few keyframes + a structured prompt and returns JSON: is the subject armed, with
  what, with what apparent intent, at what confidence, plus a short scene description. This second opinion
  collapses most false positives and produces the natural-language context the voice agent reuses.
- **Trigger conditions (stage-1 → stage-2):** weapon class detected; person in a restricted zone/time;
  loitering beyond threshold; rapid approach toward an entry. All thresholds are config (FR-5).

Detailed model/eval design: [VISION_PIPELINE.md](VISION_PIPELINE.md).

## 4. Threat state machine (FR-5)

```
                 ┌─────────┐  person/track appears          ┌────────┐
                 │ NORMAL  │ ─────────────────────────────► │ WATCH  │
                 └─────────┘                                └────────┘
                     ▲   ▲   no qualifying activity (timeout)     │ stage-1 trigger
                     │   └───────────────────────────────────────┤
          cooldown   │                                            ▼
          elapsed +  │                                       ┌─────────┐ stage-2: not a threat
          owner clr  │                                       │ SUSPECT │ ───────────► (back to WATCH/NORMAL)
                     │                                       └─────────┘
                     │                                            │ stage-2: armed/threat,
                     │                                            │ sustained ≥ confirmation window
                     │             owner clears / threat gone     ▼
                 ┌─────────┐ ◄──────────────────────────────  ┌────────┐
                 │  ALARM  │                                  │ THREAT │
                 └─────────┘ ─── enter: siren+mesh+voice+notify└────────┘
```

- **Hysteresis & confirmation window** prevent flicker: SUSPECT→THREAT requires the assessment to persist.
- **Cooldown** prevents thrashing after an event clears; ALARM is latched until the threat is gone *and* the
  owner acknowledges, or a timeout policy elapses.
- **Manual panic** (FR-14) forces ALARM from any state. **Test mode** runs the chain without latching a real
  incident.
- Per-zone instances allow multi-zone operation (FR-16): each zone runs its own machine; the hub aggregates.

## 5. Alarm & LoRa mesh

- **Local:** `alarm/` drives a siren + strobe via GPIO/relay or USB-audio (ICD-4) on ALARM entry.
- **Mesh:** `comms/` talks to a LoRa radio over USB-serial (ICD-2). The hub is the coordinator; nodes are
  responders. Messages are signed (HMAC-SHA256, truncated) with a monotonic counter (SR-1), addressed (or
  broadcast), and ACK'd. **Bidirectional heartbeats** (FR-9) mean: a node that stops hearing the hub fails
  *safe* to local alert; a node the hub stops hearing is flagged offline/tampered (SR-2, PR-7). Nodes report
  **mains-loss** (FR-10) so power-cuts are observable. Full wire format: [COMMS_PROTOCOL.md](COMMS_PROTOCOL.md).
- **Hub radio:** simplest build is an ESP32+LoRa board running the node firmware in "gateway" mode over USB;
  alternative is a Waveshare SX1262 SPI HAT.

## 6. Voice de-escalation

`voice/` runs faster-whisper (STT) → local LLM (Qwen2.5/Llama-3.2) → Piper (TTS). The LLM's system prompt
fixes a calm, authoritative persona; **each turn is injected with the live `ThreatAssessment`** so replies
respond to what the camera sees ("Sir, put down the weapon and step back from the door"). Barge-in is
supported. It runs **in parallel** with the alarm and never gates it (FR-12, SE-1/2). Design + guardrails:
[VOICE_AGENT.md](VOICE_AGENT.md).

## 7. Reliability & degraded operation

`app.py` supervises every long-running task with timeouts and restarts (RR-1). On a subsystem failure the
system enters **DEGRADED**: e.g. camera-loss → reconnect + owner alert; VLM-timeout → fall back to the
stage-1 decision and a conservative bias; mesh-loss → local siren still fires + alert. It never fails silent.
Power and watchdog design: [POWER_AND_RELIABILITY.md](POWER_AND_RELIABILITY.md). Failure handling per
component: [FMEA.md](FMEA.md).

## 8. Deployment

- **Hub:** JetPack/Ubuntu; the `autosentry` service runs under systemd with a hardware + software watchdog
  (`deploy/`). Models are pulled by `scripts/download_models.py` (not committed). Config in `config.yaml` +
  secrets outside the repo.
- **Nodes:** ESP32 firmware flashed via PlatformIO; provisioned with the shared HMAC key (SR-3).
- **Power:** hub on 12 V LiFePO4 + DC-DC/UPS; nodes on LiFePO4/18650 + charger + USB-mains power-path.

## 9. Key decisions (see [DECISIONS.md](DECISIONS.md) for the trade studies)

- Jetson Orin over Mac Mini / x86 — edge-AI throughput per watt, GPIO, batteryability.
- LoRa over ESP-NOW / Wi-Fi — range + wall penetration + router-independence + jam resistance.
- Two-tier vision over single-model — the false-positive/latency trade.
- Local-first over cloud — survivability + privacy (pillars 1 & 4).
