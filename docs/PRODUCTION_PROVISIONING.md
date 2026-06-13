# PRODUCTION_PROVISIONING — Building & Shipping Units Fast

**Audience:** you, manufacturing AutoSentry systems to sell. This turns the one-off
[HARDWARE_SETUP.md](HARDWARE_SETUP.md) runbook into a **repeatable, ~20-minute-per-unit**
assembly line with a per-deployment secret, a QA gate, and a customer handoff. Security
posture is non-negotiable: **one unique mesh key per customer property** (never a fleet-wide
key), keys never committed, processing stays on-device (pillars 3–5, SR-1/SR-3).

> A "unit" = one **deployment** = one hub + its N alarm nodes for **one customer property**.
> Everything in a unit shares one mesh key; different units get different keys.

---

## 0. One-time: build a "golden" hub image

Do the slow steps once, then clone the disk image for every hub:

1. Follow [HARDWARE_SETUP.md](HARDWARE_SETUP.md) §B on a reference Jetson: JetPack, Ollama, the
   repo at `/opt/autosentry`, the venv, **and** `scripts/download_models.py` so the models are
   baked in (the unit ships ready to run offline).
2. Install the service unit but leave it **disabled** and the config **unkeyed/disarmed**.
3. Capture the disk image (`dd`/NVIDIA tools). This **golden image** is your per-hub starting
   point — no network, no model download, no pip install at the bench.

Re-bake the image only when you bump the software or the model set. Track its version.

---

## 1. Per-unit assembly line

For each customer unit, run these stations. The commands assume the repo at `/opt/autosentry`
and PlatformIO on the flashing workstation.

### Station 1 — flash the hub disk
Clone the golden image to the unit's NVMe. (No per-unit software install — it's all in the
image.)

### Station 2 — mint the deployment key (once per unit)
```bash
cd /opt/autosentry
KEY="$(hub/.venv/bin/python scripts/provision.py new-key)"
echo "$KEY"        # record this in your provisioning log / customer record (treat as a secret)
```

### Station 3 — key the hub
On the unit's hub (or by mounting its disk):
```bash
hub/.venv/bin/python scripts/provision.py hub-env --key "$KEY" --out /etc/autosentry/mesh.env
# writes AUTOSENTRY_MESH_KEY=... at mode 0600; the systemd unit reads it via EnvironmentFile
```

### Station 4 — flash the nodes (unique address each) + the gateway
```bash
scripts/provision_node.sh --env lilygo_t3s3 --addr 1 --key "$KEY"   # node 1
scripts/provision_node.sh --env lilygo_t3s3 --addr 2 --key "$KEY"   # node 2
scripts/provision_node.sh --env lilygo_t3s3 --addr 3 --key "$KEY"   # node 3 …
scripts/provision_node.sh --env hub_gateway --gateway              # the hub's USB radio
```
- **Addresses must be unique within the unit** (1..N; 0 is the hub).
- A node flashed without the real key refuses to boot (SR-3) — your QA catches a missed key.
- Label each node's enclosure with its address.

### Station 5 — set the site config
Edit `/etc/autosentry/config.yaml` for the unit: `capture.sources`/`zones` (1:1), `comms.port`,
`comms.enabled: true`, `detection.weapon_model` (your shipped weapon head), regional band on
the radios. Leave `armed: false` (the installer arms after on-site self-test).

---

## 2. QA gate (every unit must pass before it ships)

Run the bench self-test ([HARDWARE_SETUP.md](HARDWARE_SETUP.md) §E) and tick all of these:

- [ ] Hub boots the service clean: `journalctl -u autosentry` shows models present, camera
      enumerated, pipeline looping, **no** "WEAPON DETECTION IS DISABLED" warning (weapon head
      configured).
- [ ] Dashboard reachable on loopback; zone shows `NORMAL`.
- [ ] **Every** node appears **online** under Mesh nodes and ACKs heartbeats.
- [ ] Test-mode pulse fires the hub siren **and every node siren** (FMEA F9 / OS-8).
- [ ] Kill a node → hub marks it offline ≤30 s (SR-2/PR-7). Pull a node's mains → reports
      on-battery (FR-10).
- [ ] Pull the hub mains → hub rides through on its UPS (OS-4).
- [ ] `python scripts/bench_lora.py --port <gw>` round-trip passes (signed + ACK).
- [ ] Mesh key recorded in the customer record; **no** key written anywhere in the repo
      (`git status` clean; `git grep` finds no key).
- [ ] Firmware built from a tagged release; `pio test -e native` green on that build.

A unit that fails any item does not ship. Log the QA result against the unit serial.

---

## 3. Customer handoff

Ship with:
- The hub (disarmed), nodes (labelled by address), antennas, PSUs/UPS, mounting hardware.
- A one-page install card: mount locations, power-up order, how to reach the dashboard, how to
  **arm** (per [HARDWARE_SETUP.md](HARDWARE_SETUP.md) §F–G), and the shadow-mode-first advice.
- The owner's notification endpoint configured in `notify.endpoint` (their own push service —
  AutoSentry sends event metadata only, no images; SE-4).

**Key custody:** give the customer their mesh key (sealed) and tell them it's required to add
nodes later. Store your copy encrypted, scoped to that one customer. **Never** reuse a key
across customers — a single compromise must never reach beyond one property (SR-1/SR-3).

---

## 4. Field service

- **Add a node to an existing unit:** retrieve that unit's key, flash the new node with the
  next free address (`provision_node.sh --addr N --key "$KEY"`), mount, confirm it shows online
  on the dashboard.
- **Replace a node:** flash the replacement with the **same address and key** as the one it
  replaces.
- **Rotate the key (suspected compromise):** mint a new key, re-run Stations 3–4 for the hub
  and **every** node on that property, update the customer record. (Per-property keying means
  this is scoped to one site.)
- **Software/model update:** re-bake the golden image (§0), re-image hubs; node firmware via
  `provision_node.sh` from the new tagged release.

---

## 5. Security & compliance checklist (per unit)

- [ ] Unique per-property mesh key (SR-1/SR-3); not the placeholder; not committed.
- [ ] Regional LoRa band correct on every radio + antenna (legal + functional).
- [ ] Processing on-device; `notify` points only at the owner's endpoint; no third-party
      analytics/telemetry added (SE-4, pillar 4).
- [ ] No autonomous-harm wiring — siren/strobe/voice only; nothing that acts physically against
      a person (SE-1, pillar 2).
- [ ] Recording/retention/consent configured per the customer's jurisdiction
      ([SAFETY_ETHICS_LEGAL.md](SAFETY_ETHICS_LEGAL.md)).
- [ ] Unit serial ↔ key ↔ QA result recorded in your provisioning log.

---

## Tooling reference

| Tool | What it does |
|------|--------------|
| `scripts/provision.py new-key` | mint a fresh URL-safe per-deployment mesh key |
| `scripts/provision.py hub-env --key K [--out PATH]` | write the hub's `AUTOSENTRY_MESH_KEY` env (0600) |
| `scripts/provision.py node-flags --key K --addr N` | the PlatformIO build flags for a node (used by the flasher) |
| `scripts/provision_node.sh --env E --addr N --key K` | flash an alarm node with key + address |
| `scripts/provision_node.sh --env hub_gateway --gateway` | flash the hub's USB radio (no key) |
| `scripts/download_models.py` | fetch the on-device models (baked into the golden image) |
| `scripts/bench_lora.py --port P` | hub↔node signed round-trip QA check |
