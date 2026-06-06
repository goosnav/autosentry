# SECURITY — Product Threat Model

**V-Model level:** L4. **Requirements:** SR-1..4, FR-9, SE-4; pillar 5 (the system defends itself). This is
the threat model of **AutoSentry itself** — how an adversary might attack the security system, and how we
resist. (For physical-threat *detection*, see [VISION_PIPELINE.md](VISION_PIPELINE.md).)

A security product that can be trivially disabled is worse than none — it gives false confidence. We assume a
**motivated adversary who knows AutoSentry is present.**

---

## 1. Assets to protect
- **Availability** of the detection→alarm chain (the core function).
- **Integrity** of mesh commands (no forged alarms or forged "all-clear").
- **Confidentiality** of recordings/events and the pre-shared keys (SE-4, SR-3).
- **Trustworthiness** of alerts (no spoofed notifications).

## 2. Adversaries & capabilities
1. **Physical intruder** — can cut mains, cut internet, smash/unplug a node, obstruct a camera.
2. **RF attacker** — can sniff/replay/jam the LoRa band near the site.
3. **Network attacker** — present only if the hub is networked for notifications (non-critical path).
4. **Insider/misuse** — someone with legitimate access misusing the system (covered in
   [SAFETY_ETHICS_LEGAL.md](SAFETY_ETHICS_LEGAL.md) §7).

## 3. Threats → mitigations (STRIDE-flavored)
| Threat | Vector | Mitigation | Req |
|--------|--------|------------|-----|
| **Spoofing** | Forge an ALARM or "all-clear" over LoRa | HMAC-authenticated frames; no key ⇒ no valid frame | SR-1 |
| **Tampering/Replay** | Capture & replay a frame | Per-src monotonic counter; replays rejected | SR-1 |
| **Repudiation** | Dispute what happened | Append-only event log w/ timestamps + keyframes + actions | FR-15 |
| **Information disclosure** | Read recordings/keys | On-device storage; keys git-ignored + provisioned at flash; retention limits | SE-4, SR-3 |
| **Denial of service (RF jam)** | Jam the band | Spread-spectrum sub-GHz; **heartbeat-loss → fail-safe alert**; jam detection | SR-2, FR-9 |
| **Denial of service (power)** | Cut mains | Battery backup + mains-loss reporting (observable, not silent) | FR-10, RR-3 |
| **Denial of service (smash node)** | Destroy a node | Heartbeat loss ⇒ offline/tamper alert ≤30 s; other nodes unaffected | SR-2, PR-7, RR-5 |
| **Camera tamper** | Obstruct/blind/spray a camera | Scene-tamper heuristic ⇒ alert; multi-cam overlap | RR-4, FMEA F2 |
| **Elevation/remote exploit** | Attack a network service | **No remote attack surface in the critical path** (local-first) | SR-4 |

## 4. Key security principles
- **No unauthenticated control path.** Anything that can cause the system to alarm, clear, or reconfigure is
  authenticated (SR-1). Never add a bypass "for convenience."
- **Fail loud, fail safe.** Every DoS attempt converts to an *alert*, because going silent is exactly what an
  attacker wants (pillar 1). A node that loses the hub escalates rather than mutes.
- **Minimize attack surface.** The critical path has no inbound network listener (SR-4). Notifications are
  outbound, best-effort, off-path (ICD-6).
- **Defense in depth.** Independent alarm channels (local ∥ mesh ∥ voice ∥ notify) mean disabling one doesn't
  disable the function.
- **Secret hygiene.** Pre-shared keys never enter the repo (`.gitignore`), are provisioned at flash, and a
  provisioning self-test validates them before arming (FMEA F20).

## 5. Residual risks (accepted, tracked)
- **Sophisticated wideband jamming** can deny RF; we *detect* and fail-safe but cannot *prevent* it (R5).
- **Simultaneous destruction of hub + all nodes** before any alert exceeds v1's protection; mitigated by
  fast heartbeat detection and multiple independent nodes, revisited with multi-hub post-v1 (R10).
- **Determined insider misuse** is a policy/legal control, not a technical one (R13).
These are recorded in [RISK_REGISTER.md](RISK_REGISTER.md) with owners.

## 6. Verification
SR-1 by HMAC/replay test vectors (L4) + bench (L3); SR-2/PR-7 by OS-6 jam/tamper drill; SR-3 by inspection;
SR-4 by an attack-surface review of the critical path. See
[VERIFICATION_AND_VALIDATION.md](VERIFICATION_AND_VALIDATION.md).
