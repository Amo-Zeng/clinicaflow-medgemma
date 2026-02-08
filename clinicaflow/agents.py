from __future__ import annotations

from dataclasses import asdict

from clinicaflow.models import PatientIntake, StructuredIntake, Vitals
from clinicaflow.policy_pack import PolicySnippet, load_policy_pack, match_policies
from clinicaflow.rules import RISK_FACTORS, compute_risk_tier, estimate_confidence, find_red_flags

SYMPTOM_LEXICON = [
    "chest pain",
    "chest tightness",
    "shortness of breath",
    "can’t catch breath",
    "cough",
    "fever",
    "headache",
    "dizziness",
    "fainting",
    "near-syncope",
    "nausea",
    "vomiting",
    "abdominal pain",
    "rash",
    "blurred vision",
    "slurred speech",
    "weakness one side",
    "word-finding difficulty",
    "confusion",
]


class IntakeStructuringAgent:
    name = "intake_structuring"

    def run(self, intake: PatientIntake) -> dict:
        text = intake.combined_text().lower()
        symptoms = [symptom for symptom in SYMPTOM_LEXICON if symptom in text]

        risk_factors: list[str] = []
        for factor in RISK_FACTORS:
            if factor in text:
                risk_factors.append(factor)

        missing_fields: list[str] = []
        if not intake.chief_complaint:
            missing_fields.append("chief_complaint")
        if intake.vitals.heart_rate is None:
            missing_fields.append("heart_rate")
        if intake.vitals.spo2 is None:
            missing_fields.append("spo2")
        if intake.vitals.temperature_c is None:
            missing_fields.append("temperature_c")

        structured = StructuredIntake(
            symptoms=symptoms or ["unspecified symptoms"],
            risk_factors=risk_factors,
            missing_fields=missing_fields,
            normalized_summary=intake.combined_text()[:1200],
        )
        return asdict(structured)


class MultimodalClinicalReasoningAgent:
    name = "multimodal_reasoning"

    def run(self, structured: StructuredIntake, vitals: Vitals) -> dict:
        differential: list[str] = []
        symptoms_text = " ".join(structured.symptoms)

        if "chest pain" in symptoms_text:
            differential.extend(["Acute coronary syndrome", "Pulmonary embolism", "GERD"])
        if "shortness of breath" in symptoms_text:
            differential.extend(["Pneumonia", "Asthma/COPD exacerbation", "Heart failure"])
        if "fever" in symptoms_text and "cough" in symptoms_text:
            differential.extend(["Community-acquired pneumonia", "Viral respiratory infection"])
        if not differential:
            differential.extend(["Viral syndrome", "Medication side effect", "Dehydration"])

        rationale = (
            "Differentials are prioritized using symptom pattern + available vitals. "
            "Final diagnosis is not made by the model; clinician validation is required."
        )

        return {
            "differential_considerations": _dedupe(differential)[:5],
            "reasoning_rationale": rationale,
            "uses_multimodal_context": bool(structured.normalized_summary),
        }


class EvidencePolicyAgent:
    name = "evidence_policy"

    def run(self, reasoning: dict, structured: StructuredIntake) -> dict:
        policies = _default_policies()
        matched = match_policies(policies, text=structured.normalized_summary)

        action_pool = [
            "Repeat full set of vitals within 15 minutes",
            "Obtain focused history for symptom onset, severity, and progression",
            "Document explicit red-flag checks in triage note",
        ]
        for policy in matched[:2]:
            action_pool.extend(policy.recommended_actions)

        return {
            "protocol_citations": [policy.to_dict() for policy in matched[:2]],
            "recommended_next_actions": _dedupe(action_pool)[:6],
            "evidence_note": "Recommendations are grounded in a demo policy pack; replace with site protocol IDs and citations.",
        }


class SafetyEscalationAgent:
    name = "safety_escalation"

    def run(self, structured: StructuredIntake, vitals: Vitals, recommended_actions: list[str]) -> dict:
        red_flags = find_red_flags(structured, vitals)
        risk_tier = compute_risk_tier(red_flags, structured.missing_fields, vitals)
        confidence, uncertainty_reasons = estimate_confidence(risk_tier, red_flags, structured.missing_fields)

        escalation_required = risk_tier in {"critical", "urgent"}
        if escalation_required and "Urgent clinician review" not in recommended_actions:
            recommended_actions = ["Urgent clinician review", *recommended_actions]

        return {
            "risk_tier": risk_tier,
            "red_flags": red_flags,
            "escalation_required": escalation_required,
            "confidence": confidence,
            "uncertainty_reasons": uncertainty_reasons,
            "recommended_next_actions": _dedupe(recommended_actions),
        }


class CommunicationAgent:
    name = "communication"

    def run(self, intake: PatientIntake, safety: dict, reasoning: dict) -> dict:
        clinician_handoff = (
            f"Risk tier: {safety['risk_tier']}. "
            f"Key concerns: {', '.join(safety['red_flags']) or 'No explicit red flags detected'}. "
            f"Top differentials: {', '.join(reasoning['differential_considerations'])}."
        )

        patient_summary = (
            "You were evaluated with an AI-assisted triage tool. "
            "This output supports your care team and is not a final diagnosis. "
            "If symptoms worsen, seek urgent medical care immediately."
        )

        return {
            "clinician_handoff": clinician_handoff,
            "patient_summary": patient_summary,
        }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


_CACHED_POLICIES: list[PolicySnippet] | None = None


def _default_policies() -> list[PolicySnippet]:
    global _CACHED_POLICIES  # noqa: PLW0603
    if _CACHED_POLICIES is not None:
        return _CACHED_POLICIES
    try:
        from importlib.resources import files

        policy_path = files("clinicaflow.resources").joinpath("policy_pack.json")
        _CACHED_POLICIES = load_policy_pack(policy_path)
    except Exception:  # noqa: BLE001
        _CACHED_POLICIES = []
    return _CACHED_POLICIES
