# INTERFACES — Interface Control Documents (ICD-1..7)

**V-Model level:** L3 (left arm). **Parent:** [ARCHITECTURE.md](ARCHITECTURE.md). **Verified by:** Subsystem
Integration & Test.

An interface is a **contract**. If code on either side of a seam changes the contract, this document changes
in the same PR. Integration tests exercise these seams directly.

---

## ICD-1 — Camera ↔ Hub

| Aspect | Specification |
|--------|---------------|
| Physical | USB (UVC), CSI/MIPI (Jetson `nvarguscamerasrc`), or Ethernet (RTSP/PoE IP camera). |
| Discovery | Hub enumerates video devices on boot + hotplug (FR-1); maps each to a configured **zone**. |
| Format | Frames decoded to BGR/RGB ndarray; configured resolution (default 1920×1080) + FPS (default ≥15). |
| Night | IR/low-light source or IR-capable sensor; pipeline is illumination-agnostic (ER-2). |
| Failure | No frames within `capture.timeout_s` → reconnect loop + DEGRADED + owner alert (RR-4, FMEA: Camera). |
| Contract | Produces `Frame{zone, ts, image, seq}` (see ICD-7). |

## ICD-2 — Hub ↔ LoRa Radio Gateway (local wire)

| Aspect | Specification |
|--------|---------------|
| Physical | USB-serial (CDC-ACM) to an ESP32+LoRa board in gateway mode, **or** SPI to an SX1262 HAT. |
| Baud | 115200 (serial variant), 8N1. |
| Framing | COBS-encoded frames with a 1-byte type + length; CRC8 over the frame. |
| Commands (host→gw) | `SEND(payload)`, `SET_CHANNEL`, `GET_STATUS`, `PING`. |
| Events (gw→host) | `RX(payload, rssi, snr)`, `TX_DONE`, `STATUS`, `LOG`. |
| Note | The gateway is a dumb radio modem; all signing/auth happens in the hub's `comms/` and is carried in `payload` (ICD-3). |

## ICD-3 — LoRa Air Protocol (the load-bearing ICD)

Full rationale and state machines: [COMMS_PROTOCOL.md](COMMS_PROTOCOL.md). Summary contract:

| Aspect | Specification |
|--------|---------------|
| Band/PHY | 915 MHz (US) / 868 MHz (EU); SF, BW, CR configured per deployment for the range/airtime trade. |
| Addressing | 1-byte `net_id`, 1-byte `src`, 1-byte `dst` (`0xFF` = broadcast). |
| Packet | `ver(1) | type(1) | net_id(1) | src(1) | dst(1) | counter(4, LE) | payload(n) | hmac(8)` |
| Types | `ALARM`, `ACK`, `HEARTBEAT`, `HEARTBEAT_ACK`, `STATUS`(battery/mains), `CONFIG`, `TEST`. |
| Auth (SR-1) | `hmac` = first 8 bytes of HMAC-SHA256(key, bytes-before-hmac). Receiver recomputes; mismatch → drop + log. |
| Anti-replay (SR-1) | Per-`src` monotonic `counter`; receiver rejects counter ≤ last-seen for that src. |
| ACK | Every addressed `ALARM`/`CONFIG` is ACK'd by the addressed node; hub retries `comms.retries` times. |
| Heartbeat (FR-9) | Hub→nodes every `hb_interval_s`; nodes→hub likewise. Miss > `hb_miss_max` ⇒ offline (hub side) / fail-safe local alert (node side). |
| Mains (FR-10) | `STATUS` carries `{battery_mv, on_battery, siren_active, fw_ver}`. |
| Keying (SR-3) | Pre-shared per-network HMAC key provisioned at flash time; never committed (see `.gitignore`). |

## ICD-4 — Hub ↔ Local Alarm Peripherals

| Aspect | Specification |
|--------|---------------|
| Siren | GPIO → relay/MOSFET driving a 12 V siren, **or** USB-audio playing a siren asset through a powered speaker. |
| Strobe | GPIO → relay/MOSFET driving a high-output strobe. |
| Activation | `alarm/` asserts on ALARM entry, deasserts on clear; latched per state-machine policy (FR-6). |
| Contract | Consumes `AlarmCommand{action: ARM|TRIGGER|CLEAR|TEST, zone}` (ICD-7). |

## ICD-5 — Node Electrical (per alarm node)

| Aspect | Specification |
|--------|---------------|
| Power-path | USB-mains adapter → charger → battery → board+siren; auto-switch to battery on mains loss. |
| Battery | LiFePO4 (~6 Ah) or 2×18650 Li-ion with protection + appropriate charger IC. |
| Sense | INA219 (or divider+ADC) for `battery_mv` and mains presence → reported via ICD-3 `STATUS` (FR-10). |
| Siren driver | MOSFET/relay rated for the siren; strobe likewise; flyback/snubber as needed. |
| Enclosure | ≥ IP65 for outdoor nodes; documented temp range (ER-1). |

## ICD-6 — Hub ↔ Notification / Cloud (non-critical path)

| Aspect | Specification |
|--------|---------------|
| Criticality | **Best-effort only.** Never in the detection→alarm critical path (pillar 1). |
| Transport | Push provider or self-hosted endpoint; HTTPS. |
| Offline | Notifications queue locally (SQLite) and flush on reconnect (FR-13). |
| Payload | `{event_id, zone, ts, threat_level, assessment_summary, keyframe_ref}`; respects retention policy (SE-4). |
| Escalation | Authority-contact recommendation requires human confirmation (SE-5). |

## ICD-7 — Internal Software Data Contracts (`hub/autosentry/contracts.py`)

The only types allowed to cross module boundaries (IR-4). Loose dicts across seams are a defect.

```python
Frame(zone: str, ts: float, image: ndarray, seq: int)
Detection(cls: str, conf: float, bbox: BBox, ts: float)            # cls ∈ {person, handgun, rifle, knife, ...}
Track(track_id: int, cls: str, bbox: BBox, first_ts: float, last_ts: float, history: list[BBox])
ThreatAssessment(armed: bool, weapon_type: str|None, intent: str, confidence: float,
                 description: str, zone: str, ts: float)            # stage-2 output, schema-validated
ThreatState(level: Level, zone: str, since: float, reason: str)    # Level ∈ NORMAL/WATCH/SUSPECT/THREAT/ALARM
AlarmCommand(action: Action, zone: str)                            # Action ∈ ARM/TRIGGER/CLEAR/TEST
MeshMessage(type: MsgType, dst: int, payload: bytes, counter: int) # serialized per ICD-3 by comms/
NodeStatus(node_id: int, online: bool, battery_mv: int, on_battery: bool, last_seen: float)
VoiceTurn(role: str, text: str, vision_context: ThreatAssessment, ts: float)
```

Versioning: contract changes bump a `CONTRACTS_VERSION` constant and update every consumer + this ICD in the
same PR.
