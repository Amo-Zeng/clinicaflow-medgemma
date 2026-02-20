from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_RISK_TIERS = {"routine", "urgent", "critical"}
ALLOWED_RED_FLAG_CATEGORIES = {
    "cardiopulmonary",
    "neurologic",
    "syncope",
    "gi_bleed",
    "obstetric",
    "hypoxemia",
    "hemodynamic",
    "sepsis",
}


def validate_vignettes_jsonl(path: str | Path | object) -> list[str]:
    """Validate a vignette JSONL file."""

    errors: list[str] = []
    try:
        text = _read_text(path)
    except Exception as exc:  # noqa: BLE001
        return [f"vignettes: failed_to_read: {exc}"]

    seen_ids: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{_label(path)}:{lineno}: invalid_json: {exc}")
            continue

        prefix = f"{_label(path)}:{lineno}"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: row must be an object")
            continue

        vid = str(row.get("id") or "").strip()
        if not vid:
            errors.append(f"{prefix}.id: required")
        if vid and vid in seen_ids:
            errors.append(f"{prefix}.id: duplicate '{vid}'")
        if vid:
            seen_ids.add(vid)

        case_input = row.get("input")
        if not isinstance(case_input, dict):
            errors.append(f"{prefix}.input: required object")
            continue

        chief = str(case_input.get("chief_complaint") or "").strip()
        if not chief:
            errors.append(f"{prefix}.input.chief_complaint: required")

        vitals = case_input.get("vitals") or {}
        if vitals is not None and not isinstance(vitals, dict):
            errors.append(f"{prefix}.input.vitals: must be an object")
        elif isinstance(vitals, dict):
            errors.extend(_validate_vitals(prefix, vitals))

        labels = row.get("labels")
        if not isinstance(labels, dict):
            errors.append(f"{prefix}.labels: required object")
            continue

        tier = str(labels.get("gold_risk_tier") or "").strip().lower()
        if tier not in ALLOWED_RISK_TIERS:
            errors.append(f"{prefix}.labels.gold_risk_tier: invalid '{tier}' (allowed: {sorted(ALLOWED_RISK_TIERS)})")

        cats = labels.get("gold_red_flag_categories") or []
        if not isinstance(cats, list) or not all(isinstance(x, str) and x.strip() for x in cats):
            errors.append(f"{prefix}.labels.gold_red_flag_categories: expected array of strings")
            cats_list: list[str] = []
        else:
            cats_list = [str(x).strip() for x in cats]
        for c in cats_list:
            if c not in ALLOWED_RED_FLAG_CATEGORIES:
                errors.append(
                    f"{prefix}.labels.gold_red_flag_categories: unknown category '{c}' (allowed: {sorted(ALLOWED_RED_FLAG_CATEGORIES)})"
                )

        esc = labels.get("gold_escalation_required")
        if not isinstance(esc, bool):
            errors.append(f"{prefix}.labels.gold_escalation_required: expected boolean")

        rationale = str(row.get("rationale") or "").strip()
        if not rationale:
            errors.append(f"{prefix}.rationale: required")

    return errors


def _validate_vitals(prefix: str, vitals: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "heart_rate",
        "systolic_bp",
        "diastolic_bp",
        "temperature_c",
        "spo2",
        "respiratory_rate",
    }
    for k in vitals:
        if k not in allowed:
            errors.append(f"{prefix}.input.vitals.{k}: unknown field (allowed: {sorted(allowed)})")

    for k in allowed:
        if k not in vitals:
            continue
        v = vitals.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            errors.append(f"{prefix}.input.vitals.{k}: must be a number, got bool")
            continue
        if isinstance(v, (int, float)):
            continue
        # allow numeric strings
        try:
            float(str(v))
        except ValueError:
            errors.append(f"{prefix}.input.vitals.{k}: must be numeric, got {type(v).__name__}")

    return errors


def _read_text(path: str | Path | object) -> str:
    # importlib.resources Traversable
    if hasattr(path, "read_text"):
        return path.read_text(encoding="utf-8")  # type: ignore[no-any-return]
    return Path(path).read_text(encoding="utf-8")


def _label(path: str | Path | object) -> str:
    try:
        return str(Path(path))
    except TypeError:
        # importlib.resources Traversable may not be Path-able.
        return str(path)

