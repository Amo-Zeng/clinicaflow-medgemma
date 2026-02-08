### Project name

**ClinicaFlow** — an agentic, human-centered triage copilot built for clinics that need **safe decision support under constraints** (limited staff time, intermittent connectivity, and strict privacy requirements).

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
2. **(Multi)modal Reasoning Agent**: generates a short differential + rationale (this is where MedGemma is intended to power clinical reasoning).
3. **Evidence & Policy Agent**: translates reasoning into concrete next actions and attaches lightweight protocol-style citations (demo policy pack; replace with site protocols).
4. **Safety & Escalation Agent**: applies deterministic red-flag rules + uncertainty thresholds to prevent under-triage.
5. **Communication Agent**: produces a clinician handoff summary and patient-facing return precautions in plain language.

**Safety-first behaviors**

- Deterministic red-flag triggers from symptoms + vitals (hard to “prompt-jailbreak”).
- Mandatory escalation when urgent/critical criteria are met.
- Uncertainty reasons are surfaced for clinician review.
- Clear “decision support, not diagnosis” posture.

### Technical details (product feasibility)

- **Runnable everywhere**: the open-source scaffold runs without GPUs and includes a local demo server.
- **Reproducible evaluation**: we ship a synthetic benchmark + baseline so improvements are measurable and repeatable.
- **Auditability**: every run records a 5-step trace that can be logged and inspected.
- **Production-ready scaffolding**:
  - request IDs end-to-end (`X-Request-ID`),
  - probes (`GET /health`, `GET /ready`, `GET /live`),
  - OpenAPI spec + metrics endpoint,
  - optional JSON logs (`CLINICAFLOW_JSON_LOGS=true`) for log pipelines,
  - optional API-key protection for `POST /triage` (`CLINICAFLOW_API_KEY`),
  - `clinicaflow doctor` for quick runtime/policy-pack sanity checks,
  - Docker image + CI.
- **Governance metadata**:
  - Evidence agent emits `policy_pack_sha256` + `policy_pack_source`,
  - external reasoning emits `reasoning_backend_model` + `reasoning_prompt_version`.
- **Reliability & security** (when using an external model endpoint):
  - retry/backoff knobs (`CLINICAFLOW_REASONING_MAX_RETRIES`, `...RETRY_BACKOFF_S`),
  - basic prompt-injection hardening (quotes patient summary as JSON; ignores embedded instructions).

**Clinic deployment path (practical)**

- **Local-first**: ClinicaFlow can run on a clinic workstation or small on-prem server; the reasoning model can be served as a separate on-prem service.
- **Human-in-the-loop**: clinicians confirm escalation/disposition; ClinicaFlow drafts the note + checklist and highlights safety triggers.
- **QA/compliance workflow**: `clinicaflow audit --input ... --out-dir ...` writes an audit bundle (input + output + doctor diagnostics + manifest with hashes). Use `--redact` to drop demographics/notes/images from the saved bundle.

**Code entry points**

- CLI: `python -m clinicaflow --input examples/sample_case.json --pretty`
- Local API: `python -m clinicaflow.demo_server` (UI `/`, POST `/triage`, GET `/openapi.json`, GET `/metrics`)

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

### Responsible use and limitations

- ClinicaFlow is a **decision-support system**, not an autonomous diagnostic device.
- Outputs require clinician verification before action.
- Synthetic benchmarks do not replace site-specific validation on real clinical distributions.

### Required links

- **Video (≤3 min):** https://www.youtube.com/watch?v=vZgvNssSSGk
- **Public code repository:** https://github.com/Amo-Zeng/clinicaflow-medgemma
- **Public interactive demo (bonus):** https://github.com/Amo-Zeng/clinicaflow-medgemma (run `clinicaflow.demo_server`)
- **Open-weight HF model tracing to HAI-DEF (bonus):** Not released in this round (code-only submission).

### References

1. The MedGemma Impact Challenge: https://www.kaggle.com/competitions/med-gemma-impact-challenge
2. MedGemma overview: https://developers.google.com/health-ai-developer-foundations/medgemma
3. MedGemma 1.5 model card: https://developers.google.com/health-ai-developer-foundations/medgemma/model-card
4. HAI-DEF terms: https://developers.google.com/health-ai-developer-foundations/terms
