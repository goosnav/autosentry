# COMMS_PROTOCOL — LoRa Mesh Detailed Design

**V-Model level:** L4. **Parent:** [INTERFACES.md](INTERFACES.md) ICD-2/ICD-3. **Requirements:** FR-7, FR-8,
FR-9, FR-10, SR-1, SR-2, SR-3, PR-3, PR-6, PR-7, RR-5. **Modules:** `hub/autosentry/comms/`,
`firmware/alarm_node/`.

The mesh is what makes "every node on the property sounds, network or not" (STK-4) real, and what lets the
system **defend itself** (pillar 5). This is the wire format, the security design, and the node/hub state
machines. Ends with the component test definition.

---

## 1. Topology
- **Coordinator:** the hub, via a LoRa radio gateway (ESP32+LoRa over USB-serial per ICD-2, or SX1262 HAT).
- **Responders:** N alarm nodes, each with a 1-byte address; `0xFF` = broadcast.
- **Star** topology in v1 (hub ↔ each node). Multi-hop relay is a documented post-v1 option.

## 2. Packet format (ICD-3, authoritative)
```
 offset  size  field
   0      1    ver        protocol version (start 0x01)
   1      1    type       ALARM|ACK|HEARTBEAT|HEARTBEAT_ACK|STATUS|CONFIG|TEST
   2      1    net_id     network id (isolates co-located deployments)
   3      1    src        sender address
   4      1    dst        recipient address (0xFF broadcast)
   5      4    counter    monotonic per-src sequence, little-endian
   9      n    payload    type-specific (see §4)
  9+n     8    hmac       first 8 bytes of HMAC-SHA256(key, bytes[0 .. 9+n-1])
```
Max payload sized to the chosen SF/BW airtime budget; control frames are tiny.

## 3. Security (SR-1, SR-3) — pillar 5
- **Authentication:** every frame carries a truncated **HMAC-SHA256** over all preceding bytes, keyed by a
  **pre-shared per-network key**. Receiver recomputes; mismatch ⇒ **drop + log** (never act).
- **Anti-replay:** receiver keeps the last-seen `counter` per `src` and rejects `counter ≤ last_seen`. The hub
  persists counters across restarts; nodes keep them in RTC/flash. A small forward window tolerates loss.
- **Key provisioning (SR-3):** key injected at flash time (`node_keys.yaml`, git-ignored). A provisioning
  **self-test in TEST mode** confirms hub↔node auth before the site is armed (FMEA F20).
- **What this stops:** spoofed "all-clear" or spoofed "alarm" from an attacker who sniffs the air — without
  the key they cannot forge a valid HMAC; captured frames can't be replayed (counter).
- **What it doesn't stop:** brute jamming of the RF — handled by detection + fail-safe (§6), not prevention.

## 4. Message types & payloads
| Type | Dir | Payload | Behavior |
|------|-----|---------|----------|
| `ALARM` | hub→node(s) | `{level, zone_id, pattern}` | Node sounds siren/strobe with `pattern`; ACKs. Latched until `CLEAR`. |
| `ACK` | node→hub | `{ref_counter}` | Confirms receipt of an addressed command. |
| `HEARTBEAT` | both | `{uptime_s}` | Liveness ping at `hb_interval_s`. |
| `HEARTBEAT_ACK` | both | `{ref_counter}` | Reply to heartbeat. |
| `STATUS` | node→hub | `{battery_mv, on_battery, siren_active, fw_ver}` | Health + mains state (FR-10). |
| `CONFIG` | hub→node | `{hb_interval_s, patterns, ...}` | Update node params; ACKed. |
| `TEST` | hub→node | `{}` | Exercise siren/strobe briefly; no incident latch (FR-14/OS-8). |

## 5. Reliability (FR-8, PR-3, RR-5)
- **ACK + retry:** addressed `ALARM`/`CONFIG` are retried up to `comms.retries` with backoff until ACKed.
  Broadcast `ALARM` is sent `broadcast_repeats` times (no per-node ACK guarantee) **and** followed by
  addressed confirmation to known nodes for assurance.
- **Latency budget:** confirm→mesh ≤3 s (PR-3) including retries; tune SF/BW for the airtime/range trade
  (PR-6). Document the chosen profile per deployment.
- **Independence (RR-5):** losing one node never affects others or the hub; the hub's node table tracks each
  independently.

## 6. Heartbeats, offline & fail-safe (FR-9, SR-2, PR-7) — never fail silent
- Hub→node and node→hub heartbeats every `hb_interval_s`.
- **Hub side:** a node missing `hb_miss_max` heartbeats ⇒ marked **offline/tamper** and raised as an alert
  within ≤30 s (PR-7). This catches a destroyed, unplugged, dead-battery, or jammed node (FMEA F11/F14).
- **Node side:** a node that misses `hb_miss_max` hub heartbeats assumes isolation (jam/hub-down) and
  **fails safe to local alert** per policy — it does **not** go quiet (pillar 1). Policy is configurable
  (e.g. "alert if previously in ALARM" vs "always alert on isolation") to balance against nuisance.

## 7. Node state machine (firmware)
```
 BOOT → PROVISION-CHECK → IDLE ⇄ ALARMING
                           │  ↑      │
                           │  └─ CLEAR (authenticated)
                           │
                           └─ ISOLATED (hub heartbeat lost) → local fail-safe alert per policy
 (any state) → report STATUS on interval and on mains-loss edge
```

## 8. Hub `comms/` responsibilities
Serialize/sign/verify (ICD-3), drive the gateway (ICD-2), run the retry + heartbeat loops, maintain the
`NodeStatus` table, surface offline/tamper + low-battery + mains-loss as events to `app.py`/`notify`.

## 9. Component test definition (L4 right arm)
- **Codec/HMAC vectors:** fixed key + bytes → known HMAC; encode/decode round-trips; tamper a byte ⇒ reject;
  replay an old `counter` ⇒ reject (SR-1).
- **Retry/ACK logic:** simulated lossy link ⇒ retries then success/failure reported correctly.
- **Heartbeat/offline:** drop heartbeats ⇒ hub flags offline within budget; node enters ISOLATED → fail-safe.
- **Bench (L3):** real hub gateway ↔ one ESP32 node — `scripts/bench_lora.py` triggers ALARM, observes siren
  + ACK; pull node mains ⇒ `on_battery`; kill node ⇒ offline ≤30 s.
- **Range (L2):** walk-test ≥200 m through a structure (PR-6/TPM-6).
