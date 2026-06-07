# VERIFICATION & VALIDATION — V&V Plan + Traceability

**V-Model:** the entire **right arm**. **Verification** = "did we build the system right?" (against the SRD).
**Validation** = "did we build the right system?" (against the ConOps). Methods: **I**/**A**/**D**/**T**.

A requirement is **DONE only when its V&V activity passes** and its RTM row is green.

---

## 0. v1 exit punch list (pointer to the work)

The full ordered list of v1-acceptance work lives in:

- [docs/STATUS.md §4](STATUS.md) — the punch list, in the order it unblocks the most downstream items
  (labeled benchmark first, then on-target vision, LoRa, power, voice, then multi-cam / notify / dashboard
  demos, then the 8 OS drills).
- [docs/ROADMAP.md "v1 acceptance roadmap"](ROADMAP.md) — same ordering with milestone context.
- [docs/CONOPS.md §7](CONOPS.md) — OS-1..8 definitions; full runbooks in §6.1 below.

This document is the **V-Method record**: the right-arm V&V activities per requirement (§5 RTM), the TPMs
(§3) and how to measure them (§3.1), the benchmark dataset SOW (§4), and the drill runbooks (§6.1).
When a row's status flips in the RTM, the TPM log (§3.1) and [docs/STATUS.md](STATUS.md) are updated in
the same change.

**Acceptance for v1** = every RTM row ☑ **and** every OS drill passes (especially the OS-3
network-then-mains-pulled drill).

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

### 3.1 TPM measurement log

The "Current" column above starts at "—" because every TPM is on-target only. As measurements are
recorded, append a row here and flip the row in the table above. **A TPM is "verified" only when this
log has a row whose value meets the threshold.** A PR that records a measurement cites the commit-sha
and the hardware profile.

| TPM | Date | Value | Hardware | Commit-SHA | Conditions | Notes |
|-----|------|-------|----------|------------|------------|-------|
| _example_ | 2026-06-07 | 18.4 FPS | Jetson Orin NX 16GB, JetPack 6.x, FP16 | _short-sha_ | 1080p, 25 °C ambient, sustained 5 min | First on-target measurement; within goal headroom |

(empty — first on-target measurement pending)

## 4. Benchmark dataset SOW (the PR-4 / PR-5 / SE-3 gate)

**Purpose.** The single source of truth for "is the detector safe to ship?" This dataset gates **PR-4**
(false-positive rate), **PR-5** (weapon-present false-negative ≤5%), and **SE-3** (demographic bias
slices within tolerance). It is the largest open blocker for v1 (see [STATUS.md §4 Block 0](STATUS.md)
and [ROADMAP.md "v1 acceptance roadmap"](ROADMAP.md)). `scripts/eval_detection.py` is the gate runner;
its `check_gates()` / `weapon_fn_rate()` logic is already implemented and unit-tested — the dataset is
what's missing.

**Composition.** Labeled images spanning:
- **Weapons** (per FR-3): at minimum `handgun`, `rifle`, `knife` (extensible).
- **Benign subjects:** people without weapons in typical residential / small-business settings.
- **Hard negatives** (the typical stage-1 false-positive triggers): mobile phones, umbrellas, power
  tools, sports gear (hockey sticks, baseball bats, golf clubs), gardening tools, brooms, pipes, large
  pets, mirrors / reflections.

**Stratification (R12 — domain gap, ER-2 — night, SE-3 — bias).** Every stratum must have a
documented minimum count; the gate fails on imbalance, not just on overall metric.
- **Condition:** day / night-or-IR, and within each: close / medium / far distance, none / partial /
  heavy occlusion, low / medium / high motion blur.
- **Demographic:** balanced across the slices the policy defines (age, gender presentation, skin tone
  — to be agreed in writing before dataset build; the slices become part of the gate).

**Size target.** At least N total labeled frames, with the minimum per stratum sized so the
stratified metrics are statistically meaningful (sample size for the FN-rate confidence interval to be
useful at the 5% threshold). **TBD** by the curation owner; the exact number goes here once decided,
and the gate's tolerance bands are then set against it.

**Sources (in order of preference).** Open datasets with permissive licenses first; licensed datasets
with documented rights second; collected/augmented site data third. Every source must have a documented
license and attribution in the dataset README. Do not commit media to the repo — use `bench/` (git-
ignored media) and a tracked `bench/README.md` + `bench/manifest.{json,csv}` (labels + splits).

**Augmentation.** Standard augmentations for the conditions above (lighting, blur, crop, weather) to
grow the set without inventing new content. Augmentations are labeled with the source they augment.

**Curation owner.** _TBD_ (one named individual; the dataset is too important to be community-curated
in the abstract).

**How the gate consumes it.**
```
python scripts/eval_detection.py --set bench/   # PR-4/PR-5/SE-3 gate
```
The script loads `bench/`, runs the live Detector, calls `check_gates()` (PR-5 weapon-only FN ≤ 5%;
PR-4 benign major-alarm count = 0), and exits non-zero on failure. CI runs the gate on the labeled set
on a schedule and on PR-conditional regressions; `check_gates()` itself is unit-tested in
`hub/tests/test_eval_detection.py`.

**Regression policy.** A baseline is captured on the first green run (stored in `bench/baseline.json`).
CI fails if a future run regresses beyond the agreed tolerance (FN-rate +2pp absolute, FP count +0
absolute) vs the baseline.

**Closing the open ADR.** This SOW is the implementation of the open
[ADR-9](../DECISIONS.md) decision; close ADR-9 when the dataset lands and the gate runs green.

## 5. Requirements Traceability Matrix (RTM)

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
| PR-4 | A/T | L2 | Benign suite ≈0 false alarms; 30-day duty-cycle analysis ≤1. | M2 | ◐ acceptance gate implemented + pinned: `check_gates()` fails the build on any benign-suite major-alarm trigger; `test_eval_detection` covers the zero-trigger pass and the >0-trigger fail ☑; on-benchmark run + 30-day duty-cycle analysis pending the labeled benign suite |
| PR-5 | T | L2 | Weapon-present benchmark false-negative ≤5%. | M2 | ◐ metric + gate implemented + pinned: `weapon_fn_rate()` computes the weapon-only FN-rate (person misses excluded) and `check_gates()` fails the build above the 5% threshold; `test_eval_detection` covers weapon-vs-person FN accounting + pass/fail at threshold ☑; on-benchmark measurement pending the labeled weapon-present set |
| PR-6 | T | L2 | Range walk-test through structure ≥200 m. | M3 | ☐ deferred to on-hardware range walk-test |
| PR-7 | T | L2 | Time from node-kill to hub-offline-flag ≤30 s. | M3 | ◐ offline-detection logic verified (`test_node_goes_offline_after_missed_heartbeats`, deadline = hb_interval×hb_miss_max ≤30 s); wall-clock on-target pending |
| PR-8 | T | L2 | Measure subject-stop→reply-audio ≤2 s. | M5 | ☐ |
| IR-1..4 | I/T | L3 | Inspect each seam against ICD-1..7; codec round-trip tests. | M0–M3 | ◐ IR-2 (ICD-2 transport) COBS/CRC round-trip + corruption ☑; IR-3 (ICD-3 air) payload codec round-trips ☑; IR-4 scaffolded |
| RR-1 | T | L2 | Crash/hang injection → auto-restart. | M4 | ◐ `test_watchdog` ping cadence + stalled-loop-stops-pinging ☑; `deploy/autosentry.service` Type=notify w/ WatchdogSec; on-target systemd kill/restart demo pending |
| RR-2 | A | L2 | Availability computed from MTBF/MTTR ≥99.9%. | M4 | ☐ deferred to on-target MTBF/MTTR analysis |
| RR-3 | T | L2 | Battery-runtime measurement hub/node. | M4 | ☐ deferred to hardware battery-runtime bench |
| RR-4 | T | L3 | Inject camera/VLM/mesh failures → graceful DEGRADED. | M4 | ◐ `test_reliability` detector-fault-degrades-no-crash, assessor-fault-never-manufactures-ALARM ☑; mesh-broadcast fault caught in `_actuate` (local siren unaffected) ☑; on-target fault injection pending |
| RR-5 | A/T | L3 | Kill one node → mesh + hub unaffected. | M3/M4 | ◐ per-source node-health isolation unit-tested (one node offline doesn't perturb others); multi-node bench pending |
| SR-1 | T | L4 | HMAC test vectors; replayed counter rejected. | M3 | ◐ forged-HMAC drop + replayed-counter reject unit-tested (`test_comms_protocol`, `test_mesh_gateway`); **frozen cross-implementation golden vector** (`firmware/alarm_node/test/wire_vectors.json`, generated from the authoritative codec by `scripts/gen_wire_vectors.py`) pinned on the hub side by `test_wire_vectors` (exact frame bytes + HMAC tag, independent of the encoder) ☑; node-side `pio test` against the same vector is specified in `firmware/alarm_node/test/README.md`, pending a host that runs PlatformIO |
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

## 6. Validation drills (L1, against the ConOps OS-1..8)

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

### 6.1 OS drill runbooks

Each drill is a 1-page runbook: setup → safety brief (where relevant) → procedure → expected → pass/fail →
record. **Run on-target with real hardware. Record the result in this section (append a row) and update
the RTM in the same change.** Use inert props where applicable; brief all participants; run on private
property. AutoSentry is a software/hardware test, not a tactical drill.

**Record template (one row per drill run):**

```
| OS-x | YYYY-MM-DD | pass/fail | commit-sha | hardware profile | operator | notes |
```

---

**OS-1 — Nominal monitoring.** *Exercises PR-4 (long-run FP rate), RR-2 (availability).*
- **Setup:** hub + ≥1 camera + ≥1 node, armed, all zones empty, stable lighting, no personnel in frame.
- **Procedure:** run for a documented duration (suggest 24 h as the minimum for FP-rate confidence).
- **Expected:** 0 false alarms; NORMAL/WATCH levels only; stable CPU/memory; event log + keyframe count
  match expectations; no DEGRADED entries.
- **Pass:** `len(ALARM-events) == 0`, no mesh triggers, no mesh retries above the steady-state baseline,
  no DEGRADED entries.

**OS-2 — Benign visitor.** *Exercises PR-4 (the "don't cry wolf" case), FR-5 (state machine).*
- **Setup:** armed, single zone, normal lighting. Recruit a volunteer (mail-carrier role, hands visible,
  no objects held).
- **Procedure:** volunteer approaches the entry, pauses, leaves. Repeat with variations (package in
  hand, second person, pet on leash, vehicle).
- **Expected:** state may go to WATCH or SUSPECT, **never** THREAT or ALARM. No mesh broadcast. No
  owner push.
- **Pass:** no major alarm; no mesh trigger; no push. WATCH/SUSPECT entries logged with reason.

**OS-3 — Armed approach.** *Exercises FR-3..9, FR-11..15, PR-1..3, PR-7 — the v1 acceptance drill.*
- **Safety brief:** use an obviously-inert prop (orange training gun, clearly fake). Brief the volunteer
  on the script. Have a designated "stop" signal. No real weapons on-site.
- **Setup:** armed, ≥1 camera at the entry, ≥1 node, voice enabled (if exercising M5), notify
  configured.
- **Procedure:** volunteer approaches from out-of-zone, presents the prop at the trigger distance,
  advances to the entry. Time from first presenting the prop to ALARM entry.
- **Expected:** stage-1 trigger within TPM-1 budget; stage-2 confirms armed; state machine reaches
  ALARM within TPM-2; local siren+strobe fires within TPM-3 (local); mesh broadcast within TPM-3
  (mesh) and nodes sound; voice engages (if enabled); owner push fires (if online; else queued); full
  event log + keyframe persisted.
- **Pass:** all the above; the OS-3 acceptance is the **end-to-end** version: with WAN pulled first
  (OS-5 conditions), then hub mains pulled (OS-4 conditions), the chain still fires.

**OS-4 — Mains cut.** *Exercises RR-3, FR-10, R7.*
- **Setup:** armed, hub on battery/UPS, ≥1 node on battery (mains removed from the node too).
- **Procedure:** pull mains from the node (or both); observe hub. Repeat with hub mains cut.
- **Expected:** hub + nodes continue on battery; node `STATUS.on_battery` true at hub within
  heartbeats; no DEGRADED beyond a single "mains_lost" entry; alarm chain intact.
- **Pass:** chain survives ≥ the documented runtime; `on_battery` reported; OS-3 still works on battery.

**OS-5 — Internet cut.** *Exercises STK-2, FR-13.*
- **Setup:** armed, all systems nominal, notify endpoint configured.
- **Procedure:** pull WAN; trigger a benign ALARM (e.g. via TEST + manual or a forced event); restore
  WAN.
- **Expected:** local chain (siren + mesh + voice) fires regardless; owner push **queues** while offline
  and **flushes** on reconnect; the notifier does not retry forever and does not drop the event.
- **Pass:** local chain OK; outbox length grows offline; drains on reconnect; oldest-first flush order.

**OS-6 — Radio jam / node tamper.** *Exercises SR-2, FR-9, PR-7, RR-5, R5/R6.*
- **Setup:** armed, hub + ≥2 nodes. Two scenarios: (a) physically power down / unplug one node; (b)
  apply a sub-GHz jammer (or a Faraday shield) to one node.
- **Procedure:** execute the scenario; wait one heartbeat window × `hb_miss_max`; observe hub.
- **Expected:** hub flags the affected node **offline/tamper** within TPM-7 (≤30 s). The still-online
  node and the local siren continue unaffected (RR-5). An **isolated but powered node** fails safe
  (sounds its own siren per its policy) — **never silent** (pillar 1).
- **Pass:** offline alert within TPM-7; mesh + hub unaffected; isolated node fails safe.

**OS-7 — Multi-zone.** *Exercises FR-16, FR-5 (per-zone attribution).*
- **Setup:** armed, ≥2 cameras/zones; benign activity scripted in zone A, an armed approach scripted in
  zone B.
- **Procedure:** run both scripts in parallel.
- **Expected:** zone A: WATCH/SUSPECT only. Zone B: ALARM, attributed to zone B. No cross-talk in
  the event log; mesh broadcast per zone attribution; voice engages in zone B only.
- **Pass:** correct attribution, independent per-zone state machines.

**OS-8 — Test + panic.** *Exercises FR-14, OS-8 itself.*
- **Setup:** armed, all systems nominal, voice + notify configured.
- **Procedure:** (a) enter test mode, observe; (b) hit manual panic from the dashboard.
- **Expected:**
  - Test mode: sirens/mesh pulse without latching; a "test" event is logged but not an `ALARM`-level
    incident; nothing is pushed to the owner as an alarm.
  - Panic: ALARM **immediately** from any state (armed or disarmed); full chain fires (siren, mesh,
    voice, push); disarmed zone with panic still sounds (owner override).
- **Pass:** test no-latch; panic forces ALARM from each mode.

---

## 7. CI gates
- PR: `ruff`, `ruff format --check`, `mypy` (typed modules), `pytest`, `pio test` (firmware) must pass.
- Detection eval (PR-4/PR-5) runs on the benchmark set and must not regress beyond tolerance.
