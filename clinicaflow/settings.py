from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    debug: bool
    log_level: str
    json_logs: bool
    max_request_bytes: int
    policy_top_k: int
    policy_pack_path: str
    cors_allow_origin: str
    api_key: str


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings_from_env() -> Settings:
    debug = _get_env_bool("CLINICAFLOW_DEBUG", False)
    log_level = os.environ.get("CLINICAFLOW_LOG_LEVEL", "INFO").strip().upper()
    json_logs = _get_env_bool("CLINICAFLOW_JSON_LOGS", False)
    max_request_bytes = int(os.environ.get("CLINICAFLOW_MAX_REQUEST_BYTES", "262144").strip())
    policy_top_k = int(os.environ.get("CLINICAFLOW_POLICY_TOPK", "2").strip())
    policy_pack_path = os.environ.get("CLINICAFLOW_POLICY_PACK_PATH", "").strip()
    cors_allow_origin = os.environ.get("CLINICAFLOW_CORS_ALLOW_ORIGIN", "*").strip() or "*"
    api_key = os.environ.get("CLINICAFLOW_API_KEY", "").strip()

    return Settings(
        debug=debug,
        log_level=log_level,
        json_logs=json_logs,
        max_request_bytes=max_request_bytes,
        policy_top_k=policy_top_k,
        policy_pack_path=policy_pack_path,
        cors_allow_origin=cors_allow_origin,
        api_key=api_key,
    )
