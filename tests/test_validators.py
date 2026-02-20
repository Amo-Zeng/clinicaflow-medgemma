from __future__ import annotations

import unittest

from clinicaflow.validators import validate_all


class ValidatorTests(unittest.TestCase):
    def test_packaged_resources_validate(self) -> None:
        report = validate_all()
        if not report.ok:
            self.fail("Validation errors:\n- " + "\n- ".join(report.errors))


if __name__ == "__main__":
    unittest.main()

