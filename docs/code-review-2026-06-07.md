# Code Review — 2026-06-07

**Audience:** another agent tasked with fixing the issues below.

**Scope:** every `.py` in `hub/autosentry/` + `scripts/`, the firmware at
`firmware/alarm_node/src/main.cpp`, and `hub/tests/`.

**Method:** line-by-line reading of all sources, cross-referenced with
`docs/VISION_PIPELINE.md`, `docs/ARCHITECTURE.md`, the RTM, and ICD docs.
Tests were checked for completeness but **not executed** (assume CI is green).

---

## Severity key

| Label | Impact |
|-------|--------|
| **CRITICAL** | Causes incorrect behaviour in production that violates a requirement or pillar. |
| **HIGH**     | Will cause a crash or misbehaviour in a realistic deployment path that is not exercised by current tests. |
| **MEDIUM**   | Design flaw that degrades correctness, safety margin, or maintainability. |
| **LOW**      | Minor doc-code skew, fragile patterns, or missing test coverage. |

---

## Critical

### C1. Firmware ACK payloads are empty; hub expects a 4-byte ref_counter

**File:** `firmware/alarm_node/src/main.cpp:165`
**File:** `hub/autosentry/comms/gateway.py:156-157`

The firmware responds to every ALARM, TEST, HEARTBEAT, and CONFIG with
`send_frame(MSG_ACK, ..., nullptr, 0)` / `send_frame(MSG_HEARTBEAT_ACK, ..., nullptr, 0)`.
The payload is zero bytes long.

The hub's `_observe()` at `gateway.py:156` checks
`len(pkt.payload) >= 4` and calls `payloads.decode_ref(pkt.payload)`, which
unpacks a 4-byte little-endian counter. Because the firmware ACK payload is
empty, this condition is **always False**, and the ACK is silently dropped.

**Consequence:** `MeshGateway.send_command()` (line 106-122) retries all
`cfg.retries + 1` attempts, then returns `False` — **every time**. The
`send_command` method is not currently called by the Hub's pipeline
(`broadcast_alarm` doesn't wait for ACKs), so the system is not actively
broken. But the ICD-3 wire contract is violated, and any future CONFIG
owner-ack path (including the documented `CFG_CLEAR` sub-command in
firmware line 174) will be non-functional.

**Fix:**
- The firmware must encode the `ref_counter` (the hub's original counter
  being ACKed) in the ACK payload as 4-byte LE, matching `payloads.encode_ref()`.
- The hub side is correct; this is purely a firmware production bug.

---

### C2. Firmware: missing `radio.startReceive()` after TX, node deaf for ~5 s

**File:** `firmware/alarm_node/src/main.cpp:141,165,219`

`send_frame()` calls `radio.transmit()`, which transitions the SX1262 from
RX to TX. The radio is only returned to RX mode at `radio.startReceive()` on
line **219**, which is inside the heartbeat block that fires every
`HEARTBEAT_INTERVAL_MS` (5000 ms).

After sending an ACK (e.g. in response to ALARM at line 165, or TEST at
line 168, or CONFIG/HEARTBEAT at lines 170-174), the node is **deaf for up
to 5 seconds**. It cannot hear a second ALARM, a CONFIG clear, or any hub
heartbeat during this window.

**Consequence:** Violates FR-9 (heartbeat liveness guarantees) and SR-2
(fail-safe on tamper/jam) by creating a regular 5 s window where the node
cannot receive anything. On the hub side, the `hb_miss_max=3` ×
`hb_interval_s=5` = 15 s timeout means a single missed cycle won't trip it,
but this is still a reliability gap.

**Fix:** Insert `radio.startReceive()` immediately after `radio.transmit()`
in `send_frame()`, or as the last operation in `handle_frame()` before
returning.

---

## High

### H1. `zip(strict=False)` silently truncates mismatched sources/zones

**File:** `hub/autosentry/app.py:330`

```python
for src, zone in zip(sources, self.zones, strict=False)
```

If a user configures 3 sources but only 2 zones, the third camera is
silently dropped. A configuration error is invisible until the operator
wonders why a zone has no feed.

**Fix:** Change to `strict=True`. The config schema already requires
sources and zones to be 1:1; this makes enforcement a runtime check.
(Requires Python ≥3.10, which is already the minimum.)

---

### H2. `GpioSink` crashes when both pins are `None`

**File:** `hub/autosentry/alarm/gpio_sink.py:23-25,32-33`

```python
for pin in (self.cfg.siren_gpio, self.cfg.strobe_gpio):
    if pin is not None:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
```

Default config: `siren_gpio: null, strobe_gpio: null`. If an alarm fires
and `AlarmController._ensure_sink()` constructs a `GpioSink`, the loop
does nothing (correct). But if a user configures one pin or both, and the
config changes later, the behaviour depends on which pins are None.

The `_set()` method has the same loop pattern at line 32 and will call
`gpio.output(None, level)` if `None` leaks through.

**Consequence:** `GpioSink._set(False)` at the end of `test()` (line 48)
will crash if both pins are None. On the critical alarm path, `_ensure_sink()`
succeeds but `trigger()` → `apply(TRIGGER)` → `sink.on()` → `_set(True)` →
`gpio.output(None, HIGH)` will raise `TypeError`.

**Fix:**
```python
def _set(self, value: bool) -> None:
    gpio = self._ensure_gpio()
    level = gpio.HIGH if value else gpio.LOW
    for pin in (self.cfg.siren_gpio, self.cfg.strobe_gpio):
        if pin is not None:
            gpio.output(pin, level)
```

Also guard `test()` against the same: if both pins are None, log a warning
and return.

---

### H3. `log_event` records `state.since` instead of the event timestamp

**File:** `hub/autosentry/notify/notifier.py:83`

```python
db.execute("INSERT INTO events (ts, zone, level, ...) VALUES (?, ...)",
           (state.since, ...))
```

`state.since` is the time the current *level* was **entered**, not the time
this specific event occurred. If a level persists for 10 minutes before a
state transition triggers `log_event`, the audit row will show a timestamp
10 minutes in the past.

**Consequence:** The FR-15 audit log has misleading timestamps for
non-level-change events (e.g. repeated stage-1 triggers in the same state).
An operator reviewing events sees them in the wrong order or with
impossible durations.

**Fix:** Use `time.time()` (or the frame `ts` that was passed to `step()`)
instead of `state.since`.

---

### H4. `dashboard/service.py:events()` loads entire table into memory

**File:** `hub/autosentry/dashboard/service.py:110`

```python
def events(self, limit=None):
    limit = self.event_limit if limit is None else limit
    return list(reversed(self.hub.notifier.events()))[:limit]
```

`self.hub.notifier.events()` executes `SELECT ... FROM events ORDER BY id`
which returns **every row** in the SQLite table. On a system that has
logged thousands of events (months of operation), this reads the entire
table into a Python list, reverses it, then takes the last N.

**Consequence:** Unbounded memory growth and latency on dashboard refresh.

**Fix:** Push the limit and ordering into SQL:
```python
db.execute("SELECT ... FROM events ORDER BY id DESC LIMIT ?", (limit,))
```
Then no Python reversal or slicing is needed.

---

### H5. Firmware `MESH_KEY` is a compile-time constant, shared across all nodes

**File:** `firmware/alarm_node/src/main.cpp:42`

```cpp
static const uint8_t MESH_KEY[] = "REPLACE_AT_PROVISIONING";
```

The HMAC pre-shared key is a hardcoded compile-time constant. While
documented as a placeholder, there is:
1. no guard against accidentally shipping with the placeholder value;
2. no per-device key (every node in the fleet shares one key);
3. no key-rotation mechanism.

**Consequence:** Single-key compromise breaks authentication for the entire
deployment (SR-1). No practical way to revoke a compromised node without
rekeying every node.

**Fix:** Store the key in flash at provisioning time (e.g. ESP32
`nvs` partition or efuse). The compile-time constant should be removed;
the node should fail loudly at boot if no key is present. Hub side
(`CommsConfig.key_env`) is already correct.

---

## Medium

### M1. `assert self._threat_since is not None` stripped in optimized Python

**File:** `hub/autosentry/state/machine.py:116`

```python
assert self._threat_since is not None
if (now - self._threat_since) >= self.cfg.confirmation_window_s:
```

When Python runs with `-O` (or `PYTHONOPTIMIZE=1`), `assert` statements
are compiled away. The subsequent `now - self._threat_since` will raise
`TypeError: unsupported operand type(s) for -: 'float' and 'NoneType'`.

**Consequence:** Crash on the safety-critical state-machine path — the one
subsystem that must *never* crash (pillar 3).

**Fix:** Replace with an explicit runtime check:
```python
if self._threat_since is None:
    self._threat_since = now
elif (now - self._threat_since) >= self.cfg.confirmation_window_s:
```

---

### M2. Approach speed uses full-track average, masks sudden sprints

**File:** `hub/autosentry/detection/triggers.py:72-77`

```python
first, last = t.history[0], t.history[-1]
dist = math.hypot(last.cx - first.cx, last.cy - first.cy)
return dist / dt
```

Speed = (first history bbox → last history bbox) / (track lifetime). This
is a **lifetime average**. An intruder who loiters for 60 seconds then
sprints toward the house in 2 seconds has:
- average speed ≈ sprint_distance / 62s, which is well below
  `approach_px_s = 120 px/s`.

**Consequence:** The approach trigger is easily defeated by a
loiter-then-sprint pattern, weakening PR-2 (the threshold at which the
state machine may escalate toward ALARM).

**Fix:** Compute speed over a sliding window (last N seconds or last N
bboxes). A simple approach: `history[-2:]` if len ≥ 2, and use the last
two bboxes' distance / their timestamp delta. The track already stores
per-bbox timestamps from `Track.last_ts` — but currently `history` stores
only `BBox` objects without per-bbox timestamps. Either add timestamps to
`BBox` or store `(BBox, ts)` pairs in the history.

---

### M3. No timeout on `urllib.request.urlopen` in model download

**File:** `hub/autosentry/models.py:136`

```python
with urllib.request.urlopen(url) as resp, open(tmp, "wb") as fh:
```

No timeout argument. If the network is misconfigured or the download source
is unreachable, this can hang indefinitely, blocking `_ensure_models()`
and preventing the hub from starting (FR-18).

**Fix:** Add `timeout=30` (seconds). The outer try/except in
`ensure_present` will catch the `URLError` and degrade gracefully.

---

### M4. Firmware radio-gateway role not implemented (documented but empty)

**File:** `firmware/alarm_node/platformio.ini:47-54`

The `hub_gateway` build environment exists but no corresponding source
file implements the USB-serial <-> LoRa bridge. The `env:hub_gateway` only
sets `-DAUTOSENTRY_ROLE_GATEWAY=1` without a `#ifdef` handler in `main.cpp`.
This means the hub cannot talk to the LoRa radio until the gateway firmware
exists.

**Consequence:** `MeshGateway` → `SerialTransport` sends COBS-framed bytes
to `/dev/ttyUSB0`, but nothing on the other end decodes and forwards them
over LoRa. The radio link is non-functional until the gateway role is
implemented, making M3 integration impossible.

**Fix:** Implement `#ifdef AUTOSENTRY_ROLE_GATEWAY` in `main.cpp` that
reads from `Serial` → radio.transmit and radio.read → `Serial`. A first
cut is ~40 lines. The ICD-2 framing is already tested
(`test_comms_transport.py`).

---

### M5. `hub/autosentry/detection/yolo_backend.py` — no fallback logging

**File:** `hub/autosentry/detection/yolo_backend.py:48`

```python
self._model = YOLO(self._resolve(self.cfg.weapon_model or self.cfg.model))
```

If `weapon_model` is set but the file doesn't exist (including after a
provisioning failure), YOLO will throw. The `_load()` method has no
try/except, so the exception propagates up to `Hub.step()` which catches
it and degrades. However, the log message `"detect failed: {e}"` at
`app.py:149` will be opaque — it will contain a stack trace from
ultralytics, not a clear "weapon model not found" message.

**Consequence:** Operator troubleshooting: "detect failed: Model file
'/path/to/weights.pt' not found" — actually helpful, so this is minor.
But if `weapon_model` is set and missing, the system silently falls back
to the base model. Is that desired? The VISION_PIPELINE.md §6 says weapons
"require a fine-tuned head." With `weapon_model: null` (default), the base
model won't detect weapons via COCO (COCO doesn't have handgun/rifle/knife
as distinct classes). **Any person with a visible weapon will go
undetected at stage-1 unless `weapon_model` is configured.**

This is a **configuration documentation gap** — the default `config.yaml`
is safe for development but not for a security deployment.

---

## Low

### L1. No `test_capture.py`

**File:** `hub/tests/` (missing)

`capture/source.py` implements the reconnect loop (FMEA F1), the
sequencer, and `list_cameras()`. None of this has unit tests. The
reconnect logic (timeout-based retry) is testable with a fake capture.

### L2. No `test_assessor.py`

**File:** `hub/tests/` (missing)

The `Assessor.assess()` parse/validate/retry/fallback logic is the
critical safety net for a hallucinating VLM (FMEA F6/F7). It has no unit
tests. `VISION_PIPELINE.md §9` lists this as a L4 test target. The
current coverage is only via `test_pipeline.py` integration tests which
use a `FakeAssessor` that never fails.

### L3. `test_comms_gateway.py` doesn't test `broadcast_alarm`

`test_comms_gateway.py` exists but I didn't exhaustively audit it.
`broadcast_alarm` with repeated sends and the ACK-retry logic in
`send_command` should have unit tests with a fake transport.

### L4. `reasoning/ollama_backend.py` — `"format": "json"` may not be honored

**File:** `hub/autosentry/reasoning/ollama_backend.py:27`

Ollama's `format: json` is a hint, not a guarantee. The model may still
produce non-JSON output, or wrap JSON in markdown fences. The
`Assessor._parse()` regex `r"\{.*\}"` with `re.DOTALL` handles the
markdown case, but a model that produces broken JSON (e.g. trailing comma)
will be caught by `json.loads()` and retried/fallback. This is correctly
handled — just worth noting it's a best-effort feature.

### L5. Doc: `weapon_model: null` default means **no weapon detection** on COCO

**File:** `hub/autosentry/config.yaml:17`
**File:** `docs/VISION_PIPELINE.md §6`

The default config sets `weapon_model: null`. COCO classes do not include
handgun, rifle, or knife. The `_CLASS_ALIASES` map in `yolo_backend.py` can
never match. **A base YOLO model with `weapon_model: null` will never
detect a weapon.** This is a shipping default that makes FR-3 (weapon
detection) non-functional out of the box. The doc says weapons "require a
fine-tuned head" but does not highlight that the default config is
cosmetically safe but operationally useless for weapon detection.

### L6. `deploy/autosentry.service` hardcodes paths specific to Jetson setup

**File:** `deploy/autosentry.service`

Paths like `/opt/autosentry` and `/etc/autosentry/` are not documented
as install locations. No install script or Makefile exists. The
`WorkingDirectory` and `ExecStart` paths assume a specific venv location.
Consider adding an install script or documenting the setup.

### L7. `contracts.py:64` — `Frame.image: object` is too loose

Using `object` instead of `numpy.ndarray` was a deliberate choice to avoid
the numpy import at module level. But every consumer (yolo_backend,
keyframes, ollama_backend) assumes it's an ndarray. A user passing
e.g. a PIL image will get opaque errors at runtime. Consider using
`TYPE_CHECKING` to annotate properly, or add a `@property` that validates
the type once.

### L8. `detection/tracking.py:27-28` — redundant `max(0.0, ...)` masks bugs

```python
area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
```

If a bbox has x2 < x1 (inverted coordinates), `max(0.0, ...)` silently
gives area 0, returning a correct IoU of 0. The caller never sees the
inverted bbox. Better to validate bbox order once in the `BBox` dataclass
or at the point of creation.

---

## Architecture observations

### A1. No fusion module

The repo map in `CLAUDE.md` lists `fusion/` for "sensor fusion" but no
`hub/autosentry/fusion/` directory exists. The fusion logic is spread
between `trigger` policy and the state machine. This is fine for M1–M6
but should be noted for the architecture diagram.

### A2. `Hub.step()` is the only orchestration seam

The `Hub` class is both the dependency-injection root and the pipeline
orchestrator. It works for the current scale but makes it hard to test
individual actuator sequences (`_actuate`, `_engage_voice`, `_notify_owner`)
without the full Hub wiring. The `_actuate` method, for instance, is 25
lines with 3 try/except blocks and 3 side-effect subsystems — it should be
a testable strategy class.

### A3. Configuration must be reloaded via environment, not file for some settings

`CommsConfig.key_env` and `DashboardConfig.host` are settable via YAML but
also have environment overrides (`AUTOSENTRY_*`). The mesh key is *only*
from env (no YAML key field by design — SR-3). This is correct but
non-obvious for operators.

---

## Summary table

| ID | Area | Severity | Fix effort |
|----|------|----------|------------|
| C1 | firmware ACK payload | CRITICAL | 1 line |
| C2 | firmware radio RX after TX | CRITICAL | 1 line |
| H1 | `strict=False` in zip | HIGH | 1 char |
| H2 | GPIO sink crashes on None pins | HIGH | 4 lines |
| H3 | log_event wrong timestamp | HIGH | 1 line |
| H4 | dashboard load-all-events | HIGH | ~5 lines |
| H5 | firmware hardcoded key | HIGH | structural |
| M1 | assert stripped in -O | MEDIUM | 2 lines |
| M2 | approach speed full-track avg | MEDIUM | ~10 lines |
| M3 | model download no timeout | MEDIUM | 1 param |
| M4 | gateway role unimplemented | MEDIUM | ~40 lines |
| M5 | weapon_model default gap | MEDIUM | docs + config |
| L1-L8 | various low | LOW | varies |

**Total:** 2 critical, 5 high, 5 medium, 8 low.

---

## Resolution (triaged + fixed 2026-06-07)

Each item was re-verified against the code before action. **Refuted** = the claim does not
hold against the current source.

| ID | Verdict | Action |
|----|---------|--------|
| C1 | Legit | **Fixed** (firmware): `send_ack()` now echoes the acked counter as 4-byte LE; the four ACK/HEARTBEAT_ACK sites use it. Compile-unverified here; `pio test` assertion #7 added to `test/README.md`. |
| C2 | Legit | **Fixed** (firmware): `radio.startReceive()` now runs at the end of `send_frame()`, so the node is never deaf between heartbeats. Compile-unverified here. |
| H1 | Legit | **Fixed**: `CaptureConfig` model_validator requires `len(sources)==len(zones)` (fails loud at load); the run-loop `zip` is now `strict=True`. Test: `test_config::test_sources_and_zones_must_be_one_to_one`. |
| H2 | **Refuted** | `GpioSink._set()` already guards `if pin is not None` — the review's proposed "fix" is the existing code. No change. |
| H3 | **Refuted** | `log_event()` is only called on level transitions, where `state.since == now == event time`. No misleading timestamps. No change. |
| H4 | Legit | **Fixed**: added `Notifier.recent_events(limit)` pushing `ORDER BY id DESC LIMIT` into SQL; the dashboard uses it instead of loading the whole table. Tests in `test_event_log`. |
| H5 | Legit | **Fixed** (firmware): key now sourced from `-DAUTOSENTRY_MESH_KEY`; the node refuses to boot (blinks + logs) on the committed placeholder. Per-device key / NVS-efuse provisioning remains the production path (noted in `test/README.md`). Compile-unverified here. |
| M1 | Legit | **Fixed**: the `assert self._threat_since is not None` on the safety path is replaced with a runtime guard (asserts vanish under `python -O`). |
| M2 | Legit | **Deferred**: approach speed is a lifetime average; the docstring already flags it as the M1 proxy "refined on hardware." A correct fix needs per-bbox timestamps in `Track.history` (tracker + triggers + tests). Flagged, not blind-fixed. |
| M3 | Legit | **Fixed**: `urllib.request.urlopen(url, timeout=30)` so a stalled mirror surfaces as a URLError instead of hanging boot. |
| M4 | Legit | **Deferred**: the `hub_gateway` firmware role is a missing *feature* (~40 lines of untestable-here C++), not a bug. Flagged for the M3 hardware bring-up. |
| M5 / L5 | Legit | **Fixed (loud-warning)**: the Hub now logs a prominent warning at startup when `detection.weapon_model` is unset (base COCO can't detect weapons); `config.yaml` comment strengthened. The real fix (a fine-tuned head) is gated on the labeled dataset (ADR-9). |
| L4 | Note | Best-effort `format:json` is already handled by the parser; the JSON extractor is now a balanced-brace scan (robust to nesting + trailing prose). |
| L1, L2, L3 | **Refuted** | `test_capture.py`, `test_assessor.py`, and `test_mesh_gateway.py` all exist (the reviewer's "missing" note was incorrect). |
| L6, L7, L8 | Legit (minor) | **Noted, deferred**: install-path docs (L6), `Frame.image: object` annotation (L7, deliberate to avoid a module-level numpy import), and the `max(0.0, …)` IoU guard (L8) are low-value/by-design; not changed this pass. The `os.scandir` FD leak adjacent to L8's area was fixed in `models.py`. |

**Net this pass:** 8 issues fixed (C1, C2, H1, H4, H5, M1, M3, M5) + the JSON-extractor and scandir hardening; 2 deferred with rationale (M2, M4); 5 refuted (H2, H3, L1–L3); the rest noted. Hub fixes are covered by new/updated tests (suite 205 → green, ruff + mypy clean). Firmware fixes (C1/C2/H5) are compile-unverified in this environment and gated on the `pio test` run specified in `firmware/alarm_node/test/README.md`.
