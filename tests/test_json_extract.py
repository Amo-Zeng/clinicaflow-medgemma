from __future__ import annotations

import unittest

from clinicaflow.inference.json_extract import JsonExtractError, extract_first_json_object


class JsonExtractTests(unittest.TestCase):
    def test_direct_json_object(self) -> None:
        payload = extract_first_json_object('{"a": 1, "b": "x"}')
        self.assertEqual(payload["a"], 1)
        self.assertEqual(payload["b"], "x")

    def test_json_in_code_fence(self) -> None:
        text = "```json\n{\"ok\": true, \"items\": [1, 2]}\n```"
        payload = extract_first_json_object(text)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["items"], [1, 2])

    def test_json_wrapped_in_prose(self) -> None:
        text = "Here you go:\n{\"x\": 3}\nThanks!"
        payload = extract_first_json_object(text)
        self.assertEqual(payload["x"], 3)

    def test_empty_raises(self) -> None:
        with self.assertRaises(JsonExtractError):
            extract_first_json_object("")


if __name__ == "__main__":
    unittest.main()

