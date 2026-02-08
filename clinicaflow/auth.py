from __future__ import annotations

from typing import Mapping


def is_authorized(*, headers: Mapping[str, str], expected_api_key: str) -> bool:
    """Simple optional API key auth (no deps).

    If `expected_api_key` is empty, auth is disabled and all requests are allowed.

    Accepted headers:
    - Authorization: Bearer <token>
    - X-API-Key: <token>
    """

    if not expected_api_key:
        return True

    bearer = _extract_bearer(headers.get("Authorization", ""))
    if bearer and _constant_time_eq(bearer, expected_api_key):
        return True

    x_api_key = (headers.get("X-API-Key") or headers.get("X-Api-Key") or "").strip()
    if x_api_key and _constant_time_eq(x_api_key, expected_api_key):
        return True

    return False


def _extract_bearer(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return ""
    scheme, token = parts
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _constant_time_eq(a: str, b: str) -> bool:
    # Constant-time compare for small secrets.
    if len(a) != len(b):
        return False
    result = 0
    for ca, cb in zip(a.encode("utf-8"), b.encode("utf-8"), strict=False):
        result |= ca ^ cb
    return result == 0

