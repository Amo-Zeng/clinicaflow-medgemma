# Clinical Vignette Regression Sets (standard n=30, adversarial n=20, extended n=100, realworld n=24, case_reports n=50)

This repository includes a small **synthetic clinical vignette** regression set intended to:

- catch **under-triage regressions**,
- verify **red-flag detection** on common high-acuity patterns,
- and provide a repeatable “demo-ready” evaluation beyond the fully synthetic generator.

Important:

- **standard / adversarial / extended / realworld** are **synthetic** (no patient records).
- **case_reports** are **de-identified, paraphrased vignettes** derived from **open-access case reports** (linked in each row).
- None of these sets represent real clinical distributions; they exist to catch **safety regressions** (especially under-triage).

## Files

- Standard vignettes: `clinicaflow/resources/vignettes.jsonl` (n=30)
- Adversarial vignettes: `clinicaflow/resources/vignettes_adversarial.jsonl` (n=20)
- Extended vignettes: `clinicaflow/resources/vignettes_extended.jsonl` (n=100)
- Realworld-inspired vignettes: `clinicaflow/resources/vignettes_realworld.jsonl` (n=24)
- Case-report-derived vignettes: `clinicaflow/resources/vignettes_case_reports.jsonl` (n=50)
- Benchmark runner: `clinicaflow/benchmarks/vignettes.py`

The **realworld** set is still synthetic (no patient records). Each vignette includes a `source` field linking to a
public symptom/red-flag description (e.g., MedlinePlus/CDC/NHS) that inspired the scenario. The intent is to improve
*terminology coverage* (synonyms like “melena”, “thunderclap”) without claiming clinical validation.

The **case_reports** set is intentionally **compact** and high-acuity. Each row links to an open-access case report (PMC) and
paraphrases the presentation into a structured triage intake. This is **not** used for clinical claims; it is a
**regression test** to ensure the workflow does not under-triage common red-flag patterns when terminology varies.

The **adversarial** set is intentionally crafted to stress:

- abbreviations (e.g., `CP`, `SOB`, `AMS`),
- negation + contrast ("no X, but Y"),
- prompt-injection-like strings inside patient text,
- Unicode punctuation variants (e.g., “Can’t”),
- and non-English snippets.

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
python -m clinicaflow.benchmarks.vignettes --set standard --print-markdown
```

Run on the extended set:

```bash
python -m clinicaflow.benchmarks.vignettes --set extended --print-markdown
```

Run on the adversarial set:

```bash
python -m clinicaflow.benchmarks.vignettes --set adversarial --print-markdown
```

Run on both combined:

```bash
python -m clinicaflow.benchmarks.vignettes --set all --print-markdown
```

Run on all packaged sets combined:

```bash
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown
```

Run on all packaged sets + case reports:

```bash
python -m clinicaflow.benchmarks.vignettes --set ultra --print-markdown
```

Run on the realworld-inspired set:

```bash
python -m clinicaflow.benchmarks.vignettes --set realworld --print-markdown
```

Run on the case-report-derived set:

```bash
python -m clinicaflow.benchmarks.vignettes --set case_reports --print-markdown
```

Write JSON outputs:

```bash
python -m clinicaflow.benchmarks.vignettes \\
  --set standard \\
  --out results/vignette_summary.json \\
  --cases-out results/vignette_cases.json
```

## Clinician review (recommended)

Generate a review packet to collect qualitative feedback (no PHI):

```bash
python -m clinicaflow.benchmarks.review_packet --set standard --out reviews/clinician_review_packet.md --include-gold
```

See `docs/CLINICIAN_REVIEW_TEMPLATE.md` for suggested questions and how to cite the feedback responsibly.
