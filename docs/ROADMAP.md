# ROADMAP — Milestones M0–M6

**Parent:** [REQUIREMENTS.md](REQUIREMENTS.md), [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md).

Each milestone produces **left-arm artifacts** (design/code) **and** the **right-arm verification** that
closes its requirements. A milestone **exits** only when its RTM rows are ☑ and its High-band risks are
reduced. Milestones are ordered to **de-risk** the next (lowest-TRL items get early spikes).

---

## M0 — Scaffold & baseline  *(current)*
**Goal:** a repository a contributor understands cold, with the full engineering baseline.
- Repo structure; all `docs/` (CONOPS, REQUIREMENTS, ARCHITECTURE, INTERFACES, V&V, RISK, FMEA, DECISIONS +
  subsystem docs); `CLAUDE.md`/`AGENTS.md`.
- `hub/` package with typed contracts (ICD-7) and module stubs; `firmware/alarm_node/` skeleton; config
  system; CI lint/test; `deploy/` unit; `hardware/BOM.csv`; `scripts/` placeholders.
**Verifies:** IR-4 (contracts scaffolded), SE-1 (architectural inspection).
**Exit:** structure matches ARCHITECTURE; docs internally consistent; `pytest`/lint green on the skeleton.

## M1 — Vision core
**Goal:** see and track on-target.
- `capture/` (webcam now; auto-detect/hotplug), `detection/` (YOLO+ByteTrack via TensorRT), `state/` machine,
  eval harness, night/IR samples.
**Verifies:** FR-1, FR-2, FR-3, FR-5, PR-1, ER-2 (and FR-5 unit tests).
**Risks burned:** R4 (thermal on-target), R12 baseline, R2 baseline eval.
**Exit:** ≥15 FPS @1080p on Orin; state machine unit tests pass; detection precision/recall baselined.

## M2 — Reasoning + local alarm
**Goal:** confirm threats and sound the local alarm, with the anti-false-positive gate in place.
- `reasoning/` (VLM stage-2, schema-validated, timeout/fallback), `alarm/` (real siren+strobe), event log
  (FR-15), bias eval (SE-3), shadow mode.
**Verifies:** FR-4, FR-6, FR-15, PR-2, PR-3(local), PR-4, PR-5, SE-3, SE-4, SR-4.
**Risks burned:** **R1 (false positives), R3 (bias)** — gates before any arming.
**Exit:** benign suite (OS-2) ≈0 false alarms; FN-rate ≤5%; bias slices within tolerance.

## M3 — LoRa mesh
**Goal:** every node sounds, securely, network-independent.
- `comms/` (sign/verify, retries, heartbeats, node table), node firmware (ALARM/ACK/HEARTBEAT/STATUS),
  `scripts/bench_lora.py`.
**Verifies:** FR-7, FR-8, FR-9, IR-2, IR-3, SR-1, SR-2, PR-3(mesh), PR-6, PR-7, RR-5.
**Risks burned:** R5 (jam), R6 (spoof/replay), R10 (independence).
**Exit:** bench ALARM fires node + ACK; HMAC/replay vectors pass; node-kill → offline ≤30 s; range ≥200 m.

## M4 — Power & reliability
**Goal:** survive power cuts and crashes; never fail silent.
- Battery/UPS integration, hub mains-sense, node power-path + INA219 + mains-loss reporting, HW+SW watchdog,
  degraded-mode behaviors, TEST mode + per-zone arm + panic.
**Verifies:** FR-10, FR-14, RR-1, RR-2, RR-3, RR-4, ER-1.
**Risks burned:** R7 (power cut), R10 (supervision).
**Exit:** OS-4 drill passes; watchdog restarts on crash+hang; battery runtimes met.

## M5 — Voice agent
**Goal:** intelligent, vision-aware de-escalation that never gates the alarm.
- `voice/` STT→LLM→TTS with per-turn vision-context injection, persona + guardrails + content filter +
  logging.
**Verifies:** FR-11, FR-12, PR-8, SE-1(re-inspect), SE-2.
**Risks burned:** R9 (harmful utterance).
**Exit:** replies change with vision context; guardrail adversarial tests blocked+logged; alarm fires with
voice killed; first-audio ≤2 s.

## M6 — Multi-cam + notifications + dashboard
**Goal:** scale to a real site and close the owner loop.
- `notify/` (owner push, offline queue/flush), multi-camera/zones, local web dashboard (`dashboard/`,
  opt-in, off the critical path), authority-contact recommendation with human confirm.
**Verifies:** FR-13, FR-16, FR-17, SE-5; revisits PR-4 multi-zone.
**Exit:** OS-5 + OS-7 drills pass; SE-5 human-confirm demonstrated.

---

## v1 acceptance
All RTM rows ☑ and all OS-1..8 validation drills pass — culminating in the end-to-end **OS-3 armed-approach**
drill with the network then mains pulled, proving local siren + all LoRa nodes + voice + notification all fire
and the system stays operational ([VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) §5).

## Post-v1 (recorded, not committed)
Multi-hop mesh + multi-hub for large sites (R10/ADR-10), professional-monitoring integration, richer
dashboard/app, TTS realism upgrade (XTTS-v2, ADR-6). Each must re-pass the five pillars before adoption.
