# CODEBASE — Developer's Guide to the AutoSentry Source

**Audience:** an engineer (or agent) about to read, extend, or debug the code. This is the
map and the mental model; the *why* behind decisions lives in the bibles
([ARCHITECTURE.md](ARCHITECTURE.md), [VISION_PIPELINE.md](VISION_PIPELINE.md),
[COMMS_PROTOCOL.md](COMMS_PROTOCOL.md), …) and the *contract* lives in
[INTERFACES.md](INTERFACES.md). Read [CLAUDE.md](../CLAUDE.md) first — its five pillars
override everything here.

---

## 1. The one-paragraph mental model

Cameras feed a **Jetson Orin hub**. Each frame goes through a fixed pipeline:
`capture → detect+track (stage-1 YOLO) → trigger policy → [stage-2 VLM only when triggered]
→ threat state machine → response`. The state machine is the safety-critical brain: it turns
noisy detections into a stable threat level (`NORMAL→WATCH→SUSPECT→THREAT→ALARM`) with
hysteresis and a confirmation window so a single frame can't cry wolf. On `ALARM` the hub
sounds a local siren, broadcasts a **signed LoRa** trigger to battery-backed ESP32 nodes,
engages a vision-aware voice agent, and notifies the owner — every one of those four
responses is independent and **best-effort**, so a failure in any one never blocks the siren.
Everything runs offline.

The whole hub is wired together by one class: **`Hub`** in `hub/autosentry/app.py`.

---

## 2. Repository layout

```
docs/        engineering baseline (requirements, ICDs, designs, V&V, this file)
hub/         the Jetson Python package `autosentry`  ← most of the code
firmware/    ESP32 alarm-node + hub-gateway firmware (PlatformIO, C++)
hardware/    BOM + wiring
scripts/     model download, eval, LoRa bench, wire-vector generator, provisioning
deploy/      systemd unit + watchdog
```

### The hub package (`hub/autosentry/`)

| Module | Responsibility | Key entry points | Reqs |
|--------|----------------|------------------|------|
| `app.py` | **The orchestrator.** Owns one instance of every subsystem, the per-zone pipeline (`step`), the response fan-out (`_actuate`), the run loop + camera threads, operator controls. | `Hub`, `Hub.step`, `Hub.run`, `main` | FR-2/14/16 |
| `config.py` | All tunables as pydantic models loaded from `config.yaml` + env. No magic constants in logic. | `Settings`, `load_settings` | FR-5/16 |
| `contracts.py` | The typed data that crosses module boundaries (ICD-7). **Never pass loose dicts across a seam — use these.** | `Frame`, `Detection`, `Track`, `ThreatAssessment`, `ThreatState`, `MeshMessage`, `NodeStatus`, `VoiceTurn`, `Level`, `MsgType` | ICD-7 |
| `capture/` | Camera ingest (UVC/CSI/RTSP) with auto-reconnect. | `OpenCVCamera`, `list_cameras` | FR-1/2, ICD-1 |
| `detection/` | Stage-1: YOLO backend + IoU/ByteTrack tracker + the stage-1→stage-2 trigger policy. | `Detector`, `IoUTracker`, `TriggerEvaluator` | FR-3 |
| `reasoning/` | Stage-2: VLM threat assessment, schema-validated, with retry + timeout fallback. | `Assessor`, `OllamaBackend` | FR-4 |
| `state/` | The threat state machine (hysteresis, confirmation window, latch/cooldown). | `StateMachine`, `StateInputs` | FR-5 |
| `alarm/` | Local siren/strobe orchestration. | `AlarmController`, `GpioSink` | FR-6, ICD-4 |
| `comms/` | LoRa mesh: the air-protocol codec (HMAC+counter), payload codecs, the serial transport (ICD-2), and the `MeshGateway` that drives them. | `MeshGateway`, `encode`/`decode`, `frame`/`unframe` | FR-7..10, SR-1/2, ICD-2/3 |
| `voice/` | De-escalation agent: STT→LLM→TTS, vision-context injection, SE-2 guardrails. | `VoiceAgent` | FR-11/12, SE-2 |
| `notify/` | Owner push (durable outbox) + the FR-15 audit event log + keyframe persistence. | `Notifier`, `write_keyframe` | FR-13/15 |
| `dashboard/` | Non-critical local operator web UI (read state + the same controls a human has). | `DashboardService`, `start_dashboard` | FR-17 |
| `models.py` | On-device model auto-provisioning: fetch any missing detector/VLM/voice model at boot, then run offline. | `ensure_present`, `targets` | FR-18 |
| `watchdog.py` | systemd `sd_notify` liveness (the SW half of the HW+SW watchdog). | `Watchdog` | RR-1 |

---

## 3. The data contract (ICD-7) — the spine

Everything that crosses a module boundary is a typed object from `contracts.py`. The pipeline
is literally a chain of these:

```
Frame ─▶ Detection[] ─▶ Track[] ─▶ ThreatAssessment? ─▶ ThreatState ─▶ {AlarmCommand, MeshMessage, VoiceTurn}
capture   detection      tracker     reasoning            state           alarm / comms / voice
```

- **`Frame`** — one captured image + `zone` + `ts` + `seq`. `image` is typed `object` to keep
  numpy out of the module-level imports; every consumer treats it as an ndarray.
- **`Detection`** — `cls` (person/handgun/rifle/knife) + `conf` + `BBox` + `ts`.
- **`Track`** — a `Detection` given a persistent `track_id` plus `history`/`history_ts` (so the
  trigger policy can reason over *time*: loiter, approach).
- **`ThreatAssessment`** — the stage-2 VLM's structured output, **pydantic-validated**
  (`0≤confidence≤1`, enum weapon types). `zone`/`ts` are stamped by the hub, never taken from
  the model (anti-spoofing).
- **`ThreatState`** — `level` + `zone` + `since` + `reason`. The state machine's output.
- **`MeshMessage`/`NodeStatus`/`VoiceTurn`** — the response-side contracts.

If you add a field that crosses a seam, it goes here, typed, not in an ad-hoc dict.

---

## 4. The Hub pipeline, step by step (`app.py`)

`Hub.__init__` builds one detector + state machine **per zone** (track IDs and threat levels
must not collide across cameras, FR-16), plus the shared subsystems (assessor, alarm, mesh,
voice, notifier, watchdog).

`Hub.step(zone, frame)` is the heart — one frame in, the resulting `ThreatState` out:

1. `detector.track(frame)` → `Track[]` (stage-1). A fault here degrades `vision` and returns
   the current state — it never crashes the loop (RR-4).
2. `triggers.evaluate(...)` → does anything warrant the expensive stage-2? (weapon / loiter /
   restricted zone+time / approach).
3. **Only if triggered:** `assessor.assess(...)` → `ThreatAssessment`. A timeout/failure
   yields the *conservative fallback* (armed, confidence held strictly below the arm
   threshold) so a broken stage-2 holds at SUSPECT — loud, never silently clear (pillar 3).
4. `machine.update(StateInputs(...))` → new `ThreatState`.
5. **On a level transition only:** `_actuate(...)` drives the response, the keyframe is
   persisted, and the event is logged (FR-15); on ALARM the owner is notified (FR-13).

`Hub._actuate` encodes the pillar ordering: **local siren latches first**, then mesh, then
voice, then the SE-5 authority recommendation — each later actuator wrapped so a dead radio or
hung LLM can never block or silence the local alarm. Arming gates physical response (a
disarmed zone still reaches ALARM in the log but sounds nothing); test mode pulses without
latching; a manual panic overrides both.

`Hub.run()` provisions models (FR-18), spins one capture **thread per zone** (independent, so
one camera stalling never blocks another), starts the watchdog + the opt-in dashboard, and
loops until interrupted — tearing everything down in `finally`.

---

## 5. The swappable-backend pattern (how to test heavy things without hardware)

Every subsystem that needs a heavy/external dependency (YOLO, the VLM, whisper/Ollama/piper,
the serial radio, the camera) follows the same shape, so the *logic* is unit-tested with a
fake and the *real* dependency is lazy-imported only when actually used:

```python
class VLMBackend(Protocol):              # the seam
    def generate(self, prompt, images) -> str: ...

class Assessor:
    def __init__(self, cfg, backend=None):
        self._backend = backend          # inject a fake in tests
    def _ensure_backend(self):
        if self._backend is None:
            from .ollama_backend import OllamaBackend   # heavy, lazy
            self._backend = OllamaBackend(self.cfg)
        return self._backend
```

Consequences you should preserve:
- **Never import a heavy dep at module top** (httpx, ultralytics, faster_whisper, cv2, serial,
  Jetson.GPIO). Lazy-import it inside the method that needs it.
- **The critical path must not depend on network or cloud** (pillar 1). The only network calls
  are localhost inference, one-time model downloads, and the opt-in owner push.
- Tests inject fakes and assert on the *contract*, never touching a model.

---

## 6. Configuration (`config.py` + `config.yaml`)

All thresholds live in config so sensitivity is tunable without code changes. `Settings` is a
`pydantic-settings` model; nested env overrides use `AUTOSENTRY_<SECTION>__<FIELD>` (e.g.
`AUTOSENTRY_STATE__ARM_CONFIDENCE=0.7`). Secrets never live here — the mesh HMAC key loads from
`$AUTOSENTRY_MESH_KEY` only (SR-3). Validators fail **loud at load**: e.g. `capture.sources`
and `capture.zones` must be 1:1, and `models.dir` propagates to the detection/voice loaders so
there's a single source of truth for where weights live.

When you add a tunable, add it to the right `*Config` model with a sane default + a one-line
comment, and (if it ships) to `config.yaml`.

---

## 7. The mesh (`comms/`) — the load-bearing security surface

Three layers, all pure-stdlib and unit-tested, plus the hardware glue:

- **`protocol.py` (ICD-3, the air format):** `encode`/`decode` a `Packet`
  (`ver|type|net_id|src|dst|counter|payload|hmac`). Every frame is **HMAC-SHA256-truncated**
  signed and carries a **monotonic counter**; `ReplayWindow` rejects replays per source. A
  forged or replayed frame is dropped and never updates state (SR-1).
- **`payloads.py`:** the per-message-type payload codecs (alarm level/zone, heartbeat uptime,
  status battery/mains, ack ref-counter).
- **`transport.py` (ICD-2, the serial link):** COBS+CRC8 framing between the hub and the
  USB radio gateway. The gateway is a dumb modem — it never authenticates.
- **`gateway.py` (`MeshGateway`):** ties it together — signs + broadcasts ALARMs (repeated,
  one counter so nodes de-dupe), sends ACK-retried commands, emits heartbeats, and tracks
  per-node health (offline after missed heartbeats = an alarm in itself, SR-2).

The **firmware** (`firmware/alarm_node/src/main.cpp`) is the byte-compatible counterpart. The
**golden vectors** in `firmware/alarm_node/test/wire_vectors.json` (generated from the hub
codec by `scripts/gen_wire_vectors.py`) pin both sides — the hub asserts them in
`test_wire_vectors.py`, the firmware against them in `pio test`. Change the wire format and you
regenerate the vectors **and** bump the version in both implementations, in one change.

---

## 8. Firmware (`firmware/alarm_node/`)

One PlatformIO project, two roles selected by a build flag:

- **`AUTOSENTRY_ROLE_NODE`** (default) — listens for a signed ALARM, sounds the siren, ACKs,
  heartbeats, reports battery/mains, and **fails safe** (alerts) if it loses the hub. Every
  inbound frame is HMAC+counter-checked before any action.
- **`AUTOSENTRY_ROLE_GATEWAY`** — the hub's USB radio modem: bridges COBS-framed serial
  (ICD-2) ↔ raw LoRa air bytes (ICD-3). No HMAC/replay — the hub owns auth.

The mesh key is injected at flash time via `-DAUTOSENTRY_MESH_KEY`; a node flashed with the
committed placeholder **refuses to boot** (SR-3, fail loud). Host-side unit tests live under
`firmware/alarm_node/test/` (run with `pio test -e native`); see that directory's `README.md`.

---

## 9. Testing & verification

- **Hub:** `cd hub && pytest` — ~200 tests covering the state machine, contracts, codecs +
  HMAC/replay + golden wire vectors, trigger policy, assessor parse/validate/fallback, voice
  guardrails, notify queue, dashboard, model provisioning, config validators, security
  invariants (`test_security.py`). `ruff` + `ruff format` + `mypy` (a curated `files` list of
  the typed modules) must pass.
- **Eval:** `scripts/eval_detection.py` computes precision/recall + the **weapon-only**
  false-negative rate and the PR-4/PR-5 acceptance gate (`check_gates`); the metric/gate logic
  is unit-tested, the on-benchmark run awaits the labeled dataset.
- **Firmware:** `pio test -e native` (host, no hardware) against the golden vectors.
- **Traceability:** every change cites a requirement ID; its row in
  [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) (the RTM) is updated, and
  [STATUS.md](STATUS.md) mirrors the counts. A requirement is "done" only when its V&V passes.

---

## 10. How to make common changes

- **Add a camera/zone:** add a matching pair to `capture.sources` + `capture.zones` (the
  validator enforces 1:1). Per-zone detector + state machine are created automatically.
- **Tune sensitivity:** edit `state.arm_confidence`, `state.confirmation_window_s`,
  `trigger.*` in `config.yaml` — no code change. Re-run the benign eval suite before lowering
  thresholds (pillar 3).
- **Swap a model:** change `detection.model` / `reasoning.model` / `voice.*_model` in config;
  `models.py` provisions the new weight on next boot. Add an entry to `targets()` if it's a new
  *kind* of model.
- **Add a stage-1 trigger:** extend `TriggerEvaluator.evaluate` with a new condition + a config
  threshold + a `TriggerResult` reason; unit-test it in `test_triggers.py`.
- **Add a new mesh message type:** add it to `MsgType` + the `_TYPE_TO_CODE` map + a payload
  codec in `payloads.py`, mirror it in the firmware, **regenerate the golden vectors**, and
  add a round-trip + golden-vector test.
- **Add a response actuator:** wire it into `Hub._actuate` *after* the siren latches, wrapped
  in try/except that degrades (never raises) — it must be additive, never a precondition
  (FR-12, pillar 1).

When in doubt, find the requirement, read the ICD you cross, write the test, then the code.
