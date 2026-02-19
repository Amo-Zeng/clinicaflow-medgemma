from __future__ import annotations

import os

from clinicaflow.inference.json_extract import JsonExtractError, extract_first_json_object
from clinicaflow.inference.openai_compatible import (
    InferenceError,
    chat_completion,
    load_openai_compatible_config_from_env,
)

COMMUNICATION_PROMPT_VERSION = "2026-02-19.v1"


def build_communication_prompt(*, draft_clinician: str, draft_patient: str) -> tuple[str, str]:
    system = (
        "You are a clinical documentation and patient-instructions assistant. "
        "You MUST NOT add new clinical facts, vitals, meds, diagnoses, or red flags. "
        "You may only rewrite the provided drafts for clarity and conciseness. "
        "Keep a conservative safety posture and preserve the disclaimer language. "
        "Return ONLY valid JSON matching the requested schema."
    )

    user = f"""Rewrite the following two drafts.

Rules:
- Do NOT introduce any new medical facts.
- Do NOT introduce any definitive diagnosis.
- You may reformat bulleting and wording for clarity.
- Keep the meaning and safety constraints the same.

Schema (JSON object):
- clinician_handoff: string (may include bullets)
- patient_summary: string (plain language; includes return precautions)

Draft clinician_handoff:
{draft_clinician.strip()}

Draft patient_summary:
{draft_patient.strip()}

Return ONLY JSON.
"""
    return system, user


def run_communication_backend(*, draft_clinician: str, draft_patient: str) -> dict | None:
    backend = os.environ.get("CLINICAFLOW_COMMUNICATION_BACKEND", "deterministic").strip().lower()
    if backend in {"", "deterministic"}:
        return None

    if backend not in {"openai", "openai_compatible"}:
        raise ValueError(f"Unsupported CLINICAFLOW_COMMUNICATION_BACKEND: {backend}")

    config = load_openai_compatible_config_from_env()
    system, user = build_communication_prompt(draft_clinician=draft_clinician, draft_patient=draft_patient)
    text = chat_completion(config=config, system=system, user=user)

    try:
        payload = extract_first_json_object(text)
    except JsonExtractError as exc:
        raise InferenceError(f"Model did not return valid JSON: {exc}") from exc

    clinician = payload.get("clinician_handoff")
    patient = payload.get("patient_summary")

    if not isinstance(clinician, str) or not clinician.strip():
        raise InferenceError("Invalid JSON: clinician_handoff must be a non-empty string")
    if not isinstance(patient, str) or not patient.strip():
        raise InferenceError("Invalid JSON: patient_summary must be a non-empty string")

    return {
        "clinician_handoff": clinician.strip(),
        "patient_summary": patient.strip(),
        "communication_backend_model": config.model,
        "communication_prompt_version": COMMUNICATION_PROMPT_VERSION,
    }

