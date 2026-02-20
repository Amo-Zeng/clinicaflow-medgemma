from __future__ import annotations

from typing import Any

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


def compute_safety_triggers(red_flags: list[str], missing_fields: list[str], vitals: Vitals) -> list[dict[str, Any]]:
    """Return structured safety triggers that explain why a tier/escalation was chosen.

    This is used for transparency in the UI and in report exports. It mirrors the
    deterministic tier logic in `compute_risk_tier_with_rationale()` but returns
    a structured explanation instead of a single string.
    """

    triggers: list[dict[str, Any]] = []

    def add(id_: str, severity: str, label: str, detail: str) -> None:
        triggers.append({"id": id_, "severity": severity, "label": label, "detail": detail})

    # Critical triggers (highest priority).
    if any("Hypotension" in rf or "Severe tachycardia" in rf for rf in red_flags):
        add(
            "hemodynamic_instability",
            "critical",
            "Hemodynamic instability",
            "Hypotension (SBP < 90) or severe tachycardia (HR > 130).",
        )

    has_hypox = any("Low oxygen saturation" in rf for rf in red_flags)
    has_cardio = any("Respiratory compromise risk" in rf or "acute coronary syndrome" in rf.lower() for rf in red_flags)
    if has_hypox and has_cardio:
        add(
            "hypoxemia_with_cardiopulmonary",
            "critical",
            "Hypoxemia + cardiopulmonary complaint",
            "SpO₂ < 92% with a cardiopulmonary red-flag pattern.",
        )

    if len(red_flags) >= 2:
        add("multiple_red_flags", "critical", "Multiple red flags", "2+ red flags detected in the same intake.")

    # Urgent triggers.
    if red_flags:
        add("red_flags_present", "urgent", "Red flags present", "1+ red flags detected in the intake.")

    vital_concern = (
        (vitals.heart_rate is not None and vitals.heart_rate >= 110)
        or (vitals.temperature_c is not None and vitals.temperature_c >= 38.5)
        or (vitals.spo2 is not None and vitals.spo2 < 95)
    )
    if vital_concern:
        add("vital_concern", "urgent", "Vital-sign concern", "HR ≥110, Temp ≥38.5°C, or SpO₂ <95%.")

    if len(missing_fields) >= 3:
        add("insufficient_intake_fields", "urgent", "Insufficient intake fields", "3+ critical fields missing.")

    # Dedupe by id while preserving ordering (severity ordering matters).
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in triggers:
        tid = str(t.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(t)
    return out


def compute_risk_scores(*, structured: StructuredIntake, vitals: Vitals) -> dict[str, Any]:
    """Compute lightweight, interpretable risk scores (demo only).

    These scores are provided for clinician situational awareness and are NOT
    intended to replace formal clinical tools or site protocols.
    """

    scores: dict[str, Any] = {}

    # Shock index (HR/SBP) is a simple hemodynamic instability signal.
    if vitals.heart_rate is not None and vitals.systolic_bp is not None and vitals.systolic_bp > 0:
        shock_index = float(vitals.heart_rate) / float(vitals.systolic_bp)
        scores["shock_index"] = round(shock_index, 2)
        scores["shock_index_high"] = bool(shock_index >= 0.9)

    # qSOFA (approximate): RR >=22, SBP <=100, and altered mental status (proxy via "confusion" symptom).
    q = 0
    rr = vitals.respiratory_rate
    sbp = vitals.systolic_bp
    has_ams = "confusion" in (" ".join(structured.symptoms).lower())
    if rr is not None and rr >= 22:
        q += 1
    if sbp is not None and sbp <= 100:
        q += 1
    if has_ams:
        q += 1
    scores["qsofa"] = int(q)
    scores["qsofa_high_risk"] = bool(q >= 2)
    scores["qsofa_components"] = {
        "rr_ge_22": bool(rr is not None and rr >= 22),
        "sbp_le_100": bool(sbp is not None and sbp <= 100),
        "ams_proxy": bool(has_ams),
    }

    return scores


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


def safety_rules_catalog() -> dict[str, Any]:
    """Return a static, explainable catalog of deterministic safety rules.

    This is intended for governance transparency and UI "rulebook" views. It is
    not a clinical guideline and must be replaced/validated against site
    protocols before any deployment.
    """

    vitals_red_flags = [
        {"id": "spo2_lt_92", "label": "Low oxygen saturation (<92%)", "condition": "spo2 < 92"},
        {"id": "sbp_lt_90", "label": "Hypotension (SBP < 90)", "condition": "systolic_bp < 90"},
        {"id": "hr_gt_130", "label": "Severe tachycardia (HR > 130)", "condition": "heart_rate > 130"},
        {"id": "temp_gte_39_5", "label": "High fever (>= 39.5°C)", "condition": "temperature_c >= 39.5"},
    ]

    trigger_catalog = [
        {
            "id": "hemodynamic_instability",
            "severity": "critical",
            "label": "Hemodynamic instability",
            "detail": "Hypotension (SBP < 90) or severe tachycardia (HR > 130).",
        },
        {
            "id": "hypoxemia_with_cardiopulmonary",
            "severity": "critical",
            "label": "Hypoxemia + cardiopulmonary complaint",
            "detail": "SpO₂ < 92% with a cardiopulmonary red-flag pattern.",
        },
        {
            "id": "multiple_red_flags",
            "severity": "critical",
            "label": "Multiple red flags",
            "detail": "2+ red flags detected in the same intake.",
        },
        {
            "id": "red_flags_present",
            "severity": "urgent",
            "label": "Red flags present",
            "detail": "1+ red flags detected in the intake.",
        },
        {
            "id": "vital_concern",
            "severity": "urgent",
            "label": "Vital-sign concern",
            "detail": "HR ≥110, Temp ≥38.5°C, or SpO₂ <95%.",
        },
        {
            "id": "insufficient_intake_fields",
            "severity": "urgent",
            "label": "Insufficient intake fields",
            "detail": "3+ critical fields missing.",
        },
    ]

    return {
        "safety_rules_version": SAFETY_RULES_VERSION,
        "red_flag_keywords": dict(RED_FLAG_KEYWORDS),
        "risk_factor_keywords": sorted(RISK_FACTORS),
        "vitals_red_flags": vitals_red_flags,
        "safety_trigger_catalog": trigger_catalog,
        "notes": [
            "Decision support only. Not a diagnosis.",
            "This catalog is a demo rulebook for transparency; replace with site protocols.",
        ],
    }
