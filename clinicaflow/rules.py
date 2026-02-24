from __future__ import annotations

from typing import Any

from clinicaflow.models import StructuredIntake, Vitals

SAFETY_RULES_VERSION = "2026-02-24.v3"

EVIDENCE_LINKS: dict[str, list[dict[str, str]]] = {
    # Vitals triggers
    "spo2_lt_92": [
        {
            "title": "MedlinePlus — Pulse oximetry (SpO₂ ≤92%: contact provider; ≤88%: seek immediate care)",
            "url": "https://medlineplus.gov/lab-tests/pulse-oximetry/",
        }
    ],
    "sbp_lt_90": [
        {
            "title": "NICE — Suspected sepsis (age ≥16): SBP ≤90 mmHg is high risk",
            "url": "https://www.nice.org.uk/guidance/ng253/chapter/Evaluating-risk",
        },
        {"title": "MedlinePlus — Low blood pressure: severe hypotension from shock is an emergency", "url": "https://medlineplus.gov/ency/article/007278.htm"},
    ],
    "hr_gt_130": [
        {
            "title": "NICE — Suspected sepsis (age ≥16): HR >130 bpm is high risk",
            "url": "https://www.nice.org.uk/guidance/ng253/chapter/Evaluating-risk",
        },
        {"title": "American Heart Association — Tachycardia (fast heart rate) overview", "url": "https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/tachycardia--fast-heart-rate"},
    ],
    "temp_gte_39_5": [
        {
            "title": "MedlinePlus — Fever: adult fever staying at/above 103°F (39.4°C) warrants contacting a provider",
            "url": "https://medlineplus.gov/ency/article/003090.htm",
        },
        {"title": "CDC — Sepsis: fever and high heart rate are warning signs", "url": "https://www.cdc.gov/sepsis/about/index.html"},
    ],
    # Safety trigger catalog
    "hemodynamic_instability": [
        {
            "title": "NICE — Suspected sepsis (age ≥16): SBP ≤90 mmHg or HR >130 bpm are high-risk criteria",
            "url": "https://www.nice.org.uk/guidance/ng253/chapter/Evaluating-risk",
        }
    ],
    "hypoxemia_with_cardiopulmonary": [
        {
            "title": "MedlinePlus — Pulse oximetry (SpO₂ ≤92%: contact provider; ≤88%: seek immediate care)",
            "url": "https://medlineplus.gov/lab-tests/pulse-oximetry/",
        },
        {"title": "CDC — Heart attack symptoms: chest discomfort and shortness of breath; call 9-1-1", "url": "https://www.cdc.gov/heart-disease/about/heart-attack.html"},
    ],
    "multiple_red_flags": [
        {"title": "CDC — Sepsis is a medical emergency: may include confusion, shortness of breath, high heart rate", "url": "https://www.cdc.gov/sepsis/about/index.html"},
        {"title": "MedlinePlus — Stroke symptoms can be sudden; call 911 right away", "url": "https://medlineplus.gov/stroke.html"},
    ],
    "red_flags_present": [
        {"title": "CDC — Heart attack symptoms: call 9-1-1", "url": "https://www.cdc.gov/heart-disease/about/heart-attack.html"},
        {"title": "MedlinePlus — Stroke symptoms: call 911 right away", "url": "https://medlineplus.gov/stroke.html"},
        {"title": "MedlinePlus — GI bleeding: black tarry stool / vomiting blood → emergency care", "url": "https://medlineplus.gov/ency/article/003133.htm"},
    ],
    "vital_concern": [
        {"title": "CDC — Sepsis warning signs include fever, high heart rate, and shortness of breath", "url": "https://www.cdc.gov/sepsis/about/index.html"},
        {"title": "MedlinePlus — Pulse oximetry guidance for low SpO₂ values", "url": "https://medlineplus.gov/lab-tests/pulse-oximetry/"},
    ],
    "insufficient_intake_fields": [
        {
            "title": "NICE — Suspected sepsis: risk evaluation relies on physiologic/vital-sign assessment",
            "url": "https://www.nice.org.uk/guidance/ng253/chapter/Evaluating-risk",
        }
    ],
}

RED_FLAG_KEYWORDS = {
    "chest pain": "Potential acute coronary syndrome",
    "chest tightness": "Potential acute coronary syndrome",
    "shortness of breath": "Respiratory compromise risk",
    "can't catch breath": "Respiratory compromise risk",
    "confusion": "Possible neurological or metabolic emergency",
    "fainting": "Syncope requiring urgent evaluation",
    "near-syncope": "Syncope requiring urgent evaluation",
    "severe headache": "Possible intracranial pathology",
    "worst headache": "Possible intracranial pathology",
    "thunderclap": "Possible intracranial pathology",
    "weakness one side": "Possible stroke",
    "slurred speech": "Possible stroke",
    "word-finding difficulty": "Possible stroke",
    "bloody stool": "Possible gastrointestinal bleed",
    "black tarry": "Possible gastrointestinal bleed",
    "tarry stool": "Possible gastrointestinal bleed",
    "melena": "Possible gastrointestinal bleed",
    "vomiting blood": "Possible upper GI bleed",
    "hematemesis": "Possible upper GI bleed",
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
        triggers.append(
            {
                "id": id_,
                "severity": severity,
                "label": label,
                "detail": detail,
                "evidence": EVIDENCE_LINKS.get(id_, []),
            }
        )

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
        {
            "id": "spo2_lt_92",
            "label": "Low oxygen saturation (<92%)",
            "condition": "spo2 < 92",
            "evidence": EVIDENCE_LINKS.get("spo2_lt_92", []),
        },
        {
            "id": "sbp_lt_90",
            "label": "Hypotension (SBP < 90)",
            "condition": "systolic_bp < 90",
            "evidence": EVIDENCE_LINKS.get("sbp_lt_90", []),
        },
        {
            "id": "hr_gt_130",
            "label": "Severe tachycardia (HR > 130)",
            "condition": "heart_rate > 130",
            "evidence": EVIDENCE_LINKS.get("hr_gt_130", []),
        },
        {
            "id": "temp_gte_39_5",
            "label": "High fever (>= 39.5°C)",
            "condition": "temperature_c >= 39.5",
            "evidence": EVIDENCE_LINKS.get("temp_gte_39_5", []),
        },
    ]

    trigger_catalog = [
        {
            "id": "hemodynamic_instability",
            "severity": "critical",
            "label": "Hemodynamic instability",
            "detail": "Hypotension (SBP < 90) or severe tachycardia (HR > 130).",
            "evidence": EVIDENCE_LINKS.get("hemodynamic_instability", []),
        },
        {
            "id": "hypoxemia_with_cardiopulmonary",
            "severity": "critical",
            "label": "Hypoxemia + cardiopulmonary complaint",
            "detail": "SpO₂ < 92% with a cardiopulmonary red-flag pattern.",
            "evidence": EVIDENCE_LINKS.get("hypoxemia_with_cardiopulmonary", []),
        },
        {
            "id": "multiple_red_flags",
            "severity": "critical",
            "label": "Multiple red flags",
            "detail": "2+ red flags detected in the same intake.",
            "evidence": EVIDENCE_LINKS.get("multiple_red_flags", []),
        },
        {
            "id": "red_flags_present",
            "severity": "urgent",
            "label": "Red flags present",
            "detail": "1+ red flags detected in the intake.",
            "evidence": EVIDENCE_LINKS.get("red_flags_present", []),
        },
        {
            "id": "vital_concern",
            "severity": "urgent",
            "label": "Vital-sign concern",
            "detail": "HR ≥110, Temp ≥38.5°C, or SpO₂ <95%.",
            "evidence": EVIDENCE_LINKS.get("vital_concern", []),
        },
        {
            "id": "insufficient_intake_fields",
            "severity": "urgent",
            "label": "Insufficient intake fields",
            "detail": "3+ critical fields missing.",
            "evidence": EVIDENCE_LINKS.get("insufficient_intake_fields", []),
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
