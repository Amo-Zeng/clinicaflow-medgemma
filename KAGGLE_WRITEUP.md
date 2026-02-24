# ClinicaFlow — Agentic Multimodal Triage with MedGemma

**Track selection:** Main Track + **Agentic Workflow Prize**

**Team:** `shilehaoduomingzile` (solo)

ClinicaFlow is a **local-first**, **auditable** triage copilot that reframes triage as a **5-agent workflow** with a deterministic safety gate. It uses **MedGemma (HAI‑DEF)** for clinical reasoning (and optionally communication polish), while keeping safety‑critical escalation deterministic to reduce under‑triage risk.

> DISCLAIMER: Decision support only. Not a diagnosis. Use synthetic data only (no PHI). Clinician confirmation required.

---

## Judge fast path (60 seconds)

1) Open the **Streamlit Console demo** → click **3-minute demo** → run the **critical chest pain** vignette.  
2) Download **Judge pack.zip** and open:
   - `case_meta.json` → vignette provenance (including open-access case-report source URLs for `case_reports`)  
   - `manifest.json` → artifact hashes + redaction metadata  

## Required links (for judges)

- **Video (≤3 min):** https://youtu.be/dDdy8LIowQI  
- **Streamlit Console demo (recommended):** https://clinicaflow-medgemma-console-2026.streamlit.app/  
- **Public interactive live demo (static; bonus):** https://amo-zeng.github.io/clinicaflow-medgemma/ (fallback: https://2agi.me/clinicaflow-medgemma/)  
- **Public code repository:** https://github.com/Amo-Zeng/clinicaflow-medgemma  

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

If port `8000` is already in use, the script auto-selects a free port and prints the correct URL.  
If you want it to stop an existing local ClinicaFlow server on `8000`, run:

```bash
DEMO_KILL_EXISTING=1 bash scripts/demo_one_click.sh
```

If UI buttons don’t respond (stale cached assets), open `/?reset=1` or click **Clear demo data** in the top bar.

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

**MedGemma integration evidence pack (synthetic-only; optional):**

```bash
bash scripts/capture_medgemma_evidence.sh
```

Writes `tmp/medgemma_evidence/run_<timestamp>/` containing `doctor.json` (connectivity), `ping_reasoning.json`, and a few audit bundles
generated using your configured MedGemma backend.

**Reproducibility (one command):**

```bash
bash scripts/reproduce_writeup.sh
```

Outputs deterministic benchmark tables + governance gate artifacts in `tmp/writeup_assets/`.

**Preflight (tests + vignette validation + submission pack):**

```bash
bash scripts/verify_release.sh
```

---

## Execution & communication (30%)

- Clear “judge path”: `docs/JUDGES.md` + Director-mode 3‑minute guided demo.
- Code quality: stdlib server, typed models, unit tests, reproducible benchmark scripts, and CI.
- Public demo: GitHub Pages static app (`public_demo/`) + full local server demo (`scripts/demo_one_click.sh`).
- Auditability: per-run `audit bundle` + `judge pack.zip` export with trace + policy pack hashes.

---

## Results (reproducible, synthetic-only proxies)

We avoid clinical claims and report only reproducible proxy benchmarks.

**Synthetic proxy benchmark (seed=17, n=220):**
- Red-flag recall: **55.6% → 100.0%**
- Unsafe recommendation rate: **22.7% → 0.0%**
- Median write-up time (proxy): **5.03 → 4.26 min**

Reproduce:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

**Vignette regression sets (standard n=30, adversarial n=20, extended n=100, realworld n=24, case_reports n=50):**
- Combined mega (n=174): red-flag recall **53.3% → 100.0%**, under-triage **41.3% → 0.0%**
- Realworld-inspired (n=24): red-flag recall **90.0% → 100.0%**, under-triage **0.0% → 0.0%**
- Case-report-derived (n=50, open-access sources; de-identified paraphrases): red-flag recall **44.0% → 100.0%**, under-triage **48.0% → 0.0%**

Reproduce:

```bash
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown
python -m clinicaflow.benchmarks.vignettes --set realworld --print-markdown
python -m clinicaflow.benchmarks.vignettes --set case_reports --print-markdown
clinicaflow benchmark governance --set mega --gate
```

**Ablation (ultra = mega + case_reports, n=224):**

Reproduce:

```bash
python -m clinicaflow.benchmarks.ablation --set ultra --print-markdown
```

| Variant | Red-flag recall | Under-triage | Over-triage | Avg actions | Avg citations | Completeness (0–5) |
|---|---:|---:|---:|---:|---:|---:|
| `baseline` | `51.0%` | `42.9%` | `47.4%` | `0.00` | `0.00` | `1.54` |
| `reasoning_only` | `43.6%` | `57.1%` | `0.0%` | `0.00` | `0.00` | `2.39` |
| `safety_only` | `100.0%` | `0.0%` | `0.0%` | `3.28` | `0.00` | `2.82` |
| `full` | `100.0%` | `0.0%` | `0.0%` | `7.90` | `0.87` | `4.90` |

Labeling rubric + red-flag categories: `docs/VIGNETTE_REGRESSION.md`.

**Real-world case highlights (from open-access case reports; paraphrased + de-identified):**

- Thunderclap headache / suspected SAH: https://pmc.ncbi.nlm.nih.gov/articles/PMC3317281/ (vignette `cr06_thunderclap_sah_negative_angio`)
- Melena + fatigue (GI bleed red flag): https://pmc.ncbi.nlm.nih.gov/articles/PMC3719128/ (vignette `cr09_melena_anemia`)
- Pregnancy spotting + near-syncope (high-risk OB pattern): https://pmc.ncbi.nlm.nih.gov/articles/PMC5410482/ (vignette `cr11_pregnancy_spotting_near_syncope`)

---

## Clinician review (optional)

I include tooling + UI to collect **qualitative clinician review** notes (no PHI), but **no external clinician review was performed** for this submission.

- Review packet generator + template: `reviews/README.md`
