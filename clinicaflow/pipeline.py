from __future__ import annotations

import time

from clinicaflow.version import __version__
from clinicaflow.agents import (
    CommunicationAgent,
    EvidencePolicyAgent,
    IntakeStructuringAgent,
    MultimodalClinicalReasoningAgent,
    SafetyEscalationAgent,
)
from clinicaflow.models import AgentTrace, PatientIntake, StructuredIntake, TriageResult, new_run_id, utc_now_iso
from clinicaflow.rules import SAFETY_RULES_VERSION
from clinicaflow.text import sanitize_untrusted_text


class ClinicaFlowPipeline:
    """Deterministic 5-agent triage workflow scaffold."""

    def __init__(self) -> None:
        self.intake_structuring = IntakeStructuringAgent()
        self.multimodal_reasoning = MultimodalClinicalReasoningAgent()
        self.evidence_policy = EvidencePolicyAgent()
        self.safety_escalation = SafetyEscalationAgent()
        self.communication = CommunicationAgent()

    def run(self, intake: PatientIntake, *, request_id: str | None = None) -> TriageResult:
        """Run the triage workflow.

        Production posture (demo-safe): this pipeline attempts to **fail safe**.

        - Each agent is wrapped in an error boundary.
        - If an agent raises unexpectedly, we continue with conservative fallback
          outputs and record the exception string in the agent trace.
        - The Safety agent is treated as the primary safety boundary; if it
          fails, we escalate to `urgent` by default and require clinician review.
        """

        run_id = new_run_id()
        request_id = request_id or run_id
        created_at = utc_now_iso()

        total_start = time.perf_counter()
        trace: list[AgentTrace] = []

        def missing_fields_for(i: PatientIntake) -> list[str]:
            missing: list[str] = []
            if not str(i.chief_complaint or "").strip():
                missing.append("chief_complaint")
            if i.vitals.heart_rate is None:
                missing.append("heart_rate")
            if i.vitals.spo2 is None:
                missing.append("spo2")
            if i.vitals.temperature_c is None:
                missing.append("temperature_c")
            return missing

        def append_trace(*, agent: str, output: dict, started: float, error: str | None = None) -> None:
            trace.append(
                AgentTrace(
                    agent=agent,
                    output=output,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    error=error or None,
                )
            )

        start = time.perf_counter()
        structured_error = None
        try:
            structured_payload = self.intake_structuring.run(intake)
        except Exception as exc:  # noqa: BLE001
            structured_error = str(exc)
            from clinicaflow.privacy import detect_phi_hits
            from clinicaflow.quality import intake_quality_warnings

            structured_payload = {
                "symptoms": ["unspecified symptoms"],
                "risk_factors": [],
                "missing_fields": missing_fields_for(intake),
                "normalized_summary": sanitize_untrusted_text(intake.combined_text(), max_chars=1200),
                "phi_hits": detect_phi_hits(intake.combined_text()),
                "data_quality_warnings": intake_quality_warnings(intake),
            }
        append_trace(agent=self.intake_structuring.name, output=structured_payload, started=start, error=structured_error)

        structured = StructuredIntake(**structured_payload)

        start = time.perf_counter()
        reasoning_error = None
        try:
            reasoning_payload = self.multimodal_reasoning.run(structured, intake.vitals, image_data_urls=intake.image_data_urls)
        except Exception as exc:  # noqa: BLE001
            reasoning_error = str(exc)
            reasoning_payload = {
                "differential_considerations": [],
                "reasoning_rationale": "Reasoning step unavailable (system error). Proceeding with deterministic safety triage only.",
                "uses_multimodal_context": bool(structured.normalized_summary) or bool(intake.image_data_urls),
                "reasoning_backend": "deterministic",
                "reasoning_backend_error": reasoning_error,
                "images_present": len(intake.image_data_urls or []),
                "images_sent": 0,
                "reasoning_backend_model": "",
                "reasoning_prompt_version": "",
            }
        append_trace(agent=self.multimodal_reasoning.name, output=reasoning_payload, started=start, error=reasoning_error)

        start = time.perf_counter()
        policy_error = None
        try:
            policy_payload = self.evidence_policy.run(reasoning_payload, structured)
        except Exception as exc:  # noqa: BLE001
            policy_error = str(exc)
            policy_payload = {
                "policy_pack_sha256": "",
                "policy_pack_source": "",
                "protocol_citations": [],
                "recommended_next_actions": [
                    "Repeat full set of vitals within 15 minutes",
                    "Obtain focused history for symptom onset, severity, and progression",
                    "Document explicit red-flag checks in triage note",
                ],
                "evidence_note": "Evidence/policy step unavailable (system error); using minimal default actions.",
            }
        append_trace(agent=self.evidence_policy.name, output=policy_payload, started=start, error=policy_error)

        start = time.perf_counter()
        safety_error = None
        recommended_actions = policy_payload.get("recommended_next_actions") if isinstance(policy_payload, dict) else None
        recommended_actions_list = recommended_actions if isinstance(recommended_actions, list) else []
        try:
            safety_payload = self.safety_escalation.run(structured, intake.vitals, recommended_actions_list)
        except Exception as exc:  # noqa: BLE001
            safety_error = str(exc)
            base_actions = ["Urgent clinician review"]
            seen: set[str] = set()
            merged: list[str] = []
            for item in [*base_actions, *[str(x) for x in recommended_actions_list]]:
                t = str(item or "").strip()
                if not t or t in seen:
                    continue
                seen.add(t)
                merged.append(t)

            safety_payload = {
                "risk_tier": "urgent",
                "risk_tier_rationale": "Safety gate unavailable (system error) — escalating for clinician review.",
                "safety_triggers": [
                    {
                        "id": "system_error",
                        "severity": "urgent",
                        "label": "System error",
                        "detail": "Safety agent raised unexpectedly; fail-safe escalation is required.",
                    }
                ],
                "risk_scores": {},
                "red_flags": ["System error (safety agent)"],
                "escalation_required": True,
                "confidence": 0.45,
                "uncertainty_reasons": [
                    "System error in safety gate; clinician review required.",
                    *([f"Missing intake fields: {', '.join(structured.missing_fields)}"] if structured.missing_fields else []),
                ],
                "safety_rules_version": SAFETY_RULES_VERSION,
                "missing_fields": structured.missing_fields,
                "recommended_next_actions": merged[:10],
                "actions_added_by_safety": base_actions,
            }
        append_trace(agent=self.safety_escalation.name, output=safety_payload, started=start, error=safety_error)

        start = time.perf_counter()
        communication_error = None
        try:
            communication_payload = self.communication.run(intake, safety_payload, reasoning_payload)
        except Exception as exc:  # noqa: BLE001
            communication_error = str(exc)
            tier = str((safety_payload or {}).get("risk_tier") or "").strip().lower() or "urgent"
            clinician = "\n".join(
                [
                    "Clinician handoff (system fallback):",
                    "",
                    f"- Chief complaint: {intake.chief_complaint or '(missing)'}",
                    f"- Risk tier: {tier} (escalation_required=True)",
                    "- Note: system error occurred while generating handoff; clinician review required.",
                ]
            ).strip()
            patient = "\n".join(
                [
                    "Decision support only — this is not a diagnosis.",
                    f"Triage level: {tier.upper()}.",
                    "",
                    "Because of a system error, please seek clinician evaluation and follow local emergency guidance if symptoms worsen.",
                ]
            ).strip()
            communication_payload = {
                "clinician_handoff": clinician,
                "patient_summary": patient,
                "communication_backend": "deterministic",
                "communication_backend_error": communication_error,
            }
        append_trace(agent=self.communication.name, output=communication_payload, started=start, error=communication_error)

        total_latency_ms = round((time.perf_counter() - total_start) * 1000, 2)
        return TriageResult(
            run_id=run_id,
            request_id=request_id,
            created_at=created_at,
            pipeline_version=__version__,
            total_latency_ms=total_latency_ms,
            risk_tier=safety_payload["risk_tier"],
            escalation_required=safety_payload["escalation_required"],
            differential_considerations=reasoning_payload["differential_considerations"],
            red_flags=safety_payload["red_flags"],
            recommended_next_actions=safety_payload["recommended_next_actions"],
            clinician_handoff=communication_payload["clinician_handoff"],
            patient_summary=communication_payload["patient_summary"],
            confidence=safety_payload["confidence"],
            uncertainty_reasons=safety_payload["uncertainty_reasons"],
            trace=trace,
        )
