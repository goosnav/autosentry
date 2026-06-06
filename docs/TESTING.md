# TESTING — How We Test AutoSentry

**Parent:** [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) (the formal V&V plan + RTM). This
doc is the **practical how-to**: commands, fixtures, and the drill procedures. It maps to the four V-levels.

Principle: **a requirement is done when its test passes and its RTM row is ☑.** Don't claim a feature works
without the evidence.

---

## L4 — Unit / component tests
```bash
cd hub && pytest                 # state machine, contracts, codecs, HMAC vectors, reasoning schema
cd firmware/alarm_node && pio test
```
Key suites:
- **state machine (FR-5):** transitions, hysteresis, confirmation window, cooldown, panic, per-zone.
- **contracts (IR-4):** (de)serialization + version checks for ICD-7 types.
- **comms codec + HMAC (SR-1):** fixed-key test vectors; tampered byte ⇒ reject; replayed counter ⇒ reject.
- **reasoning schema (FR-4):** malformed/over-bounds VLM output ⇒ rejected/retried/fallback.
- **detection (FR-3):** known images ⇒ expected classes within IoU; track-ID continuity on a sequence.

## L3 — Subsystem integration tests
```bash
python -m autosentry.app --source tests/fixtures/clip_armed.mp4    # full pipeline on a clip
python scripts/bench_lora.py --port /dev/ttyUSB0                   # hub gateway <-> one node
```
- **capture→detection→reasoning→state:** a clip drives the pipeline to ALARM; assert state timeline.
- **state→alarm (FR-6):** ALARM asserts siren/strobe (GPIO/audio mock or real).
- **state→comms→node (FR-7/8/9):** ALARM → signed broadcast → node siren + ACK; drop heartbeats → offline /
  fail-safe.
- **voice (FR-11/12):** mocked `ThreatAssessment` ⇒ context-appropriate reply; kill voice ⇒ alarm still fires.

## L2 — System verification (on-target, Jetson + real radios)
Measure against the TPMs:
```bash
python scripts/eval_detection.py --set bench/   # PR-4/PR-5 precision/recall, FN-rate, bias slices
python -m autosentry.app --source 0 --measure   # PR-1 FPS, PR-2/PR-3 latencies
```
- PR-1 FPS ≥15; PR-2 confirm ≤2 s; PR-3 local ≤1 s / mesh ≤3 s; PR-6 range ≥200 m (walk-test); PR-7 offline
  ≤30 s; PR-8 voice ≤2 s; RR-3 battery runtimes.

## L1 — Validation drills (field, against ConOps OS-1..8)
Run with real hardware on-site/bench. Each drill: **procedure → expected → record result** in the V&V doc.

| Drill | Procedure | Expected |
|-------|-----------|----------|
| OS-1 Nominal | Arm; empty scene; long run | 0 false alarms; stable resources |
| OS-2 Benign | Person approaches w/o weapon, leaves | No major alarm / mesh trigger (the key FP test) |
| OS-3 Armed | Staged weapon-display approach (use a clearly-fake prop; safety-brief everyone) | ALARM in budget; siren+mesh+voice+notify; full log |
| OS-4 Mains cut | Pull hub + node mains mid-drill | Continue on battery; `on_battery` reported |
| OS-5 Net cut | Disconnect WAN | Local chain works; notify queues+flushes |
| OS-6 Jam/tamper | Unplug/kill a node | Offline alert ≤30 s; isolated node fails safe |
| OS-7 Multi-zone | Threat in A, benign in B | Correct attribution; no cross-talk |
| OS-8 Test+panic | Run TEST mode; hit panic | TEST no-latch; panic forces ALARM |

**Safety for OS-3:** never use a real weapon. Use an obviously-inert prop, brief all participants, and run on
private property — this is a software/hardware test, not a tactical drill.

## Continuous integration
- Every PR: `ruff`, `ruff format --check`, `mypy` (typed modules), `pytest`, `pio test`.
- Detection eval (PR-4/PR-5) gate: FN-rate ≤5%, benign suite no major alarm, no regression beyond tolerance.
- A PR satisfying a requirement updates its **RTM row** + names the evidence.

## Fixtures & data
- `hub/tests/fixtures/` — short clips + labeled frames (armed / unarmed / ambiguous / benign).
- `bench/` — the stratified evaluation set (by condition: day/night, distance, occlusion) — large data is
  git-ignored and fetched via `scripts/`.
