from __future__ import annotations

import unittest

from clinicaflow.auth import is_authorized


class AuthTests(unittest.TestCase):
    def test_auth_disabled_when_no_key(self) -> None:
        self.assertTrue(is_authorized(headers={}, expected_api_key=""))

    def test_bearer_token_authorizes(self) -> None:
        headers = {"Authorization": "Bearer secret123"}
        self.assertTrue(is_authorized(headers=headers, expected_api_key="secret123"))
        self.assertFalse(is_authorized(headers=headers, expected_api_key="other"))

    def test_x_api_key_authorizes(self) -> None:
        headers = {"X-API-Key": "secret123"}
        self.assertTrue(is_authorized(headers=headers, expected_api_key="secret123"))
        self.assertFalse(is_authorized(headers=headers, expected_api_key="other"))

    def test_wrong_scheme_rejected(self) -> None:
        headers = {"Authorization": "Basic secret123"}
        self.assertFalse(is_authorized(headers=headers, expected_api_key="secret123"))


if __name__ == "__main__":
    unittest.main()

