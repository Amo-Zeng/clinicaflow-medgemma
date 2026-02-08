# ClinicaFlow Architecture

ClinicaFlow is an **agentic triage workflow** designed to be safe-by-default and easy to audit.
The pipeline is intentionally modular so that a MedGemma-backed reasoning component can be swapped in without changing safety governance.

## High-level flow

```
Patient intake (text + vitals + optional image context)
  ↓
Intake Structuring Agent
  ↓
(Multi)modal Reasoning Agent
  ↓
Evidence & Policy Agent
  ↓
Safety & Escalation Agent
  ↓
Communication Agent
  ↓
Structured triage result + trace
```

## Agents

1. **Intake Structuring Agent** (`clinicaflow/agents.py`)
   - Extracts symptom keywords and risk factors.
   - Emits a normalized summary and a list of missing critical fields.

2. **(Multi)modal Reasoning Agent** (`clinicaflow/agents.py`)
   - Produces a short differential and a reasoning rationale.
   - Optional OpenAI-compatible inference backend (`CLINICAFLOW_REASONING_BACKEND=openai_compatible`).
   - Intended integration point for MedGemma inference.

3. **Evidence & Policy Agent** (`clinicaflow/agents.py`)
   - Converts the reasoning output into concrete next actions.
   - Uses a lightweight **policy pack** (`clinicaflow/resources/policy_pack.json`) to attach protocol-like citations.
   - In production, this should be replaced with site protocols and IDs.
   - Emits `policy_pack_sha256` + `policy_pack_source` for governance (so changes to protocols are auditable).

4. **Safety & Escalation Agent** (`clinicaflow/agents.py`, `clinicaflow/rules.py`)
   - Applies deterministic red-flag logic.
   - Computes a conservative `risk_tier` and forces escalation when needed.
   - Emits `uncertainty_reasons` to avoid “black box” handoff.

5. **Communication Agent** (`clinicaflow/agents.py`)
   - Produces a clinician handoff summary and patient return precautions.

## Trace / auditability

Every pipeline run returns a `trace` list (agent name + output payload).
This is meant to support:

- safety review and regression testing,
- deployment governance (prompt/policy versioning),
- and human debugging when a case looks wrong.

For production-ish workflows, `clinicaflow audit` can persist an audit bundle (input + output + diagnostics + manifest with hashes).

## Local demo

The stdlib demo server (`clinicaflow/demo_server.py`) exposes:

- `GET /health`
- `POST /triage` (body: `examples/sample_case.json`-compatible)
