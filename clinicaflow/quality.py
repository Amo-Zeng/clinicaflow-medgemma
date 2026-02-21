from __future__ import annotations

from typing import Any

from clinicaflow.models import PatientIntake, Vitals


def intake_quality_warnings(intake: PatientIntake) -> list[str]:
    """Return lightweight data-quality warnings for common input issues.

    This is intentionally conservative and non-diagnostic. It is designed to
    catch obvious unit/range issues (e.g., SpO₂ > 100) that can meaningfully
    degrade downstream decision support.
    """

    warnings: list[str] = []

    demo = dict(intake.demographics or {})
    age = demo.get("age")
    if isinstance(age, (int, float)):
        if age < 0:
            warnings.append("Age < 0 (input error)")
        elif age > 120:
            warnings.append("Age > 120 (check units/input)")

    warnings.extend(_vitals_quality_warnings(intake.vitals))
    return _dedupe(warnings)


def _vitals_quality_warnings(vitals: Vitals) -> list[str]:
    w: list[str] = []

    hr = vitals.heart_rate
    if isinstance(hr, (int, float)):
        if hr <= 0:
            w.append("Heart rate ≤ 0 (input error)")
        elif hr < 20 or hr > 250:
            w.append("Heart rate out of plausible range (check units/input)")

    sbp = vitals.systolic_bp
    dbp = vitals.diastolic_bp
    if isinstance(sbp, (int, float)):
        if sbp <= 0:
            w.append("Systolic BP ≤ 0 (input error)")
        elif sbp < 50 or sbp > 250:
            w.append("Systolic BP out of plausible range (check units/input)")
    if isinstance(dbp, (int, float)):
        if dbp <= 0:
            w.append("Diastolic BP ≤ 0 (input error)")
        elif dbp < 30 or dbp > 160:
            w.append("Diastolic BP out of plausible range (check units/input)")
    if isinstance(sbp, (int, float)) and isinstance(dbp, (int, float)) and sbp > 0 and dbp > 0 and dbp >= sbp:
        w.append("Diastolic BP ≥ systolic BP (input error)")

    temp = vitals.temperature_c
    if isinstance(temp, (int, float)):
        if temp < 25:
            w.append("Temp < 25°C (possible Fahrenheit / input error)")
        elif temp > 45:
            w.append("Temp > 45°C (input error)")

    spo2 = vitals.spo2
    if isinstance(spo2, (int, float)):
        if spo2 < 0:
            w.append("SpO₂ < 0 (input error)")
        elif spo2 > 100:
            w.append("SpO₂ > 100 (input error)")

    rr = vitals.respiratory_rate
    if isinstance(rr, (int, float)):
        if rr <= 0:
            w.append("Respiratory rate ≤ 0 (input error)")
        elif rr < 4 or rr > 80:
            w.append("Respiratory rate out of plausible range (check units/input)")

    return w


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        t = str(item or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def safe_dict(value: Any) -> dict[str, Any]:
    """Return `value` as a dict if possible, else empty dict."""

    if isinstance(value, dict):
        return value
    return {}

