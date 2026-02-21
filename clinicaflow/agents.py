from __future__ import annotations

from dataclasses import asdict
import re

from clinicaflow.models import PatientIntake, StructuredIntake, Vitals
from clinicaflow.policy_pack import PolicySnippet, load_policy_pack, match_policies, policy_pack_sha256
from clinicaflow.privacy import detect_phi_hits, external_calls_allowed
from clinicaflow.quality import intake_quality_warnings
from clinicaflow.rules import (
    RISK_FACTORS,
    SAFETY_RULES_VERSION,
    compute_safety_triggers,
    compute_risk_tier_with_rationale,
    compute_risk_scores,
    estimate_confidence,
    find_red_flags,
)
from clinicaflow.settings import load_settings_from_env
from clinicaflow.text import normalize_text, sanitize_untrusted_text

SYMPTOM_LEXICON = [
    "chest pain",
    "chest tightness",
    "shortness of breath",
    "can't catch breath",
    "cough",
    "fever",
    "headache",
    "severe headache",
    "dizziness",
    "fainting",
    "near-syncope",
    "nausea",
    "vomiting",
    "vomiting blood",
    "abdominal pain",
    "bloody stool",
    "pregnancy bleeding",
    "rash",
    "blurred vision",
    "slurred speech",
    "weakness one side",
    "word-finding difficulty",
    "confusion",
]

_SYMPTOM_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    ("chest pain", [re.compile(r"\bchest pain\b"), re.compile(r"\bchest pressure\b"), re.compile(r"\bcp\b")]),
    ("chest tightness", [re.compile(r"\bchest tightness\b"), re.compile(r"\btightness in (the|my) chest\b")]),
    (
        "shortness of breath",
        [re.compile(r"\bshortness of breath\b"), re.compile(r"\bsob\b"), re.compile(r"\bdyspnea\b"), re.compile(r"\bdifficulty breathing\b")],
    ),
    ("can't catch breath", [re.compile(r"\b(can't|cannot) catch (my )?breath\b")]),
    ("confusion", [re.compile(r"\bconfusion\b"), re.compile(r"\bams\b"), re.compile(r"\baltered mental status\b"), re.compile(r"\bnot making sense\b")]),
    ("slurred speech", [re.compile(r"\bslurred speech\b"), re.compile(r"\bdysarthria\b")]),
    (
        "weakness one side",
        [
            re.compile(r"\b(one[- ]sided|unilateral)\b.{0,12}\bweakness\b"),
            re.compile(r"\bweakness on (the )?(left|right) (side|arm|leg)\b"),
            re.compile(r"\bweakness( on)? one side\b"),
        ],
    ),
    ("word-finding difficulty", [re.compile(r"\bword[- ]finding\b"), re.compile(r"\baphasia\b"), re.compile(r"\btrouble finding words\b")]),
    ("severe headache", [re.compile(r"\bsevere headache\b"), re.compile(r"\bworst headache\b"), re.compile(r"\bthunderclap\b")]),
    ("fainting", [re.compile(r"\bfaint(ed|ing)?\b"), re.compile(r"\bsyncope\b"), re.compile(r"\bpassed out\b")]),
    ("near-syncope", [re.compile(r"\bnear[- ]syncope\b"), re.compile(r"\bnear syncop(al|e)\b"), re.compile(r"\balmost faint(ed|ing)?\b"), re.compile(r"\bnearly passed out\b")]),
    ("vomiting blood", [re.compile(r"\bvomit(ing)? blood\b"), re.compile(r"\bhemat\s*emesis\b"), re.compile(r"\bhematemesis\b"), re.compile(r"\bcoffee[- ]ground\b")]),
    (
        "bloody stool",
        [
            re.compile(r"\bbloody stool\b"),
            re.compile(r"\bmelena\b"),
            re.compile(r"\bblack (tarry )?stool(s)?\b"),
            re.compile(r"\bhematochezia\b"),
            re.compile(r"\bbright red blood per rectum\b"),
            re.compile(r"\bbrbpr\b"),
        ],
    ),
    # pregnancy bleeding is added via a two-factor check (pregnancy + bleeding/spotting).
]


class IntakeStructuringAgent:
    name = "intake_structuring"

    def run(self, intake: PatientIntake) -> dict:
        combined = intake.combined_text()
        text = normalize_text(combined).lower()

        symptoms: list[str] = []
        for canonical, patterns in _SYMPTOM_RULES:
            for pat in patterns:
                if _contains_non_negated_regex(text, pat):
                    symptoms.append(canonical)
                    break

        # Two-factor: only trigger obstetric red-flag when pregnancy context is present.
        if _contains_non_negated_regex(text, re.compile(r"\bpregnan")) and _contains_non_negated_regex(
            text, re.compile(r"\b(bleeding|spotting)\b")
        ):
            symptoms.append("pregnancy bleeding")

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

        phi_hits = detect_phi_hits(combined)
        quality_warnings = intake_quality_warnings(intake)

        structured = StructuredIntake(
            symptoms=_dedupe(symptoms) or ["unspecified symptoms"],
            risk_factors=risk_factors,
            missing_fields=missing_fields,
            normalized_summary=sanitize_untrusted_text(intake.combined_text(), max_chars=1200),
            phi_hits=phi_hits,
            data_quality_warnings=quality_warnings,
        )
        return asdict(structured)


class MultimodalClinicalReasoningAgent:
    name = "multimodal_reasoning"

    def run(self, structured: StructuredIntake, vitals: Vitals, *, image_data_urls: list[str] | None = None) -> dict:
        phi_hits = [str(x) for x in (structured.phi_hits or []) if str(x).strip()]
        backend_skipped_reason = ""
        if not external_calls_allowed(phi_hits=phi_hits):
            backend_skipped_reason = f"PHI guard blocked external call: {', '.join(phi_hits)}"

        try:
            from clinicaflow.inference.reasoning import run_reasoning_backend

            backend_payload = (
                None
                if backend_skipped_reason
                else run_reasoning_backend(structured=structured, vitals=vitals, image_data_urls=image_data_urls)
            )
            if backend_payload:
                backend_payload["reasoning_backend"] = "external"
                return backend_payload
        except Exception as exc:  # noqa: BLE001
            backend_error = str(exc)
        else:
            backend_error = ""

        differential: list[str] = []
        symptoms_text = normalize_text(" ".join(structured.symptoms)).lower()

        if "chest pain" in symptoms_text or "chest tightness" in symptoms_text:
            differential.extend(["Acute coronary syndrome", "Pulmonary embolism", "GERD"])
        if "shortness of breath" in symptoms_text or "can't catch breath" in symptoms_text:
            differential.extend(["Pneumonia", "Asthma/COPD exacerbation", "Heart failure"])
        if "fever" in symptoms_text and "cough" in symptoms_text:
            differential.extend(["Community-acquired pneumonia", "Viral respiratory infection"])
        if "slurred speech" in symptoms_text or "word-finding difficulty" in symptoms_text or "weakness one side" in symptoms_text:
            differential.extend(["Acute ischemic stroke", "Intracranial hemorrhage", "Hypoglycemia"])
        if not differential:
            differential.extend(["Viral syndrome", "Medication side effect", "Dehydration"])

        rationale = (
            "Differentials are prioritized using symptom pattern + available vitals. "
            "Final diagnosis is not made by the model; clinician validation is required."
        )

        return {
            "differential_considerations": _dedupe(differential)[:5],
            "reasoning_rationale": rationale,
            "uses_multimodal_context": bool(structured.normalized_summary) or bool(image_data_urls),
            "reasoning_backend": "deterministic",
            "reasoning_backend_error": backend_error,
            "reasoning_backend_skipped_reason": backend_skipped_reason,
            "phi_hits": phi_hits,
        }


class EvidencePolicyAgent:
    name = "evidence_policy"

    def run(self, reasoning: dict, structured: StructuredIntake) -> dict:
        settings = load_settings_from_env()
        policies = _default_policies()
        matched = match_policies(policies, text=structured.normalized_summary)
        meta = _policy_pack_meta()

        action_pool = [
            "Repeat full set of vitals within 15 minutes",
            "Obtain focused history for symptom onset, severity, and progression",
            "Document explicit red-flag checks in triage note",
        ]
        for policy in matched[: settings.policy_top_k]:
            action_pool.extend(policy.recommended_actions)

        return {
            **meta,
            "protocol_citations": [policy.to_dict() for policy in matched[: settings.policy_top_k]],
            "recommended_next_actions": _dedupe(action_pool)[:6],
            "evidence_note": "Recommendations are grounded in a demo policy pack; replace with site protocol IDs and citations.",
        }


class SafetyEscalationAgent:
    name = "safety_escalation"

    def run(self, structured: StructuredIntake, vitals: Vitals, recommended_actions: list[str]) -> dict:
        red_flags = find_red_flags(structured, vitals)
        risk_tier, risk_tier_rationale = compute_risk_tier_with_rationale(red_flags, structured.missing_fields, vitals)
        safety_triggers = compute_safety_triggers(red_flags, structured.missing_fields, vitals)
        risk_scores = compute_risk_scores(structured=structured, vitals=vitals)
        confidence, uncertainty_reasons = estimate_confidence(risk_tier, red_flags, structured.missing_fields)

        escalation_required = risk_tier in {"critical", "urgent"}
        safety_actions = _safety_actions_for(risk_tier=risk_tier, red_flags=red_flags, vitals=vitals)

        evidence_actions = [str(x) for x in (recommended_actions or []) if str(x).strip()]
        full_actions = _dedupe([*safety_actions, *evidence_actions])

        return {
            "risk_tier": risk_tier,
            "risk_tier_rationale": risk_tier_rationale,
            "safety_triggers": safety_triggers,
            "risk_scores": risk_scores,
            "red_flags": red_flags,
            "escalation_required": escalation_required,
            "confidence": confidence,
            "uncertainty_reasons": uncertainty_reasons,
            "safety_rules_version": SAFETY_RULES_VERSION,
            "missing_fields": structured.missing_fields,
            # Keep deterministic safety actions first for "product feel" and operational clarity.
            "recommended_next_actions": full_actions[:10],
            "actions_added_by_safety": _dedupe(safety_actions),
        }


class CommunicationAgent:
    name = "communication"

    def run(self, intake: PatientIntake, safety: dict, reasoning: dict) -> dict:
        red_flags = [str(x) for x in (safety.get("red_flags") or []) if str(x).strip()]
        actions = [str(x) for x in (safety.get("recommended_next_actions") or []) if str(x).strip()]
        differential = [str(x) for x in (reasoning.get("differential_considerations") or []) if str(x).strip()]
        risk_tier = str(safety.get("risk_tier") or "").strip() or "unknown"
        rationale = str(safety.get("risk_tier_rationale") or "").strip()
        confidence = safety.get("confidence")
        uncertainty = [str(x) for x in (safety.get("uncertainty_reasons") or []) if str(x).strip()]
        missing_fields = [str(x) for x in (safety.get("missing_fields") or []) if str(x).strip()]

        vitals_line = _format_vitals(intake.vitals)

        clinician_lines: list[str] = []
        clinician_lines.append("Clinician handoff (SBAR draft):")
        clinician_lines.append("")
        clinician_lines.append("S) Situation")
        clinician_lines.append(f"- Chief complaint: {intake.chief_complaint or '(missing)'}")
        if vitals_line:
            clinician_lines.append(f"- Vitals: {vitals_line}")

        clinician_lines.append("")
        clinician_lines.append("B) Background")
        if intake.history:
            clinician_lines.append(f"- History: {intake.history}")
        else:
            clinician_lines.append("- History: (not provided)")

        clinician_lines.append("")
        clinician_lines.append("A) Assessment (decision support; not a diagnosis)")
        clinician_lines.append(f"- Risk tier: {risk_tier} (escalation_required={bool(safety.get('escalation_required'))})")
        if rationale:
            clinician_lines.append(f"- Rationale: {rationale}")
        if red_flags:
            clinician_lines.append(f"- Red flags: {', '.join(red_flags)}")
        else:
            clinician_lines.append("- Red flags: (none detected)")
        if differential:
            clinician_lines.append(f"- Differential (top): {', '.join(differential)}")
        if isinstance(confidence, (int, float)):
            clinician_lines.append(f"- Confidence (proxy): {float(confidence):.2f}")
        if missing_fields:
            clinician_lines.append(f"- Missing critical fields: {', '.join(missing_fields)}")
        if uncertainty:
            clinician_lines.append(f"- Uncertainty notes: {', '.join(uncertainty)}")

        clinician_lines.append("")
        clinician_lines.append("R) Recommendation")
        if actions:
            for item in actions[:10]:
                clinician_lines.append(f"- {item}")
        else:
            clinician_lines.append("- (no actions suggested)")

        patient_lines: list[str] = []
        patient_lines.append("Decision support only — this is not a diagnosis.")
        patient_lines.append(f"Triage level: {risk_tier.upper()}.")
        patient_lines.append("")
        patient_lines.append("What to do now:")
        if risk_tier == "critical":
            patient_lines.append("- Seek emergency evaluation now (ED / call local emergency services).")
        elif risk_tier == "urgent":
            patient_lines.append("- Seek same-day evaluation by a clinician or urgent care.")
        else:
            patient_lines.append("- Consider routine evaluation if symptoms persist.")
        patient_lines.append("")
        patient_lines.append("Return precautions (seek urgent care now if any):")
        for item in _patient_return_precautions(red_flags):
            patient_lines.append(f"- {item}")

        draft_clinician = "\n".join(clinician_lines).strip()
        draft_patient = "\n".join(patient_lines).strip()

        # Optional: use an external model to rewrite drafts for clarity.
        # Safety governance and triage decisions remain deterministic.
        backend_error = ""
        backend_skipped_reason = ""
        phi_hits = detect_phi_hits(intake.combined_text())
        if not external_calls_allowed(phi_hits=phi_hits):
            backend_skipped_reason = f"PHI guard blocked external call: {', '.join(phi_hits)}"
        try:
            from clinicaflow.inference.communication import run_communication_backend

            backend_payload = (
                None
                if backend_skipped_reason
                else run_communication_backend(draft_clinician=draft_clinician, draft_patient=draft_patient)
            )
            if backend_payload:
                backend_payload["communication_backend"] = "external"
                return backend_payload
        except Exception as exc:  # noqa: BLE001
            backend_error = str(exc)

        return {
            "clinician_handoff": draft_clinician,
            "patient_summary": draft_patient,
            "communication_backend": "deterministic",
            "communication_backend_error": backend_error,
            "communication_backend_skipped_reason": backend_skipped_reason,
            "phi_hits": phi_hits,
        }


def _safety_actions_for(*, risk_tier: str, red_flags: list[str], vitals: Vitals) -> list[str]:
    """Deterministic safety-first action suggestions.

    Purpose:
    - Make the output feel "product-ready" even when the policy pack is minimal.
    - Ensure high-acuity cases always include an explicit escalation/disposition action.

    Important: This is decision support and must be adapted to local protocols.
    """

    tier = str(risk_tier or "").strip().lower()
    flags = [str(x) for x in (red_flags or []) if str(x).strip()]

    actions: list[str] = []

    # Disposition / escalation (put first).
    if tier == "critical":
        actions.append("Emergency evaluation now (ED / call local emergency services).")
        actions.append("Urgent clinician review")
    elif tier == "urgent":
        actions.append("Urgent clinician review")
        actions.append("Arrange same-day clinician evaluation (urgent care / ED if worsening).")

    # Red-flag specific nudges (kept intentionally broad).
    if any("Potential acute coronary syndrome" in f for f in flags):
        actions.append("Obtain 12-lead ECG within 10 minutes (per protocol).")

    if any("Possible stroke" in f for f in flags):
        actions.append("Activate stroke pathway per local protocol; document last-known-well time.")

    if any("Respiratory compromise risk" in f for f in flags) or any("Low oxygen saturation" in f for f in flags):
        actions.append("Pulse oximetry monitoring; follow local oxygenation protocol if indicated.")

    if any("Hypotension" in f for f in flags) or any("Severe tachycardia" in f for f in flags):
        actions.append("Repeat full set of vitals immediately; consider placing on monitor per protocol.")

    if any("gastrointestinal bleed" in f.lower() or "gi bleed" in f.lower() for f in flags):
        actions.append("Assess hemodynamic stability and ongoing bleeding; follow local GI bleed pathway.")

    if any("obstetric" in f.lower() for f in flags):
        actions.append("Escalate to obstetric-capable evaluation per local protocol.")

    if any("High fever" in f for f in flags):
        actions.append("Perform sepsis screen per local protocol; reassess mental status and perfusion.")

    # Vitals-only safety prompts (in case symptom parsing missed something).
    if vitals.spo2 is not None and vitals.spo2 < 92:
        actions.append("Confirm low SpO₂ with repeat measurement; assess work of breathing.")
    if vitals.systolic_bp is not None and vitals.systolic_bp < 90:
        actions.append("Confirm hypotension with repeat BP; assess perfusion and mental status.")
    if vitals.heart_rate is not None and vitals.heart_rate > 130:
        actions.append("Recheck tachycardia; assess pain, fever, dehydration, or bleeding per protocol.")

    return _dedupe(actions)


def _format_vitals(vitals: Vitals) -> str:
    parts: list[str] = []
    if vitals.heart_rate is not None:
        parts.append(f"HR {int(vitals.heart_rate) if float(vitals.heart_rate).is_integer() else vitals.heart_rate}")
    if vitals.systolic_bp is not None:
        if vitals.diastolic_bp is not None:
            parts.append(
                f"BP {int(vitals.systolic_bp) if float(vitals.systolic_bp).is_integer() else vitals.systolic_bp}/"
                f"{int(vitals.diastolic_bp) if float(vitals.diastolic_bp).is_integer() else vitals.diastolic_bp}"
            )
        else:
            parts.append(
                f"SBP {int(vitals.systolic_bp) if float(vitals.systolic_bp).is_integer() else vitals.systolic_bp}"
            )
    if vitals.temperature_c is not None:
        parts.append(f"Temp {vitals.temperature_c}°C")
    if vitals.spo2 is not None:
        parts.append(f"SpO₂ {int(vitals.spo2) if float(vitals.spo2).is_integer() else vitals.spo2}%")
    if vitals.respiratory_rate is not None:
        parts.append(
            f"RR {int(vitals.respiratory_rate) if float(vitals.respiratory_rate).is_integer() else vitals.respiratory_rate}"
        )
    return ", ".join(parts)


def _patient_return_precautions(red_flags: list[str]) -> list[str]:
    # Generic safety net.
    precautions: list[str] = [
        "Trouble breathing, blue lips, or worsening shortness of breath",
        "New chest pain/pressure, fainting, or severe sweating",
        "New confusion, one-sided weakness, facial droop, or trouble speaking",
        "Vomiting blood or black/bloody stools",
        "Severe headache unlike usual, seizure, or neck stiffness",
        "Pregnancy with bleeding, severe abdominal pain, or dizziness",
        "Symptoms rapidly worsening or you feel unsafe at home",
    ]

    # If we have explicit red flags, surface the most relevant ones first.
    prioritized: list[str] = []
    for flag in red_flags:
        f = str(flag)
        if "coronary" in f or "chest pain" in f:
            prioritized.append("Chest pain/pressure, pain spreading to arm/jaw, or shortness of breath")
        if "Respiratory compromise" in f or "oxygen" in f:
            prioritized.append("Worsening shortness of breath, low oxygen readings, or trouble breathing")
        if "stroke" in f or "intracranial" in f or "neurological" in f:
            prioritized.append("New trouble speaking, facial droop, or weakness/numbness on one side")
        if "Syncope" in f:
            prioritized.append("Fainting, near-fainting, or severe dizziness")
        if "gastrointestinal bleed" in f or "GI bleed" in f or "upper GI bleed" in f:
            prioritized.append("Vomiting blood or black/bloody stools")
        if "obstetric" in f:
            prioritized.append("Pregnancy with bleeding, severe abdominal pain, or dizziness")
        if "fever" in f:
            prioritized.append("High fever with confusion, rapid breathing, or worsening weakness")
        if "Hypotension" in f:
            prioritized.append("Feeling faint or unable to stay awake")

    out = _dedupe(prioritized) + [x for x in precautions if x not in set(prioritized)]
    return out[:7]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


_NEGATION_CUES = ("no", "denies", "deny", "without", "not")
_NEGATION_BREAKS = ("but", "however", "except")
_BOUNDARY_CHARS = ".;\n"


def _contains_non_negated(text: str, needle: str) -> bool:
    """Return True if `needle` appears without an obvious nearby negation cue.

    This is a lightweight heuristic intended to reduce false positives like
    "no shortness of breath" or "no fainting" triggering symptoms.
    """

    if not needle:
        return False

    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            return False
        if not _is_negated(text, idx):
            return True
        start = idx + len(needle)

def _contains_non_negated_regex(text: str, pat: re.Pattern[str]) -> bool:
    for m in pat.finditer(text):
        if not _is_negated(text, m.start()):
            return True
    return False


def _is_negated(text: str, idx: int, *, window: int = 40) -> bool:
    left = text[max(0, idx - window) : idx]
    if not left:
        return False

    # Only consider the fragment after the last sentence-ish boundary.
    boundary = max(left.rfind(ch) for ch in _BOUNDARY_CHARS)
    frag = left[boundary + 1 :] if boundary != -1 else left
    frag = frag.strip()
    if not frag:
        return False

    # Find last negation cue in the fragment.
    cue_spans = [m.span() for cue in _NEGATION_CUES for m in re.finditer(rf"\b{re.escape(cue)}\b", frag)]
    if not cue_spans:
        return False
    last_cue_start, last_cue_end = max(cue_spans, key=lambda s: s[0])

    # If there is a clear contrast word after the cue, treat as not negated.
    after = frag[last_cue_end :]
    if any(re.search(rf"\b{re.escape(b)}\b", after) for b in _NEGATION_BREAKS):
        return False

    return True


_CACHED_POLICIES: list[PolicySnippet] | None = None
_CACHED_POLICY_SHA256: str | None = None
_CACHED_POLICY_SOURCE: str | None = None


def _default_policies() -> list[PolicySnippet]:
    global _CACHED_POLICIES  # noqa: PLW0603
    global _CACHED_POLICY_SHA256  # noqa: PLW0603
    global _CACHED_POLICY_SOURCE  # noqa: PLW0603
    if _CACHED_POLICIES is not None:
        return _CACHED_POLICIES
    try:
        settings = load_settings_from_env()
        from importlib.resources import files

        if settings.policy_pack_path:
            source = settings.policy_pack_path
            _CACHED_POLICIES = load_policy_pack(source)
            _CACHED_POLICY_SHA256 = policy_pack_sha256(source)
            _CACHED_POLICY_SOURCE = str(source)
        else:
            policy_path = files("clinicaflow.resources").joinpath("policy_pack.json")
            _CACHED_POLICIES = load_policy_pack(policy_path)
            _CACHED_POLICY_SHA256 = policy_pack_sha256(policy_path)
            _CACHED_POLICY_SOURCE = "package:clinicaflow.resources/policy_pack.json"
    except Exception:  # noqa: BLE001
        _CACHED_POLICIES = []
        _CACHED_POLICY_SHA256 = None
        _CACHED_POLICY_SOURCE = None
    return _CACHED_POLICIES


def _policy_pack_meta() -> dict[str, str]:
    # Ensure cache is populated.
    _default_policies()
    return {
        "policy_pack_sha256": _CACHED_POLICY_SHA256 or "",
        "policy_pack_source": _CACHED_POLICY_SOURCE or "",
    }
