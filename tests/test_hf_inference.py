from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from clinicaflow.inference.hf_inference import (
    DEFAULT_HF_ROUTER_BASE_URL,
    hf_generate_text,
    load_hf_inference_config_from_env_prefix,
)
from clinicaflow.inference.openai_compatible import InferenceError


class HFInferenceTests(unittest.TestCase):
    def test_load_config_defaults_base_url(self) -> None:
        with mock.patch.dict(os.environ, {"CLINICAFLOW_REASONING_MODEL": "google/medgemma-4b-it"}, clear=True):
            cfg = load_hf_inference_config_from_env_prefix("CLINICAFLOW_REASONING")
        self.assertEqual(cfg.base_url, DEFAULT_HF_ROUTER_BASE_URL)
        self.assertEqual(cfg.model, "google/medgemma-4b-it")

    def test_hf_generate_text_parses_generated_text_list(self) -> None:
        cfg_env = {
            "CLINICAFLOW_REASONING_MODEL": "google/medgemma-4b-it",
            "CLINICAFLOW_REASONING_API_KEY": "hf_xxx",
            "CLINICAFLOW_REASONING_BASE_URL": "https://router.huggingface.co/hf-inference",
            "CLINICAFLOW_REASONING_MAX_TOKENS": "12",
            "CLINICAFLOW_REASONING_TEMPERATURE": "0.1",
        }

        class _FakeResp:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return self._payload

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            url = getattr(req, "full_url", "")
            self.assertEqual(
                url,
                "https://router.huggingface.co/hf-inference/models/google%2Fmedgemma-4b-it",
            )
            headers = {k.lower(): v for k, v in dict(getattr(req, "header_items")()).items()}
            self.assertEqual(headers.get("authorization"), "Bearer hf_xxx")

            body = json.loads(getattr(req, "data").decode("utf-8"))
            self.assertEqual(body["parameters"]["max_new_tokens"], 12)
            self.assertAlmostEqual(float(body["parameters"]["temperature"]), 0.1, places=6)
            self.assertIn("inputs", body)

            return _FakeResp(json.dumps([{"generated_text": "OK"}]).encode("utf-8"))

        with mock.patch.dict(os.environ, cfg_env, clear=True):
            cfg = load_hf_inference_config_from_env_prefix("CLINICAFLOW_REASONING")
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                out = hf_generate_text(config=cfg, prompt="hello")
        self.assertEqual(out, "OK")

    def test_hf_generate_text_raises_on_error_payload(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CLINICAFLOW_REASONING_MODEL": "google/medgemma-4b-it", "CLINICAFLOW_REASONING_API_KEY": "hf_xxx"},
            clear=True,
        ):
            cfg = load_hf_inference_config_from_env_prefix("CLINICAFLOW_REASONING")

        class _FakeResp:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return self._payload

            def __enter__(self) -> "_FakeResp":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
                return None

        def fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:  # noqa: ANN001
            return _FakeResp(json.dumps({"error": "Invalid username or password."}).encode("utf-8"))

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(InferenceError):
                hf_generate_text(config=cfg, prompt="hello")


if __name__ == "__main__":
    unittest.main()
