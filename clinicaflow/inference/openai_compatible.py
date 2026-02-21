from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    open_until_s: float = 0.0
    last_failure_s: float = 0.0
    last_error: str = ""


_CIRCUIT_LOCK = threading.Lock()
_CIRCUITS: dict[str, _CircuitState] = {}


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, str(default)) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, str(default)) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _circuit_key(config: OpenAICompatibleConfig) -> str:
    base = config.base_url.rstrip("/")
    return f"{base}::{config.model}"


def _circuit_params() -> tuple[int, float, float]:
    """Return (threshold_failures, cooldown_s, window_s)."""

    threshold = max(1, _env_int("CLINICAFLOW_INFERENCE_CIRCUIT_FAILS", 2))
    cooldown_s = max(0.0, _env_float("CLINICAFLOW_INFERENCE_CIRCUIT_COOLDOWN_S", 15.0))
    window_s = max(1.0, _env_float("CLINICAFLOW_INFERENCE_CIRCUIT_WINDOW_S", 60.0))
    return threshold, cooldown_s, window_s


def _circuit_check_or_raise(*, config: OpenAICompatibleConfig) -> None:
    key = _circuit_key(config)
    now = time.time()
    with _CIRCUIT_LOCK:
        state = _CIRCUITS.get(key)
        if not state:
            return
        if state.open_until_s <= now:
            return
        remaining = state.open_until_s - now
        tail = f" ({remaining:.1f}s remaining)" if remaining > 0 else ""
        raise InferenceError(f"Circuit open{tail}: {state.last_error}".strip())


def _circuit_record_success(*, config: OpenAICompatibleConfig) -> None:
    key = _circuit_key(config)
    with _CIRCUIT_LOCK:
        state = _CIRCUITS.get(key)
        if not state:
            return
        state.failures = 0
        state.open_until_s = 0.0
        state.last_failure_s = 0.0
        state.last_error = ""


def _circuit_record_failure(*, config: OpenAICompatibleConfig, error: str) -> None:
    key = _circuit_key(config)
    now = time.time()
    threshold, cooldown_s, window_s = _circuit_params()
    with _CIRCUIT_LOCK:
        state = _CIRCUITS.get(key)
        if not state:
            state = _CircuitState()
            _CIRCUITS[key] = state

        # Only count failures within a rolling window.
        if state.last_failure_s and now - state.last_failure_s > window_s:
            state.failures = 0

        state.failures += 1
        state.last_failure_s = now
        state.last_error = str(error or "").strip()[:200]

        if cooldown_s > 0 and state.failures >= threshold:
            state.open_until_s = now + cooldown_s


def load_openai_compatible_config_from_env() -> OpenAICompatibleConfig:
    return load_openai_compatible_config_from_env_prefix("CLINICAFLOW_REASONING")


def load_openai_compatible_config_from_env_prefix(prefix: str) -> OpenAICompatibleConfig:
    """Load OpenAI-compatible client config from env vars.

    Examples:
    - Reasoning: prefix="CLINICAFLOW_REASONING"
      - CLINICAFLOW_REASONING_BASE_URL, CLINICAFLOW_REASONING_MODEL, ...
    - Communication rewrite: prefix="CLINICAFLOW_COMMUNICATION"
      - CLINICAFLOW_COMMUNICATION_BASE_URL, CLINICAFLOW_COMMUNICATION_MODEL, ...

    Back-compat: when prefix is not CLINICAFLOW_REASONING, missing values fall
    back to the CLINICAFLOW_REASONING_* env vars.
    """

    prefix = (prefix or "").strip().upper()
    if not prefix:
        prefix = "CLINICAFLOW_REASONING"

    def env(name: str, default: str = "") -> str:
        key = f"{prefix}_{name}"
        fallback = f"CLINICAFLOW_REASONING_{name}" if prefix != "CLINICAFLOW_REASONING" else ""
        if key in os.environ:
            return str(os.environ.get(key) or "").strip()
        if fallback and fallback in os.environ:
            return str(os.environ.get(fallback) or "").strip()
        return default

    def env_opt(name: str) -> str | None:
        key = f"{prefix}_{name}"
        fallback = f"CLINICAFLOW_REASONING_{name}" if prefix != "CLINICAFLOW_REASONING" else ""
        if key in os.environ:
            return os.environ.get(key)
        if fallback and fallback in os.environ:
            return os.environ.get(fallback)
        return None

    base_url = env("BASE_URL", "")
    model = env("MODEL", "")
    api_key = env_opt("API_KEY")
    timeout_s = float(env("TIMEOUT_S", "30"))
    max_retries = int(env("MAX_RETRIES", "1"))
    retry_backoff_s = float(env("RETRY_BACKOFF_S", "0.5"))
    temperature = float(env("TEMPERATURE", "0.2"))
    max_tokens = int(env("MAX_TOKENS", "600"))

    if not base_url:
        raise InferenceError(f"Missing env var: {prefix}_BASE_URL")
    if not model:
        raise InferenceError(f"Missing env var: {prefix}_MODEL")
    if max_retries < 0:
        raise InferenceError(f"{prefix}_MAX_RETRIES must be >= 0")
    if timeout_s <= 0:
        raise InferenceError(f"{prefix}_TIMEOUT_S must be > 0")
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
    return chat_completion_messages(
        config=config,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )


def chat_completion_messages(*, config: OpenAICompatibleConfig, messages: list[dict[str, Any]]) -> str:
    _circuit_check_or_raise(config=config)
    url = config.base_url.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": config.model,
        "messages": messages,
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
            if last_exc is not None:
                _circuit_record_failure(config=config, error=str(last_exc))
            raise last_exc from last_cause
        time.sleep(config.retry_backoff_s * (2**attempt))

    if last_exc is not None:
        _circuit_record_failure(config=config, error=str(last_exc))
        raise last_exc from last_cause

    try:
        choice0 = payload["choices"][0]
        message = choice0.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            _circuit_record_success(config=config)
            return content
        # Some servers return 'text' instead.
        text = choice0.get("text")
        if isinstance(text, str) and text.strip():
            _circuit_record_success(config=config)
            return text
    except (KeyError, IndexError, TypeError) as exc:
        err = InferenceError(f"Unexpected OpenAI-compatible response: {payload!r}")
        _circuit_record_failure(config=config, error=str(err))
        raise err from exc

    err = InferenceError(f"Empty completion content: {payload!r}")
    _circuit_record_failure(config=config, error=str(err))
    raise err
