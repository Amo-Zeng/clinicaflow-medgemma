from __future__ import annotations

import unittest

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


class PolicyPackTests(unittest.TestCase):
    def test_policy_citations_present_for_chest_pain(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Chest tightness and chest pain after exertion",
                "history": "history of hypertension",
                "vitals": {"heart_rate": 96, "systolic_bp": 122, "temperature_c": 37.0, "spo2": 97},
            }
        )

        result = ClinicaFlowPipeline().run(intake)

        evidence_trace = next(step for step in result.trace if step.agent == "evidence_policy")
        citations = evidence_trace.output.get("protocol_citations", [])
        self.assertTrue(citations)
        self.assertIn("TRIAGE-CHESTPAIN-001", {c.get("policy_id") for c in citations})


if __name__ == "__main__":
    unittest.main()

