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

API spec & metrics:

- OpenAPI: http://127.0.0.1:8000/openapi.json
- Metrics: http://127.0.0.1:8000/metrics

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

## Integrating Real MedGemma Inference

Current code uses deterministic logic to keep the project runnable everywhere.
To integrate a real model endpoint:

1. Start an OpenAI-compatible endpoint for MedGemma (e.g. vLLM server mode).
2. Set:
   - `CLINICAFLOW_REASONING_BACKEND=openai_compatible`
   - `CLINICAFLOW_REASONING_BASE_URL=http://127.0.0.1:8001`
   - `CLINICAFLOW_REASONING_MODEL=<YOUR_MODEL_NAME>`
3. Run the pipeline normally; the reasoning agent will call the endpoint and fall back safely if it fails.

See `docs/MEDGEMMA_INTEGRATION.md` for details.

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
