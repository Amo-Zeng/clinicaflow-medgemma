from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class InferenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 30.0


def load_openai_compatible_config_from_env() -> OpenAICompatibleConfig:
    base_url = os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip()
    model = os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip()
    api_key = os.environ.get("CLINICAFLOW_REASONING_API_KEY")
    timeout_s = float(os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "30").strip())

    if not base_url:
        raise InferenceError("Missing env var: CLINICAFLOW_REASONING_BASE_URL")
    if not model:
        raise InferenceError("Missing env var: CLINICAFLOW_REASONING_MODEL")
    return OpenAICompatibleConfig(base_url=base_url, model=model, api_key=api_key, timeout_s=timeout_s)


def chat_completion(*, config: OpenAICompatibleConfig, system: str, user: str) -> str:
    url = config.base_url.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    req = urllib.request.Request(url=url, method="POST", data=data, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise InferenceError(f"OpenAI-compatible request failed: {exc}") from exc

    try:
        choice0 = payload["choices"][0]
        message = choice0.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        # Some servers return 'text' instead.
        text = choice0.get("text")
        if isinstance(text, str) and text.strip():
            return text
    except (KeyError, IndexError, TypeError) as exc:
        raise InferenceError(f"Unexpected OpenAI-compatible response: {payload!r}") from exc

    raise InferenceError(f"Empty completion content: {payload!r}")

