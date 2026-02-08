from __future__ import annotations

import os

from clinicaflow.inference.json_extract import JsonExtractError, extract_first_json_object
from clinicaflow.inference.openai_compatible import (
    InferenceError,
    chat_completion,
    load_openai_compatible_config_from_env,
)
from clinicaflow.models import StructuredIntake, Vitals


def build_reasoning_prompt(*, structured: StructuredIntake, vitals: Vitals) -> tuple[str, str]:
    system = (
        "You are a careful clinical decision-support assistant. "
        "You must not provide definitive diagnoses. "
        "Return ONLY valid JSON that matches the requested schema."
    )

    user = f"""You are helping a triage workflow.

Schema (JSON object):
- differential_considerations: array of up to 5 strings
- reasoning_rationale: string (1-3 sentences)
- uses_multimodal_context: boolean

Patient structured intake:
- symptoms: {structured.symptoms}
- risk_factors: {structured.risk_factors}
- missing_fields: {structured.missing_fields}
- summary: {structured.normalized_summary}

Vitals:
- heart_rate: {vitals.heart_rate}
- systolic_bp: {vitals.systolic_bp}
- diastolic_bp: {vitals.diastolic_bp}
- temperature_c: {vitals.temperature_c}
- spo2: {vitals.spo2}
- respiratory_rate: {vitals.respiratory_rate}

Return ONLY JSON.
"""

    return system, user


def run_reasoning_backend(*, structured: StructuredIntake, vitals: Vitals) -> dict | None:
    backend = os.environ.get("CLINICAFLOW_REASONING_BACKEND", "deterministic").strip().lower()
    if backend in {"", "deterministic"}:
        return None

    if backend not in {"openai", "openai_compatible"}:
        raise ValueError(f"Unsupported CLINICAFLOW_REASONING_BACKEND: {backend}")

    config = load_openai_compatible_config_from_env()
    system, user = build_reasoning_prompt(structured=structured, vitals=vitals)
    text = chat_completion(config=config, system=system, user=user)

    try:
        payload = extract_first_json_object(text)
    except JsonExtractError as exc:
        raise InferenceError(f"Model did not return valid JSON: {exc}") from exc

    differential = payload.get("differential_considerations")
    rationale = payload.get("reasoning_rationale")
    uses_multimodal = payload.get("uses_multimodal_context")

    if not isinstance(differential, list) or not all(isinstance(x, str) for x in differential):
        raise InferenceError("Invalid JSON: differential_considerations must be a list of strings")
    if not isinstance(rationale, str) or not rationale.strip():
        raise InferenceError("Invalid JSON: reasoning_rationale must be a non-empty string")
    if not isinstance(uses_multimodal, bool):
        raise InferenceError("Invalid JSON: uses_multimodal_context must be boolean")

    return {
        "differential_considerations": [x.strip() for x in differential if x.strip()][:5],
        "reasoning_rationale": rationale.strip(),
        "uses_multimodal_context": uses_multimodal,
    }
