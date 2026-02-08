from __future__ import annotations

import unittest
from uuid import UUID

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ClinicaFlowPipeline()

    def test_high_risk_chest_pain_case(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Chest pain and shortness of breath for 30 minutes",
                "history": "Known hypertension and diabetes",
                "vitals": {
                    "heart_rate": 132,
                    "systolic_bp": 88,
                    "temperature_c": 38.7,
                    "spo2": 90,
                },
            }
        )

        result = self.pipeline.run(intake)

        UUID(result.run_id)
        self.assertTrue(result.created_at)
        self.assertGreaterEqual(result.total_latency_ms, 0.0)
        self.assertEqual(result.risk_tier, "critical")
        self.assertTrue(result.escalation_required)
        self.assertGreaterEqual(len(result.red_flags), 2)
        self.assertEqual(len(result.trace), 5)

    def test_routine_case(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Mild cough and runny nose",
                "history": "No chronic disease reported",
                "vitals": {
                    "heart_rate": 82,
                    "systolic_bp": 118,
                    "temperature_c": 37.0,
                    "spo2": 98,
                },
            }
        )

        result = self.pipeline.run(intake)

        self.assertEqual(result.request_id, result.run_id)
        self.assertIn(result.risk_tier, {"routine", "urgent"})
        self.assertIsInstance(result.patient_summary, str)
        self.assertTrue(result.recommended_next_actions)


if __name__ == "__main__":
    unittest.main()
