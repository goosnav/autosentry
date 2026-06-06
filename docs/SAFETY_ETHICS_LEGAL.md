# SAFETY, ETHICS & LEGAL

**V-Model level:** L4 design constraints elevated to **pillars** (see [../CLAUDE.md](../CLAUDE.md) §0).
**Requirements:** SE-1..5, SR-3, SR-4. This document governs what AutoSentry is allowed to do. It outranks
features. When a request conflicts with it, the request loses.

AutoSentry is a **defensive forewarning system**. Its purpose is to give people protecting their home or
property *time and information*. It is not a weapon, not a punishment device, and not a surveillance dragnet.

---

## 1. The bright line: no autonomous physical force (SE-1, pillar 2)
AutoSentry's only outputs are **alarms (sound + light), synthesized speech, and notifications.** There is, and
will be, **no interface to any mechanism that applies physical force to a person** — no locks-as-traps, no
projectiles, no electrification, no "active countermeasures."
- Verified by **inspection at every milestone** (SE-1).
- PRs or hardware adding such capability are rejected on principle (ADR-5, immutable).
- The voice agent has no actuator control beyond the speaker (FR-12, SE-1).

## 2. False positives are a safety issue, not just UX (PR-4, R1, R3)
Falsely flagging an innocent person as a threat can cause real harm (panic, confrontation, discrimination).
So:
- The two-tier detector + confirmation window exist to make a major alarm **hard to trip** (FR-5).
- **Shadow mode** before arming: detection-only, to learn a site's benign patterns and tune thresholds.
- A major alarm is a Sev-high event; weakening confirmation requires an eval proving FP-rate holds.

## 3. Bias & fairness (SE-3, R3)
- The system must key on **objects and behavior (a weapon, an approach)**.

## 4. Privacy & data minimization (SE-4)
- **On-device processing** — frames are analyzed locally; no cloud vision in the critical path (ADR-4).
- **No biometric identity database in v1** — no face recognition / persistent identity matching.
- **Retention controls:** recordings/events have configurable retention; default minimal. Logs hold what's
  needed to audit a decision (FR-15), not more.
- **No covert mode:** the product does not hide that recording is occurring; signage guidance is part of
  install docs.
- **Telemetry:** none by default; any future telemetry requires an ADR and opt-in (pillar 4).

## 5. Legal compliance (owner-facing, install docs)
Laws vary by jurisdiction; the product and its documentation must help owners stay lawful:
- **Recording/consent:** audio recording in particular is restricted in many places (two-party-consent
  states; the EU). Voice-agent audio capture and any recording must be configurable and clearly documented.
- **Camera placement:** must point at the owner's own property; do not surveil neighbors/public spaces beyond
  what's lawful.
- **Data protection:** if commercialized, GDPR (EU), CCPA/CPRA (California), BIPA (Illinois, biometrics) and
  similar apply — another reason for on-device + no-biometrics in v1.
- **Alarms/nuisance:** comply with local false-alarm and noise ordinances; the anti-false-positive design and
  TEST mode support this.
> This is engineering guidance, **not legal advice.** Commercial deployment requires review by qualified
> counsel in each market. Record those reviews as ADRs.

## 6. Emergency escalation (SE-5)
Contacting authorities is **recommended to the owner with human confirmation required** — AutoSentry does not
auto-dial 911/emergency services in v1 (ConOps §8). This avoids automated false reports and keeps a human in
the loop on the highest-consequence action.

## 7. Acceptable use (R13)
AutoSentry is for **lawful defensive protection** of one's own people and property. It must not be used for
harassment, stalking, unlawful surveillance, or targeting individuals. The absence of covert mode and the
on-device design are deliberate guardrails against misuse.

## 8. Honesty in deterrence (SE-2)
The voice agent may state true facts to deter ("you are being recorded," "the owner has been alerted") **only
when those are actually true** (they fire in parallel). It must not fabricate capabilities or make illegal
threats (see [VOICE_AGENT.md](VOICE_AGENT.md) §5).

## 9. Review cadence
This document is reviewed at every milestone exit and whenever a model, dataset, or output channel changes.
SE-1..5 appear in the RTM and must remain ☑.
