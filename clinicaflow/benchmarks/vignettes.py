from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


@dataclass(frozen=True, slots=True)
class VignetteBenchmarkSummary:
    n_cases: int
    n_gold_urgent_critical: int
    red_flag_recall_baseline: float
    red_flag_recall_clinicaflow: float
    under_triage_rate_baseline: float
    under_triage_rate_clinicaflow: float
    over_triage_rate_baseline: float
    over_triage_rate_clinicaflow: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown_table(self) -> str:
        def pct(v: float) -> str:
            return f"{v:.1f}%"

        lines = [
            "| Metric | Baseline | ClinicaFlow |",
            "|---|---:|---:|",
            f"| Red-flag recall (category-level) | `{pct(self.red_flag_recall_baseline)}` | `{pct(self.red_flag_recall_clinicaflow)}` |",
            f"| Under-triage rate (gold urgent/critical → predicted routine) | `{pct(self.under_triage_rate_baseline)}` | `{pct(self.under_triage_rate_clinicaflow)}` |",
            f"| Over-triage rate (gold routine → predicted urgent/critical) | `{pct(self.over_triage_rate_baseline)}` | `{pct(self.over_triage_rate_clinicaflow)}` |",
        ]
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clinical vignette regression benchmark for ClinicaFlow.")
    parser.add_argument("--path", type=Path, help="Path to vignettes JSONL (default: packaged resource)")
    parser.add_argument("--out", type=Path, help="Optional JSON output path for the summary")
    parser.add_argument("--cases-out", type=Path, help="Optional JSON output path for per-case results")
    parser.add_argument("--print-markdown", action="store_true", help="Print the markdown table")
    return parser


def load_default_vignette_path() -> Path:
    from importlib.resources import files

    return Path(files("clinicaflow.resources").joinpath("vignettes.jsonl"))


def load_vignettes(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        rows.append(json.loads(raw))
    return rows


def _category_set(categories: Any) -> set[str]:
    if not categories:
        return set()
    if isinstance(categories, list):
        return {str(x).strip() for x in categories if str(x).strip()}
    return {str(categories).strip()}


def categories_from_red_flags(red_flags: list[str]) -> set[str]:
    cats: set[str] = set()
    for flag in red_flags:
        f = str(flag or "")
        if not f:
            continue

        if "Potential acute coronary syndrome" in f or "Respiratory compromise risk" in f:
            cats.add("cardiopulmonary")
        if "Possible stroke" in f or "Possible neurological or metabolic emergency" in f or "Possible intracranial pathology" in f:
            cats.add("neurologic")
        if "Possible gastrointestinal bleed" in f or "Possible upper GI bleed" in f:
            cats.add("gi_bleed")
        if "Possible obstetric emergency" in f:
            cats.add("obstetric")
        if "Syncope requiring urgent evaluation" in f:
            cats.add("syncope")

        if "Low oxygen saturation" in f:
            cats.add("hypoxemia")
        if "Hypotension" in f or "Severe tachycardia" in f:
            cats.add("hemodynamic")
        if "High fever" in f:
            cats.add("sepsis")

    return cats


def baseline_predict(case: dict[str, Any]) -> tuple[str, set[str]]:
    """A simple vitals-first baseline that misses many synonym patterns."""

    text = f"{case.get('chief_complaint','')} {case.get('history','')}".lower()
    vitals = dict(case.get("vitals", {}) or {})

    hr = _to_float(vitals.get("heart_rate"))
    sbp = _to_float(vitals.get("systolic_bp"))
    temp = _to_float(vitals.get("temperature_c"))
    spo2 = _to_float(vitals.get("spo2"))

    cats: set[str] = set()

    # Minimal keyword detection (intentionally limited).
    if "chest pain" in text or "shortness of breath" in text:
        cats.add("cardiopulmonary")
    if "slurred speech" in text or "confusion" in text:
        cats.add("neurologic")
    if "vomiting blood" in text:
        cats.add("gi_bleed")
    if "fainting" in text:
        cats.add("syncope")

    # Vitals triggers (baseline is stronger here).
    if spo2 is not None and spo2 < 92:
        cats.add("hypoxemia")
    if sbp is not None and sbp < 90:
        cats.add("hemodynamic")
    if hr is not None and hr > 130:
        cats.add("hemodynamic")
    if temp is not None and temp >= 39.5:
        cats.add("sepsis")

    vital_concern = (hr is not None and hr >= 110) or (temp is not None and temp >= 38.5) or (spo2 is not None and spo2 < 95)

    if "hemodynamic" in cats or ("hypoxemia" in cats and "cardiopulmonary" in cats) or len(cats) >= 2:
        tier = "critical"
    elif cats or vital_concern:
        tier = "urgent"
    else:
        tier = "routine"

    return tier, cats


def run_benchmark(path: Path) -> tuple[VignetteBenchmarkSummary, list[dict[str, Any]]]:
    rows = load_vignettes(path)
    pipeline = ClinicaFlowPipeline()

    gold_urgent_critical = 0
    baseline_under = 0
    cf_under = 0

    gold_routine = 0
    baseline_over = 0
    cf_over = 0

    gold_has_flags = 0
    baseline_flag_hit = 0
    cf_flag_hit = 0

    per_case: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("id", "")).strip()
        case_input = dict(row.get("input") or {})
        labels = dict(row.get("labels") or {})

        gold_tier = str(labels.get("gold_risk_tier") or "").strip().lower()
        gold_cats = _category_set(labels.get("gold_red_flag_categories"))
        gold_escalation = bool(labels.get("gold_escalation_required", gold_tier in {"urgent", "critical"}))

        baseline_tier, baseline_cats = baseline_predict(case_input)

        intake = PatientIntake.from_mapping(case_input)
        cf = pipeline.run(intake)
        cf_tier = cf.risk_tier
        cf_cats = categories_from_red_flags(cf.red_flags)

        # Red-flag recall (category-level).
        if gold_cats:
            gold_has_flags += 1
            baseline_flag_hit += int(bool(baseline_cats & gold_cats))
            cf_flag_hit += int(bool(cf_cats & gold_cats))

        # Under-triage.
        if gold_tier in {"urgent", "critical"}:
            gold_urgent_critical += 1
            baseline_under += int(baseline_tier == "routine")
            cf_under += int(cf_tier == "routine")

        # Over-triage.
        if gold_tier == "routine":
            gold_routine += 1
            baseline_over += int(baseline_tier != "routine")
            cf_over += int(cf_tier != "routine")

        per_case.append(
            {
                "id": case_id,
                "gold": {"risk_tier": gold_tier, "categories": sorted(gold_cats), "escalation_required": gold_escalation},
                "baseline": {"risk_tier": baseline_tier, "categories": sorted(baseline_cats)},
                "clinicaflow": {
                    "risk_tier": cf_tier,
                    "categories": sorted(cf_cats),
                    "red_flags": cf.red_flags,
                    "escalation_required": cf.escalation_required,
                    "confidence": cf.confidence,
                },
            }
        )

    def safe_pct(n: int, d: int) -> float:
        return 100.0 * n / max(1, d)

    summary = VignetteBenchmarkSummary(
        n_cases=len(rows),
        n_gold_urgent_critical=gold_urgent_critical,
        red_flag_recall_baseline=round(safe_pct(baseline_flag_hit, gold_has_flags), 1),
        red_flag_recall_clinicaflow=round(safe_pct(cf_flag_hit, gold_has_flags), 1),
        under_triage_rate_baseline=round(safe_pct(baseline_under, gold_urgent_critical), 1),
        under_triage_rate_clinicaflow=round(safe_pct(cf_under, gold_urgent_critical), 1),
        over_triage_rate_baseline=round(safe_pct(baseline_over, gold_routine), 1),
        over_triage_rate_clinicaflow=round(safe_pct(cf_over, gold_routine), 1),
    )

    return summary, per_case


def main() -> None:
    args = build_parser().parse_args()
    path = args.path or load_default_vignette_path()

    summary, per_case = run_benchmark(path)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    if args.cases_out:
        args.cases_out.parent.mkdir(parents=True, exist_ok=True)
        args.cases_out.write_text(json.dumps(per_case, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.print_markdown:
        print(summary.to_markdown_table())
    else:
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
