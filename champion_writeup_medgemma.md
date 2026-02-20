### Project name

**ClinicaFlow** — an agentic, human-centered triage copilot built for clinics that need **safe decision support under constraints** (limited staff time, intermittent connectivity, and strict privacy requirements).

**Track selection:** Main Track + **Agentic Workflow Prize** (agentic, auditable workflow re-design).

### Your team

**Team name:** `shilehaoduomingzile`

- `Amo Zeng (shilehaoduomingzile)` — Solo builder (clinical problem framing, agent workflow design, safety rules, evaluation harness, and full-stack implementation).

### Problem statement (impact potential)

Primary/urgent-care triage is a high-stakes synthesis task: clinicians must combine free-text complaints, vitals, prior notes, and (sometimes) images **quickly** and **consistently**. In real settings, three failure modes dominate:

1. **Missed red flags** → delayed escalation for truly urgent/critical patients.
2. **Under/over-triage variance** → inconsistent quality across providers and shifts.
3. **Documentation overhead** → handoff notes and discharge instructions degrade under time pressure.

This is amplified in low-resource clinics where cloud-only tools are unreliable and privacy constraints demand **local-first** options.

### Overall solution (agentic workflow + safety)

ClinicaFlow reframes triage as a **5-agent workflow** with an auditable trace, rather than a single prompt:

```
Intake → Structuring → Reasoning → Evidence/Policy → Safety/Escalation → Communication
```

1. **Intake Structuring Agent**: normalizes free-text into a compact schema and flags missing critical fields.
2. **(Multi)modal Reasoning Agent**: generates a short differential + rationale **powered by MedGemma** (served via an OpenAI-compatible endpoint; falls back safely if unreachable).
3. **Evidence & Policy Agent**: translates reasoning into concrete next actions and attaches lightweight protocol-style citations (demo policy pack; replace with site protocols).
4. **Safety & Escalation Agent**: applies deterministic red-flag rules + uncertainty thresholds to prevent under-triage.
5. **Communication Agent**: produces a clinician handoff summary and patient-facing return precautions in plain language (optionally rewritten by MedGemma for clarity; rewrite-only, no new facts).
   - Clinician handoff is formatted as an SBAR-style draft for faster review.

**Safety-first behaviors**

- Deterministic red-flag triggers from symptoms + vitals (hard to “prompt-jailbreak”).
- Mandatory escalation when urgent/critical criteria are met.
- Deterministic, tier-specific disposition actions (so “critical” outputs always read like a real triage workflow).
- Lightweight interpretable risk scores (demo): shock index + qSOFA (for clinician situational awareness).
- Uncertainty reasons are surfaced for clinician review.
- Clear “decision support, not diagnosis” posture.

### Technical details (product feasibility)

- **Runnable everywhere**: the open-source scaffold runs without GPUs and includes a local demo server.
- **Reproducible evaluation**: we ship a synthetic benchmark + baseline so improvements are measurable and repeatable.
- **Auditability**: every run records a 5-step trace that can be logged and inspected.
- **Production-ready scaffolding**:
  - request IDs end-to-end (`X-Request-ID`),
  - probes (`GET /health`, `GET /ready`, `GET /live`),
  - OpenAPI spec + metrics endpoint (JSON + Prometheus),
  - packaged-resource validation (`clinicaflow validate`) to prevent broken policy packs / vignette sets,
  - policy-pack introspection endpoint (`GET /policy_pack`) with sha256 + policy IDs (governance-ready),
  - optional JSON logs (`CLINICAFLOW_JSON_LOGS=true`) for log pipelines,
  - optional API-key protection for `POST /triage` (`CLINICAFLOW_API_KEY`),
  - `clinicaflow doctor` for quick runtime/policy-pack sanity checks,
  - minimal FHIR bundle export (`POST /fhir_bundle`) for demo interoperability (includes `Task`s for the next-action checklist),
  - printable triage report export (`report.html`) + action checklist (local-only storage),
  - Docker image (non-root runtime + healthcheck) + CI.
- **Multimodal path (practical):**
  - demo UI supports image uploads (`image_data_urls`),
  - optional vision send-to-model toggle (`CLINICAFLOW_REASONING_SEND_IMAGES=1`),
  - redacted audit bundles exclude images; full bundles store them as separate files under `images/` (not inline base64 in `intake.json`).
- **Governance metadata**:
  - Evidence agent emits `policy_pack_sha256` + `policy_pack_source`,
  - external reasoning emits `reasoning_backend_model` + `reasoning_prompt_version`.
- **Reliability & security** (when using an external model endpoint):
  - retry/backoff knobs (`CLINICAFLOW_REASONING_MAX_RETRIES`, `...RETRY_BACKOFF_S`),
  - basic prompt-injection hardening (sanitize injection-like lines; quote patient summary as JSON; ignore embedded instructions).
  - optional communication rewrite: `CLINICAFLOW_COMMUNICATION_BACKEND=openai_compatible`.

**Clinic deployment path (practical)**

- **Local-first**: ClinicaFlow can run on a clinic workstation or small on-prem server; the reasoning model can be served as a separate on-prem service.
- **Human-in-the-loop**: clinicians confirm escalation/disposition; ClinicaFlow drafts the note + checklist and highlights safety triggers.
- **QA/compliance workflow**: `clinicaflow audit --input ... --out-dir ...` writes an audit bundle (input + output + doctor diagnostics + manifest with hashes + checklist + human-readable note/report). Use `--redact` to drop demographics/notes/images from the saved bundle.

**Code entry points**

- CLI: `python -m clinicaflow --input examples/sample_case.json --pretty`
- Local demo (one-click): `bash scripts/demo_one_click.sh`
  - UI: ClinicaFlow Console at `/` (triage + checklist + printable report + workspace + regression + clinician review + audit bundle download)
  - API: `POST /triage`, `POST /audit_bundle`, `GET /doctor`, `GET /policy_pack`, `GET /bench/vignettes`
  - With real MedGemma via vLLM (GPU machine): `MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh`

### Results (internal synthetic proxy benchmark, n=220)

To avoid inflated claims, we report a reproducible **proxy benchmark** from synthetic triage scenarios that stress symptom ambiguity, vitals instability, and edge cases.

Reproduce exactly with:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

| Metric | Baseline | ClinicaFlow | Delta |
|---|---:|---:|---:|
| Red-flag recall | `55.6%` | `100.0%` | `+44.4 pp` |
| Unsafe recommendation rate | `22.7%` | `0.0%` | `-22.7 pp` |
| Median triage write-up time (proxy) | `5.03 min` | `4.26 min` | `-15.3%` |
| Handoff completeness (0-5 proxy) | `2.52/5` | `4.94/5` | `+2.42` |
| Clinician usefulness (0-5 proxy) | `3.11/5` | `4.76/5` | `+1.65` |

### Results (clinical vignette regression sets)

To complement the generator-based benchmark, we ship **three synthetic vignette regression sets** with a transparent labeling rubric to catch under-triage regressions:

- `standard` (n=30): demo-ready core patterns
- `adversarial` (n=20): abbrev/negation/injection-like strings + Unicode edge cases
- `extended` (n=100): broader coverage across cardiopulmonary/neuro/syncope/GI/OB/sepsis patterns

Rubric details: `docs/VIGNETTE_REGRESSION.md`

#### Standard (n=30)

Reproduce exactly with:

```bash
python -m clinicaflow.benchmarks.vignettes --set standard --print-markdown
```

| Metric | Baseline | ClinicaFlow |
|---|---:|---:|
| Red-flag recall (category-level) | `87.5%` | `100.0%` |
| Under-triage rate (gold urgent/critical → predicted routine) | `11.5%` | `0.0%` |
| Over-triage rate (gold routine → predicted urgent/critical) | `50.0%` | `0.0%` |

#### Adversarial (n=20)

Reproduce exactly with:

```bash
python -m clinicaflow.benchmarks.vignettes --set adversarial --print-markdown
```

| Metric | Baseline | ClinicaFlow |
|---|---:|---:|
| Red-flag recall (category-level) | `78.9%` | `100.0%` |
| Under-triage rate (gold urgent/critical → predicted routine) | `10.5%` | `0.0%` |
| Over-triage rate (gold routine → predicted urgent/critical) | `100.0%` | `0.0%` |

#### Extended (n=100)

Reproduce exactly with:

```bash
python -m clinicaflow.benchmarks.vignettes --set extended --print-markdown
```

| Metric | Baseline | ClinicaFlow |
|---|---:|---:|
| Red-flag recall (category-level) | `30.3%` | `100.0%` |
| Under-triage rate (gold urgent/critical → predicted routine) | `65.6%` | `0.0%` |
| Over-triage rate (gold routine → predicted urgent/critical) | `30.0%` | `0.0%` |

#### Combined (mega, n=150)

Reproduce exactly with:

```bash
python -m clinicaflow.benchmarks.vignettes --set mega --print-markdown
```

| Metric | Baseline | ClinicaFlow |
|---|---:|---:|
| Red-flag recall (category-level) | `47.7%` | `100.0%` |
| Under-triage rate (gold urgent/critical → predicted routine) | `47.4%` | `0.0%` |
| Over-triage rate (gold routine → predicted urgent/critical) | `40.0%` | `0.0%` |

### Clinician review (qualitative)

Below is a **copy-paste template** for the final submission writeup. It is designed to be **strictly non-fabricated**: fill in real values only, or use the "no clinician review" variant. Do **not** include PHI.

**Variant A (if clinician review was performed; fill in blanks, then delete this header):** A clinician reviewer (role: ___; experience: ___) qualitatively reviewed ClinicaFlow outputs on ___ synthetic triage vignettes on ___ (YYYY-MM-DD). They reported: (1) ___, (2) ___, (3) ___. Most helpful: ___. Top improvement area: ___. This feedback is qualitative UX/safety input only and does not substitute for site-specific clinical validation.

**Variant B (if no clinician review was performed; delete this header):** We provide tooling to collect a lightweight clinician review without PHI, but we did not conduct a clinician review for this competition submission; therefore we report no clinician feedback here.

### Responsible use and limitations

- ClinicaFlow is a **decision-support system**, not an autonomous diagnostic device.
- Outputs require clinician verification before action.
- Synthetic benchmarks do not replace site-specific validation on real clinical distributions.

### Required links

- **Video (≤3 min):** https://www.youtube.com/watch?v=vZgvNssSSGk
- **Public code repository:** https://github.com/Amo-Zeng/clinicaflow-medgemma
- **Public interactive demo (bonus):** https://github.com/Amo-Zeng/clinicaflow-medgemma (run `bash scripts/demo_one_click.sh`)
- **Open-weight HF model tracing to HAI-DEF (bonus):** Not released in this round (code-only submission).

### References

1. The MedGemma Impact Challenge: https://www.kaggle.com/competitions/med-gemma-impact-challenge
2. MedGemma overview: https://developers.google.com/health-ai-developer-foundations/medgemma
3. MedGemma 1.5 model card: https://developers.google.com/health-ai-developer-foundations/medgemma/model-card
4. HAI-DEF terms: https://developers.google.com/health-ai-developer-foundations/terms
5. Competition citation: Fereshteh Mahvar, Yun Liu, Daniel Golden, Fayaz Jamil, Sunny Jansen, Can Kirmizi, Rory Pilgrim, David F. Steiner, Andrew Sellergren, Richa Tiwari, Sunny Virmani, Liron Yatziv, Rebecca Hemenway, Yossi Matias, Ronit Levavi Morad, Avinatan Hassidim, Shravya Shetty, and María Cruz. *The MedGemma Impact Challenge*. https://kaggle.com/competitions/med-gemma-impact-challenge, 2026. Kaggle.
