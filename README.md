# AutoSentry

**Local-first intelligent security.** AutoSentry turns one or more cameras into a smart sentry that detects
genuine physical threats (an armed or aggressive person), sounds a major alarm, triggers a mesh of
battery-backed alarm nodes around the property **over radio (LoRa), not the network**, and can engage an
intruder with an intelligent, vision-aware voice agent that tries to de-escalate the situation.

The entire stack runs **offline on edge hardware** (NVIDIA Jetson Orin) so it keeps working even if an
intruder cuts the power or the internet.

> **What AutoSentry is — and is not.** AutoSentry *detects, alerts, and de-escalates*. It **never** takes
> physical action against a person. It is a forewarning and deterrence system, engineered to give the people
> it protects time and information. See [docs/SAFETY_ETHICS_LEGAL.md](docs/SAFETY_ETHICS_LEGAL.md).

---

## How it works

```
cameras → [Stage-1 YOLO + tracking] → [Stage-2 VLM threat assessment] → THREAT STATE MACHINE
                                                                              │
                  ┌───────────────────────────┬───────────────────────────┬──┘
                  ▼                            ▼                           ▼
            local siren/strobe          voice de-escalation        LoRa mesh → alarm nodes
                                        (STT → LLM → TTS)           (signed, ACK, heartbeat)
```

A **two-tier detector** keeps false alarms near zero: a fast YOLO model runs every frame and only escalates
to a heavier vision-language model when something looks wrong. A **state machine** with confirmation windows
turns noisy detections into a stable threat level before any alarm fires.

## Repository layout

| Path | What's there |
|------|--------------|
| [`docs/`](docs/) | The engineering "bible" — ConOps, requirements, architecture, interfaces, V&V, risk, FMEA, and per-subsystem design docs |
| [`hub/`](hub/) | The Jetson "brain" — Python package: capture → detection → reasoning → state → alarm/comms/voice/notify |
| [`firmware/alarm_node/`](firmware/alarm_node/) | ESP32 + LoRa alarm-node firmware (PlatformIO). Same code base runs the hub's USB radio gateway. |
| [`hardware/`](hardware/) | Bill of materials, wiring, enclosure notes |
| [`scripts/`](scripts/) | Provisioning, model download, flashing, LoRa bench test |
| [`deploy/`](deploy/) | systemd units + watchdog for fail-operational supervision |

## Engineering method

AutoSentry is developed against the **NASA V-Model**: every capability traces from a stakeholder need →
a numbered, verifiable requirement → design → implementation → a verification/validation activity. Start
here:

1. [docs/CONOPS.md](docs/CONOPS.md) — what the system does, operationally (the 8 scenarios we validate against)
2. [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — the numbered SRD
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how it's built
4. [docs/INTERFACES.md](docs/INTERFACES.md) — the ICDs (every hardware/software seam)
5. [docs/VERIFICATION_AND_VALIDATION.md](docs/VERIFICATION_AND_VALIDATION.md) — how we prove it works
6. [docs/ROADMAP.md](docs/ROADMAP.md) — milestones M0–M6

**If you are an AI agent or a new contributor, read [CLAUDE.md](CLAUDE.md) first.** It is the working
constitution for this repo.

## Quickstart (development)

> Full provisioning is in [docs/HARDWARE.md](docs/HARDWARE.md) and `scripts/`. This is the dev-loop summary.

```bash
# Hub (Python 3.10+; a Jetson, or a Mac/Linux dev box for non-vision work)
cd hub
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # unit tests (L4 verification)
python -m autosentry.app --source 0      # run against webcam 0 (or --source path/to/clip.mp4)

# Alarm node firmware (ESP32 + LoRa via PlatformIO)
cd firmware/alarm_node
pio run                 # build
pio run -t upload       # flash a connected board
pio test                # firmware unit tests

# LoRa bench loopback (hub radio gateway <-> one node)
python scripts/bench_lora.py --port /dev/ttyUSB0
```

## Status

**M0 — Scaffold & baseline.** Repo structure, engineering baseline docs, and code/firmware skeletons are in
place. Subsystems are implemented milestone by milestone per [docs/ROADMAP.md](docs/ROADMAP.md); a requirement
is only "done" when its row in the [traceability matrix](docs/VERIFICATION_AND_VALIDATION.md) passes.

## License

TBD (project is pre-release).
