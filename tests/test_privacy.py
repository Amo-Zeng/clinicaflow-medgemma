from __future__ import annotations

import os
import unittest
from unittest import mock

from clinicaflow.privacy import (
    detect_phi_hits,
    external_calls_allowed,
    scrub_phi,
    scrub_phi_in_obj,
)


class PrivacyTests(unittest.TestCase):
    def test_detect_phi_hits(self) -> None:
        text = "Email john.doe@example.com phone 415-555-1234 SSN 123-45-6789 MRN: 1234567 DOB: 01/02/1980"
        hits = detect_phi_hits(text)
        self.assertIn("email", hits)
        self.assertIn("phone", hits)
        self.assertIn("ssn", hits)
        self.assertIn("mrn", hits)
        self.assertIn("dob", hits)

    def test_scrub_phi_replaces_tokens(self) -> None:
        text = "Reach me at john.doe@example.com or 415-555-1234."
        scrubbed = scrub_phi(text)
        self.assertNotIn("john.doe@example.com", scrubbed)
        self.assertNotIn("415-555-1234", scrubbed)
        self.assertIn("[REDACTED_EMAIL]", scrubbed)
        self.assertIn("[REDACTED_PHONE]", scrubbed)

    def test_scrub_phi_in_obj_recurses(self) -> None:
        payload = {"a": "john.doe@example.com", "b": ["415-555-1234", {"c": "DOB: 01/02/1980"}]}
        out = scrub_phi_in_obj(payload)
        text = str(out)
        self.assertIn("[REDACTED_EMAIL]", text)
        self.assertIn("[REDACTED_PHONE]", text)
        self.assertIn("[REDACTED_DOB]", text)

    def test_external_calls_allowed_blocks_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(external_calls_allowed(phi_hits=["email"]))

    def test_external_calls_allowed_can_be_disabled(self) -> None:
        with mock.patch.dict(os.environ, {"CLINICAFLOW_PHI_GUARD": "0"}, clear=True):
            self.assertTrue(external_calls_allowed(phi_hits=["email"]))


if __name__ == "__main__":
    unittest.main()

