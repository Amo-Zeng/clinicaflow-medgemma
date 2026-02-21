from __future__ import annotations

import unittest
from unittest.mock import patch

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


class GuardrailsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ClinicaFlowPipeline()

    def test_phi_guard_skips_external_reasoning_when_phi_detected(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Fever and cough",
                "history": "Contact: test@example.com",
                "vitals": {"heart_rate": 92, "temperature_c": 37.2, "spo2": 98},
            }
        )

        with patch.dict("os.environ", {"CLINICAFLOW_REASONING_BACKEND": "openai_compatible"}, clear=False):
            result = self.pipeline.run(intake)

        structured = next((x.output for x in result.trace if x.agent == "intake_structuring"), {})
        self.assertIn("email", structured.get("phi_hits") or [])

        reasoning = next((x.output for x in result.trace if x.agent == "multimodal_reasoning"), {})
        self.assertEqual(reasoning.get("reasoning_backend"), "deterministic")
        self.assertTrue(str(reasoning.get("reasoning_backend_skipped_reason") or "").lower().startswith("phi guard"))
        self.assertEqual(str(reasoning.get("reasoning_backend_error") or ""), "")

    def test_phi_guard_skips_external_communication_when_phi_detected(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Mild cough",
                "history": "Call me at (415) 555-1212",
                "vitals": {"heart_rate": 80, "temperature_c": 37.0, "spo2": 99},
            }
        )

        with patch.dict("os.environ", {"CLINICAFLOW_COMMUNICATION_BACKEND": "openai_compatible"}, clear=False):
            result = self.pipeline.run(intake)

        comm = next((x.output for x in result.trace if x.agent == "communication"), {})
        self.assertEqual(comm.get("communication_backend"), "deterministic")
        self.assertTrue(str(comm.get("communication_backend_skipped_reason") or "").lower().startswith("phi guard"))
        self.assertEqual(str(comm.get("communication_backend_error") or ""), "")

    def test_phi_guard_can_be_disabled(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Mild cough",
                "history": "Contact: test@example.com",
                "vitals": {"heart_rate": 80, "temperature_c": 37.0, "spo2": 99},
            }
        )

        with patch.dict(
            "os.environ",
            {
                "CLINICAFLOW_PHI_GUARD": "0",
                "CLINICAFLOW_COMMUNICATION_BACKEND": "openai_compatible",
            },
            clear=False,
        ):
            result = self.pipeline.run(intake)

        comm = next((x.output for x in result.trace if x.agent == "communication"), {})
        self.assertEqual(comm.get("communication_backend"), "deterministic")
        self.assertEqual(str(comm.get("communication_backend_skipped_reason") or ""), "")
        self.assertTrue(str(comm.get("communication_backend_error") or ""))

    def test_quality_warnings_surface_in_structured_trace(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Routine check",
                "vitals": {"heart_rate": 72, "temperature_c": 37.0, "spo2": 150},
            }
        )
        result = self.pipeline.run(intake)

        structured = next((x.output for x in result.trace if x.agent == "intake_structuring"), {})
        warnings = structured.get("data_quality_warnings") or []
        self.assertTrue(any("SpO₂" in str(w) for w in warnings))


if __name__ == "__main__":
    unittest.main()

