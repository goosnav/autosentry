# HARDWARE_SETUP — From Parts to an Armed System (Exact Steps)

**Audience:** you, setting up **one** AutoSentry system end-to-end — hub + cameras + one or
more alarm nodes. This is the click-by-click runbook. For *what to buy* see
[HARDWARE.md](HARDWARE.md); for *manufacturing many units fast* see
[PRODUCTION_PROVISIONING.md](PRODUCTION_PROVISIONING.md); for *why* see the bibles.

> ⚠️ **Before anything:** confirm your **regional LoRa band** — **915 MHz (US)** / **868 MHz
> (EU)** — on every radio and antenna. A band mismatch means no mesh, and TX out of band is
> illegal. AutoSentry detects, alerts, and de-escalates — it must **never** be wired to take
> physical action against a person (pillar 2, SE-1).

The whole flow: **A.** assemble → **B.** flash the hub → **C.** generate the mesh key →
**D.** flash the nodes → **E.** first boot + self-test → **F.** field placement → **G.** arm.
Budget ~2–3 hours for your first unit.

---

## A. Bench assembly (do this first, indoors, on mains)

You'll bring the whole system up on the bench before mounting anything.

1. **Hub:** seat the NVMe SSD in the Jetson Orin, attach the active cooler, connect the USB
   webcam (dev) or CSI/RTSP camera (prod), and the USB mic + powered speaker.
2. **Hub radio:** plug the ESP32+LoRa gateway board into the Jetson via USB (it becomes
   `/dev/ttyUSB0` or `/dev/ttyACM0`). Screw on the band-correct antenna **before** powering —
   transmitting without an antenna can damage the radio.
3. **Each alarm node:** wire siren + strobe through their MOSFET/relay driver (never off an MCU
   pin), the INA219 across the battery/mains, and the LoRa antenna. Keep the antenna clear of
   the metal enclosure and the siren wiring. **Don't connect the battery yet** — flash first.
4. Power the Jetson from its supply; keep nodes on USB/bench power for now.

---

## B. Flash & install the hub (Jetson Orin)

1. **Flash JetPack** (Ubuntu + CUDA/TensorRT) with NVIDIA SDK Manager or a JetPack SD image,
   per NVIDIA's instructions for your board. Boot to a desktop/terminal and update:
   ```bash
   sudo apt update && sudo apt -y upgrade
   sudo apt -y install python3-venv python3-pip git
   ```
2. **Install Ollama** (serves the stage-2 VLM and the voice LLM locally):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   systemctl --now enable ollama        # local server on 127.0.0.1:11434
   ```
3. **Get the code and create the venv:**
   ```bash
   sudo mkdir -p /opt/autosentry && sudo chown "$USER" /opt/autosentry
   git clone <your-repo-url> /opt/autosentry
   cd /opt/autosentry/hub
   python3 -m venv .venv
   .venv/bin/pip install -e .            # add '.[voice]' for STT/TTS extras on the hub
   ```
4. **Fetch the models** (one-time; needs network — afterward the box runs offline):
   ```bash
   cd /opt/autosentry
   hub/.venv/bin/python scripts/download_models.py        # YOLO + VLM + voice into models/
   ```
   This is idempotent and also runs automatically on first `autosentry` boot when
   `models.auto_download` is on. `--list` shows what the current config needs.
5. **Create the hub config** at `/etc/autosentry/config.yaml`. Start from the shipped default
   and edit it for your site:
   ```bash
   sudo mkdir -p /etc/autosentry
   sudo cp /opt/autosentry/hub/autosentry/config.yaml /etc/autosentry/config.yaml
   sudoedit /etc/autosentry/config.yaml
   ```
   Set at minimum:
   - `capture.sources` and `capture.zones` — **one source per zone, 1:1** (e.g. `["0"]` +
     `["front"]`; the hub refuses to start on a mismatch).
   - `comms.port` — your gateway's serial device (`/dev/ttyUSB0`).
   - `comms.enabled: true` once the radio is connected.
   - `detection.weapon_model` — path to your fine-tuned weapon head. **If left `null`, stage-1
     weapon detection is OFF** and the hub logs a loud warning at boot (base COCO has no
     weapon classes).
   - Leave `armed: false` for now (you arm after self-tests pass, OS-8).

---

## C. Generate the mesh key (once per deployment)

The hub and every node on **one property** share one HMAC key. It is **never committed** and
lives only in the environment on the hub and in flash on the nodes (SR-3).

```bash
cd /opt/autosentry
hub/.venv/bin/python scripts/provision.py new-key            # prints a fresh random key
```
Store the hub's copy out-of-tree and lock it down:
```bash
sudo install -d -m 700 /etc/autosentry
printf 'AUTOSENTRY_MESH_KEY=%s\n' "<paste-the-key>" | sudo install -m 600 /dev/stdin /etc/autosentry/mesh.env
```
Keep the key somewhere safe (a password manager) — you need the **same** key for every node
below, and to add nodes later.

---

## D. Flash the alarm nodes (and the hub gateway)

Install PlatformIO (`pip install platformio`) on any workstation, then from
`firmware/alarm_node/`:

1. **Each alarm node** — flash with the shared key and a **unique address per node**
   (`-DNODE_ADDR=N`, N ≥ 1). The helper script wraps this:
   ```bash
   cd /opt/autosentry
   scripts/provision_node.sh --env lilygo_t3s3 --addr 1 --key "<the-mesh-key>"
   scripts/provision_node.sh --env lilygo_t3s3 --addr 2 --key "<the-mesh-key>"   # next node
   ```
   A node flashed without a real key (the committed placeholder) **refuses to boot** and
   blinks its strobe — that's the intended fail-loud (SR-3).
2. **The hub gateway** (the radio plugged into the Jetson) — flash the gateway role; it needs
   **no** key (it's a dumb modem):
   ```bash
   scripts/provision_node.sh --env hub_gateway --gateway
   ```
3. Watch the serial monitor (`pio device monitor`) on a node — after boot it should log
   heartbeats and, once the hub is running, ACK them.

---

## E. First boot + self-test (still on the bench)

1. **Run the hub in the foreground** to watch it come up:
   ```bash
   cd /opt/autosentry/hub
   AUTOSENTRY_MESH_KEY="<the-mesh-key>" .venv/bin/python -m autosentry.app \
       --config /etc/autosentry/config.yaml --source 0
   ```
   You should see: models present, camera enumerated, the pipeline looping, and (with
   `comms.enabled`) heartbeats to the nodes.
2. **Open the dashboard** (if `dashboard.enabled: true`) at `http://127.0.0.1:8088` — confirm
   the zone shows `NORMAL`, and each node appears under **Mesh nodes** as online.
3. **Walk-test detection:** step in front of the camera; the zone should rise to `WATCH`. (Full
   weapon/threat escalation needs your fine-tuned `weapon_model`.)
4. **Test the alarm path without latching:** flip **test mode** on the dashboard (or send a
   panic on a disarmed zone) — the local siren and every node's siren should pulse, and the
   dashboard should show the event. This is OS-8 / FMEA F9.
5. **Fail-safe drill (OS-6):** power off a node → within ~30 s the hub marks it **offline**
   (an alarm in itself); unplug the node's mains → it reports **on-battery** (FR-10).
6. **Install the service** so it auto-starts and is watchdog-supervised:
   ```bash
   sudo useradd -r -s /usr/sbin/nologin autosentry 2>/dev/null || true
   sudo cp /opt/autosentry/deploy/autosentry.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now autosentry
   journalctl -u autosentry -f          # watch it run
   ```

---

## F. Field placement

- **Hub:** central, ventilated, on the LiFePO4 + DC-UPS so it rides through a mains cut; camera
  covering the approach; speaker aimed at the engagement zone; mic near it.
- **Nodes:** one at the driveway/gate, one at each entry, one at any far outbuilding **within
  LoRa range** — verify each node still ACKs from its mounted location (this is the PR-6 range
  check). Mount the antenna vertical and clear of metal.
- **Outdoor nodes:** in their ≥IP65 enclosures; connect the battery and confirm the power-path
  switches cleanly mains→battery (OS-4) before you button it up.

---

## G. Shadow-run, then arm

1. **Shadow mode (recommended):** leave `armed: false` for a few days and review the dashboard
   event log to collect site-specific false triggers; tune `trigger.*` and
   `state.arm_confidence` accordingly. Do **not** lower thresholds without checking the benign
   suite — a false alarm is a Sev-high defect (pillar 3).
2. **Arm:** set `armed: true` (or arm per-zone from the dashboard) once self-tests pass.
3. Re-run the OS-3 staged-approach and the OS-4/OS-5 (pull mains, pull internet) drills from
   [TESTING.md](TESTING.md) to confirm the system stays operational and loud.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Hub won't start, "sources/zones must be 1:1" | mismatched `capture.*` lists | make `sources` and `zones` the same length |
| "WEAPON DETECTION IS DISABLED" at boot | `detection.weapon_model: null` | set a fine-tuned weapon head |
| Nodes never ACK | wrong/again band, key mismatch, or `comms.enabled: false` | same band everywhere; same `AUTOSENTRY_MESH_KEY` on hub + nodes; enable comms |
| Node blinks strobe, won't run | flashed with the placeholder key | reflash with `provision_node.sh --key …` |
| Model download hangs/fails | no network or bad mirror | downloads now time out (30 s) and degrade; re-run `download_models.py` when online |
| Voice silent | `voice.enabled: false` or models missing | enable voice; re-run model download with the `[voice]` extra |
| Mesh key error at hub start | `AUTOSENTRY_MESH_KEY` unset | source `/etc/autosentry/mesh.env` (the service does this automatically) |
