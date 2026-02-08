from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from clinicaflow.audit import write_audit_bundle
from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


class AuditBundleTests(unittest.TestCase):
    def test_write_audit_bundle_redacted(self) -> None:
        intake = PatientIntake.from_mapping(
            {
                "chief_complaint": "Chest pain and shortness of breath for 20 minutes",
                "history": "history of diabetes and hypertension",
                "demographics": {"age": 61, "sex": "female"},
                "vitals": {"heart_rate": 128, "systolic_bp": 92, "temperature_c": 37.9, "spo2": 93},
                "image_descriptions": ["Portable chest image: mild bilateral interstitial opacities"],
                "prior_notes": ["Prior episode of exertional chest tightness last week"],
            }
        )
        result = ClinicaFlowPipeline().run(intake, request_id="req-audit-1")

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "bundle"
            write_audit_bundle(out_dir=out_dir, intake=intake, result=result, redact=True)

            self.assertTrue((out_dir / "intake.json").exists())
            self.assertTrue((out_dir / "triage_result.json").exists())
            self.assertTrue((out_dir / "doctor.json").exists())
            self.assertTrue((out_dir / "manifest.json").exists())

            intake_payload = json.loads((out_dir / "intake.json").read_text(encoding="utf-8"))
            self.assertEqual(intake_payload["demographics"], {})
            self.assertEqual(intake_payload["prior_notes"], [])
            self.assertEqual(intake_payload["image_descriptions"], [])

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["request_id"], "req-audit-1")
            self.assertEqual(manifest["run_id"], result.run_id)
            self.assertTrue(manifest["created_at"])
            self.assertTrue(manifest["pipeline_version"])
            self.assertTrue(manifest["redacted"])

            hashes = manifest["file_hashes_sha256"]
            self.assertIn("intake.json", hashes)
            self.assertIn("triage_result.json", hashes)
            self.assertIn("doctor.json", hashes)


if __name__ == "__main__":
    unittest.main()

