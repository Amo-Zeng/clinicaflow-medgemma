from __future__ import annotations

import os
import time
from typing import Any

from clinicaflow.inference.openai_compatible import InferenceError


def ping_inference_backend(*, env_prefix: str) -> dict[str, Any]:
    """Best-effort deep connectivity check (no PHI).

    This intentionally runs a tiny inference call to verify the configured backend
    is actually able to serve requests (vs only responding to health/config).
    """

    prefix = (env_prefix or "").strip().upper()
    if not prefix:
        prefix = "CLINICAFLOW_REASONING"

    backend = os.environ.get(f"{prefix}_BACKEND", "deterministic").strip().lower()
    started = time.perf_counter()

    if backend in {"", "deterministic"}:
        return {"ok": True, "backend": "deterministic", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}

    if backend == "gradio_space":
        from clinicaflow.inference.gradio_space import gradio_chat_completion, load_gradio_space_configs_from_env_prefix

        configs = load_gradio_space_configs_from_env_prefix(prefix)
        errors: list[str] = []
        for cfg in configs:
            try:
                text = gradio_chat_completion(
                    config=cfg,
                    system="Return exactly 'PONG' and nothing else.",
                    user="Return only PONG.",
                )
                ok = "PONG" in str(text or "").strip().upper()
                return {
                    "ok": ok,
                    "backend": "gradio_space",
                    "base_url": cfg.base_url,
                    "api_name": cfg.api_name,
                    "response_preview": str(text or "").strip()[:60],
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            except InferenceError as exc:
                errors.append(f"{cfg.base_url} ({cfg.api_name}): {exc}")
                continue

        return {
            "ok": False,
            "backend": "gradio_space",
            "error": "All Gradio Spaces failed.",
            "errors_preview": errors[:3],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    if backend in {"openai", "openai_compatible"}:
        from clinicaflow.inference.openai_compatible import chat_completion, load_openai_compatible_config_from_env_prefix

        cfg = load_openai_compatible_config_from_env_prefix(prefix)
        text = chat_completion(
            config=cfg,
            system="Return exactly 'PONG' and nothing else.",
            user="Return only PONG.",
        )
        ok = "PONG" in str(text or "").strip().upper()
        return {
            "ok": ok,
            "backend": backend,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "response_preview": str(text or "").strip()[:60],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    if backend == "hf_inference":
        from clinicaflow.inference.hf_inference import hf_generate_text, load_hf_inference_config_from_env_prefix

        cfg = load_hf_inference_config_from_env_prefix(prefix)
        prompt = "\n".join(
            [
                "SYSTEM:",
                "Return exactly 'PONG' and nothing else.",
                "",
                "USER:",
                "Return only PONG.",
                "",
                "ASSISTANT:",
            ]
        ).strip()
        text = hf_generate_text(config=cfg, prompt=prompt)
        ok = "PONG" in str(text or "").strip().upper()
        return {
            "ok": ok,
            "backend": "hf_inference",
            "base_url": cfg.base_url,
            "model": cfg.model,
            "response_preview": str(text or "").strip()[:60],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    return {
        "ok": False,
        "backend": backend,
        "error": f"Unsupported backend: {backend}",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
