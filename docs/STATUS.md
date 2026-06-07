# STATUS — Live project dashboard

**Last updated:** 2026-06-07 · **RTM commit:** `04c2652`

**One-line summary:** M0–M6 implemented in code; **v1 acceptance = closing the ☐ RTM rows on real
hardware + the labeled benchmark**. The first 4 RTM rows (FR-4, FR-5, SR-3, SR-4) are ☑; the rest is
verification work.

> **Authoritative source for status:** the RTM in
> [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) §4. This document mirrors the RTM
> and adds a milestone-level rollup and an ordered punch list. If the two ever disagree, the RTM wins.
> PRs that change a row's status update the RTM and the "Last updated" stamp here in the same change.

---

## 1. At a glance

| Bucket | Count | Rows |
|--------|------:|------|
| **☑ Verified** | 4 | FR-4, FR-5, SR-3, SR-4 |
| **◐ In progress** | 27 | FR-1, FR-2, FR-3, FR-6, FR-7, FR-8, FR-9, FR-10, FR-11, FR-12, FR-13, FR-14, FR-15, FR-16, FR-17, FR-18, PR-2, PR-3, PR-4, PR-5, PR-7, IR-1..4, RR-1, RR-4, RR-5, SR-1, SR-2, SE-2, SE-4, SE-5 |
| **☐ Not started / hardware-deferred** | 8 | **PR-1, PR-6, PR-8, RR-2, RR-3, SE-3, ER-1, ER-2** |

A "◐ in progress" row has its **logic** implemented and unit-tested; the wall-clock / on-target / on-hardware
demonstration is the still-open part. Every ☐ row is blocked on **real hardware** (Jetson + cameras + nodes +
batteries + enclosures) or the **labeled benchmark dataset** (the same set gates PR-4, PR-5, and SE-3).

**High-band risk status** (R1, R3, R7, R8 per [RISK_REGISTER.md](RISK_REGISTER.md)): all four are still **Open**
in the RTM. Closing them is the on-target work, not new code.

---

## 2. Full RTM (mirror)

Status: ☐ not started · ◐ in progress · ☑ verified.

| Req | M# | Status | Evidence / what remains |
|-----|----|--------|-------------------------|
| **FR-1** | M1 | ◐ | `test_capture` reconnect logic ☑; on-target hotplug demo pending. |
| **FR-2** | M1 | ◐ | Capture resume ☑; on-target watchdog restart demo pending. |
| **FR-3** | M1 | ◐ | `test_tracking` + `test_eval_detection` metrics ☑; labeled benchmark run pending (gates PR-5). |
| **FR-4** | M2 | ☑ | `test_assessor` (parse/validate/retry/fallback, no zone/ts spoof). |
| **FR-5** | M1 | ☑ | `test_state_machine` + `test_pipeline`. |
| **FR-6** | M2 | ◐ | `test_alarm` latch + `test_pipeline` ALARM entry via fake sink ☑; real GPIO/audio bench pending. |
| **FR-7** | M3 | ◐ | `test_mesh_gateway` signed broadcast + counter repeats ☑; ALARM→mesh wired in `Hub._actuate` (gated `comms.enabled`); on-target node-siren bench pending. |
| **FR-8** | M3 | ◐ | ACK-gated retry + node-health table + offline-flag ☑; on-target ACK bench pending. |
| **FR-9** | M3/M4 | ◐ | Hub heartbeat cadence + offline-after-misses ☑; node fail-safe implemented in firmware; on-target bench pending. |
| **FR-10** | M4 | ◐ | STATUS→on_battery surfaced + `power_alerts()`/`health()` ☑; real INA219 bench pending. |
| **FR-11** | M5 | ◐ | Prompt-carries-vision-context + context-changes-prompt ☑; on-target live STT→LLM→TTS demo pending. |
| **FR-12** | M5 | ◐ | `test_pipeline` hung-voice-never-blocks-or-silences-siren + voice-engages-on-ALARM ☑; on-target concurrent demo pending. |
| **FR-13** | M6 | ◐ | Durable outbox + multi-zone push ☑; live push-provider demo pending. |
| **FR-14** | M4/M6 | ◐ | Panic / test-mode / arm-disarm logic + dashboard controls ☑; on-target demo pending. |
| **FR-15** | M2 | ◐ | `test_event_log` ts/zone/level/assessment/actions + keyframe paths + failure-doesn't-break-pipeline ☑; on-target image-quality review pending. |
| **FR-16** | M6 | ◐ | `test_multizone` per-zone independence + correct attribution ☑; on-target multi-camera demo pending. |
| **FR-17** | M6 | ◐ | `test_dashboard` 12 tests + HTTP server + controls routing ☑; on-target browser demo pending. |
| **FR-18** | M6 | ◐ | `test_models` present-not-refetched, missing-fetched, etc. + `download_models.py --list` ☑; on-target live fetch (YOLO / Ollama / whisper / piper) pending. |
| **PR-1** | M1 | ☐ | FPS ≥15 @1080p on Orin NX — **on-Jetson bench only**. |
| **PR-2** | M2 | ◐ | Confirmation-window logic ☑; wall-clock latency **on-Jetson bench only**. |
| **PR-3** | M2/M3 | ◐ | Mesh broadcast path wired + `bench_lora` ping/echo RTT harness ready ☑; wall-clock **on-target bench only**. |
| **PR-4** | M2 | ◐ | `check_gates()` fails the build on any benign-suite major-alarm trigger; `test_eval_detection` pins pass/fail ☑. Benign-suite run + 30-day duty-cycle analysis pending the **labeled benchmark**. |
| **PR-5** | M2 | ◐ | `weapon_fn_rate()` (weapon-only FN) + `check_gates()` (fail above 5%) implemented + unit-tested ☑. On-benchmark measurement pending the **labeled weapon-present set**. |
| **PR-6** | M3 | ☐ | Range walk-test ≥200 m through structure — **hardware only**. |
| **PR-7** | M3 | ◐ | `test_node_goes_offline_after_missed_heartbeats` (deadline ≤30 s) ☑; **on-target wall-clock only**. |
| **PR-8** | M5 | ☐ | First-audio ≤2 s — **on-Jetson bench with real STT/LLM/TTS**. |
| **IR-1..4** | M0–M3 | ◐ | ICD-2 COBS/CRC round-trip + ICD-3 codec round-trips ☑; on-hardware conformance of IR-1/IR-2 (real camera + real gateway) pending. |
| **RR-1** | M4 | ◐ | `test_watchdog` cadence + stalled-loop-stops-pinging + `autosentry.service` Type=notify ☑; on-target systemd kill/restart demo pending. |
| **RR-2** | M4 | ☐ | MTBF/MTTR analysis **on-target only** (assumes real field data). |
| **RR-3** | M4 | ☐ | Battery runtime — **hardware only** (LiFePO4 + INA219). |
| **RR-4** | M4 | ◐ | `test_reliability` detector-fault / assessor-fault / mesh-fault containment ☑; on-target fault injection pending. |
| **RR-5** | M3/M4 | ◐ | Per-source node-health isolation ☑; multi-node bench pending. |
| **SR-1** | M3 | ◐ | Forged-HMAC drop + replayed-counter reject + node-side ReplayWindow ☑. |
| **SR-2** | M3/M4 | ◐ | Hub offline-flag + node fail-safe ☑; physical jam/tamper bench pending. |
| **SR-3** | M3 | ☑ | SR-3 inspection (SECURITY.md §6.1) + `test_security` regression (key from `AUTOSENTRY_MESH_KEY`, no committed default, .gitignore covers secret artifacts, no secret tracked). Node-side provisioning self-test (FMEA F20) on-hardware pending. |
| **SR-4** | M2 | ☑ | SR-4 analysis (SECURITY.md §6.2) + `test_security` regression (no inbound listener on critical path, dashboard opt-in loopback off-path, no third-party analytics). |
| **SE-1** | all | ◐ | Architectural; re-inspect at every milestone exit (no interface to physical-force mechanism). |
| **SE-2** | M5 | ◐ | `test_voice` guardrail blocks + `agent.blocked` + full log ☑; broader adversarial red-team set pending. |
| **SE-3** | M2 | ☐ | Bias eval across demographic slices — **needs the same labeled benchmark as PR-4/PR-5**. |
| **SE-4** | M2 | ◐ | Code-inspection evidence (SECURITY.md §6.2) ☑; retention-window + consent-signage policy controls pending (SAFETY_ETHICS_LEGAL.md). |
| **SE-5** | M6 | ◐ | `test_multizone` + `test_dashboard` SE-5 paths human-only ☑; live confirm-from-dashboard demo pending. |
| **ER-1** | M4 | ☐ | Enclosure IP65 + temp spec — **hardware inspection only**. |
| **ER-2** | M1 | ☐ | Night/low-light detection demo — **on-Jetson + IR-capable camera**. |

---

## 3. Milestone rollup

For each milestone: **code deliverables** (what landed in `hub/`, `firmware/`, `scripts/`, `docs/`) and
**verification deliverables** (what's still open). Row statuses are taken from the RTM.

### M0 — Scaffold & baseline  *(exited)*
- **Code:** repo structure, all baseline docs, typed contracts (ICD-7), config, CI lint+test, `deploy/` unit, `hardware/BOM.csv`, scripts placeholders.
- **Verify:** IR-4 ☑, SE-1 ◐ (always re-inspect).

### M1 — Vision core
- **Code:** `capture/` (webcam, auto-reconnect), `detection/` (YOLO + ByteTrack, ONNX-RT fallback), `state/` machine, `eval_detection.py` (metrics core + PR-4/PR-5 gate), state machine + tracking unit tests.
- **Verify:** ◐ FR-1 (hotplug demo), ◐ FR-2 (watchdog restart demo), ◐ FR-3 (P/R on labeled set), ☐ PR-1 (Orin FPS), ☐ PR-5 (FN ≤5%, gated by dataset), ☐ ER-2 (night demo). **Everything past "logic verified" is on-Jetson bench + the labeled benchmark.**

### M2 — Reasoning + local alarm
- **Code:** `reasoning/` (Ollama/llama.cpp stage-2, schema-validated, timeout, retry, fallback), `alarm/` (controller + GPIO sink), audit log with keyframe persistence, bias-eval slot.
- **Verify:** ☑ FR-4, ◐ FR-6 (real GPIO/audio bench), ◐ FR-15 (on-target image-quality review), ◐ PR-2 (wall-clock), ☐ PR-4 (benign suite), ☐ PR-5 (weapon FN), ☐ SE-3 (bias slices). **Three ☐ rows all share the labeled benchmark as their single blocker.**

### M3 — LoRa mesh
- **Code:** `comms/` (HMAC-SHA256 trunc + monotonic counter + ACK + retry + heartbeat + node-health table), `scripts/bench_lora.py`, ESP32-S3 + SX1262 node firmware (parse/verify, siren GPIO, heartbeat/STATUS payloads, hub-timeout fail-safe).
- **Verify:** ◐ FR-7/8/9 (on-target bench), ◐ SR-1 (vectors ☑, physical on-bench pending), ◐ SR-2 (jam/tamper bench), ◐ PR-3 (wall-clock), ◐ PR-7 (wall-clock), ◐ RR-5 (multi-node), ☐ PR-6 (range walk-test).

### M4 — Power & reliability
- **Code:** `watchdog.py` (sd_notify READY=1/WATCHDOG=1), per-zone arming, test mode, manual panic, graceful-degradation map, `power_alerts()` / `health()` surfaces, `autosentry.service` Type=notify with WatchdogSec.
- **Verify:** ◐ FR-10 (real INA219 bench), ◐ RR-1 (on-target systemd kill/restart), ◐ RR-4 (on-target fault injection), ☐ RR-2 (MTBF/MTTR analysis), ☐ RR-3 (battery runtime bench), ☐ ER-1 (enclosure IP inspection).

### M5 — Voice agent
- **Code:** `voice/` STT (faster-whisper) → LLM (Ollama local) → TTS (Piper), vision-context injection per turn, persona + content-filter guardrails, full utterance log, non-blocking + non-gating of the alarm chain.
- **Verify:** ◐ FR-11 (on-target live STT→LLM→TTS demo), ◐ FR-12 (concurrent alarm+voice demo), ◐ SE-2 (broader red-team), ☐ PR-8 (first-audio ≤2 s).

### M6 — Multi-cam + notifications + dashboard
- **Code:** `notify/` (durable outbox + reconnect flush), multi-camera/multi-zone per-zone state machines, `dashboard/` (opt-in, loopback-bound, single-page UI + JSON API), `models.py` + `download_models.py` (on-device provisioning of stage-1 / stage-2 / voice), SE-5 human-confirm path.
- **Verify:** ◐ FR-13 (live push-provider demo), ◐ FR-16 (on-target multi-camera), ◐ FR-17 (on-target browser demo), ◐ FR-18 (on-target live model fetch), ◐ SE-5 (live confirm from dashboard). **All logic ☑ — every ◐ here is a single on-target demo.**

---

## 4. v1 exit punch list

Ordered roughly by what unblocks the most downstream work first. **The labeled benchmark is the single
biggest gate** — PR-4, PR-5, and SE-3 all need it.

### Block 0 — the labeled benchmark dataset (unblocks PR-4, PR-5, SE-3)
- Source/curate the labeled set (weapons + benign + demographic strata). SOW lives in V&V (planned, see open work).
- Add hard-negative mining (phones, umbrellas, tools, sports gear).
- Augment for conditions: day/night/IR, distance, occlusion, motion blur.
- Wire `scripts/eval_detection.py --set bench/` to load it and call `check_gates()`. `check_gates()` is already
  unit-tested (PR-5 weapon-only FN, PR-4 benign-major-alarm count); the dataset is what's missing.
- Run in CI on a schedule (nightly on labeled set + PR-regression tolerance).

### Block 1 — on-target vision bench (M1/M2 verification)
- ☐ PR-1: FPS ≥15 @1080p on Orin NX (and document thermal behavior — risk R4).
- ☐ PR-5: weapon FN ≤5% on the labeled set (after Block 0).
- ☐ PR-4: benign suite ≈0 major alarms (after Block 0).
- ☐ SE-3: bias slices within tolerance (after Block 0).
- ◐ FR-3: P/R on labeled set (after Block 0; this is the gating metric).
- ◐ FR-1: live hotplug demo (Jetson + UVC).
- ◐ FR-2: watchdog restart demo (Jetson + simulated camera-loss).
- ☐ ER-2: night / IR detection demo (Jetson + IR-capable camera + illuminator).

### Block 2 — LoRa bench (M3 verification)
- ◐ FR-7: ALARM → signed LoRa broadcast → real node siren fires + ACK.
- ◐ FR-8: kill node → marked offline on hub.
- ◐ FR-9: heartbeat loss → hub alert; isolated node → local alert.
- ☐ PR-6: range walk-test ≥200 m through structure.
- ◐ PR-7: node-kill → hub-offline ≤30 s (wall-clock).
- ◐ PR-3: confirm→mesh ≤3 s (wall-clock).
- ◐ SR-2: physical jam / node tamper drill.
- ◐ RR-5: multi-node independence on the bench.

### Block 3 — power & reliability bench (M4 verification)
- ◐ FR-10: pull node mains → `STATUS.on_battery` true at hub.
- ◐ RR-1: on-target systemd kill/restart + on-target hang (stops petting).
- ◐ RR-4: real fault injection (camera, VLM, gateway, notify) → graceful DEGRADED.
- ☐ RR-2: MTBF/MTTR analysis (on-target, post-field-data).
- ☐ RR-3: battery runtime — hub ≥4 h, node ≥24 h standby + ≥10 min siren.
- ☐ ER-1: enclosure ≥IP65 + temp spec inspection.

### Block 4 — voice on-target (M5 verification)
- ◐ FR-11: live STT→LLM→TTS demo (replies change with vision context).
- ◐ FR-12: concurrent voice + alarm demo (kill voice → alarm still fires).
- ☐ PR-8: first-audio ≤2 s wall-clock.
- ◐ SE-2: broader adversarial red-team set.

### Block 5 — multi-cam / notify / dashboard demos (M6 verification)
- ◐ FR-13: live push-provider demo (offline → queued → reconnect → flushed).
- ◐ FR-16: on-target multi-camera (threat in A, benign in B).
- ◐ FR-17: on-target browser demo of the dashboard.
- ◐ FR-18: on-target live model fetch (YOLO / Ollama / whisper / piper).
- ◐ SE-5: live confirm-authority from the dashboard.

### Block 6 — the 8 validation drills (L1, against ConOps)
OS-1..8 from [CONOPS.md §7](CONOPS.md) + [TESTING.md L1](TESTING.md). OS-3 is the v1 acceptance
drill ("network then mains pulled"); all ☐ and ◐ TPM/FR rows must be ☑ before it ships.

### TPM measurement log (to be filled in on-target)
| TPM | Threshold | Goal | Method | Current |
|-----|-----------|------|--------|---------|
| TPM-1 FPS @1080p | ≥15 | ≥25 | T | — |
| TPM-2 confirm latency | ≤2 s | ≤1 s | T | — |
| TPM-3 local/mesh latency | ≤1/≤3 s | ≤0.5/≤1.5 s | T | — |
| TPM-4 FP rate | ≤1/30 d | ≈0 | A/T | — |
| TPM-5 FN rate | ≤5% | ≤2% | T | — |
| TPM-6 LoRa range | ≥200 m | ≥500 m | T | — |
| TPM-7 offline detect | ≤30 s | ≤10 s | T | — |
| TPM-8 node battery | ≥24 h / ≥10 min | ≥72 h / ≥30 min | T | — |
| TPM-9 hub battery | ≥4 h | ≥8 h | T | — |
| TPM-10 voice first-audio | ≤2 s | ≤1 s | T | — |

---

## 5. Open ADRs / open risks

### ADRs ready to close (in DECISIONS.md)
- **ADR-7 — Local web dashboard vs minimal status UI.** Decided: local web UI (loopback-bound, opt-in), per `dashboard/server.py` (FR-17).
- **ADR-8 — Notification transport.** Decided: provider-agnostic HTTPS sender (`notify/sender.py`); self-hosted or commercial provider, owner-configured.

### ADRs explicitly open
- **ADR-9 — Weapon-detection dataset/model sourcing & fine-tuning approach** (gates PR-4, PR-5, SE-3 — see Block 0).
- **ADR-10 — Multi-hub coordination for larger sites** (post-v1, per ROADMAP).

### High-band risks still Open
- **R1 (false positives)** — mitigation logic ☑; close when the benign suite (PR-4) gates pass.
- **R3 (demographic bias)** — close when SE-3 analysis passes.
- **R7 (mains cut)** — close when OS-4 drill passes and `on_battery` reporting is observed on-target.
- **R8 (legal/privacy)** — close when SE-4 retention/consent policy controls land (SAFETY_ETHICS_LEGAL.md).

Full text: [DECISIONS.md](DECISIONS.md), [RISK_REGISTER.md](RISK_REGISTER.md).

---

## 6. Active branch / uncommitted work

- **Branch:** `m3-lora-mesh` (misnamed — contains M0–M6 code, not just M3).
- **Latest commit:** `04c2652` — "Implement + verify PR-4/PR-5 detection acceptance gates" (the
  `check_gates()` / `weapon_fn_rate()` eval-gate work + 5 tests, now committed and pushed).
- **Working tree:** clean apart from this dashboard refresh (STATUS/ROADMAP/DECISIONS/CLAUDE/README docs).
- **Recommendation:** rename or merge the branch. Suggested: merge back to `main` since the branch has no
  M3-unique content; new milestone work should be short-lived topic branches.
