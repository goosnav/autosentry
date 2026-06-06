# VISION_PIPELINE — Detailed Design

**V-Model level:** L4 (detailed design). **Parent:** [ARCHITECTURE.md](ARCHITECTURE.md) §3. **Requirements:**
FR-3, FR-4, PR-1, PR-2, PR-4, PR-5, SE-3, ER-2. **Modules:** `hub/autosentry/{capture,detection,reasoning,state}`.

This is the design of record for the two-tier vision system and its evaluation. Ends with the **component
test definition** (the L4 right-arm entry).

---

## 1. Pipeline

```
capture ─► detection (stage-1) ─► tracker ─► trigger policy ─► reasoning (stage-2) ─► state machine
 Frame      Detection[]            Track[]     bool/why          ThreatAssessment       ThreatState
```

## 2. Stage-1 — fast detector (FR-3, PR-1)
- **Model:** Ultralytics YOLO (v8 or v11), exported to **TensorRT (FP16/INT8)** for the Orin. ONNX Runtime is
  the portable fallback for dev on non-Jetson machines.
- **Classes:** `person` + weapon set `{handgun, rifle, knife}` (extensible). Person uses COCO weights;
  weapons require a fine-tuned head (see §6).
- **Tracker:** **ByteTrack** assigns a persistent `track_id` per subject so downstream logic reasons over
  **time**, not single frames. Track holds bbox history, first/last seen, class votes.
- **Throughput:** target ≥15 FPS @1080p (PR-1/TPM-1). Lever knobs: input size, model scale (n/s/m), INT8
  calibration, frame-skip with track interpolation. All in `config.yaml`.
- **Output:** `Detection[]` + `Track[]` per frame (ICD-7).

## 3. Trigger policy (stage-1 → stage-2)
Stage-2 is expensive, so we gate it. A track triggers stage-2 when **any** holds (all thresholds in config):
- a **weapon** class is associated with the track above `conf_weapon`;
- the track is a **person in a restricted zone** during a restricted time window;
- **loitering** — dwell time in zone > `loiter_s`;
- **rapid approach** — closing speed toward a configured entry > `approach_px_s`.
Triggering captures **N keyframes** (best-quality crops + context frame) for stage-2. A per-track cooldown
avoids re-triggering on every frame.

## 4. Stage-2 — VLM threat assessment (FR-4, PR-2)
- **Model:** a vision-language model (Qwen2-VL 2B/7B or Llama-3.2-Vision) served by **Ollama** or
  **llama.cpp** locally. Sized to co-reside with stage-1 on the Orin (R4); 2B class is the default, 7B if
  headroom allows or on AGX.
- **Prompt:** structured, asks for a **strict JSON** object and nothing else:
  ```json
  {"armed": true, "weapon_type": "rifle", "intent": "approaching entry, weapon raised",
   "confidence": 0.86, "description": "Adult holding a long gun, ~5 m from front door, advancing."}
  ```
- **Validation (FMEA F7):** output is parsed against the `ThreatAssessment` schema with bounds checks
  (`0≤confidence≤1`, enum `weapon_type`). Malformed → one retry → else fall back to stage-1 conservative call
  and log the raw output.
- **Timeout (FMEA F6):** hard `reasoning.timeout_s`; on timeout, bias toward alert (do not silently drop) and
  record DEGRADED.
- **Reuse:** the `description` + `intent` feed the voice agent's per-turn context (FR-11) — one assessment,
  two consumers.

## 5. State machine inputs (→ [ARCHITECTURE.md](ARCHITECTURE.md) §4, FR-5)
The machine fuses: stage-1 triggers (with track persistence), stage-2 `armed/confidence/intent`, zone/time
policy, and dwell/approach signals. SUSPECT→THREAT requires the assessment to **persist across the
confirmation window** so a single frame can't trip a major alarm (PR-4).

## 6. Datasets, fine-tuning & bias (FR-3, PR-5, SE-3)
- **Weapon detection** needs a fine-tuned model — curate from open datasets + collected/augmented site data;
  hard-negative mining on common false triggers (phones, umbrellas, tools, power drills, sports gear).
- **Conditions** matter most (R12): night/IR, occlusion, odd angles, distance, motion blur. The benchmark is
  **stratified by condition** so we don't average away a blind spot.
- **Bias (SE-3):** evaluate detection/assessment across demographic slices; the system must key on
  **objects and behavior, not appearance**. Any slice disparity beyond tolerance blocks arming (R3). Document
  the bias eval with the benchmark results.
- **Shadow mode:** before a site is armed, run detection-only (no alarms) to collect site-specific false
  triggers and tune thresholds.

## 7. Evaluation (PR-4, PR-5)
- **Harness:** `scripts/eval_detection.py` runs the labeled benchmark and reports per-class and
  per-condition **precision/recall**, the **false-negative rate** (PR-5, weapon-present), and a
  **false-positive** proxy on the benign suite (PR-4 / OS-2).
- **Gate:** CI fails if FN-rate >5% or the benign suite produces a major-alarm trigger, or if either
  regresses beyond tolerance vs the last baseline.

## 8. Night / low-light (ER-2)
IR illuminator + IR-capable sensor; the pipeline is illumination-agnostic (works on IR frames). Include
night samples in every benchmark stratum.

## 9. Component test definition (L4 right arm)
- `detection` unit tests: known images → expected classes/boxes within IoU tolerance; **track-ID continuity**
  across a synthetic sequence (FR-3).
- `reasoning` unit tests: fixture frames (armed / unarmed / ambiguous) → schema-valid JSON, correct `armed`,
  bounded `confidence`; malformed-output and timeout paths exercised (FMEA F6/F7).
- `eval_detection.py`: precision/recall + FN-rate vs thresholds (PR-4/PR-5/TPM-4/TPM-5); bias slices (SE-3).
- `state` machine tests live with FR-5 but consume this module's outputs (integration seam, L3).
