# POWER_AND_RELIABILITY — Detailed Design

**V-Model level:** L4. **Parent:** [ARCHITECTURE.md](ARCHITECTURE.md) §7. **Requirements:** RR-1..5, FR-10,
ER-1; pillar 1 (fail-operational). **Modules:** `hub/autosentry/app.py` (supervision), `deploy/`, firmware
power-path, [HARDWARE.md](HARDWARE.md) (parts).

The system must keep running when an intruder cuts mains or internet, and must **degrade loudly, never
silently**. This doc specifies power architecture, watchdogs, and degraded-mode behavior.

---

## 1. Power architecture
**Hub (Jetson):** mains → 12 V supply → **DC-UPS / LiFePO4** pack → DC-DC to the Jetson + peripherals. Mains
presence is sensed; on loss the system runs on battery (≥4 h, TPM-9/RR-3) and reports it. Orderly low-battery
behavior: warn early, keep the critical path alive longest, log state.

**Alarm node:** mains-USB adapter → charger → **LiFePO4 (~6 Ah) or 2×18650** → board + siren. A power-path so
the node runs from mains while charging and switches seamlessly to battery on mains loss (≥24 h standby +
≥10 min siren, TPM-8/RR-3). **INA219** (or divider+ADC) measures battery voltage + mains presence, reported
via ICD-3 `STATUS` (FR-10). Outdoor nodes ≥ IP65 with documented temp range (ER-1).

**Why batteries everywhere:** cutting power is the obvious intruder move (R7). Battery backup + mains-loss
reporting turns that attack into an *observable event* rather than a blackout.

## 2. Watchdogs (RR-1) — defeating silent hangs (FMEA F4)
Two layers:
- **Software watchdog:** implemented as `autosentry.watchdog.Watchdog` (`hub/autosentry/watchdog.py`). The
  main loop in `Hub.run()` calls `watchdog.ready()` once up (→ systemd `READY=1`) then `watchdog.ping()` after
  each frame (→ `WATCHDOG=1`, throttled to `watchdog.sw_timeout_s`). When the loop hangs, `ping()` is never
  called again, so the pet stops and systemd's `WatchdogSec` deadline fires — a stalled hub is killed, not
  left blind. Off systemd (`$NOTIFY_SOCKET` unset) the notifier is a silent no-op for dev/test.
- **Hardware watchdog:** the Jetson/SoC hardware watchdog timer (and systemd `WatchdogSec=`) reboots the box
  if userspace stops petting it — covers kernel/driver hangs the software watchdog can't.
- **systemd:** `Type=notify` + `Restart=always` + `WatchdogSec` (`deploy/autosentry.service`) restarts on
  crash (FMEA F3) and on missed pets. Pipeline auto-resumes (FR-2).

## 3. Degraded mode (RR-4) — graceful, observable
On a subsystem failure the system enters **DEGRADED**, continues at reduced capability, and **announces it**
(owner alert + log). Per-failure behavior (see [FMEA.md](FMEA.md)):
| Failure | Degraded behavior |
|---------|-------------------|
| Camera lost (F1) | Reconnect loop; other zones keep running; alert |
| Camera tampered/blinded (F2) | Tamper alert; treat zone as compromised |
| VLM timeout/hang (F6) | Fall back to stage-1 conservative decision (bias to alert) |
| Local siren dead (F9) | Mesh + voice + notify still fire; periodic self-test catches it |
| LoRa gateway down (F10) | Local siren fires; alert; auto-reopen serial |
| Notifications down (F17) | Local alarm primary; queue + flush later |
| Mains lost (F18/F13) | Run on battery; report; low-batt policy |

**Invariant:** there is **no single failure that silences all alarm paths** — local siren ∥ mesh ∥ voice ∥
notify are independent (FMEA theme). The state machine and supervisor enforce that an unhandled error biases
toward *alerting*, never toward silence.

**Implementation:** `Hub` tracks `degraded: dict[subsystem→reason]` (`hub/autosentry/app.py`); `_degrade()`
logs a loud `ERROR` once on entry and `_recover()` clears it. `step()` wraps `detector.track` (→
`degraded["vision"]`, returns last state, no crash) and `assessor.assess` (→ `degraded["reasoning"]`,
assessment stays `None`). The latter is the load-bearing case for pillar 3: a stage-2 fault yields no
assessment, so the machine **cannot** reach THREAT/ALARM — degrading never manufactures a false alarm.
`_actuate()` catches mesh-broadcast faults (→ `degraded["mesh"]`) **after** firing the local siren, so a
dead radio never silences the local alarm (pillar 1). `health()` surfaces the degraded map for dashboards.

## 4. Availability (RR-2)
Target ≥99.9% computed from MTBF/MTTR with auto-recovery: most faults self-heal via watchdog restart
(seconds of MTTR). The analysis lives in the V&V doc (RR-2 row) and is updated as field data arrives.

## 5. Self-tests (TEST mode, OS-8)
Before arming and on a schedule, TEST mode exercises: camera liveness, siren/strobe (local + each node),
mesh auth/provisioning (FMEA F20), battery levels, and free disk (FMEA F19). Failures block arming and alert.

## 6. Component test definition (L4 right arm)
- **Watchdog:** `test_watchdog.py` ☑ — ready→`READY=1`, first ping fires then throttles, stalled loop stops
  pinging (systemd then restarts), no-op without `$NOTIFY_SOCKET`. On-target systemd hang/crash→restart demo
  pending hardware (RR-1, FR-2).
- **Degraded paths:** `test_reliability.py` ☑ — detector fault degrades without crashing, assessor fault never
  manufactures an ALARM, alarm path intact; mesh-fault containment exercised via `_actuate`. On-target
  fault-injection (real camera/VLM/gateway/notify) pending (RR-4).
- **Arming / test / panic:** `test_reliability.py` ☑ — disarmed reaches ALARM-level but sounds nothing
  (`suppressed_disarmed`), armed fires the siren, test mode pulses without latching, panic forces ALARM even
  when disarmed (FR-14).
- **Node power surfacing:** `test_mesh_gateway.py` + `test_reliability.py` ☑ — `STATUS.on_battery` surfaced
  only while online; `Hub.power_alerts()`/`health()` report offline + on-battery nodes (FR-10). Real INA219
  mains-sense bench pending.
- **Battery (on-target, L2):** measure hub ≥4 h, node ≥24 h standby + ≥10 min siren (RR-3/TPM-8/9); pull mains
  ⇒ `on_battery` reported (FR-10).
- **Availability (A):** compute from injected-fault MTTR + assumed MTBF (RR-2).
