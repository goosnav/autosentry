# CLAUDE.md — AutoSentry AI-Dev Constitution

This file is the working agreement for any AI agent (or human) developing AutoSentry. Read it fully before
writing code. `AGENTS.md` points here; this is the single source of truth.

AutoSentry is a **safety-relevant cyber-physical security system**. Reliability is the product. We develop
against the **NASA V-Model**: need → requirement → design → implementation → verification. Nothing ships
unverified.

---

## 0. The five pillars (hard constraints — never violate)

These are not guidelines. They override convenience, cleverness, and even feature requests.

1. **Local-first / fail-operational.** No cloud service may sit in the critical detection→alarm path. Power
   loss and network loss must degrade *gracefully and loudly*, never silently. Every long-running component
   has a watchdog.
2. **Detect, alert, de-escalate — never autonomous harm.** AutoSentry warns and talks. It must never be wired
   to take physical action against a person (no locks-as-traps, no projectiles, no shocks, no "active
   countermeasures"). Code or PRs that add such capability are rejected. (Requirement **SE-1**.)
3. **False positives are a product-killing bug.** Treat a false alarm as a Sev-high defect. The two-tier
   detector + state machine exist to prevent crying wolf. Never weaken confirmation logic to "catch more"
   without an eval showing false-positive rate holds. (Requirements **PR-4**, **FR-5**.)
4. **Privacy and law by design.** Processing stays on-device. Recording, retention, and consent are governed
   by [docs/SAFETY_ETHICS_LEGAL.md](docs/SAFETY_ETHICS_LEGAL.md). Do not add data exfiltration, third-party
   analytics, or telemetry without an explicit decision recorded in `docs/DECISIONS.md`.
5. **The system defends itself.** The radio link is authenticated and replay-protected. A node going silent
   is itself an alarm. Never add an unauthenticated control path or disable HMAC/heartbeat checks for
   convenience. (Requirements **SR-1**, **SR-2**.)

When a request conflicts with a pillar, stop and surface the conflict rather than quietly complying.

---

## 1. What we're building (one paragraph)

Cameras feed a Jetson Orin hub. A fast YOLO detector (stage-1) runs every frame and tracks people/weapons; on
a suspicious trigger a vision-language model (stage-2) produces a structured threat assessment. A state
machine converts that into a stable threat level. On a confirmed threat the hub fires a local siren/strobe,
broadcasts a **signed LoRa** trigger to battery-backed ESP32 alarm nodes around the property, engages a
vision-aware voice agent (STT→LLM→TTS) to de-escalate, and notifies the owner. Everything runs offline.

## 2. Repo map (where things live)

```
docs/        engineering baseline — READ BEFORE CODING (see §3)
hub/         Jetson Python package `autosentry`
  capture/     camera ingest (UVC/CSI/RTSP)            [ICD-1]
  detection/   YOLO stage-1 + ByteTrack                [FR-3]
  reasoning/   VLM stage-2 structured assessment       [FR-4]
  state/       threat state machine                    [FR-5]
  alarm/       local siren/strobe orchestration        [FR-6]
  comms/       LoRa gateway (serial) + mesh protocol   [ICD-2/3, FR-7..10]
  voice/       STT → LLM → TTS de-escalation           [FR-11/12]
  notify/      owner push (non-critical path)          [FR-13]
  dashboard/   local operator web UI (non-critical)    [FR-17]
  contracts.py typed data models shared across modules [ICD-7]
  config.py    pydantic settings + config.yaml
  app.py       supervised main loop
firmware/alarm_node/   ESP32 + LoRa (PlatformIO); also the hub's USB radio gateway
hardware/    BOM, wiring, enclosures
scripts/     provisioning, model download, flashing, bench_lora.py
deploy/      systemd units + watchdog
```

## 3. Read order for a new task

1. The requirement(s) you're touching in [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — find the FR/PR/etc ID.
2. The interface(s) you cross in [docs/INTERFACES.md](docs/INTERFACES.md) — ICD-1..7.
3. The subsystem design doc (e.g. [docs/COMMS_PROTOCOL.md](docs/COMMS_PROTOCOL.md)).
4. The verification activity for that requirement in
   [docs/VERIFICATION_AND_VALIDATION.md](docs/VERIFICATION_AND_VALIDATION.md).

If a task has no requirement, it doesn't get built until one exists. Propose the requirement first.

## 4. Definition of Done (every change)

A change is done only when **all** hold:
- [ ] It traces to a numbered requirement (cite the ID in the PR/commit).
- [ ] Crossed interfaces match the ICD; if the ICD changed, the ICD doc changed in the same PR.
- [ ] Its verification activity exists and passes (`pytest`, `pio test`, eval harness, or a documented
      demonstration). A requirement's row in the traceability matrix is updated.
- [ ] No pillar (§0) is violated.
- [ ] Failure modes are handled per [docs/FMEA.md](docs/FMEA.md) — what happens when this thing breaks?
- [ ] Lint/format pass (`ruff`, `ruff format`; `mypy` for typed modules).

## 5. Coding conventions

**Hub (Python 3.10+):**
- Typed throughout. Shared data crosses module boundaries only as the dataclasses/pydantic models in
  `hub/autosentry/contracts.py` (ICD-7) — never loose dicts.
- Modules are independently testable: each subsystem exposes a small interface and can run against a fake/
  recorded input. The critical path must not depend on network or cloud.
- Config via `config.py` (pydantic-settings) + `config.yaml`. No magic constants in logic; thresholds live in
  config so sensitivity is tunable without code changes.
- Logging is structured; every alarm-relevant decision is logged with enough context to audit later (FR-15).
- Long-running loops are cancellable and supervised; add timeouts to every model call (VLM/LLM/STT/TTS).

**Firmware (C++/Arduino, PlatformIO):**
- Non-blocking main loop; no `delay()` in the alarm path. Use timers for heartbeats.
- Fail safe: if the node loses the hub heartbeat for the configured window, it escalates to local alert — it
  does **not** go quiet.
- Every received packet is authenticated (HMAC) and counter-checked before action (SR-1). Reject and log
  otherwise.

**General:** small modules, clear names, comments only for non-obvious *why*. No speculative abstraction —
build for the current milestone, not imagined ones.

## 6. How to run & verify each subsystem

```bash
# First-time setup: fetch the local AI models (FR-18). Idempotent; also runs automatically
# on first `autosentry.app` boot when models.auto_download is on. Needs Ollama running.
python scripts/download_models.py             # YOLO + VLM + voice STT/LLM/TTS into models/

# Unit / component (L4)
cd hub && pytest                              # state machine, contracts, HMAC vectors, codecs
cd firmware/alarm_node && pio test -e native  # node firmware units (host; see test/README.md)
python scripts/gen_wire_vectors.py            # regen golden LoRa/serial vectors (on ICD-2/3 change)

# Provisioning (per-deployment secret + flashing) — docs/PRODUCTION_PROVISIONING.md
python scripts/provision.py new-key           # mint a per-property mesh key (SR-3)
scripts/provision_node.sh --env lilygo_t3s3 --addr 1 --key "$KEY"   # flash an alarm node

# Subsystem & system (L3/L2)
python -m autosentry.app --source 0           # live webcam (auto-provisions models if missing)
python -m autosentry.app --source clip.mp4    # recorded scenario
python scripts/eval_detection.py --set bench/ # detection precision/recall (PR-4/PR-5)
python scripts/bench_lora.py --port /dev/ttyUSB0   # hub<->node loopback (PR-6/PR-7)

# Validation (L1) — scripted field drills OS-1..8, see docs/TESTING.md
```

## 7. Milestones

M0 scaffold/docs → M1 vision core → M2 reasoning+local alarm → M3 LoRa mesh → M4 power/reliability →
M5 voice agent → M6 multi-cam/notify/dashboard. **M0–M6 are implemented in code; v1 acceptance is the
remaining verification work.** Live status (counts, full RTM mirror, v1 exit punch list) is in
[docs/STATUS.md](docs/STATUS.md); the milestone map + verification deliverables per milestone are in
[docs/ROADMAP.md](docs/ROADMAP.md). Do not skip ahead; each milestone de-risks the next.

## 8. When in doubt

- Conflicts with a pillar → surface it, don't silently comply.
- Missing requirement → propose it in `docs/REQUIREMENTS.md` before coding.
- Interface ambiguity → resolve it in `docs/INTERFACES.md` first; the ICD is the contract.
- A trade-off between approaches → record it in `docs/DECISIONS.md` (a short trade study), then proceed.
