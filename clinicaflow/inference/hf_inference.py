from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from clinicaflow.inference.openai_compatible import InferenceError


DEFAULT_HF_ROUTER_BASE_URL = "https://router.huggingface.co/hf-inference"


@dataclass(frozen=True, slots=True)
class HFInferenceConfig:
    """Hugging Face router inference config (serverless; API-token auth).

    This targets the Hugging Face "router" endpoint:
      https://router.huggingface.co/hf-inference/models/<model_id>
    """

    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: float = 45.0
    max_retries: int = 1
    retry_backoff_s: float = 0.5
    temperature: float = 0.2
    max_tokens: int = 600
    wait_for_model: bool = True


def load_hf_inference_config_from_env_prefix(prefix: str) -> HFInferenceConfig:
    prefix = (prefix or "").strip().upper() or "CLINICAFLOW_REASONING"

    def env(name: str, default: str = "") -> str:
        key = f"{prefix}_{name}"
        return str(os.environ.get(key, default) or "").strip()

    def env_opt(name: str) -> str | None:
        key = f"{prefix}_{name}"
        return os.environ.get(key)

    base_url = env("BASE_URL", "") or DEFAULT_HF_ROUTER_BASE_URL
    model = env("MODEL", "")
    api_key = env_opt("API_KEY")
    timeout_s = float(env("TIMEOUT_S", "45"))
    max_retries = int(env("MAX_RETRIES", "1"))
    retry_backoff_s = float(env("RETRY_BACKOFF_S", "0.5"))
    temperature = float(env("TEMPERATURE", "0.2"))
    max_tokens = int(env("MAX_TOKENS", "600"))
    wait_for_model = env("HF_WAIT_FOR_MODEL", "1").strip().lower() in {"1", "true", "yes", "y", "on"}

    if not model:
        raise InferenceError(f"Missing env var: {prefix}_MODEL")
    if max_retries < 0:
        raise InferenceError(f"{prefix}_MAX_RETRIES must be >= 0")
    if timeout_s <= 0:
        raise InferenceError(f"{prefix}_TIMEOUT_S must be > 0")

    return HFInferenceConfig(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=min(max_retries, 5),
        retry_backoff_s=max(0.0, float(retry_backoff_s)),
        temperature=temperature,
        max_tokens=max(1, int(max_tokens)),
        wait_for_model=bool(wait_for_model),
    )


def _hf_model_url(config: HFInferenceConfig) -> str:
    base = str(config.base_url or "").rstrip("/")
    # Model IDs contain slashes; must be URL-escaped.
    model = urllib.parse.quote(str(config.model or "").strip(), safe="")
    return f"{base}/models/{model}"


def hf_generate_text(*, config: HFInferenceConfig, prompt: str) -> str:
    """Generate text via Hugging Face router inference.

    Response shapes observed in the wild include:
    - [{"generated_text": "..."}]
    - {"generated_text": "..."}
    - {"error": "..."}
    """

    url = _hf_model_url(config)
    body = {
        "inputs": str(prompt or ""),
        "parameters": {
            "max_new_tokens": int(config.max_tokens),
            "temperature": float(config.temperature),
            "return_full_text": False,
        },
        "options": {"wait_for_model": bool(config.wait_for_model)},
    }

    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    req = urllib.request.Request(url=url, method="POST", data=data, headers=headers)  # noqa: S310

    last_exc: InferenceError | None = None
    last_cause: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:  # noqa: S310
                raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
            last_exc = None
            last_cause = None
            break
        except urllib.error.HTTPError as exc:
            try:
                body_preview = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                body_preview = ""
            last_exc = InferenceError(f"HF inference HTTP {exc.code}: {body_preview}".strip())
            last_cause = exc
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = InferenceError(f"HF inference request failed: {exc}")
            last_cause = exc
            retryable = True

        if attempt >= config.max_retries or not retryable:
            raise last_exc from last_cause
        time.sleep(config.retry_backoff_s * (2**attempt))

    if last_exc is not None:
        raise last_exc from last_cause

    if isinstance(payload, list) and payload:
        item0 = payload[0]
        if isinstance(item0, dict):
            txt = item0.get("generated_text")
            if isinstance(txt, str) and txt.strip():
                return txt

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, str) and err.strip():
            raise InferenceError(f"HF inference error: {err}".strip())
        txt = payload.get("generated_text")
        if isinstance(txt, str) and txt.strip():
            return txt

    raise InferenceError(f"Unexpected HF inference response: {payload!r}")

