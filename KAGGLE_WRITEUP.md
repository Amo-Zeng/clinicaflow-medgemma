# ClinicaFlow — Agentic Multimodal Triage with MedGemma

**Track selection:** Main Track + **Agentic Workflow Prize**

**Team:** `shilehaoduomingzile` (solo)

ClinicaFlow is a **local-first**, **auditable** triage copilot that reframes triage as a **5-agent workflow** with a deterministic safety gate. It uses **MedGemma (HAI‑DEF)** via an **OpenAI-compatible** endpoint for clinical reasoning and (optionally) communication polishing, while keeping safety-critical escalation deterministic.

> DISCLAIMER: Decision support only. Not a diagnosis. Use synthetic data only (no PHI). Clinician confirmation required.

---

## Problem statement (Problem domain + Impact potential)

In primary/urgent care triage, the dominant failure modes are:

1) **Missed red flags → under-triage** (delayed escalation for urgent/critical cases)  
2) **Inconsistent triage quality** across staff/shifts  
3) **Documentation overhead** (handoff + patient instructions degrade under time pressure)

**Impact potential (transparent estimate; not clinical validation):** Using our reproducible synthetic proxy benchmark as a time proxy, median triage write-up time improves from **5.03 → 4.26 min** (−15.3%). For a clinic doing ~60 triage encounters/day, that suggests ~46 minutes/day saved (0.77 min × 60), while enforcing a deterministic under-triage safety gate for common red-flag patterns. This estimate is illustrative only and must be validated on site workflows and distributions.

---

## Overall solution (Effective use of HAI‑DEF models)

ClinicaFlow runs a 5-agent workflow with a full trace:

**Intake → Structuring → Reasoning (MedGemma) → Evidence/Policy → Safety gate → Communication**

1) **Intake Structuring Agent**: normalizes text into a compact schema; flags missing critical fields; emits data-quality warnings and PHI-pattern hits (heuristic).  
2) **Multimodal Clinical Reasoning Agent (MedGemma)**: produces a short differential + rationale from structured intake (and optional images). Falls back safely if unreachable.  
3) **Evidence & Policy Agent**: maps the case to a lightweight protocol pack (demo) with citations and suggested actions (replace with site protocols).  
4) **Safety & Escalation Agent (deterministic)**: red-flag rules + vitals thresholds + conservative escalation to prevent under-triage; produces explainable `safety_triggers`.  
5) **Communication Agent**: drafts SBAR clinician handoff + patient return precautions; optional MedGemma rewrite-only polish (no new facts).

**Why MedGemma here:** free-text synthesis into an actionable differential/rationale is where open-weight foundation models add the most value. **Safety escalation is kept deterministic** to reduce jailbreak/overreach risk.

---

## Technical details (Product feasibility)

**One-click demo UI + API (CPU-only by default):**

```bash
bash scripts/demo_one_click.sh
```

Then open the printed UI URL (e.g. `http://127.0.0.1:8000/`).  
Recording mode (auto Director overlay + reset local demo storage):

```bash
DEMO_RECORD=1 bash scripts/demo_one_click.sh
```

**Real MedGemma (OpenAI-compatible endpoint, e.g. vLLM server mode):**

```bash
REQUIRE_MEDGEMMA=1 MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh
```

**Production-ish scaffolding included (stdlib-only server):**
- request IDs (`X-Request-ID`) + probes (`/health`, `/ready`, `/live`)
- `/openapi.json` + `/metrics` (JSON + Prometheus)
- optional API key auth for POST endpoints (`CLINICAFLOW_API_KEY`)
- streaming triage endpoint (`POST /triage_stream`, NDJSON) powering **real-time agent stepper + progressive trace render**
- policy pack endpoint + sha256 (`/policy_pack`) for governance
- deterministic safety rulebook endpoint (`/safety_rules`) for transparency
- **audit bundles** (redacted/full) and **judge pack.zip** exports from the UI
- minimal FHIR Bundle export (`/fhir_bundle`) for interoperability demos

**Reproducibility (one command):**

```bash
bash scripts/reproduce_writeup.sh
```

Outputs deterministic benchmark tables + governance gate artifacts in `tmp/writeup_assets/`.

---

## Results (reproducible, synthetic-only)

We avoid clinical claims and report only reproducible synthetic proxies.

**Synthetic proxy benchmark (seed=17, n=220):**
- Red-flag recall: **55.6% → 100.0%**
- Unsafe recommendation rate: **22.7% → 0.0%**
- Median write-up time (proxy): **5.03 → 4.26 min**

Reproduce:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

**Vignette regression sets (standard n=30, adversarial n=20, extended n=100):**
- Combined mega (n=150): red-flag recall **47.7% → 100.0%**, under-triage **47.4% → 0.0%**

Reproduce:

```bash
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown
clinicaflow benchmark governance --set mega --gate
```

Labeling rubric + red-flag categories: `docs/VIGNETTE_REGRESSION.md`.

---

## Links (required/bonus)

- **Video (≤3 min):** https://www.youtube.com/watch?v=vZgvNssSSGk *(placeholder; replace before final submission)*  
- **Public code repository:** https://github.com/Amo-Zeng/clinicaflow-medgemma  
- **Bonus: public interactive demo:** run locally via `bash scripts/demo_one_click.sh` (local-first)  
