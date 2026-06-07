# ROADMAP — Milestones M0–M6

**Parent:** [REQUIREMENTS.md](REQUIREMENTS.md), [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md).
**Live status:** [STATUS.md](STATUS.md) (counts, full RTM mirror, v1 exit punch list).

Each milestone produces **left-arm artifacts** (design/code) **and** the **right-arm verification** that
closes its requirements. A milestone **exits** only when its RTM rows are ☑ and its High-band risks are
reduced. Milestones are ordered to **de-risk** the next (lowest-TRL items get early spikes).

**M0–M6 implemented in code** (see [STATUS.md](STATUS.md) for the live counts); **v1 acceptance** is
closing the ☐ RTM rows on real hardware + the labeled benchmark. The "v1 acceptance roadmap" at the end
of this document orders that work.

---

## M0 — Scaffold & baseline

**Goal:** a repository a contributor understands cold, with the full engineering baseline.

### Code deliverables (☑)
- Repo structure; all `docs/` (CONOPS, REQUIREMENTS, ARCHITECTURE, INTERFACES, V&V, RISK, FMEA, DECISIONS +
  subsystem docs); `CLAUDE.md`/`AGENTS.md`.
- `hub/` package with typed contracts (ICD-7) and module stubs; `firmware/alarm_node/` skeleton; config
  system; CI lint/test; `deploy/` unit; `hardware/BOM.csv`; `scripts/` placeholders.

### Verification deliverables
- ☑ IR-4 (contracts scaffolded) — codec/version tests in `hub/tests/`.
- ◐ SE-1 (architectural, **re-inspect at every milestone exit**): no interface to a physical-force mechanism.

**Exit:** structure matches ARCHITECTURE; docs internally consistent; `pytest`/lint green on the skeleton.

---

## M1 — Vision core

**Goal:** see and track on-target.

### Code deliverables (☑)
- `capture/` (webcam now; auto-detect/hotplug), `detection/` (YOLO+ByteTrack via TensorRT, ONNX-RT fallback),
  `state/` machine, `eval_detection.py` (metrics core + PR-4/PR-5 gate, in-progress on branch).
- `test_state_machine`, `test_tracking`, `test_detector`, `test_eval_detection`.

### Verification deliverables (still open)
- ◐ FR-1 — live hotplug demo on Jetson + UVC webcam.
- ◐ FR-2 — on-target watchdog restart demo (Jetson + simulated camera-loss).
- ◐ FR-3 — precision/recall on the **labeled benchmark** (not committed; see [STATUS.md §4 Block 0](STATUS.md)).
- ☑ FR-5 — state machine unit tests.
- ☐ PR-1 — FPS ≥15 @1080p on Orin NX (**on-Jetson bench only**).
- ☐ ER-2 — night / IR detection demo (IR-capable camera + illuminator).

**Risks burned:** R4 (thermal on-target), R12 (baseline), R2 (baseline eval) — close as the on-target work lands.

**Exit:** ≥15 FPS @1080p on Orin; state machine unit tests pass; detection P/R baselined on the labeled set.

---

## M2 — Reasoning + local alarm

**Goal:** confirm threats and sound the local alarm, with the anti-false-positive gate in place.

### Code deliverables (☑)
- `reasoning/` (VLM stage-2, schema-validated, timeout + retry + fallback to stage-1 conservative call).
- `alarm/` (controller + GPIO sink).
- Event log (FR-15) with keyframe persistence; encode failure degrades to no-keyframe without breaking the
  pipeline (pillar 1).

### Verification deliverables (still open)
- ☑ FR-4 — `test_assessor` (parse/validate/retry/fallback, no zone/ts spoof).
- ◐ FR-6 — real GPIO/audio siren bench (current tests use a fake sink).
- ◐ FR-15 — on-target image-quality review of the captured keyframes.
- ◐ PR-2 — wall-clock first-qualifying-frame→confirm latency.
- ◐ PR-4 — `check_gates()` benign-major-alarm gate verified; benign-suite run pending the **labeled benchmark**.
- ◐ PR-5 — `weapon_fn_rate()` + `check_gates()` (fail >5%) verified; on-benchmark FN measurement pending the **labeled benchmark**.
- ☐ SE-3 — bias slices within tolerance — **same labeled benchmark is the gate**.
- ◐ SE-4 — retention-window + consent-signage policy controls land (SAFETY_ETHICS_LEGAL.md).
- ☑ SR-4 — attack-surface analysis (SECURITY.md §6.2) + `test_security` regression.

**Risks burned:** **R1 (false positives), R3 (bias)** — these are the gates before any site is armed. They close
on the on-target work, not on more code.

**Exit:** benign suite (OS-2) ≈0 false alarms; FN-rate ≤5%; bias slices within tolerance.

---

## M3 — LoRa mesh

**Goal:** every node sounds, securely, network-independent.

### Code deliverables (☑)
- `comms/` (`protocol.py` HMAC-SHA256 trunc + monotonic counter; `payloads.py` ICD-3 §4; `transport.py` ICD-2
  COBS/CRC; `gateway.py` signed broadcast w/ shared-counter repeats, ACK-gated retry, inbound auth + replay
  reject, node-health table, heartbeat cadence, offline detection).
- `scripts/bench_lora.py` — ping/echo RTT harness.
- `firmware/alarm_node/` — parse/verify, siren GPIO, heartbeat + STATUS payloads aligned to `payloads.py`,
  hub-timeout fail-safe, ReplayWindow mirrors `protocol.py`.
- `Hub._actuate` wires ALARM→mesh broadcast, gated on `comms.enabled`.

### Verification deliverables (still open)
- ◐ FR-7 — on-target ALARM → real node siren fires + ACK.
- ◐ FR-8 — on-target node ACKs + offline detection (kill node).
- ◐ FR-9 — on-target heartbeat-loss → hub alert; isolated node → local alert.
- ◐ IR-2/IR-3 — on-hardware conformance (real camera + real gateway).
- ◐ SR-1 — physical bench (vectors are unit-tested).
- ◐ SR-2 — physical jam / node tamper drill.
- ◐ PR-3 (mesh) — wall-clock confirm→mesh ≤3 s.
- ☐ PR-6 — range walk-test ≥200 m through a typical residential structure.
- ◐ PR-7 — wall-clock node-kill → hub-offline ≤30 s.
- ◐ RR-5 — multi-node independence on the bench.

**Risks burned:** R5 (jam), R6 (spoof/replay), R10 (independence).

**Exit:** bench ALARM fires node + ACK; HMAC/replay vectors pass (and bench confirms); node-kill → offline ≤30 s;
range ≥200 m.

---

## M4 — Power & reliability

**Goal:** survive power cuts and crashes; never fail silent.

### Code deliverables (☑)
- `watchdog.py` — `sd_notify` READY=1 / WATCHDOG=1, throttled.
- Per-zone arming, test/maintenance mode, manual panic (FR-14); arming gates physical response only (a
  disarmed zone still reaches ALARM in the log with `suppressed_disarmed`).
- `Hub.degraded` map; `_degrade()`/`_recover()` wrap every long-running call; a stage-2 fault yields no
  assessment so the machine cannot reach ALARM (degrading never manufactures a false alarm, pillar 3).
  Mesh faults are caught **after** the local siren fires (pillar 1).
- `Hub.power_alerts()` + `health()` surface offline + on-battery nodes (FR-10).
- `deploy/autosentry.service` — `Type=notify` + `Restart=always` + `WatchdogSec`.

### Verification deliverables (still open)
- ◐ FR-10 — on-target INA219 / mains-sense bench (STATUS→on_battery wired; real hardware only).
- ◐ FR-14 — on-target demo of panic / test-mode / per-zone arm.
- ◐ RR-1 — on-target systemd kill/restart + on-target hang (stops petting).
- ☐ RR-2 — MTBF/MTTR analysis ≥99.9% (on-target + assumed field data).
- ☐ RR-3 — battery runtime — hub ≥4 h, node ≥24 h standby + ≥10 min siren.
- ◐ RR-4 — on-target fault injection (camera, VLM, gateway, notify) → graceful DEGRADED.
- ☐ ER-1 — enclosure IP65 + temp spec inspection.

**Risks burned:** R7 (power cut), R10 (supervision).

**Exit:** OS-4 drill passes; watchdog restarts on crash+hang; battery runtimes met.

---

## M5 — Voice agent

**Goal:** intelligent, vision-aware de-escalation that never gates the alarm.

### Code deliverables (☑)
- `voice/` STT (faster-whisper) → LLM (local via Ollama) → TTS (Piper).
- Per-turn vision-context injection (`ThreatAssessment` reused from stage-2 — one assessment, two consumers).
- Persona + content-filter guardrails; every blocked generation kept raw in `agent.blocked` + logged (SE-2).
- Voice engages only **after** the siren latches in `Hub._actuate`; hung voice degrades to `degraded["voice"]`
  but never blocks the alarm (FR-12, pillar 1).

### Verification deliverables (still open)
- ◐ FR-11 — on-target live STT→LLM→TTS demo (replies change with vision context).
- ◐ FR-12 — on-target concurrent alarm+voice demo (kill voice → alarm still fires).
- ☐ PR-8 — first-audio ≤2 s wall-clock.
- ◐ SE-1 — re-inspect: voice has no actuator control beyond the speaker.
- ◐ SE-2 — broader adversarial red-team set (logic ☑).

**Risks burned:** R9 (harmful utterance).

**Exit:** replies change with vision context; guardrail adversarial tests blocked+logged; alarm fires with
voice killed; first-audio ≤2 s.

---

## M6 — Multi-cam + notifications + dashboard

**Goal:** scale to a real site and close the owner loop.

### Code deliverables (☑)
- `notify/` — durable outbox; delivers online, queues offline, flushes oldest-first on reconnect, stops on
  failure without dropping (FR-13).
- Multi-camera/multi-zone with per-zone detectors + state machines; correct per-zone attribution (FR-16).
- `dashboard/` — opt-in, loopback-bound, single-page UI + JSON API; exposes arm/disarm, panic, test mode, and
  SE-5 confirm-authority; off the critical path (FR-17).
- `models.py` + `scripts/download_models.py` — on-device provisioning of stage-1, stage-2, voice STT/LLM/TTS;
  runs at `Hub.run()` boot, never on the hot path (FR-18).
- `AuthorityRecommendation` — human-confirm gated (SE-5); `confirm_authority_contact` is the sole path to
  `confirmed=True`.

### Verification deliverables (still open)
- ◐ FR-13 — live push-provider demo (offline → queued → reconnect → flushed).
- ◐ FR-16 — on-target multi-camera demo (threat in A, benign in B).
- ◐ FR-17 — on-target browser demo of the dashboard.
- ◐ FR-18 — on-target live model fetch (YOLO / Ollama / whisper / piper).
- ◐ SE-5 — live confirm-authority from the dashboard.

**Exit:** OS-5 + OS-7 drills pass; SE-5 human-confirm demonstrated.

---

## v1 acceptance

**All RTM rows ☑ and all OS-1..8 validation drills pass** — culminating in the end-to-end **OS-3 armed-approach**
drill with the network then mains pulled, proving local siren + all LoRa nodes + voice + notification all fire
and the system stays operational ([VERIFICATION_AND_VALIDATION.md §5](VERIFICATION_AND_VALIDATION.md)).

The single largest blocker is the **labeled benchmark dataset** — it gates PR-4, PR-5, and SE-3. The
on-target hardware bench (Jetson + ≥2 nodes + cameras + batteries) gates everything else.

## v1 acceptance roadmap (ordered)

The remaining work, in roughly the order it unblocks the most downstream items:

0. **Labeled benchmark dataset** — source, curate, augment (day/night/distance/occlusion), hard-negative
   mining, demographic strata. Gates PR-4, PR-5, SE-3. See [STATUS.md §4 Block 0](STATUS.md).
1. **On-target vision bench** — PR-1, PR-5, PR-4, SE-3, FR-1, FR-2, FR-3, ER-2.
2. **LoRa bench** — FR-7/8/9, PR-3, PR-6, PR-7, SR-2, RR-5.
3. **Power & reliability bench** — FR-10, FR-14, RR-1, RR-2, RR-3, RR-4, ER-1.
4. **Voice on-target** — FR-11, FR-12, PR-8, SE-2.
5. **Multi-cam / notify / dashboard demos** — FR-13, FR-16, FR-17, FR-18, SE-5.
6. **OS-1..8 drills** — culminating in OS-3 with the network then mains pulled.

The TPM measurement log is in [STATUS.md §4](STATUS.md); PRs that flip a row's status update both docs.

## Post-v1 (recorded, not committed)

Multi-hop mesh + multi-hub for large sites (R10/ADR-10), professional-monitoring integration, richer
dashboard/app, TTS realism upgrade (XTTS-v2, ADR-6). Each must re-pass the five pillars before adoption.
