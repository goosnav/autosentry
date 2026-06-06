# CONOPS — Concept of Operations

**V-Model level:** L1 (top of the left arm). Validated against by **System Validation** (L1 right arm).
**Parent:** none (this is the root). **Children:** [REQUIREMENTS.md](REQUIREMENTS.md).

This document describes *what AutoSentry does operationally* and *for whom* — before any design. The
operational scenarios (OS-1..8) at the end are the acceptance set: v1 is "validated" when it behaves correctly
across all of them.

---

## 1. Mission

Give the people and property AutoSentry protects **advance warning and intelligent response** to a genuine
physical threat — primarily an armed or aggressive intruder — with enough lead time and information to take
protective action. Do this **reliably, offline, and without ever harming anyone**.

## 2. Operating environment

- **Sites:** homes, small businesses, remote/rural property, outbuildings. One hub; one or more cameras;
  several alarm nodes distributed across the property (driveway, gate, back door, barn, etc.).
- **Conditions:** day and night (IR/low-light), indoor and weather-exposed outdoor placements, intermittent
  or absent internet, and **adversarial conditions** — an intruder may attempt to cut mains power, cut the
  internet, or disable a node.
- **Connectivity:** the property may have Wi-Fi/LAN, but AutoSentry must not *depend* on it. Inter-device
  coordination is over **LoRa radio**, independent of any router or mains.

## 3. Stakeholders & needs (STK)

| ID | Stakeholder | Need |
|----|-------------|------|
| **STK-1** | Owner / occupant | Advance warning (seconds–minutes) of an armed/aggressive intruder, with time to take protective action. |
| **STK-2** | Owner / occupant | Keeps working when an intruder cuts power or internet. |
| **STK-3** | Owner / occupant | Does not cry wolf — benign visitors (mail, delivery, family) never trigger a major alarm. |
| **STK-4** | Owner / occupant | On a confirmed threat, every alarm node on the property sounds — network or not. |
| **STK-5** | Owner / occupant | Can intelligently talk to an intruder to de-escalate or make them leave. |
| **STK-6** | Public / bystanders / society | Never harms anyone; respects privacy and the law. |
| **STK-7** | Developer / company | A single developer can build v1 with AI assistance; full HW/SW/integration plans live on GitHub. |

## 4. Primary actors

- **Owner** — installs, arms/disarms, receives notifications, reviews events, sets sensitivity per zone.
- **Subject** — any person observed by a camera (could be benign or a threat; the system must distinguish).
- **Intruder (adversary)** — a subject assessed as an active threat; may also attack the system itself.
- **AutoSentry hub** — the autonomous decision-maker (within strict bounds; never physical force).
- **Alarm nodes** — distributed sirens/strobes that act on hub commands and self-alert if isolated.

## 5. System modes

- **DISARMED** — monitoring/recording per policy, but no alarms (e.g., owner home and aware).
- **ARMED** — full pipeline active; threats trigger the response chain.
- **TEST/MAINTENANCE** — exercises sirens/mesh/voice without treating it as a real event; for install & drills.
- **DEGRADED** — a subsystem has failed (camera, mesh, VLM, etc.); system continues with reduced capability
  and *loudly* reports the degradation (never silent).

Arming may be scheduled, per-zone, or manual. A **manual panic** input forces ALARM from any mode.

## 6. The response chain (nominal threat)

```
detect (stage-1) → assess (stage-2) → confirm (state machine)
   → [in parallel]  local siren+strobe  |  LoRa broadcast to all nodes  |  voice de-escalation  |  owner notify
   → log everything → de-escalate or persist until cleared by owner
```

Voice de-escalation **never replaces** the alarm or notification — it runs alongside them.

## 7. Operational scenarios (OS) — the validation set

> Each OS is executed as a scripted field drill in
> [VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md) §Validation.

- **OS-1 — Nominal monitoring.** Armed, no threat present for a long period. *Expected:* zero false alarms;
  normal logging; low/stable resource use. (Exercises PR-4, RR-2.)
- **OS-2 — Benign visitor.** A mail carrier / delivery driver / resident approaches and leaves. *Expected:*
  may enter WATCH/SUSPECT, but **no major alarm**, no mesh trigger. (Exercises PR-4, FR-5 — the "don't cry
  wolf" case.)
- **OS-3 — Armed-intruder approach.** A person displaying a weapon approaches an entry. *Expected:* stage-1
  trigger → stage-2 confirms armed → state machine reaches ALARM within latency budget → local siren+strobe,
  all nodes sound, voice engages, owner notified, full event log. (Exercises FR-3..9, FR-11..15, PR-1..3.)
- **OS-4 — Mains cut.** Intruder kills mains power mid-event (or pre-emptively). *Expected:* hub + nodes
  continue on battery; nodes report on-battery state; response chain unaffected. (Exercises RR-3, FR-10.)
- **OS-5 — Internet cut.** No WAN connectivity. *Expected:* full local detection + alarm + mesh + voice work;
  owner notifications queue and flush on reconnect. (Exercises STK-2, FR-13.)
- **OS-6 — Radio jam / node tamper.** A node is jammed, unplugged, or destroyed. *Expected:* hub detects the
  lost heartbeat within budget and raises a tamper/offline alert; the isolated node, if still powered, fails
  **safe** to local alert. **Never fails silent.** (Exercises SR-2, FR-9, PR-7.)
- **OS-7 — Multi-camera / multi-zone.** Threat in one zone, benign activity in another. *Expected:* correct
  per-zone attribution; alarm scoped/labeled by zone; no cross-talk. (Exercises FR-16, FR-5.)
- **OS-8 — Test/maintenance + panic.** Owner runs a test drill; owner hits panic. *Expected:* test exercises
  the chain without logging a real incident; panic forces ALARM immediately from any mode. (Exercises FR-14.)

## 8. Out of scope for v1 (recorded so it isn't assumed)

Professional monitoring-center integration, automatic emergency-services dialing (we *recommend* and require
human confirmation — SE-5), facial recognition / identity databases, any physical countermeasure, and
multi-site fleet management. These may be revisited post-v1 and must each pass the five pillars in
[../CLAUDE.md](../CLAUDE.md) §0.
