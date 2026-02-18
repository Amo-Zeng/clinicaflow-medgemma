from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from clinicaflow.models import PatientIntake, TriageResult, Vitals


def build_fhir_bundle(*, intake: PatientIntake, result: TriageResult, redact: bool = False) -> dict[str, Any]:
    """Build a minimal FHIR R4 Bundle for demo interoperability.

    This is intentionally lightweight and conservative:
    - No definitive diagnoses are asserted.
    - IDs are deterministic within the bundle.
    - If `redact=True`, demographics and free-text notes are omitted.
    """

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    intake_payload = asdict(intake)

    if redact:
        intake_payload["demographics"] = {}
        intake_payload["prior_notes"] = []
        intake_payload["image_descriptions"] = []
        intake_payload["history"] = ""

    patient = _patient_resource(intake_payload.get("demographics") or {}, request_id=result.request_id, redact=redact)
    observations = _vitals_observations(intake.vitals, patient_ref="Patient/patient", request_id=result.request_id)
    triage = _clinical_impression(result=result, patient_ref="Patient/patient")
    comms = _patient_communication(result=result, patient_ref="Patient/patient")

    entries = [{"resource": patient}, *[{"resource": o} for o in observations], {"resource": triage}, {"resource": comms}]

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": created_at,
        "identifier": {"system": "urn:clinicaflow:request_id", "value": result.request_id},
        "entry": entries,
    }


def _patient_resource(demographics: dict[str, Any], *, request_id: str, redact: bool) -> dict[str, Any]:
    gender = str(demographics.get("sex") or "").strip().lower()
    if gender not in {"male", "female", "other", "unknown"}:
        gender = ""

    # Age is frequently available in intake, but mapping to birthDate is unsafe.
    # We keep it only in the narrative text for demo purposes.
    age = demographics.get("age")
    age_s = str(age).strip() if age is not None else ""

    narrative_bits = []
    if age_s and not redact:
        narrative_bits.append(f"Age {age_s}")
    if gender and not redact:
        narrative_bits.append(f"Sex {gender}")
    narrative = ", ".join(narrative_bits) if narrative_bits else "Synthetic/demo patient"

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": "patient",
        "text": {"status": "generated", "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{narrative}</div>"},
        "identifier": [{"system": "urn:clinicaflow:request_id", "value": request_id}],
    }
    if gender and not redact:
        resource["gender"] = gender
    return resource


def _vitals_observations(vitals: Vitals, *, patient_ref: str, request_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def obs(*, code: str, display: str, value: float | None, unit: str, oid: str) -> None:
        if value is None:
            return
        out.append(
            {
                "resourceType": "Observation",
                "id": oid,
                "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                "subject": {"reference": patient_ref},
                "valueQuantity": {"value": value, "unit": unit},
                "identifier": [{"system": "urn:clinicaflow:request_id", "value": request_id}],
            }
        )

    obs(code="8867-4", display="Heart rate", value=vitals.heart_rate, unit="/min", oid="obs-hr")
    obs(code="8480-6", display="Systolic blood pressure", value=vitals.systolic_bp, unit="mmHg", oid="obs-sbp")
    obs(code="8462-4", display="Diastolic blood pressure", value=vitals.diastolic_bp, unit="mmHg", oid="obs-dbp")
    obs(code="8310-5", display="Body temperature", value=vitals.temperature_c, unit="°C", oid="obs-temp")
    obs(code="59408-5", display="Oxygen saturation in Arterial blood by Pulse oximetry", value=vitals.spo2, unit="%", oid="obs-spo2")
    obs(code="9279-1", display="Respiratory rate", value=vitals.respiratory_rate, unit="/min", oid="obs-rr")
    return out


def _clinical_impression(*, result: TriageResult, patient_ref: str) -> dict[str, Any]:
    return {
        "resourceType": "ClinicalImpression",
        "id": "triage",
        "status": "completed",
        "subject": {"reference": patient_ref},
        "summary": f"Triage risk tier: {result.risk_tier}. Escalation required: {result.escalation_required}.",
        "note": [
            {"text": "ClinicaFlow is decision support only; not a diagnosis."},
            {"text": f"Red flags: {', '.join(result.red_flags) if result.red_flags else '(none detected)'}"},
            {"text": f"Top differentials: {', '.join(result.differential_considerations)}"},
            {"text": "Recommended next actions:"},
            *[{"text": f"- {x}"} for x in (result.recommended_next_actions or [])],
        ],
    }


def _patient_communication(*, result: TriageResult, patient_ref: str) -> dict[str, Any]:
    return {
        "resourceType": "Communication",
        "id": "patient-precautions",
        "status": "completed",
        "subject": {"reference": patient_ref},
        "payload": [{"contentString": result.patient_summary}],
    }
