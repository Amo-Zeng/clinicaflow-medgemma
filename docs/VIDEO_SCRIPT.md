# 3-Minute Demo Video Script (Template)

This is a suggested structure for a ≤3 minute submission video.
Replace bracketed items with your actual footage/screens.

## 0:00–0:15 — Hook

- **Problem:** “Triage is a high-stakes synthesis task under time pressure.”
- **Pain:** missed red flags + inconsistent triage + documentation burden.
- **One-liner:** “ClinicaFlow is an agentic triage copilot with an auditable safety trace.”

## 0:15–0:45 — What it does (inputs/outputs)

Show the demo UI (local):

- Start:
  - deterministic: `bash scripts/demo_one_click.sh`
  - with real MedGemma via vLLM (GPU machine): `MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh`
- Open `http://127.0.0.1:8000/`
- Optional: open the **Demo** tab for a click-through runbook.
- Optional: mention `GET /openapi.json`, `GET /metrics`, `GET /doctor`, and `X-Request-ID` for audit/ops readiness.
- Load a sample case and highlight:
  - risk tier,
  - red flags,
  - recommended next actions,
  - clinician handoff,
  - patient return precautions,
  - full agent trace.
- Click **Download audit bundle (redacted)** to show QA/compliance readiness.

## 0:45–1:30 — Why it’s agentic (core novelty)

Explain the 5-agent pipeline:

1. Structuring → checks missing critical fields
2. Reasoning → differential + rationale (MedGemma integration point)
3. Evidence/Policy → attaches protocol-style citations
4. Safety/Escalation → deterministic red-flag rules + conservative thresholds
5. Communication → clinician + patient outputs

Callout: “We separate probabilistic reasoning from deterministic safety governance.”

## 1:30–2:15 — Safety behaviors (what judges care about)

Show two contrasting cases:

- **Dyspnea with low SpO₂**: escalation required, actions include oxygenation monitoring.
- **Neuro symptoms**: stroke-pathway triggers.

Emphasize:

- under-triage prevention (urgent/critical never labeled routine),
- uncertainty reasons shown,
- “decision support, not diagnosis”.

## 2:15–2:45 — Reproducibility & results

Show that results are reproducible:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

Also show the small vignette regression set (n=30):

```bash
python -m clinicaflow.benchmarks.vignettes --print-markdown
```

Or run it in the UI:

- Go to the **Regression** tab → **Run benchmark** → show summary + per-case table.

Optional: show production-ish sanity check output:

```bash
clinicaflow doctor
```

Optional: show audit bundle generation (for QA/compliance):

```bash
clinicaflow audit --input examples/sample_case.json --out-dir audits/run1 --redact
```

Explain briefly:

- baseline vs ClinicaFlow,
- proxy metrics and limitations.

## 2:45–3:00 — Close

- Impact: “faster, more consistent triage notes; fewer missed red flags.”
- Links: Kaggle writeup + GitHub repo.
- Roadmap: swap in real MedGemma inference + site protocol pack + clinical validation.
