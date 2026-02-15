# Clinical Vignette Regression Set (n=30)

This repository includes a small **synthetic clinical vignette** regression set intended to:

- catch **under-triage regressions**,
- verify **red-flag detection** on common high-acuity patterns,
- and provide a repeatable “demo-ready” evaluation beyond the fully synthetic generator.

Important: These are **not real patient records** and are not meant to represent real clinical distributions.

## Files

- Vignettes: `clinicaflow/resources/vignettes.jsonl`
- Benchmark runner: `clinicaflow/benchmarks/vignettes.py`

## Labeling rubric (transparent + lightweight)

Each vignette has:

- `gold_risk_tier`: `routine` / `urgent` / `critical`
- `gold_red_flag_categories`: a list of red-flag categories (see below)
- `gold_escalation_required`: boolean

### Red-flag categories

Categories are **coarse** on purpose (to avoid brittle string matching):

- `cardiopulmonary`: chest pain/tightness, acute dyspnea / “can’t catch breath”
- `neurologic`: slurred speech, one-sided weakness, word-finding difficulty, confusion, severe headache
- `syncope`: fainting / near-syncope
- `gi_bleed`: bloody stool, vomiting blood (hematemesis)
- `obstetric`: pregnancy bleeding
- `hypoxemia`: SpO2 < 92%
- `hemodynamic`: SBP < 90 or HR > 130
- `sepsis`: temperature >= 39.5 C

### Gold risk tier rules (used for this regression set)

- `critical`:
  - hemodynamic instability, OR
  - hypoxemia + cardiopulmonary complaint, OR
  - two or more red-flag categories in the same vignette
- `urgent`:
  - any red-flag category, OR
  - **vital concern** (HR >= 110 OR temp >= 38.5 OR SpO2 < 95)
- `routine`:
  - none of the above

This rubric is intentionally conservative (false positives preferred over false negatives).

## Metrics

- **Red-flag recall (category-level)**:
  - among vignettes with `gold_red_flag_categories != []`,
  - the fraction where the system’s predicted categories intersect the gold categories.
- **Under-triage rate**:
  - among vignettes with `gold_risk_tier in {urgent, critical}`,
  - the fraction predicted as `routine`.

We also report **over-triage** (gold routine → predicted urgent/critical), since real deployments care about workload impact.

## Run it

Print a markdown table:

```bash
python -m clinicaflow.benchmarks.vignettes --print-markdown
```

Write JSON outputs:

```bash
python -m clinicaflow.benchmarks.vignettes \\
  --out results/vignette_summary.json \\
  --cases-out results/vignette_cases.json
```

## Clinician review (recommended)

Generate a review packet to collect qualitative feedback (no PHI):

```bash
python -m clinicaflow.benchmarks.review_packet --out reviews/clinician_review_packet.md --include-gold
```

See `docs/CLINICIAN_REVIEW_TEMPLATE.md` for suggested questions and how to cite the feedback responsibly.

