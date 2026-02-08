from __future__ import annotations

import json
import os
import time
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
    max_retries: int = 1
    retry_backoff_s: float = 0.5
    temperature: float = 0.2
    max_tokens: int = 600


def load_openai_compatible_config_from_env() -> OpenAICompatibleConfig:
    base_url = os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip()
    model = os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip()
    api_key = os.environ.get("CLINICAFLOW_REASONING_API_KEY")
    timeout_s = float(os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "30").strip())
    max_retries = int(os.environ.get("CLINICAFLOW_REASONING_MAX_RETRIES", "1").strip())
    retry_backoff_s = float(os.environ.get("CLINICAFLOW_REASONING_RETRY_BACKOFF_S", "0.5").strip())
    temperature = float(os.environ.get("CLINICAFLOW_REASONING_TEMPERATURE", "0.2").strip())
    max_tokens = int(os.environ.get("CLINICAFLOW_REASONING_MAX_TOKENS", "600").strip())

    if not base_url:
        raise InferenceError("Missing env var: CLINICAFLOW_REASONING_BASE_URL")
    if not model:
        raise InferenceError("Missing env var: CLINICAFLOW_REASONING_MODEL")
    if max_retries < 0:
        raise InferenceError("CLINICAFLOW_REASONING_MAX_RETRIES must be >= 0")
    if timeout_s <= 0:
        raise InferenceError("CLINICAFLOW_REASONING_TIMEOUT_S must be > 0")
    return OpenAICompatibleConfig(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=min(max_retries, 5),
        retry_backoff_s=retry_backoff_s,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def chat_completion(*, config: OpenAICompatibleConfig, system: str, user: str) -> str:
    url = config.base_url.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    req = urllib.request.Request(url=url, method="POST", data=data, headers=headers)  # noqa: S310
    last_exc: InferenceError | None = None
    last_cause: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            last_exc = None
            last_cause = None
            break
        except urllib.error.HTTPError as exc:
            # HTTPError is a file-like response: read a small body for debugging.
            try:
                body_preview = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                body_preview = ""
            last_exc = InferenceError(f"OpenAI-compatible HTTP {exc.code}: {body_preview}".strip())
            last_cause = exc
            retryable = exc.code in {429, 500, 502, 503, 504}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = InferenceError(f"OpenAI-compatible request failed: {exc}")
            last_cause = exc
            retryable = True

        if attempt >= config.max_retries or not retryable:
            raise last_exc from last_cause
        time.sleep(config.retry_backoff_s * (2**attempt))

    if last_exc is not None:
        raise last_exc from last_cause

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
