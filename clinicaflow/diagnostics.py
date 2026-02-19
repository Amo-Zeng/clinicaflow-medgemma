from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from clinicaflow.policy_pack import load_policy_pack, policy_pack_sha256
from clinicaflow.settings import load_settings_from_env
from clinicaflow.version import __version__


def resolve_policy_pack_path() -> tuple[object, str]:
    """Return (path-like, human-readable source label)."""
    settings = load_settings_from_env()
    if settings.policy_pack_path:
        return settings.policy_pack_path, str(settings.policy_pack_path)

    from importlib.resources import files

    policy_path = files("clinicaflow.resources").joinpath("policy_pack.json")
    return policy_path, "package:clinicaflow.resources/policy_pack.json"


def collect_diagnostics() -> dict[str, Any]:
    """Collect safe runtime diagnostics (no secrets)."""
    settings = load_settings_from_env()
    policy_path, policy_source = resolve_policy_pack_path()

    try:
        policy_sha256 = policy_pack_sha256(policy_path)
        n_policies = len(load_policy_pack(policy_path))
    except Exception:  # noqa: BLE001
        policy_sha256 = ""
        n_policies = 0

    reasoning_backend = os.environ.get("CLINICAFLOW_REASONING_BACKEND", "deterministic").strip()
    reasoning_base_url = os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip()
    reasoning_model = os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip()
    reasoning_timeout_s = os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "").strip()
    reasoning_max_retries = os.environ.get("CLINICAFLOW_REASONING_MAX_RETRIES", "").strip()

    connectivity = _check_reasoning_connectivity(
        backend=reasoning_backend,
        base_url=reasoning_base_url,
        model=reasoning_model,
        timeout_s=_safe_float(reasoning_timeout_s, default=1.2),
        api_key=os.environ.get("CLINICAFLOW_REASONING_API_KEY"),
    )

    comm_backend = os.environ.get("CLINICAFLOW_COMMUNICATION_BACKEND", "deterministic").strip()
    comm_connectivity = _check_reasoning_connectivity(
        backend=comm_backend,
        base_url=reasoning_base_url,
        model=reasoning_model,
        timeout_s=_safe_float(reasoning_timeout_s, default=1.2),
        api_key=os.environ.get("CLINICAFLOW_REASONING_API_KEY"),
    )

    payload: dict[str, Any] = {
        "version": __version__,
        "settings": {
            "debug": settings.debug,
            "log_level": settings.log_level,
            "json_logs": settings.json_logs,
            "max_request_bytes": settings.max_request_bytes,
            "policy_top_k": settings.policy_top_k,
            "cors_allow_origin": settings.cors_allow_origin,
            "api_key_configured": bool(settings.api_key),
        },
        "policy_pack": {
            "source": policy_source,
            "sha256": policy_sha256,
            "n_policies": n_policies,
        },
        "reasoning_backend": {
            "backend": reasoning_backend,
            "base_url": reasoning_base_url,
            "model": reasoning_model,
            "timeout_s": reasoning_timeout_s,
            "max_retries": reasoning_max_retries,
            **connectivity,
        },
        "communication_backend": {
            "backend": comm_backend,
            "base_url": reasoning_base_url,
            "model": reasoning_model,
            "timeout_s": reasoning_timeout_s,
            "max_retries": reasoning_max_retries,
            **comm_connectivity,
        },
    }

    return payload


def _safe_float(value: str, *, default: float) -> float:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _check_reasoning_connectivity(
    *,
    backend: str,
    base_url: str,
    model: str,
    timeout_s: float,
    api_key: str | None,
) -> dict[str, Any]:
    """Best-effort connectivity check for OpenAI-compatible endpoints.

    Kept intentionally lightweight: short timeout, never raises, no secrets emitted.
    """

    backend = (backend or "").strip().lower()
    if backend not in {"openai", "openai_compatible"}:
        return {"connectivity_ok": None}
    if not base_url:
        return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_BASE_URL"}
    if not model:
        return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_MODEL"}

    url = base_url.rstrip("/") + "/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url=url, method="GET", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=max(0.2, min(timeout_s, 2.0))) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        models = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            mid = item.get("id")
            if isinstance(mid, str) and mid.strip():
                models.append(mid.strip())
        return {
            "connectivity_ok": True,
            "models_preview": models[:10],
            "model_found": bool(model and model in models) if models else None,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {"connectivity_ok": False, "connectivity_error": str(exc)[:200]}
