# Productization Notes (ClinicaFlow)

ClinicaFlow is a competition-aligned scaffold, but it is designed with a realistic clinic deployment in mind:
human-in-the-loop triage support, auditable outputs, and local-first execution.

This document describes what "production-ready" means for this project and how to get there.

## Target users and workflow fit

- **Triage nurse / MA**: capture the intake (complaint + vitals + quick history) and generate a structured note draft.
- **Clinician**: reviews red flags, differential considerations, and next actions; confirms escalation/disposition.
- **Clinic admin / QA**: reviews audit traces for safety incidents and protocol drift.

Typical flow:

1. Intake is entered (or pasted) into ClinicaFlow.
2. ClinicaFlow returns a risk tier + red flags + actions + clinician handoff + patient precautions.
3. Clinician signs off before any action.
4. Optionally, an audit bundle is stored for QA/compliance review.

## Deployment modes

1) **Local demo / offline prototyping**

- `python -m clinicaflow.demo_server`
- No external model calls; deterministic reasoning; deterministic safety.

2) **On-prem clinic LAN**

- ClinicaFlow server runs in Docker.
- Model serving runs as a separate service (OpenAI-compatible endpoint).
- Strict network boundaries: the UI/API talks only to the on-prem model server.

3) **Hybrid**

- ClinicaFlow runs on-prem but can fall back to deterministic reasoning if the model tier is unreachable.

## Safety governance and audit

Design choices intended for real-world deployment:

- Safety-critical escalation is deterministic (rules + conservative thresholds).
- Each run includes an auditable trace and timing metadata.
- Evidence agent emits `policy_pack_sha256` + `policy_pack_source` so protocol updates are traceable.
- External reasoning emits `reasoning_backend_model` + `reasoning_prompt_version` so model/prompt changes are traceable.
- `clinicaflow audit` writes a run bundle (input + output + doctor diagnostics + manifest with hashes).

## Monitoring and operations

Out of the box (stdlib server):

- Request correlation via `X-Request-ID`
- Health probes: `GET /health`, `GET /ready`, `GET /live`
- Minimal metrics: `GET /metrics`
- Optional structured JSON logs: `CLINICAFLOW_JSON_LOGS=true`
- Config sanity check: `clinicaflow doctor`

## Privacy posture

- Prefer local-first execution; avoid sending PHI to third-party endpoints.
- Do not log raw patient inputs in production log pipelines.
- If using audit bundles, store securely with access control and retention policies.

## Roadmap to real deployment (high-level)

- Replace demo policy pack with site protocols and IDs (version-controlled).
- Add site-specific evaluation with clinician review (real-world distributions, not synthetic).
- Integrate with EHR (e.g., via FHIR/HL7) for intake prefill + note export (future work).
- Add role-based access control and authenticated API (future work).
- Establish change management: model/prompt/protocol versioning, rollbacks, and QA gates.

