# FMEA — Failure Modes & Effects Analysis

**Crosscutting SE process.** For each component we ask: how can it fail, what's the effect on the mission,
how severe, how do we detect it, and how do we mitigate. **RPN = Severity × Occurrence × Detection-difficulty**
(each 1–5; higher detection-difficulty = harder to notice = worse). Design rule (pillar 1): **every failure
must be detectable and must degrade loudly, never silently.**

S: 1 negligible … 5 safety/mission-loss. O: 1 rare … 5 frequent. D: 1 obvious … 5 silent.

---

| # | Component | Failure mode | Effect on mission | S | O | D | RPN | Detection | Mitigation | Req |
|---|-----------|--------------|-------------------|---|---|---|-----|-----------|------------|-----|
| F1 | Camera | Disconnect / no frames | Blind in that zone | 5 | 3 | 2 | 30 | Frame-watchdog (`capture.timeout_s`) | Auto-reconnect; DEGRADED; owner alert; other zones unaffected | FR-1, RR-4 |
| F2 | Camera | Obstruction / blinding / spray | Effective blindness, looks "normal" | 5 | 2 | 4 | 40 | Scene-change / low-variance detector; tamper heuristic | Tamper alert; treat as DEGRADED + alert; multi-cam overlap | RR-4, SR-2 |
| F3 | Hub service | Crash | Total loss of detection | 5 | 2 | 1 | 10 | systemd + HW watchdog | Auto-restart (RR-1); nodes fail-safe on heartbeat loss | RR-1, FR-9 |
| F4 | Hub service | Hang / deadlock (no crash) | Silent total loss | 5 | 2 | 4 | 40 | SW watchdog: liveness heartbeat must tick; HW watchdog timer | Force-restart on missed tick; emit pre-restart alert | RR-1, FR-9 |
| F5 | Inference (YOLO) | Throttle / slow (thermal) | Latency/FPS miss | 3 | 3 | 3 | 27 | FPS + temp monitor vs TPM-1 | Reduce resolution/model; cooling; DEGRADED + alert | PR-1, RR-4 |
| F6 | Reasoner (VLM) | Timeout / hang | No stage-2 confirm | 4 | 3 | 2 | 24 | Hard timeout on the call | Fall back to stage-1 conservative decision (bias to alert); log | FR-4, RR-4 |
| F7 | Reasoner (VLM) | Hallucinated / malformed output | Wrong threat call | 4 | 3 | 3 | 36 | JSON schema + bounds validation | Reject + retry once → else stage-1 fallback; log raw | FR-4, R11 |
| F8 | State machine | Stuck / flicker | Missed or chattering alarms | 5 | 2 | 3 | 30 | Unit tests; state-dwell telemetry | Hysteresis + confirmation + cooldown; invariant asserts | FR-5 |
| F9 | Local siren/strobe | Driver/relay fails | No local audible alarm | 4 | 2 | 3 | 24 | Self-test in TEST mode; current sense (opt) | Mesh + voice + notify still fire; periodic self-test | FR-6, RR-4 |
| F10 | LoRa gateway | Module fault / USB drop | No mesh from hub | 4 | 2 | 2 | 16 | Gateway `GET_STATUS` + TX_DONE absent | Local siren still fires; alert; auto-reopen serial | FR-7, RR-4 |
| F11 | LoRa link | Jam / interference | Mesh commands lost | 4 | 2 | 3 | 24 | Missed ACK + heartbeat loss | Retries; heartbeat-loss → node fail-safe; jam alert | SR-2, FR-9 |
| F12 | Node | Battery depleted | Node silent | 3 | 3 | 3 | 27 | `STATUS.battery_mv` low + offline detect | Low-batt alert; siren energy reserve budget; mains charge | FR-10, RR-3 |
| F13 | Node | Mains cut (intruder) | Runs on battery (intended) | 2 | 3 | 1 | 6 | `STATUS.on_battery` | Battery backup; report; unaffected operation | FR-10, R7 |
| F14 | Node | Physically destroyed/unplugged | That node gone | 4 | 2 | 2 | 16 | Heartbeat loss at hub (PR-7) | Offline/tamper alert ≤30 s; other nodes unaffected | SR-2, RR-5 |
| F15 | Voice (LLM/TTS) | Hang | Voice stalls | 2 | 3 | 2 | 12 | Per-call timeout | Voice is non-critical; alarm/notify unaffected; skip turn | FR-12 |
| F16 | Voice (LLM) | Harmful/illegal utterance | Reputational/legal harm | 4 | 2 | 3 | 24 | Output filter + log review | Guardrails + content filter; constrained persona; full log | SE-2, R9 |
| F17 | Notifications | Provider/WAN down | Owner not alerted remotely | 3 | 3 | 2 | 18 | Send failure + offline flag | Local alarm primary; queue + flush on reconnect | FR-13 |
| F18 | Power (hub) | Mains cut | Loss if no backup | 5 | 3 | 1 | 15 | Mains-sense / UPS state | LiFePO4 + DC-UPS ≥4 h; report; orderly low-batt behavior | RR-3, R7 |
| F19 | Storage | Disk full / log overflow | Event logging fails | 3 | 2 | 3 | 18 | Free-space monitor | Rotation + retention caps; alert; never block alarm path | FR-15, SE-4 |
| F20 | Config/keys | Misprovisioned HMAC key | Nodes reject hub | 4 | 2 | 2 | 16 | ACK failures on provisioning self-test | Provisioning self-test in TEST mode before arming | SR-3 |

## Highest-RPN items (act first)
F2 (camera tamper, 40), F4 (silent hang, 40), F7 (VLM hallucination, 36), F1/F8 (30). Each must have its
detection + mitigation implemented and verified before the relevant milestone exits. Note the recurring theme
the design enforces: **independent, redundant alarm paths** (local siren ∥ mesh ∥ voice ∥ notify) mean no
single failure silences the system.
