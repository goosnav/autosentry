# REQUIREMENTS — System Requirements Document (SRD)

**V-Model level:** L2. **Parent:** [CONOPS.md](CONOPS.md) (STK-1..7). **Verified by:** System Verification
(L2 right arm) per [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md).

Every requirement is **numbered, atomic, and verifiable**. Verification method: **I**=Inspection,
**A**=Analysis, **D**=Demonstration, **T**=Test. "M#" is the target milestone. Each row links to its parent
stakeholder need and the design element that satisfies it. A requirement is *not done* until its V&V row
passes (see the RTM).

> Convention: keep requirements **solution-neutral** where possible (state the *what*, not the *how*). Design
> choices live in [ARCHITECTURE.md](ARCHITECTURE.md) and the subsystem docs.

---

## Functional (FR)

| ID | Requirement | Parent | Method | M# | Design |
|----|-------------|--------|--------|----|--------|
| **FR-1** | The hub shall automatically detect and connect to attached camera(s) on boot and on hotplug, without operator configuration of the device path. | STK-1 | D | M1 | capture/, ICD-1 |
| **FR-2** | The hub shall run threat detection continuously whenever powered and shall auto-resume the pipeline after a restart. | STK-1 | D | M1 | app.py, deploy/ |
| **FR-3** | The stage-1 detector shall classify `person` and weapon classes (≥ handgun, rifle, knife) per frame and maintain a track identity per subject across frames. | STK-1, STK-3 | T | M1 | detection/ |
| **FR-4** | On a stage-1 trigger, the stage-2 reasoner shall produce a schema-validated assessment `{armed, weapon_type, intent, confidence, description}`. | STK-1, STK-3 | T | M2 | reasoning/ |
| **FR-5** | The system shall maintain a threat state machine `NORMAL→WATCH→SUSPECT→THREAT→ALARM` with hysteresis, a confirmation window, and a cooldown, with all thresholds configurable. | STK-3 | T | M1 | state/ |
| **FR-6** | On entering ALARM, the hub shall activate a local siren and strobe. | STK-1 | T | M2 | alarm/, ICD-4 |
| **FR-7** | On entering ALARM, the hub shall broadcast a signed trigger over LoRa to all alarm nodes, and nodes shall sound their local siren/strobe. | STK-4 | T | M3 | comms/, firmware, ICD-3 |
| **FR-8** | Alarm nodes shall acknowledge (ACK) received commands; the hub shall track per-node health and surface/log offline nodes. | STK-4 | T | M3 | comms/, firmware |
| **FR-9** | The hub and nodes shall exchange periodic heartbeats; loss of heartbeat beyond the configured window shall raise a fail-safe alert (an isolated node shall escalate to local alert, not go silent). | STK-2, STK-4 | T | M3/M4 | comms/, firmware |
| **FR-10** | Alarm nodes shall detect and report mains-loss / on-battery state to the hub. | STK-2 | T | M4 | firmware, ICD-5 |
| **FR-11** | The voice agent shall run a STT→LLM→TTS dialogue loop whose replies are conditioned on the current vision context (e.g. observed weapon, distance, motion). | STK-5 | D | M5 | voice/ |
| **FR-12** | Voice de-escalation shall run in parallel with the alarm and notification chain and shall never suppress or replace them. | STK-5, STK-1 | D | M5 | app.py, voice/ |
| **FR-13** | The hub shall notify the owner on a confirmed threat; notifications shall queue when offline and flush on reconnect. | STK-1 | D | M6 | notify/, ICD-6 |
| **FR-14** | The system shall support a manual panic trigger (forces ALARM from any mode), a test/maintenance mode, and per-zone arm/disarm. | STK-1 | D | M4/M6 | state/, app.py |
| **FR-15** | The system shall log every alarm-relevant event with timestamp, keyframe(s), the stage-2 assessment, and the actions taken. | STK-6 | I | M2 | logging, notify/ |
| **FR-16** | The system shall support multiple cameras/zones with correct per-zone attribution of detections and alarms. | STK-1 | D | M6 | capture/, state/ |
| **FR-17** | The hub shall provide a local operator dashboard that displays per-zone threat state, recent events, and node/health status, and that exposes the FR-14 controls (arm/disarm, panic, test mode) and the SE-5 authority-contact confirmation. The dashboard is non-critical: it shall be off the detection→alarm path and its failure shall never affect detection, alarm, or notification. | STK-1, STK-6 | D | M6 | dashboard/, app.py |
| **FR-18** | The hub shall run all inference models (stage-1 detector, stage-2 VLM, voice STT/LLM/TTS) on-device, and on startup shall ensure each required model is present, fetching any that are missing when permitted. Once provisioned, model loading shall require no network. | STK-2, STK-7 | D | M6 | models.py, scripts/download_models.py |

## Performance (PR) — targets/margins in [the TPM table](#tpm-cross-reference)

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **PR-1** | Stage-1 detection shall sustain ≥ 15 FPS at 1080p on the Jetson Orin NX. | STK-1 | T | M1 |
| **PR-2** | Time from the first qualifying frame to a confirmed threat decision shall be ≤ 2 s. | STK-1 | T | M2 |
| **PR-3** | Local-alarm latency shall be ≤ 1 s and mesh-alarm latency ≤ 3 s, measured from threat confirmation. | STK-1, STK-4 | T | M2/M3 |
| **PR-4** | The false-positive rate shall be ≤ 1 major alarm per 30 days under nominal operation and ≈ 0 across the OS-2 benign suite. | STK-3 | A/T | M2 |
| **PR-5** | The false-negative rate shall be ≤ 5% on the weapon-present benchmark set. | STK-1 | T | M2 |
| **PR-6** | LoRa effective range shall be ≥ 200 m through a typical residential structure at the regional band. | STK-4 | T | M3 |
| **PR-7** | A node going offline shall be detected within ≤ 30 s. | STK-4, STK-2 | T | M3 |
| **PR-8** | Voice agent first-audio latency (subject stops speaking → reply audio begins) shall be ≤ 2 s. | STK-5 | T | M5 |

## Interface (IR)

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **IR-1** | Camera input shall conform to ICD-1 (UVC/USB, CSI/MIPI, or RTSP). | STK-1 | I | M1 |
| **IR-2** | The hub↔radio-gateway link shall conform to ICD-2 (USB-serial framing + command set). | STK-4 | I | M3 |
| **IR-3** | The LoRa air protocol shall conform to ICD-3 (packet layout, HMAC, counter, ACK, heartbeat). | STK-4 | I/T | M3 |
| **IR-4** | Internal module boundaries shall exchange only the typed contracts defined in ICD-7 (`contracts.py`). | STK-7 | I | M0 |

## Reliability / Availability (RR)

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **RR-1** | A watchdog shall automatically restart the hub service on crash or hang. | STK-2 | T | M4 |
| **RR-2** | System availability shall be ≥ 99.9% including auto-recovery. | STK-2 | A | M4 |
| **RR-3** | The hub shall run ≥ 4 h on battery; each node ≥ 24 h standby and ≥ 10 min continuous siren. | STK-2 | T | M4 |
| **RR-4** | The system shall degrade gracefully on camera-loss, VLM-timeout, or mesh-loss — continuing at reduced capability and reporting the degradation. | STK-2 | T | M4 |
| **RR-5** | No single non-hub component failure shall disable the rest of the mesh. | STK-4 | A/T | M3/M4 |

## Security / Self-defense (SR)

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **SR-1** | Every LoRa message shall be authenticated (HMAC) and carry a monotonic counter; the receiver shall reject unauthenticated or replayed messages. | STK-4, STK-2 | T | M3 |
| **SR-2** | Jamming or tamper (sustained heartbeat loss) shall be detected and raised as an alert. | STK-2 | T | M3/M4 |
| **SR-3** | Keys and configuration shall be stored securely; nodes shall be provisioned via a shared secret. | STK-6 | I | M3 |
| **SR-4** | There shall be no remotely reachable attack surface in the critical detection→alarm path. | STK-2 | A | M2 |

## Safety / Ethics (SE) — hard constraints (see [SAFETY_ETHICS_LEGAL.md](SAFETY_ETHICS_LEGAL.md))

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **SE-1** | The system shall never initiate physical action against a person. No interface to any such mechanism shall exist. | STK-6 | I | all |
| **SE-2** | The voice agent shall operate within guardrails: no illegal threats, a constrained persona, and full logging of every utterance. | STK-6, STK-5 | I/D | M5 |
| **SE-3** | Detection shall mitigate demographic bias via balanced datasets, a bias-evaluation step, and reliance on behavior/object signals over appearance. | STK-6 | A | M2 |
| **SE-4** | Processing shall remain on-device; recording, retention, and consent shall follow the documented privacy policy. | STK-6 | I | M2 |
| **SE-5** | Non-recoverable escalations (e.g., contacting authorities) shall require human confirmation. | STK-6 | D | M6 |

## Environmental (ER)

| ID | Requirement | Parent | Method | M# |
|----|-------------|--------|--------|----|
| **ER-1** | Outdoor nodes shall be weatherproof (≥ IP65) with a documented operating temperature range. | STK-2 | I | M4 |
| **ER-2** | The system shall operate at night via IR/low-light imaging. | STK-1 | D | M1 |

---

## TPM cross-reference

Quantitative targets and margins for the PR/RR requirements are tracked in
[VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) §TPM. Requirements state the **threshold**
(must-meet); TPMs additionally track the **goal** (stretch) and current measured value.

## Change control

Requirements are versioned with the repo. Any change to an FR/PR/etc must update (a) this doc, (b) the
affected design doc, and (c) the RTM row, in the same PR. Adding scope means adding a numbered requirement
first — never code first.
