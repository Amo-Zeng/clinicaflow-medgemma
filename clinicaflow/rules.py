from __future__ import annotations

from clinicaflow.models import StructuredIntake, Vitals

SAFETY_RULES_VERSION = "2026-02-19.v2"

RED_FLAG_KEYWORDS = {
    "chest pain": "Potential acute coronary syndrome",
    "chest tightness": "Potential acute coronary syndrome",
    "shortness of breath": "Respiratory compromise risk",
    "can't catch breath": "Respiratory compromise risk",
    "confusion": "Possible neurological or metabolic emergency",
    "fainting": "Syncope requiring urgent evaluation",
    "near-syncope": "Syncope requiring urgent evaluation",
    "severe headache": "Possible intracranial pathology",
    "weakness one side": "Possible stroke",
    "slurred speech": "Possible stroke",
    "word-finding difficulty": "Possible stroke",
    "bloody stool": "Possible gastrointestinal bleed",
    "vomiting blood": "Possible upper GI bleed",
    "pregnancy bleeding": "Possible obstetric emergency",
}

RISK_FACTORS = {
    "diabetes",
    "hypertension",
    "ckd",
    "copd",
    "asthma",
    "cancer",
    "immunosuppressed",
    "pregnancy",
}


def find_red_flags(structured: StructuredIntake, vitals: Vitals) -> list[str]:
    red_flags: list[str] = []

    symptom_text = " ".join(structured.symptoms).lower()
    for key, reason in RED_FLAG_KEYWORDS.items():
        if key in symptom_text:
            red_flags.append(reason)

    if vitals.spo2 is not None and vitals.spo2 < 92:
        red_flags.append("Low oxygen saturation (<92%)")
    if vitals.systolic_bp is not None and vitals.systolic_bp < 90:
        red_flags.append("Hypotension (SBP < 90)")
    if vitals.heart_rate is not None and vitals.heart_rate > 130:
        red_flags.append("Severe tachycardia (HR > 130)")
    if vitals.temperature_c is not None and vitals.temperature_c >= 39.5:
        red_flags.append("High fever (>= 39.5°C)")

    return _dedupe(red_flags)


def compute_risk_tier_with_rationale(red_flags: list[str], missing_fields: list[str], vitals: Vitals) -> tuple[str, str]:
    # Hemodynamic instability is an immediate escalation trigger.
    if any("Hypotension" in rf or "Severe tachycardia" in rf for rf in red_flags):
        return "critical", "Hemodynamic instability (hypotension/tachycardia)"

    # Hypoxemia is particularly high-risk when paired with a cardiopulmonary complaint.
    has_hypox = any("Low oxygen saturation" in rf for rf in red_flags)
    has_cardio = any("Respiratory compromise risk" in rf or "acute coronary syndrome" in rf.lower() for rf in red_flags)
    if has_hypox and has_cardio:
        return "critical", "Hypoxemia with cardiopulmonary complaint"

    if len(red_flags) >= 2:
        return "critical", "2+ red flags"
    if red_flags:
        return "urgent", "Red flags present"

    vital_concern = (
        (vitals.heart_rate is not None and vitals.heart_rate >= 110)
        or (vitals.temperature_c is not None and vitals.temperature_c >= 38.5)
        or (vitals.spo2 is not None and vitals.spo2 < 95)
    )
    if vital_concern:
        return "urgent", "Vital concern (HR ≥110, temp ≥38.5°C, or SpO₂ <95)"

    if len(missing_fields) >= 3:
        return "urgent", "Insufficient intake fields"

    return "routine", "No red flags and stable vitals"


def compute_risk_tier(red_flags: list[str], missing_fields: list[str], vitals: Vitals) -> str:
    return compute_risk_tier_with_rationale(red_flags, missing_fields, vitals)[0]


def estimate_confidence(risk_tier: str, red_flags: list[str], missing_fields: list[str]) -> tuple[float, list[str]]:
    base = 0.86
    reasons: list[str] = []

    if risk_tier == "critical":
        base -= 0.08
        reasons.append("High-acuity case requires clinician confirmation")
    if len(red_flags) >= 2:
        base -= 0.04
        reasons.append("Multiple red flags increase complexity")
    if missing_fields:
        base -= min(0.18, 0.04 * len(missing_fields))
        reasons.append(f"Missing intake fields: {', '.join(missing_fields)}")

    confidence = max(0.45, min(base, 0.98))
    return round(confidence, 2), reasons


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
