# Clinician Reviews (Optional, Qualitative, No PHI)

This folder is intentionally **optional**.
Do **not** store real patient data (PHI) in this repository.

## 1) Generate a review packet (synthetic vignettes)

```bash
python -m clinicaflow.benchmarks.review_packet \
  --set standard \
  --out reviews/clinician_review_packet.md \
  --include-gold
```

Share `reviews/clinician_review_packet.md` with a clinician reviewer.

## 2) Collect feedback (fast path: Console UI)

1. Run the demo: `bash scripts/demo_one_click.sh`
2. Open the UI: `http://127.0.0.1:8000/`
3. Go to the **Review** tab:
   - pick a vignette set and case
   - click **Run triage**
   - enter qualitative feedback + ratings
   - click **Download JSON**

Save the exported JSON as `reviews/clinician_reviews.json` (or anywhere you prefer).

## 3) Summarize for the writeup

```bash
clinicaflow benchmark review_summary \
  --in reviews/clinician_reviews.json \
  --print-markdown
```

## Notes

- We provide templates and tooling, but you must not fabricate clinician feedback.
- If you cannot collect a review before submission, use the "no clinician review performed" writeup variant.

