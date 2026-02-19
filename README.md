# ClinicaFlow: Agentic Multimodal Triage with MedGemma

ClinicaFlow is a competition-ready project scaffold for **The MedGemma Impact Challenge**.
It implements a deterministic, auditable 5-agent triage pipeline aligned with the write-up:

1. Intake Structuring Agent
2. Multimodal Clinical Reasoning Agent
3. Evidence & Policy Agent
4. Safety & Escalation Agent
5. Communication Agent

> This repository is a reference implementation for clinical decision support prototyping.
> It is **not** a diagnostic device and must not be used for real-world autonomous medical decisions.

## Links

- Kaggle Writeup: https://www.kaggle.com/competitions/med-gemma-impact-challenge/writeups/new-writeup-1768960611416
- Demo Video: https://www.youtube.com/watch?v=vZgvNssSSGk
- Public Repo: https://github.com/Amo-Zeng/clinicaflow-medgemma

## Repository Layout

- `clinicaflow/` — core pipeline code
- `tests/` — unit tests
- `examples/` — sample payloads
- `docs/` — architecture + benchmark + safety + video script
- `champion_writeup_medgemma.md` — competition write-up draft

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

One-click demo (starts the demo server; optionally starts a local MedGemma vLLM server if configured):

```bash
bash scripts/demo_one_click.sh
```

Run pipeline on sample case:

```bash
python -m clinicaflow --input examples/sample_case.json --pretty
```

Or via the installed CLI:

```bash
clinicaflow --input examples/sample_case.json --pretty
```

Run tests:

```bash
python -m unittest discover -s tests
```

## Audit Bundle (QA / Compliance)

Write an auditable run bundle (input + output + runtime diagnostics + manifest with hashes):

```bash
clinicaflow audit --input examples/sample_case.json --out-dir audits/run1
```

To reduce sensitive fields in the stored bundle:

```bash
clinicaflow audit --input examples/sample_case.json --out-dir audits/run1 --redact
```

Audit bundle contents include:

- `intake.json`, `triage_result.json`, `doctor.json`, `manifest.json`
- `actions_checklist.json`
- `note.md` and `report.html` (human-readable)

## FHIR Export (Demo Interoperability)

Export a minimal FHIR R4 `Bundle` (collection) containing:

- `Patient` (narrative only; no birthdate inference),
- vital-sign `Observation`s,
- triage `ClinicalImpression`,
- patient-facing `Communication` (return precautions).
- one `Task` per “next action” (checklist-friendly).

CLI:

```bash
clinicaflow fhir --input examples/sample_case.json --output exports/fhir_bundle.json --pretty --redact
```

API:

```bash
curl -s -X POST 'http://127.0.0.1:8000/fhir_bundle?redact=1' \
  -H 'Content-Type: application/json' \
  --data @examples/sample_case.json | python -m json.tool
```

## Reproduce Writeup Benchmark

This repo includes a small **synthetic proxy benchmark** used in the write-up to keep results reproducible.

Print the markdown table:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --print-markdown
```

Write JSON summary:

```bash
python -m clinicaflow.benchmarks.synthetic --seed 17 --n 220 --out results/synthetic_benchmark.json
```

## Clinical Vignette Regression Set (standard n=30, adversarial n=20)

A small **synthetic vignette** regression set is included to catch under-triage regressions and verify red-flag recall.

```bash
python -m clinicaflow.benchmarks.vignettes --set standard --print-markdown
```

Labeling rubric + definitions: `docs/VIGNETTE_REGRESSION.md`

Optional clinician review packet generator (no PHI):

```bash
python -m clinicaflow.benchmarks.review_packet --out reviews/clinician_review_packet.md --include-gold
```

Summarize clinician reviews exported from the demo UI:

```bash
clinicaflow benchmark review_summary --in clinician_reviews.json --print-markdown
```

## Demo API Server (stdlib)

Start server:

```bash
python -m clinicaflow.demo_server
```

Or:

```bash
clinicaflow serve --host 0.0.0.0 --port 8000
```

Open the local demo UI:

- http://127.0.0.1:8000/

Console features:

- Structured triage form + JSON mode
- Action checklist (progress stored locally)
- Workspace tab (save runs locally + import/export JSON)
- Built-in vignette presets (n=30)
- Agent trace viewer (audit-friendly)
- Downloadable audit bundle zip (redacted/full)
- Downloadable printable triage report (`report.html`)
- Downloadable minimal FHIR bundle JSON (redacted)
- Vignette regression tab + JSON export
- Vignette regression tab + markdown table export (copy/download)
- Clinician review tab (local-only storage + JSON/Markdown export for writeup)

API spec & metrics:

- OpenAPI: http://127.0.0.1:8000/openapi.json
- Metrics: http://127.0.0.1:8000/metrics
  - Prometheus: http://127.0.0.1:8000/metrics?format=prometheus
- Doctor (no secrets): http://127.0.0.1:8000/doctor

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Kubernetes-style probes:

- `GET /ready`
- `GET /live`

Triage request:

```bash
curl -s -X POST http://127.0.0.1:8000/triage \
  -H 'Content-Type: application/json' \
  --data @examples/sample_case.json | python -m json.tool
```

Request tracing:

- Send `X-Request-ID` to correlate logs and outputs.

## Production-ish knobs (env vars)

- `CLINICAFLOW_LOG_LEVEL` (default: `INFO`)
- `CLINICAFLOW_JSON_LOGS` (default: `false`) — emit JSON logs (better for prod log pipelines)
- `CLINICAFLOW_DEBUG` (default: `false`) — include error messages in API responses
- `CLINICAFLOW_MAX_REQUEST_BYTES` (default: `262144`)
- `CLINICAFLOW_POLICY_PACK_PATH` — replace demo policy pack with site protocols
- `CLINICAFLOW_POLICY_TOPK` (default: `2`)
- `CLINICAFLOW_CORS_ALLOW_ORIGIN` (default: `*`)
- `CLINICAFLOW_API_KEY` (default: empty) — if set, `POST /triage` requires auth (`Authorization: Bearer ...` or `X-API-Key`)
- `CLINICAFLOW_COMMUNICATION_BACKEND` (default: `deterministic`) — optional draft rewriting via an OpenAI-compatible endpoint

Quick config sanity check:

```bash
clinicaflow doctor
```

## Integrating Real MedGemma Inference

Current code uses deterministic logic to keep the project runnable everywhere.
To integrate a real model endpoint:

1. Start an OpenAI-compatible endpoint for MedGemma (e.g. vLLM server mode).
2. Set:
   - `CLINICAFLOW_REASONING_BACKEND=openai_compatible`
   - `CLINICAFLOW_REASONING_BASE_URL=http://127.0.0.1:8001`
   - `CLINICAFLOW_REASONING_MODEL=<YOUR_MODEL_NAME>`
3. Run the pipeline normally; the reasoning agent will call the endpoint and fall back safely if it fails.

Optional (human-centered language polish): reuse the same endpoint to rewrite drafts for clarity:

- `CLINICAFLOW_COMMUNICATION_BACKEND=openai_compatible`

See `docs/MEDGEMMA_INTEGRATION.md` for details.

One-click demo script options:

- Deterministic (no model server): `bash scripts/demo_one_click.sh`
- Start vLLM automatically (GPU machine): `MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh`
- Require a real MedGemma backend (fails fast if not configured): `REQUIRE_MEDGEMMA=1 MEDGEMMA_MODEL='<HF_ID_OR_LOCAL_PATH>' bash scripts/demo_one_click.sh`
- Run vignette benchmark before starting server: `RUN_BENCHMARKS=1 bash scripts/demo_one_click.sh`

## Docker (quick deploy)

Build and run:

```bash
docker build -t clinicaflow .
docker run --rm -p 8000:8000 clinicaflow
```

Then open `http://127.0.0.1:8000/`.

See `docs/DEPLOYMENT.md` for more notes.

## Submission Checklist Mapping

- ✅ Main + Special Track selection (set in Kaggle write-up)
- ✅ Structured write-up (`champion_writeup_medgemma.md`)
- ✅ Public repository with reproducible code (this repo)
- ✅ Video link (Kaggle carousel)
- ✅ Live demo instructions (`clinicaflow.demo_server`)
- ⚠️ Hugging Face model link tracing to HAI-DEF (optional; not released in this round)

## License

MIT
