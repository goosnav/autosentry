# HARDWARE — Bill of Materials & Integration

**V-Model level:** L5 (implementation). **Parent:** [ARCHITECTURE.md](ARCHITECTURE.md) §8,
[INTERFACES.md](INTERFACES.md) ICD-1/4/5. **Requirements:** PR-1, RR-3, ER-1, ER-2, FR-1, FR-10.

Recommended parts for v1, the wiring/integration notes, and the dev-vs-production split. A machine-readable
starter BOM is in [`../hardware/BOM.csv`](../hardware/BOM.csv).

> Part suggestions are representative, not an endorsement; verify current availability, your **regional LoRa
> band (915 MHz US / 868 MHz EU)**, and electrical ratings before purchase.

---

## 1. Hub / smart camera

| Item | Recommended | Notes |
|------|-------------|-------|
| Compute | **Jetson Orin NX 16GB** dev kit | Runs stage-1 + stage-2 + voice with care (ADR-1, R4). Orin Nano Super 8GB = budget; AGX Orin = headroom. |
| Storage | NVMe SSD (≥256 GB) | OS + models + event store. |
| Camera (dev) | USB UVC webcam (Logitech Brio / C920) | What you have now; plug-and-play (FR-1). |
| Camera (prod) | CSI IMX219/IMX477 **or** RTSP/PoE IP cam | CSI = low latency; IP/PoE = run + power over one cable. |
| Night | IR illuminator + IR-capable sensor | ER-2; match illuminator to lens FoV. |
| LoRa radio | **ESP32+LoRa board (LilyGO T3-S3 / Heltec V3) over USB** *or* Waveshare SX1262 HAT | Gateway mode reuses node firmware (ICD-2); HAT uses SPI. |
| Audio out | Powered speaker / horn driver | Local siren + voice agent (ICD-4). USB-audio or 3.5 mm + amp. |
| Audio in | USB mic / array mic | Voice agent STT; place near the speaker zone. |
| Siren/strobe | 12 V siren + strobe + relay/MOSFET board | Driven by GPIO (ICD-4). |
| Power/UPS | 12 V **LiFePO4** pack + DC-DC + DC-UPS board | ≥4 h hub runtime (RR-3); mains-sense for power-loss reporting. |
| Cooling | Active heatsink/fan | Mitigates thermal throttle (R4/FMEA F5). |
| Enclosure | Ventilated; weatherproof if outdoor | — |

## 2. Alarm node (build several)

| Item | Recommended | Notes |
|------|-------------|-------|
| MCU+radio | **LilyGO T3-S3** or **Heltec WiFi LoRa 32 V3** | Integrated ESP32-S3 + SX1262 + OLED → fewer wires, faster build. |
| Siren | 12 V piezo/horn siren + MOSFET driver | Loud; rated for the battery bus (ICD-5). |
| Strobe | High-output LED strobe + driver | Visual alert. |
| Battery | **LiFePO4 ~6 Ah** or 2×18650 Li-ion + protection | ≥24 h standby + ≥10 min siren (RR-3/TPM-8). |
| Charger/power-path | LiFePO4 charger (or TP4056 for Li-ion) + power-path | Run on mains, charge battery, switch to battery on loss. |
| Mains adapter | USB / 5 V supply | Mains source; its loss is sensed → reported (FR-10). |
| Sense | **INA219** (or divider + ADC) | `battery_mv` + mains presence → ICD-3 `STATUS`. |
| Enclosure | **≥ IP65** weatherproof box | Outdoor nodes (ER-1); document temp range. |
| Antenna | Band-correct LoRa antenna | 915/868 MHz; placement matters for PR-6 range. |

## 3. Network of devices
One hub coordinates N nodes over LoRa (star topology). No router or mains dependency for the alarm function
(ADR-2, pillar 1). Add nodes at: driveway/gate, each entry, and any far outbuilding within LoRa range.

## 4. Wiring & integration notes
- **Siren/strobe drivers:** use a MOSFET or relay rated above the siren's inrush; add a flyback diode/snubber
  for inductive loads. Never drive a siren directly from an MCU pin.
- **Common ground** between MCU, driver, and the 12 V bus; fuse the battery bus.
- **LoRa antenna:** keep it clear of the enclosure's metal and the siren wiring; mount externally on metal
  boxes.
- **Power-path:** validate seamless mains→battery switchover *before* relying on it (OS-4 drill).
- **Hub GPIO/USB-audio:** confirm the siren channel in TEST mode (FMEA F9) and the camera enumerates on boot
  (FR-1).
- **Keys:** flash each node with the per-network HMAC key from `node_keys.yaml` (git-ignored, SR-3); run the
  provisioning self-test (FMEA F20) before arming.

## 5. Dev vs production
- **Dev (what you have):** Jetson + USB webcam + a couple of ESP32+LoRa boards on the bench → exercises M1–M5
  end to end without the full power/enclosure build.
- **Production:** add LiFePO4/UPS, weatherproof enclosures, IP/PoE cameras + IR, and per-site LoRa profile
  tuning (PR-6).

## 6. Procurement checklist
- [ ] Regional LoRa band correct (915 US / 868 EU) on **every** radio + antenna.
- [ ] Battery chemistry/charger matched (LiFePO4 charger ≠ Li-ion charger).
- [ ] Siren/strobe driver rated for inrush; flyback/snubber present.
- [ ] Enclosures rated for placement (IP65+ outdoor).
- [ ] Cooling adequate for the Orin under sustained inference (R4).
