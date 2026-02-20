from __future__ import annotations

import json
from pathlib import Path


def validate_policy_pack(path: str | Path | object) -> list[str]:
    """Validate the demo policy pack structure.

    The policy pack is intentionally lightweight and not a full clinical guideline format.
    We validate the subset the pipeline/UI depends on.
    """

    errors: list[str] = []

    try:
        raw_text = _read_text(path)
    except Exception as exc:  # noqa: BLE001
        return [f"policy_pack: failed_to_read: {exc}"]

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return [f"policy_pack: invalid_json: {exc}"]

    if not isinstance(payload, dict):
        return ["policy_pack: root must be an object"]

    policies = payload.get("policies")
    if not isinstance(policies, list):
        errors.append("policy_pack: missing or invalid 'policies' (expected array)")
        return errors

    seen_ids: set[str] = set()
    for idx, p in enumerate(policies):
        prefix = f"policy_pack.policies[{idx}]"
        if not isinstance(p, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        pid = str(p.get("policy_id") or "").strip()
        title = str(p.get("title") or "").strip()
        citation = str(p.get("citation") or "").strip()
        triggers = p.get("triggers")
        actions = p.get("recommended_actions")

        if not pid:
            errors.append(f"{prefix}.policy_id: required")
        if pid and pid in seen_ids:
            errors.append(f"{prefix}.policy_id: duplicate '{pid}'")
        if pid:
            seen_ids.add(pid)

        if not title:
            errors.append(f"{prefix}.title: required")
        if not citation:
            errors.append(f"{prefix}.citation: required")

        if not isinstance(triggers, list) or not all(isinstance(x, str) and x.strip() for x in triggers):
            errors.append(f"{prefix}.triggers: expected non-empty array of strings")

        if not isinstance(actions, list) or not all(isinstance(x, str) and x.strip() for x in actions):
            errors.append(f"{prefix}.recommended_actions: expected non-empty array of strings")

    if not policies:
        errors.append("policy_pack: policies must not be empty")

    return errors


def _read_text(path: str | Path | object) -> str:
    """Read text from a path-like object (Path, str, or importlib.resources Traversable)."""

    # importlib.resources Traversable
    if hasattr(path, "read_text"):
        return path.read_text(encoding="utf-8")  # type: ignore[no-any-return]

    return Path(path).read_text(encoding="utf-8")
