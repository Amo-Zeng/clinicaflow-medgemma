## Project name

**ClinicaFlow** — an agentic, human-centered triage copilot built on MedGemma for clinics that need safe decision support with constrained infrastructure.

## Your team

**Team name:** `[Your Team Name]`

- `[Member 1]` — Clinical AI lead (problem definition, medical safety rubric)
- `[Member 2]` — Modeling lead (MedGemma adaptation, ablations)
- `[Member 3]` — Agent systems lead (workflow orchestration, tool routing)
- `[Member 4]` — Product lead (clinician UX, pilot testing)
- `[Member 5]` — MLOps lead (deployment, optimization, reproducibility)

## Problem statement

Triage in primary and urgent-care environments is often fragmented: clinicians must combine free-text complaints, vitals, prior notes, and occasional medical images under severe time pressure. This creates three recurring risks:

1. **Missed red flags** in high-risk patients,
2. **Inconsistent triage quality** across providers and shifts,
3. **Poor clinician-patient communication** at discharge.

This burden is most severe in low-resource settings where internet access is intermittent and cloud-only workflows are unreliable. These sites need private, local-first, adaptable AI tools that improve workflow quality without replacing clinical judgment.

**Why this problem matters:** triage quality directly impacts time-to-escalation and downstream outcomes. If we improve red-flag recall while reducing documentation overhead, clinicians spend more time on care and less time on synthesis.

**Why AI is a fit:** triage is a multimodal synthesis task with structured outputs (risk tier, next actions, escalation rationale, patient instructions). It requires medical language understanding, image-context reasoning when available, and clear generation under constraints.

## Overall solution

ClinicaFlow reframes triage as an **agentic workflow**, not a single prompt.

### Workflow overview

Input:
- free-text intake and history,
- structured vitals,
- optional image input (e.g., dermatology photo, radiology snapshot),
- prior encounter snippets.

Output:
- risk tier (`routine`, `urgent`, `critical`),
- top differential considerations,
- explicit red-flag triggers,
- suggested immediate next actions,
- clinician handoff summary,
- patient-facing return precautions in plain language.

### Agentic architecture (main novelty)

1. **Intake Structuring Agent**
   - Converts unstructured intake to a normalized schema.
   - Flags missing critical fields before reasoning.

2. **Multimodal Clinical Reasoning Agent (MedGemma 1.5 4B)**
   - Integrates text + image context.
   - Generates candidate triage plan and rationale.

3. **Evidence & Protocol Agent**
   - Grounds recommendations in local policy snippets.
   - Forces evidence-linked suggestions.

4. **Safety & Escalation Agent**
   - Applies deterministic red-flag rules and uncertainty thresholds.
   - Triggers abstain/escalate behavior when confidence is low.

5. **Communication Agent**
   - Produces concise clinician handoff and patient instructions.
   - Controls readability and action clarity.

This decomposition improves reliability and auditability over one-shot prompting and directly targets the **Agentic Workflow Prize** criteria.

### Effective use of HAI-DEF models

- We use **MedGemma 1.5 4B multimodal** as the core reasoning model.
- We adapt it with lightweight LoRA for our triage schema and output constraints.
- We use constrained generation for safety-critical sections (red flags, escalation).
- MedGemma is central to the workflow (not an add-on), because this task requires clinically grounded multimodal understanding.

## Technical details

### Data strategy

This hackathon provides no dataset, so we built a reproducible pipeline:
- de-identified open medical sources,
- synthetic but clinically realistic scenarios,
- clinician-authored edge-case sets,
- strict train/validation/test separation by scenario family.

All dataset-building scripts and provenance metadata are included in our public repository.

### Model adaptation

1. **Supervised adaptation**
   - LoRA tuning on triage-formatted outputs.
   - Multimodal instruction tuning for intake + image reasoning.

2. **Safety shaping**
   - Preference optimization using clinician rankings.
   - Hard-negative prompts targeting under-triage and overconfident behavior.

3. **Calibration**
   - Confidence calibration + threshold policy.
   - Mandatory escalation on uncertainty or missing critical inputs.

### Evaluation framework

We evaluate along three axes mapped to the judging rubric:

| Axis | Key metrics |
|---|---|
| Clinical safety | Red-flag recall (primary), unsafe recommendation rate |
| Workflow impact | Median triage documentation time, handoff completeness |
| Execution quality | Reproducibility, latency stability, communication clarity |

### Current results (replace placeholders with final values)

| Metric | Baseline | ClinicaFlow | Delta |
|---|---:|---:|---:|
| Red-flag recall | `[x1]%` | `[x2]%` | `+[x3] pp` |
| Unsafe recommendation rate | `[y1]%` | `[y2]%` | `-[y3]%` |
| Median triage write-up time | `[t1] min` | `[t2] min` | `-[t3]%` |
| Handoff completeness | `[h1]/5` | `[h2]/5` | `+[h3]` |
| Clinician usefulness | `[u1]/5` | `[u2]/5` | `+[u3]` |

### Product feasibility and deployment

- Dual deployment modes: cloud GPU and edge-optimized local mode.
- Latency optimization: quantization + constrained decoding.
- Safety operations: full audit trail, versioned prompts, deterministic fallback.
- Privacy posture: local-first processing whenever feasible.

### Responsible use and limitations

- ClinicaFlow is a **decision-support system**, not an autonomous diagnostic device.
- Outputs require clinician verification before action.
- Site-specific validation is mandatory prior to deployment.
- Multi-image and long multi-turn clinical reasoning remain future work.

## Required links

- **Video (≤3 min):** `[YouTube URL]`
- **Public code repository:** `[GitHub URL]`
- **Public interactive demo (bonus):** `[Demo URL]`
- **Open-weight HF model tracing to HAI-DEF (bonus):** `[Hugging Face URL]`

## Why this submission is competitive

- Strong alignment with all rubric dimensions.
- MedGemma is used deeply in core multimodal reasoning.
- Agentic workflow redesign is substantial and safety-oriented.
- Clear path from prototype to practical clinical deployment.
- Cohesive narrative across unmet need, method, impact, and feasibility.

## References

1. The MedGemma Impact Challenge: https://www.kaggle.com/competitions/med-gemma-impact-challenge
2. MedGemma overview: https://developers.google.com/health-ai-developer-foundations/medgemma
3. MedGemma 1.5 model card: https://developers.google.com/health-ai-developer-foundations/medgemma/model-card
4. HAI-DEF terms: https://developers.google.com/health-ai-developer-foundations/terms
