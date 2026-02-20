# Clinician Review Template (Qualitative)

You asked for a clinician review section. We **cannot fabricate** clinician feedback.
This template helps you collect **one** short, qualitative review in a responsible way.

Guidelines:

- Do **not** include PHI.
- State the reviewer’s role at a high level (e.g., “primary care physician”, “ED nurse”) and the review scope (e.g., “synthetic vignettes”).
- Treat this as **qualitative UX/safety feedback**, not a clinical validation study.

## How to generate a review packet

```bash
python -m clinicaflow.benchmarks.review_packet --set standard --out reviews/clinician_review_packet.md --include-gold
```

Share `reviews/clinician_review_packet.md` with the reviewer.

## Reviewer info (fill in)

- Reviewer role / specialty:
- Years in practice (optional):
- Setting (optional):
- Date:
- Reviewed artifacts:
  - [ ] Demo UI output
  - [ ] Vignette regression packet (n = __ )
  - [ ] Audit bundle (`clinicaflow audit`) sample

## Qualitative feedback (suggested prompts)

1) **Safety:** Were any risk tiers obviously unsafe (under-triage)? Any missing “must-not-miss” red flags?

2) **Actionability:** Are recommended next actions usable in a real clinic? What is missing?

3) **Handoff quality:** Is the clinician handoff concise and complete? What would you change?

4) **Uncertainty:** Are uncertainty reasons helpful, or too generic?

5) **Workflow fit:** Where would this save time vs. add time?

## Copy-paste summary paragraph (choose one)

**Option A (review performed; fill in):**

> A clinician reviewer (role: ___) reviewed ClinicaFlow outputs on ___ synthetic triage vignettes and noted: (1) ___, (2) ___, (3) ___. They highlighted ___ as the most helpful aspect and ___ as the top improvement area. This feedback is qualitative and does not substitute for site-specific clinical validation.

**Option B (no clinician review performed):**

> We provide tooling to collect a lightweight clinician review without PHI, but we did not conduct a clinician review for this competition submission; therefore we report no clinician feedback here.
