# Safety, Responsible Use, and Governance

ClinicaFlow is a **decision-support** scaffold intended for prototyping and research workflows.
It is **not** a diagnostic device and must not be used for autonomous medical decisions.

## Safety design goals

- Prefer **false positives over false negatives** in escalation (avoid under-triage).
- Make the workflow **auditable** (trace of every agent output).
- Keep safety-critical behaviors **deterministic** where possible.
- Surface **uncertainty reasons** for clinician review.

## What the system can and cannot do

**Can**

- Produce a structured triage note draft and next-action checklist.
- Highlight red-flag triggers from symptoms/vitals.
- Generate patient-facing return precautions as supportive text.

**Cannot**

- Replace clinician judgment.
- Confirm diagnoses or guarantee guideline adherence for a specific site.
- Make medication decisions without site protocol grounding.

## Operational guardrails (recommended)

- Require clinician sign-off before action.
- Log prompts/policies and model versions for every run.
- Perform site-specific evaluation on local distributions.
- Establish escalation pathways when model outputs conflict with clinical intuition.

## Threats considered (non-exhaustive)

- **Prompt injection** in patient-provided text: external reasoning prompt treats intake as untrusted data and instructs the model to ignore embedded instructions.
- **Model outage / invalid outputs**: reasoning backend is optional; failures fall back to deterministic reasoning, and safety escalation remains deterministic.
- **Protocol drift**: evidence agent emits `policy_pack_sha256` so protocol updates are traceable in logs/traces.

## Data and privacy posture

- Prefer **local-first** processing in constrained settings.
- Avoid logging identifiable patient information.
- If integrating a hosted model endpoint, ensure compliance with local policy and patient consent requirements.
- If writing audit bundles (`clinicaflow audit`), store them securely and follow retention/access controls.
