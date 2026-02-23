from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from clinicaflow.inference.gradio_space import (
    _GradioEndpoint,
    _build_input_data,
    _decode_image_data_url,
    _discover_endpoint,
    _ENDPOINT_CACHE,
    _ext_from_mime,
    _extract_text_from_completed,
    load_gradio_space_config_from_env_prefix,
    load_gradio_space_configs_from_env_prefix,
)
from clinicaflow.inference.openai_compatible import InferenceError


class GradioSpaceTests(unittest.TestCase):
    def tearDown(self) -> None:
        _ENDPOINT_CACHE.clear()

    def test_build_input_data_multimodal_system_slider_state(self) -> None:
        endpoint = _GradioEndpoint(
            api_prefix="/gradio_api",
            fn_index=6,
            trigger_id=15,
            inputs=[
                {"id": 1, "type": "multimodaltextbox", "props": {}},
                {"id": 17, "type": "state", "props": {}},
                {"id": 2, "type": "textbox", "props": {"label": "System Prompt"}},
                {"id": 3, "type": "slider", "props": {"label": "Max New Tokens", "minimum": 100, "maximum": 200, "step": 10}},
            ],
            output_mode="text",
        )

        data = _build_input_data(endpoint=endpoint, system="SYS", user="USER", max_tokens=175)
        self.assertEqual(data[0], {"text": "USER", "files": []})
        self.assertEqual(data[1], [])
        self.assertEqual(data[2], "SYS")
        self.assertEqual(data[3], 170)

        sample_files = [
            {
                "path": "/tmp/x.png",
                "url": "https://space.example/gradio_api/file=/tmp/x.png",
                "orig_name": "x.png",
                "size": 3,
                "mime_type": "image/png",
                "meta": {"_type": "gradio.FileData"},
            }
        ]
        data2 = _build_input_data(endpoint=endpoint, system="SYS", user="USER", max_tokens=175, files=sample_files)
        self.assertEqual(data2[0]["files"], sample_files)

    def test_build_input_data_textbox_prompt_image_optional(self) -> None:
        endpoint = _GradioEndpoint(
            api_prefix="/gradio_api",
            fn_index=0,
            trigger_id=0,
            inputs=[
                {"id": 0, "type": "textbox", "props": {"label": "Medical Query"}},
                {"id": 1, "type": "image", "props": {"label": "Medical Image (optional)"}},
            ],
            output_mode="text",
        )

        data = _build_input_data(endpoint=endpoint, system="SYS", user="USER", max_tokens=600)
        self.assertEqual(data[0], "SYS\n\nUSER")
        self.assertIsNone(data[1])

        sample_files = [
            {
                "path": "/tmp/x.png",
                "url": "https://space.example/gradio_api/file=/tmp/x.png",
                "orig_name": "x.png",
                "size": 3,
                "mime_type": "image/png",
                "meta": {"_type": "gradio.FileData"},
            }
        ]
        data2 = _build_input_data(endpoint=endpoint, system="SYS", user="USER", max_tokens=600, files=sample_files)
        self.assertEqual(data2[0], "SYS\n\nUSER")
        self.assertEqual(data2[1], sample_files[0])

    def test_decode_image_data_url(self) -> None:
        data, mime = _decode_image_data_url("data:image/png;base64,YWJj")
        self.assertEqual(data, b"abc")
        self.assertEqual(mime, "image/png")
        self.assertEqual(_ext_from_mime(mime), "png")

    def test_extract_text_from_completed_success(self) -> None:
        completed = {
            "msg": "process_completed",
            "event_id": "abc",
            "success": True,
            "output": {"data": ["PONG\n", None]},
        }
        self.assertEqual(_extract_text_from_completed(completed, output_mode="text"), "PONG\n")

    def test_extract_text_from_completed_error(self) -> None:
        completed = {
            "msg": "process_completed",
            "event_id": "abc",
            "success": False,
            "title": "Error",
            "output": {"error": "bad news"},
        }
        with self.assertRaises(InferenceError):
            _extract_text_from_completed(completed, output_mode="text")

    def test_discover_endpoint_parses_config(self) -> None:
        cfg = {
            "api_prefix": "/gradio_api",
            "dependencies": [
                {"api_name": "x"},
                {"api_name": "y"},
                {"api_name": "z"},
                {"api_name": "a"},
                {"api_name": "b"},
                {"api_name": "c"},
                {
                    "api_name": "chat",
                    "targets": [[15, "click"]],
                    "inputs": [1, 17, 2, 3],
                    "outputs": [16, 17],
                },
            ],
            "components": [
                {"id": 1, "type": "multimodaltextbox", "props": {}},
                {"id": 17, "type": "state", "props": {}},
                {"id": 2, "type": "textbox", "props": {"label": "System Prompt"}},
                {"id": 3, "type": "slider", "props": {"label": "Max New Tokens", "minimum": 100, "maximum": 8192, "step": 10}},
                {"id": 16, "type": "json", "props": {"label": "Response"}},
            ],
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
            return _FakeResp(json.dumps(cfg).encode("utf-8"))

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ep = _discover_endpoint(base_url="https://space.example", api_name="chat")

        self.assertEqual(ep.api_prefix, "/gradio_api")
        self.assertEqual(ep.fn_index, 6)
        self.assertEqual(ep.trigger_id, 15)
        self.assertEqual(len(ep.inputs), 4)
        self.assertEqual(ep.output_mode, "openai_like")

    def test_load_configs_from_env_prefix_parses_pool(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CLINICAFLOW_REASONING_BASE_URLS": "https://a.example|chat, https://b.example|predict,https://a.example|chat",
                "CLINICAFLOW_REASONING_GRADIO_API_NAME": "chat",
            },
            clear=False,
        ):
            cfgs = load_gradio_space_configs_from_env_prefix("CLINICAFLOW_REASONING")
            self.assertEqual([(c.base_url, c.api_name) for c in cfgs], [("https://a.example", "chat"), ("https://b.example", "predict")])

            first = load_gradio_space_config_from_env_prefix("CLINICAFLOW_REASONING")
            self.assertEqual(first.base_url, "https://a.example")
            self.assertEqual(first.api_name, "chat")


if __name__ == "__main__":
    unittest.main()
