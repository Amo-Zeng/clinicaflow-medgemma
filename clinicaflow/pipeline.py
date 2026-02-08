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


class ClinicaFlowPipeline:
    """Deterministic 5-agent triage workflow scaffold."""

    def __init__(self) -> None:
        self.intake_structuring = IntakeStructuringAgent()
        self.multimodal_reasoning = MultimodalClinicalReasoningAgent()
        self.evidence_policy = EvidencePolicyAgent()
        self.safety_escalation = SafetyEscalationAgent()
        self.communication = CommunicationAgent()

    def run(self, intake: PatientIntake, *, request_id: str | None = None) -> TriageResult:
        run_id = new_run_id()
        request_id = request_id or run_id
        created_at = utc_now_iso()

        total_start = time.perf_counter()
        trace: list[AgentTrace] = []

        start = time.perf_counter()
        structured_payload = self.intake_structuring.run(intake)
        trace.append(
            AgentTrace(
                agent=self.intake_structuring.name,
                output=structured_payload,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

        structured = StructuredIntake(**structured_payload)

        start = time.perf_counter()
        reasoning_payload = self.multimodal_reasoning.run(structured, intake.vitals)
        trace.append(
            AgentTrace(
                agent=self.multimodal_reasoning.name,
                output=reasoning_payload,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

        start = time.perf_counter()
        policy_payload = self.evidence_policy.run(reasoning_payload, structured)
        trace.append(
            AgentTrace(
                agent=self.evidence_policy.name,
                output=policy_payload,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

        start = time.perf_counter()
        safety_payload = self.safety_escalation.run(
            structured,
            intake.vitals,
            policy_payload["recommended_next_actions"],
        )
        trace.append(
            AgentTrace(
                agent=self.safety_escalation.name,
                output=safety_payload,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

        start = time.perf_counter()
        communication_payload = self.communication.run(intake, safety_payload, reasoning_payload)
        trace.append(
            AgentTrace(
                agent=self.communication.name,
                output=communication_payload,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

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
