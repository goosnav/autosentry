# VERIFICATION & VALIDATION — V&V Plan + Traceability

**V-Model:** the entire **right arm**. **Verification** = "did we build the system right?" (against the SRD).
**Validation** = "did we build the right system?" (against the ConOps). Methods: **I**/**A**/**D**/**T**.

A requirement is **DONE only when its V&V activity passes** and its RTM row is green.

---

## 1. The four verification levels (mapped to the V)

| Level | Question | Activities | Where |
|-------|----------|------------|-------|
| **L4 Unit/Component** | Does each part work in isolation? | `pytest hub/tests`; `pio test`; detection eval harness; HMAC/codec test vectors. | per-module |
| **L3 Subsystem Integration** | Do parts work across the ICD seams? | capture→detection→reasoning→state; state→alarm; state→comms→node loopback; voice loop w/ mocked vision. | `hub/tests/integration/`, bench |
| **L2 System Verification** | Does the assembled system meet the SRD/TPMs? | full hub on Jetson; measure FPS/latency/false-pos/neg, LoRa range, offline-detect, battery runtimes. | on-target |
| **L1 Validation** | Does it satisfy the ConOps in the field? | scripted drills OS-1..8, incl. pull-network-then-mains. | field |

## 2. Verification methods per requirement type
- **Inspection (I):** read code/config/enclosure against the spec (e.g. SE-1 — confirm no force interface exists).
- **Analysis (A):** model/compute (e.g. RR-2 availability from MTBF/MTTR; PR-4 from eval set + duty cycle).
- **Demonstration (D):** show the behavior once under nominal conditions (e.g. FR-11 voice responds to vision).
- **Test (T):** measured, repeatable, pass/fail against a threshold (e.g. PR-1 ≥15 FPS; PR-6 ≥200 m).

## 3. Technical Performance Measures (TPM) {#tpm}

Thresholds are the requirement; goals are stretch; "current" is updated as measured on-target.

| ID | Measure | Threshold | Goal | Method | Current |
|----|---------|-----------|------|--------|---------|
| TPM-1 | Stage-1 throughput @1080p (Orin NX) | ≥15 FPS | ≥25 | T | — |
| TPM-2 | Threat-confirm latency | ≤2 s | ≤1 s | T | — |
| TPM-3 | Local / mesh alarm latency | ≤1 s / ≤3 s | ≤0.5 / ≤1.5 s | T | — |
| TPM-4 | False-positive rate | ≤1/30 d | ≈0 | A/T | — |
| TPM-5 | False-negative rate (benchmark) | ≤5% | ≤2% | T | — |
| TPM-6 | LoRa range through structure | ≥200 m | ≥500 m | T | — |
| TPM-7 | Node-offline detection | ≤30 s | ≤10 s | T | — |
| TPM-8 | Node battery standby / siren | ≥24 h / ≥10 min | ≥72 h / ≥30 min | T | — |
| TPM-9 | Hub battery runtime | ≥4 h | ≥8 h | T | — |
| TPM-10 | Voice first-audio latency | ≤2 s | ≤1 s | T | — |

## 4. Requirements Traceability Matrix (RTM)

Status: ☐ not started · ◐ in progress · ☑ verified. Keep current — a PR that satisfies a requirement flips
its status and names the evidence (test id / drill / inspection note).

| Req | Method | V-Level | Verification activity | M# | Status |
|-----|--------|---------|-----------------------|----|--------|
| FR-1 | D | L2 | Boot + hotplug a webcam; pipeline auto-binds. | M1 | ◐ `test_capture` (reconnect logic); hotplug demo pending Jetson+webcam |
| FR-2 | D | L2 | Kill service; watchdog restarts; pipeline resumes. | M1 | ◐ capture resume unit-tested; watchdog restart demo pending hardware |
| FR-3 | T | L4 | `eval_detection.py` precision/recall on labeled set; track-ID continuity test. | M1 | ◐ `test_tracking` continuity + `test_eval_detection` metrics ☑; P/R gate needs labeled benchmark |
| FR-4 | T | L4 | Feed known frames; assert schema-valid JSON + correct armed/intent. | M2 | ☑ `test_assessor` (parse/validate/retry/fallback, no zone/ts spoof) |
| FR-5 | T | L4 | State-machine unit tests: hysteresis, confirmation, cooldown, panic. | M1 | ☑ `test_state_machine` + `test_pipeline` |
| FR-6 | T | L3 | ALARM entry asserts siren+strobe GPIO/audio. | M2 | ◐ `test_alarm` latch + `test_pipeline` ALARM-entry actuation via fake sink ☑; real GPIO/audio bench pending |
| FR-7 | T | L3 | ALARM → signed LoRa broadcast → node siren fires (bench). | M3 | ◐ `test_mesh_gateway` signed broadcast + shared-counter repeats ☑; ALARM→mesh wired in `Hub._actuate` (gated `comms.enabled`); node-siren bench pending hardware |
| FR-8 | T | L3 | Node ACKs; hub marks online; kill node → marked offline. | M3 | ◐ `test_mesh_gateway` ACK-gated retry + node-health table + offline-flag ☑; on-target ACK bench pending |
| FR-9 | T | L3 | Heartbeat loss → hub alert; isolated node → local alert. | M3/M4 | ◐ hub heartbeat cadence + offline-after-misses unit-tested ☑; node fail-safe implemented (firmware); bench pending |
| FR-10 | T | L2 | Pull node mains; `STATUS.on_battery` true at hub. | M4 | ◐ `test_mesh_gateway` STATUS→on_battery surfaced while online ☑; `test_reliability` Hub.power_alerts/health surface offline+on-battery ☑; firmware reports STATUS w/ on_battery; real INA219 mains-sense bench pending |
| FR-11 | D | L3 | Speak; reply changes with injected vision context. | M5 | ◐ `test_voice` prompt-carries-vision-context + same-speech-different-context-changes-prompt ☑; on-target live STT→LLM→TTS demo pending models |
| FR-12 | D | L2 | During voice dialogue, alarm + notify still fire. | M5 | ◐ `test_pipeline` hung-voice-never-blocks-or-silences-siren + voice-engages-on-ALARM ☑ (voice engaged after siren latch in `_actuate`, failure → DEGRADED); on-target concurrent demo pending |
| FR-13 | D | L2 | Offline → notification queues; reconnect → flushes. | M6 | ◐ `test_notify` durable outbox: delivers online, queues offline, flushes oldest-first on reconnect, stops-on-failure without dropping ☑; `test_multizone` ALARM enqueues a push without gating ☑; live push-provider demo pending |
| FR-14 | D | L2 | Panic forces ALARM from each mode; test mode no-latch; per-zone arm. | M4/M6 | ◐ `test_reliability` panic-forces-ALARM-when-disarmed, test-mode-pulses-no-latch, disarmed-reaches-ALARM-but-silent, armed-fires-siren ☑; `test_dashboard` operator UI exposes arm/disarm, panic, test-mode routing to the Hub ☑ |
| FR-15 | I | L2 | Inspect event log: ts, keyframe, assessment, actions present. | M2 | ◐ `test_event_log` ts/zone/level/assessment/actions + keyframe paths persisted ☑; `test_pipeline` captures the triggering frame to disk and records its path, and a failing encode degrades to no-keyframe without breaking the pipeline (pillar 1) ☑; on-target image-quality review pending |
| FR-16 | D | L2 | Threat in zone A, benign in zone B; correct attribution. | M6 | ◐ `test_multizone` armed rifle at "front" escalates to ALARM while empty "back" stays NORMAL, ALARM attributed to the right zone, per-zone detectors + state machines proven independent ☑; on-target multi-camera demo pending |
| FR-17 | D | L2 | Dashboard shows per-zone state/health, exposes FR-14 controls + SE-5 confirm, off the critical path. | M6 | ◐ `test_dashboard` status reflects per-zone level/arming/health + pending queues, system-level rollup (max across zones), latest stage-2 assessment per zone, mesh node-health (offline/on-battery), controls route to Hub, unknown-zone rejected, events newest-first ☑ (12 tests); HTTP adapter serves an enriched single-page UI (system banner, per-zone assessment, node table, arm-all/disarm-all) + JSON API, POST controls, 400 on bad input, clean shutdown; on-target browser demo pending |
| FR-18 | D | L2 | Missing models fetched on startup; present ones skipped; loads offline thereafter. | M6 | ◐ `test_models` present-not-refetched, missing-fetched, auto_download-off reports-without-fetching, force-refetch, voice-disabled drops voice targets, one-failure-isolated ☑; backends resolve provisioned weights under `models/`; `scripts/download_models.py --list` enumerates all 5 models; provisioning runs at `Hub.run()` boot, off the hot path; on-target live fetch (YOLO/Ollama/whisper/piper) pending |
| PR-1 | T | L2 | Measure FPS on Orin NX @1080p ≥15. | M1 | ☐ deferred to on-Jetson bench |
| PR-2 | T | L2 | Measure first-qualifying-frame→confirm ≤2 s. | M2 | ◐ confirmation-window logic verified (`test_pipeline`); wall-clock latency deferred to on-Jetson bench |
| PR-3 | T | L2 | Measure confirm→local ≤1 s, confirm→mesh ≤3 s. | M2/M3 | ◐ mesh broadcast path wired + `bench_lora` ping/echo RTT harness ready; wall-clock measurement deferred to on-target bench |
| PR-4 | A/T | L2 | Benign suite ≈0 false alarms; 30-day duty-cycle analysis ≤1. | M2 | ☐ |
| PR-5 | T | L2 | Weapon-present benchmark false-negative ≤5%. | M2 | ☐ |
| PR-6 | T | L2 | Range walk-test through structure ≥200 m. | M3 | ☐ deferred to on-hardware range walk-test |
| PR-7 | T | L2 | Time from node-kill to hub-offline-flag ≤30 s. | M3 | ◐ offline-detection logic verified (`test_node_goes_offline_after_missed_heartbeats`, deadline = hb_interval×hb_miss_max ≤30 s); wall-clock on-target pending |
| PR-8 | T | L2 | Measure subject-stop→reply-audio ≤2 s. | M5 | ☐ |
| IR-1..4 | I/T | L3 | Inspect each seam against ICD-1..7; codec round-trip tests. | M0–M3 | ◐ IR-2 (ICD-2 transport) COBS/CRC round-trip + corruption ☑; IR-3 (ICD-3 air) payload codec round-trips ☑; IR-4 scaffolded |
| RR-1 | T | L2 | Crash/hang injection → auto-restart. | M4 | ◐ `test_watchdog` ping cadence + stalled-loop-stops-pinging ☑; `deploy/autosentry.service` Type=notify w/ WatchdogSec; on-target systemd kill/restart demo pending |
| RR-2 | A | L2 | Availability computed from MTBF/MTTR ≥99.9%. | M4 | ☐ deferred to on-target MTBF/MTTR analysis |
| RR-3 | T | L2 | Battery-runtime measurement hub/node. | M4 | ☐ deferred to hardware battery-runtime bench |
| RR-4 | T | L3 | Inject camera/VLM/mesh failures → graceful DEGRADED. | M4 | ◐ `test_reliability` detector-fault-degrades-no-crash, assessor-fault-never-manufactures-ALARM ☑; mesh-broadcast fault caught in `_actuate` (local siren unaffected) ☑; on-target fault injection pending |
| RR-5 | A/T | L3 | Kill one node → mesh + hub unaffected. | M3/M4 | ◐ per-source node-health isolation unit-tested (one node offline doesn't perturb others); multi-node bench pending |
| SR-1 | T | L4 | HMAC test vectors; replayed counter rejected. | M3 | ◐ forged-HMAC drop + replayed-counter reject unit-tested (`test_mesh_gateway`); protocol codec + ReplayWindow tested in M0; node-side replay window mirrors protocol.py |
| SR-2 | T | L3 | Jam/tamper → alert. | M3/M4 | ◐ hub offline-flag on heartbeat silence + node hub-timeout fail-safe implemented ☑; physical jam/tamper bench pending |
| SR-3 | I | L3 | Inspect key storage/provisioning; no secret in repo. | M3 | ☑ inspection performed (SECURITY.md §6.1) + pinned by `test_security`: mesh key loads from `AUTOSENTRY_MESH_KEY` with no committed default (raises if unset), no `key` field on any config model, `config.yaml` holds only the env-var name, `.gitignore` excludes `.env`/`*.key`/`*.pem`/`secrets/`/`node_keys.yaml`, no secret tracked; node-secret provisioning is out-of-band at flash (COMMS_PROTOCOL.md) — on-hardware provisioning self-test (FMEA F20) pending |
| SR-4 | A | L2 | Attack-surface review of critical path. | M2 | ☑ analysis performed (SECURITY.md §6.2) + pinned by `test_security`: critical path (capture/detection/reasoning/state/alarm/comms) has no inbound listener (radio is serial + HMAC/counter-checked), dashboard is the only inbound surface and is opt-in + loopback-bound off-path, all other network I/O is localhost inference or owner-directed metadata-only push |
| SE-1 | I | all | Inspect: no interface to any physical-force mechanism. | all | ◐ (architectural) |
| SE-2 | I/D | L3 | Inspect guardrails + log; demo refusal of illegal content. | M5 | ◐ `test_voice` guardrail blocks threat-of-force + false-weapon-claim → safe fallback, raw retained in `agent.blocked` + logged ☑; persona system-prompt inspected; adversarial red-team set pending |
| SE-3 | A | L2 | Bias eval across demographic slices on the benchmark. | M2 | ☐ |
| SE-4 | I | L2 | Inspect on-device processing + retention/consent config. | M2 | ◐ code inspection (SECURITY.md §6.2): all inference is on-device (stage-1 local weights; stage-2 VLM + voice LLM on localhost Ollama; whisper/piper local files), recordings/keyframes + event log stay on local disk, the only data leaving the box is opt-in owner push carrying event metadata only (no image bytes) and one-time model downloads; no third-party analytics/telemetry ☑; retention-window + consent-signage policy controls pending (SAFETY_ETHICS_LEGAL.md) |
| SE-5 | D | L2 | Authority-contact path requires human confirm. | M6 | ◐ `test_multizone` ALARM only *recommends* authority contact (`pending_authority` rec, `confirmed is False`, `authority_recommended` in event actions) — never auto-confirms; `confirm_authority_contact` is the sole path to `confirmed=True` ☑; `test_dashboard` confirm-authority is human-only, confirms the right rec, rejects out-of-range ☑ |
| ER-1 | I | L3 | Inspect enclosure IP rating + temp spec. | M4 | ☐ deferred to hardware enclosure inspection (≥IP65) |
| ER-2 | D | L2 | Night/low-light detection demo. | M1 | ☐ |

## 5. Validation drills (L1, against the ConOps OS-1..8)

Each drill has a script, expected outcome, and a recorded result. Run on-target with real hardware.

| Drill | Setup | Pass criteria |
|-------|-------|---------------|
| OS-1 Nominal | Armed, empty scene, long run | 0 false alarms; stable resources |
| OS-2 Benign visitor | Person approaches w/o weapon, leaves | No major alarm, no mesh trigger |
| OS-3 Armed approach | Staged weapon display approach | ALARM within budget; siren+mesh+voice+notify; full log |
| OS-4 Mains cut | Pull hub & node mains mid-drill | Continue on battery; `on_battery` reported |
| OS-5 Internet cut | Disconnect WAN | Local chain works; notify queues+flushes |
| OS-6 Jam/tamper | Kill/unplug a node | Hub offline-alert ≤30 s; isolated node fails safe |
| OS-7 Multi-zone | Threat zone A, benign zone B | Correct attribution; no cross-talk |
| OS-8 Test+panic | Run test mode; hit panic | Test no-latch; panic forces ALARM |

**Acceptance for v1** = all RTM rows ☑ **and** all OS drills pass, culminating in the end-to-end OS-3 drill
with network then mains pulled.

## 6. CI gates
- PR: `ruff`, `ruff format --check`, `mypy` (typed modules), `pytest`, `pio test` (firmware) must pass.
- Detection eval (PR-4/PR-5) runs on the benchmark set and must not regress beyond tolerance.
