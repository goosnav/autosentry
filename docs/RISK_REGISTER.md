# RISK REGISTER — Technical Risk Management

**Crosscutting SE process.** Likelihood (L) and Consequence (C) on a 1–5 scale; **Score = L×C**. Review each
milestone; close a risk only when its mitigation is implemented *and* verified (cite the V&V evidence).

Scoring guide — L: 1 rare … 5 likely. C: 1 negligible … 5 mission-failure/safety. Bands: **≥15 High (red)**,
**8–14 Med (amber)**, **≤7 Low (green)**.

---

| ID | Risk | L | C | Score | Band | Mitigation | Req link | Verify | Owner | Status |
|----|------|---|---|-------|------|------------|----------|--------|-------|--------|
| **R1** | False positives erode trust / users disable the system | 4 | 5 | 20 | High | Two-tier detector + state machine w/ confirmation window; per-zone tunable sensitivity; optional human-confirm; benign-suite eval gate | FR-4, FR-5, PR-4 | OS-2 drill; TPM-4 | — | Open |
| **R2** | False negative — a real armed threat is missed | 2 | 5 | 10 | Med | Multi-frame tracking; conservative thresholds; redundant cues (weapon + behavior); VLM-timeout biases toward alert; continuous benchmark eval | FR-3, PR-5 | TPM-5 | — | Open |
| **R3** | Demographic bias in "threat" classification | 3 | 5 | 15 | High | Balanced/curated datasets; bias eval across slices; rely on weapon/behavior signals over appearance; audit log | SE-3 | SE-3 analysis | — | Open |
| **R4** | Jetson thermal throttling degrades FPS/latency | 3 | 3 | 9 | Med | Thermal monitoring; right-size models (TensorRT/quant); active cooling; degrade gracefully on throttle | PR-1, RR-4 | TPM-1 under load | — | Open |
| **R5** | Radio jamming / 2.4 GHz-band interference | 2 | 4 | 8 | Med | LoRa spread-spectrum + sub-GHz; heartbeat-loss fail-safe; jam detection → alert; configurable channel | SR-2, FR-9 | OS-6 drill | — | Open |
| **R6** | Replay/spoof of mesh commands (fake clear / fake alarm) | 2 | 5 | 10 | Med | HMAC auth + monotonic counter + ACK; pre-shared keys; reject+log on mismatch | SR-1 | HMAC vectors; SR-1 test | — | Open |
| **R7** | Intruder cuts mains power | 3 | 5 | 15 | High | Battery backup on hub + nodes; mains-loss reporting; fail-operational supervision | RR-3, FR-10 | OS-4 drill; TPM-8/9 | — | Open |
| **R8** | Legal/privacy exposure (recording law, GDPR/BIPA, liability) | 3 | 5 | 15 | High | On-device processing; retention/consent controls; documented policy; no biometric ID in v1 | SE-4 | SE-4 inspection | — | Open |
| **R9** | Voice agent says something harmful, illegal, or escalating | 3 | 4 | 12 | Med | Constrained persona + guardrails; content filter; full logging; voice never sole response | SE-2, FR-12 | SE-2 demo | — | Open |
| **R10** | Hub is a single point of failure | 3 | 4 | 12 | Med | HW+SW watchdog auto-recovery; nodes fail-safe independently; multi-hub on the post-v1 roadmap | RR-1, RR-5 | OS-6; RR-1 test | — | Open |
| **R11** | VLM latency spikes or hallucinated assessments | 3 | 3 | 9 | Med | Stage-2 only on trigger; schema validation + bounds; hard timeout → fall back to stage-1 conservative decision | FR-4, RR-4 | FR-4 test; PR-2 | — | Open |
| **R12** | Weapon-detection dataset scarcity / domain gap (night, occlusion, odd angles) | 3 | 4 | 12 | Med | Curate + augment; collect site data; hard-negative mining; staged rollout w/ shadow mode before arming | FR-3, PR-5 | TPM-5 by condition | — | Open |
| **R13** | Misuse of the product (harassment, unlawful surveillance) | 2 | 4 | 8 | Med | Acceptable-use policy; on-device only; no covert mode; documentation emphasizes lawful defensive use | SE-4, SE-1 | inspection | — | Open |
| **R14** | Single-developer build complexity overwhelms v1 schedule | 3 | 3 | 9 | Med | Milestone de-risking (M0→M6); AI-assisted dev; reuse mature OSS (YOLO/Ollama/Piper/LoRa libs); TRL-ordered spikes | STK-7 | roadmap reviews | — | Open |

## Risk-burndown by milestone
- **M0:** R8, R13 (policy/docs baseline); R6 spec locked (ICD-3).
- **M1:** R4, R12 (vision viability on-target); R2 baseline eval.
- **M2:** R1, R3 (false-positive + bias gates before any arming).
- **M3:** R5, R6, R10 (mesh security + resilience).
- **M4:** R7, R10 (power + supervision).
- **M5:** R9 (voice guardrails).
- Track each as ☑ only with V&V evidence; a High-band risk blocks the milestone exit until reduced.
