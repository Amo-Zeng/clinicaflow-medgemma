from __future__ import annotations

from clinicaflow.models import StructuredIntake, Vitals

RED_FLAG_KEYWORDS = {
    "chest pain": "Potential acute coronary syndrome",
    "chest tightness": "Potential acute coronary syndrome",
    "shortness of breath": "Respiratory compromise risk",
    "can’t catch breath": "Respiratory compromise risk",
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


def compute_risk_tier(red_flags: list[str], missing_fields: list[str], vitals: Vitals) -> str:
    if len(red_flags) >= 2:
        return "critical"
    if red_flags:
        return "urgent"

    vital_concern = (
        (vitals.heart_rate is not None and vitals.heart_rate >= 110)
        or (vitals.temperature_c is not None and vitals.temperature_c >= 38.5)
        or (vitals.spo2 is not None and vitals.spo2 < 95)
    )
    if vital_concern:
        return "urgent"

    if len(missing_fields) >= 3:
        return "urgent"

    return "routine"


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
