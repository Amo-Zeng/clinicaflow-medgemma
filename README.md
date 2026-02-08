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

## Repository Layout

- `clinicaflow/` — core pipeline code
- `tests/` — unit tests
- `examples/` — sample payloads
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

Run tests:

```bash
python -m unittest discover -s tests
```

## Demo API Server (stdlib)

Start server:

```bash
python -m clinicaflow.demo_server
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Triage request:

```bash
curl -s -X POST http://127.0.0.1:8000/triage \
  -H 'Content-Type: application/json' \
  --data @examples/sample_case.json | python -m json.tool
```

## Integrating Real MedGemma Inference

Current code uses deterministic logic to keep the project runnable everywhere.
To integrate a real model endpoint:

1. Replace the logic in `MultimodalClinicalReasoningAgent.run`.
2. Add your model client (local or hosted) and prompt templates.
3. Keep safety escalation rules deterministic for clinical governance.
4. Re-run tests and add benchmark scripts for your final submission metrics.

## Submission Checklist Mapping

- ✅ Main + Special Track selection (set in Kaggle write-up)
- ✅ Structured write-up (`champion_writeup_medgemma.md`)
- ✅ Public repository with reproducible code (this repo)
- ⏳ Video link (to be added)
- ⏳ Live demo link (optional)
- ⏳ Hugging Face model link tracing to HAI-DEF (optional)

## License

MIT
