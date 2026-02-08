from __future__ import annotations

import os
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

    payload: dict[str, Any] = {
        "version": __version__,
        "settings": {
            "debug": settings.debug,
            "log_level": settings.log_level,
            "json_logs": settings.json_logs,
            "max_request_bytes": settings.max_request_bytes,
            "policy_top_k": settings.policy_top_k,
            "cors_allow_origin": settings.cors_allow_origin,
        },
        "policy_pack": {
            "source": policy_source,
            "sha256": policy_sha256,
            "n_policies": n_policies,
        },
        "reasoning_backend": {
            "backend": os.environ.get("CLINICAFLOW_REASONING_BACKEND", "deterministic").strip(),
            "base_url": os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip(),
            "model": os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip(),
            "timeout_s": os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "").strip(),
            "max_retries": os.environ.get("CLINICAFLOW_REASONING_MAX_RETRIES", "").strip(),
        },
    }

    return payload

