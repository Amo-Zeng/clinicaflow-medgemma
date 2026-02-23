# ClinicaFlow — Agentic Multimodal Triage with MedGemma

**Track selection:** Main Track + **Agentic Workflow Prize**

**Team:** `shilehaoduomingzile` (solo)

ClinicaFlow is a **local-first**, **auditable** triage copilot that reframes triage as a **5-agent workflow** with a deterministic safety gate. It uses **MedGemma (HAI‑DEF)** for clinical reasoning (and optionally communication polish), while keeping safety‑critical escalation deterministic to reduce under‑triage risk.

> DISCLAIMER: Decision support only. Not a diagnosis. Use synthetic data only (no PHI). Clinician confirmation required.

---

## Required links (for judges)

- **Video (≤3 min):** https://youtu.be/dDdy8LIowQI  
- **Public code repository:** https://github.com/Amo-Zeng/clinicaflow-medgemma  
- **Public interactive live demo (bonus):** https://2agi.me/clinicaflow-medgemma/  
- **Streamlit Console demo (bonus):** https://share.streamlit.io/Amo-Zeng/clinicaflow-medgemma/main/streamlit_app.py  

---

## Project name

**ClinicaFlow** — an agentic, human-centered triage copilot built for clinics that need safe decision support under constraints
(limited staff time, intermittent connectivity, and strict privacy requirements).

## Your team

Team name: **shilehaoduomingzile** (solo)

## Problem domain (15%)

In primary/urgent care triage, the dominant failure modes are:

1) **Missed red flags → under-triage** (delayed escalation for urgent/critical cases)  
2) **Inconsistent triage quality** across staff/shifts  
3) **Documentation overhead** (handoff + patient instructions degrade under time pressure)

**User journey (target):** A clinician (or nurse/MA) enters a short intake + vitals (optionally image context). ClinicaFlow returns:
- risk tier + red-flag triggers,
- a short non-diagnostic differential/rationale (MedGemma),
- “what to do next” actions,
- clinician SBAR handoff + patient safety‑netting,
- and an audit trail for QA.

---

## Impact potential (15%)

**Transparent estimate (proxy; not clinical validation):** Using our reproducible synthetic proxy benchmark as a time proxy, median triage write-up time improves from **5.03 → 4.26 min** (−15.3%). For a clinic doing ~60 triage encounters/day, that suggests ~46 minutes/day saved (0.77 min × 60), while enforcing a deterministic under‑triage safety gate for common red‑flag patterns. This estimate is illustrative only and must be validated on site workflows and distributions.

---

## Effective use of HAI‑DEF models (20%)

ClinicaFlow runs a 5-agent workflow with a full trace:

**Intake → Structuring → Reasoning (MedGemma) → Evidence/Policy → Safety gate → Communication**

1) **Intake Structuring Agent**: normalizes text into a compact schema; flags missing critical fields; emits data-quality warnings and PHI-pattern hits (heuristic).  
2) **Multimodal Clinical Reasoning Agent (MedGemma)**: produces a short differential + rationale from structured intake (and optional images). Falls back safely if unreachable.  
3) **Evidence & Policy Agent**: maps the case to a lightweight protocol pack (demo) with citations and suggested actions; optionally attaches free external citations (PubMed / MedlinePlus / Crossref / OpenAlex / ClinicalTrials.gov) when enabled (replace with site protocols).  
4) **Safety & Escalation Agent (deterministic)**: red-flag rules + vitals thresholds + conservative escalation to prevent under-triage; produces explainable `safety_triggers`.  
5) **Communication Agent**: drafts SBAR clinician handoff + patient return precautions; optional MedGemma rewrite-only polish (no new facts).

**Why MedGemma here:** free-text synthesis into an actionable differential/rationale is where open-weight foundation models add the most value. **Safety escalation is kept deterministic** to reduce jailbreak/overreach risk.

---

## Product feasibility (20%)

**One-click demo UI + API (CPU-only by default):**

```bash
bash scripts/demo_one_click.sh
```

Then open the printed UI URL (e.g. `http://127.0.0.1:8000/`).  
In the Console UI, click **Start 3-minute demo** (Home) to launch the Director overlay (teleprompter + highlights).
Recording mode (auto Director overlay + reset local demo storage):

```bash
DEMO_RECORD=1 bash scripts/demo_one_click.sh
```

**Real MedGemma (OpenAI-compatible endpoint, e.g. vLLM server mode):**

```bash
REQUIRE_MEDGEMMA=1 MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh
```

**No GPU? Demo-only hosted MedGemma (best-effort; subject to quotas/uptime):**

```bash
USE_FREE_MEDGEMMA=1 REQUIRE_MEDGEMMA=1 bash scripts/demo_one_click.sh
```

**Alternative (token required): Hugging Face router inference (demo-only):**

```bash
CLINICAFLOW_REASONING_BACKEND=hf_inference \
CLINICAFLOW_REASONING_BASE_URL='https://router.huggingface.co/hf-inference' \
CLINICAFLOW_REASONING_MODEL='google/medgemma-4b-it' \
CLINICAFLOW_REASONING_API_KEY='<HF_TOKEN>' \
bash scripts/demo_one_click.sh
```

**Production-ish scaffolding included (stdlib-only server):**
- request IDs (`X-Request-ID`) + probes (`/health`, `/ready`, `/live`)
- `/openapi.json` + `/metrics` (JSON + Prometheus)
- optional API key auth for POST endpoints (`CLINICAFLOW_API_KEY`)
- streaming triage endpoint (`POST /triage_stream`, NDJSON) powering **real-time agent stepper + progressive trace render**
- policy pack endpoint + sha256 (`/policy_pack`) for governance
- deterministic safety rulebook endpoint (`/safety_rules`) for transparency
- governance report includes benchmark-derived **Ops SLO** stats (end-to-end p95 latency + per-agent errors)
- **audit bundles** (redacted/full; redacted bundles scrub obvious PHI patterns and record `phi_scrubbed_patterns` in `manifest.json`) and **judge pack.zip** exports from the UI
- minimal FHIR Bundle export (`/fhir_bundle`) for interoperability demos (also included as `fhir_bundle.json` inside audit bundles + judge packs)

**Reproducibility (one command):**

```bash
bash scripts/reproduce_writeup.sh
```

Outputs deterministic benchmark tables + governance gate artifacts in `tmp/writeup_assets/`.

---

## Execution & communication (30%)

- Clear “judge path”: `docs/JUDGES.md` + Director-mode 3‑minute guided demo.
- Code quality: stdlib server, typed models, unit tests, reproducible benchmark scripts, and CI.
- Public demo: GitHub Pages static app (`public_demo/`) + full local server demo (`scripts/demo_one_click.sh`).
- Auditability: per-run `audit bundle` + `judge pack.zip` export with trace + policy pack hashes.

---

## Results (reproducible, synthetic-only proxies)

We avoid clinical claims and report only reproducible synthetic proxies.

**Synthetic proxy benchmark (seed=17, n=220):**
- Red-flag recall: **55.6% → 100.0%**
- Unsafe recommendation rate: **22.7% → 0.0%**
- Median write-up time (proxy): **5.03 → 4.26 min**

Reproduce:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

**Vignette regression sets (standard n=30, adversarial n=20, extended n=100, realworld n=24):**
- Combined mega (n=174): red-flag recall **53.3% → 100.0%**, under-triage **41.3% → 0.0%**
- Realworld-inspired (n=24): red-flag recall **90.0% → 100.0%**, under-triage **0.0% → 0.0%**

Reproduce:

```bash
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown
python -m clinicaflow.benchmarks.vignettes --set realworld --print-markdown
clinicaflow benchmark governance --set mega --gate
```

Labeling rubric + red-flag categories: `docs/VIGNETTE_REGRESSION.md`.

---

## Clinician review (optional)

I include tooling + UI to collect **qualitative clinician review** notes (no PHI), but **no external clinician review was performed** for this submission.

- Review packet generator + template: `reviews/README.md`
