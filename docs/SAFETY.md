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

- **Prompt injection** in patient-provided text:
  - the prompting path treats intake as untrusted data (quotes the patient summary as JSON),
  - we sanitize high-confidence prompt-structure lines (e.g., `SYSTEM:` / `ignore previous instructions`) before sending text to an external model,
  - and safety escalation remains deterministic.
- **Model outage / invalid outputs**: reasoning backend is optional; failures fall back to deterministic reasoning, and safety escalation remains deterministic.
- **Protocol drift**: evidence agent emits `policy_pack_sha256` so protocol updates are traceable in logs/traces.

## Adversarial regression (recommended)

For a judge-friendly safety story, use the built-in adversarial vignette set (abbreviations, negation, Unicode punctuation, injection-like strings):

```bash
python -m clinicaflow.benchmarks.vignettes --set adversarial --print-markdown
```

## Data and privacy posture

- Prefer **local-first** processing in constrained settings.
- Avoid logging identifiable patient information.
- If integrating a hosted model endpoint, ensure compliance with local policy and patient consent requirements.
- If writing audit bundles (`clinicaflow audit`), store them securely and follow retention/access controls.
- If using image uploads (`image_data_urls`) in the demo UI, treat them as sensitive:
  - redacted audit bundles exclude images,
  - full audit bundles store images as separate files under `images/` (not inline base64 in `intake.json`).
