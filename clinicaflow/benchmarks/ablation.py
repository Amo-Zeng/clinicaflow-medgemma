from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clinicaflow.agents import (
    IntakeStructuringAgent,
    MultimodalClinicalReasoningAgent,
    SafetyEscalationAgent,
)
from clinicaflow.benchmarks.vignettes import (
    baseline_predict,
    categories_from_red_flags,
    load_default_vignette_paths,
    load_vignettes,
)
from clinicaflow.models import PatientIntake, StructuredIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


@dataclass(frozen=True, slots=True)
class AblationVariantSummary:
    variant: str
    n_cases: int
    red_flag_recall: float
    under_triage_rate: float
    over_triage_rate: float
    avg_actions: float
    avg_citations: float
    avg_completeness: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AblationSummary:
    set_name: str
    n_cases: int
    variants: list[AblationVariantSummary]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["variants"] = [v.to_dict() for v in self.variants]
        return payload

    def to_markdown_table(self) -> str:
        def pct(v: float) -> str:
            return f"{v:.1f}%"

        def num(v: float) -> str:
            if abs(v) >= 10:
                return f"{v:.1f}"
            return f"{v:.2f}"

        lines = [
            f"Set: `{self.set_name}` (n={self.n_cases})",
            "",
            "| Variant | Red-flag recall | Under-triage | Over-triage | Avg actions | Avg citations | Completeness (0–5) |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for v in self.variants:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{v.variant}`",
                        f"`{pct(v.red_flag_recall)}`",
                        f"`{pct(v.under_triage_rate)}`",
                        f"`{pct(v.over_triage_rate)}`",
                        f"`{num(v.avg_actions)}`",
                        f"`{num(v.avg_citations)}`",
                        f"`{num(v.avg_completeness)}`",
                    ]
                )
                + " |"
            )
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ablation benchmark: compare baseline vs reasoning-only vs safety-only vs full pipeline "
            "on packaged vignette sets. Outputs are synthetic-only proxies."
        )
    )
    parser.add_argument(
        "--set",
        choices=["standard", "adversarial", "extended", "realworld", "case_reports", "all", "mega", "ultra"],
        default="mega",
        help="Which vignette set to evaluate (default: mega).",
    )
    parser.add_argument("--out", type=Path, help="Optional JSON output path for the ablation summary")
    parser.add_argument("--cases-out", type=Path, help="Optional JSON output path for per-case ablation rows")
    parser.add_argument("--print-markdown", action="store_true", help="Print the markdown table")
    return parser


def completeness_score(*, risk_tier: str, red_flags: list[str], differential: list[str], actions: list[str], patient_summary: str) -> int:
    score = 0
    if str(risk_tier or "").strip():
        score += 1
    if [str(x).strip() for x in red_flags if str(x).strip()]:
        score += 1
    if [str(x).strip() for x in differential if str(x).strip()]:
        score += 1
    if [str(x).strip() for x in actions if str(x).strip()]:
        score += 1
    if str(patient_summary or "").strip():
        score += 1
    return score


def _category_set(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, list):
        return {str(x).strip() for x in value if str(x).strip()}
    return {str(value).strip()}


def _diff_cats(diff: list[str]) -> set[str]:
    cats: set[str] = set()
    for item in diff or []:
        t = str(item or "").strip().lower()
        if not t:
            continue
        if any(k in t for k in ("coronary", "embol", "heart failure", "pneumonia", "asthma", "copd")):
            cats.add("cardiopulmonary")
        if any(k in t for k in ("stroke", "intracranial", "hypogly", "aphasia")):
            cats.add("neurologic")
    return cats


def _reasoning_only_predict(diff: list[str]) -> tuple[str, set[str]]:
    cats = _diff_cats(diff)
    tier = "routine"
    for item in diff or []:
        t = str(item or "").strip().lower()
        if "intracranial hemorrhage" in t:
            tier = "critical"
            break
    if tier == "routine" and cats:
        tier = "urgent"
    return tier, cats


def _trace_output(result: Any, agent: str) -> dict[str, Any]:
    for step in list(getattr(result, "trace", []) or []):
        if getattr(step, "agent", "") != agent:
            continue
        out = getattr(step, "output", None)
        if isinstance(out, dict):
            return dict(out)
    return {}


def run_ablation_rows(rows: list[dict[str, Any]], *, set_name: str) -> tuple[AblationSummary, list[dict[str, Any]]]:
    pipeline = ClinicaFlowPipeline()
    structuring = IntakeStructuringAgent()
    reasoning_agent = MultimodalClinicalReasoningAgent()
    safety_agent = SafetyEscalationAgent()

    variants = ["baseline", "reasoning_only", "safety_only", "full"]
    agg: dict[str, dict[str, Any]] = {
        v: {
            "gold_has_flags": 0,
            "flag_hit": 0,
            "gold_urgent_critical": 0,
            "under": 0,
            "gold_routine": 0,
            "over": 0,
            "actions": [],
            "citations": [],
            "completeness": [],
        }
        for v in variants
    }

    per_case: list[dict[str, Any]] = []

    for row in rows:
        case_id = str(row.get("id") or "").strip()
        case_input = dict(row.get("input") or {})
        labels = dict(row.get("labels") or {})
        gold_tier = str(labels.get("gold_risk_tier") or "").strip().lower()
        gold_cats = _category_set(labels.get("gold_red_flag_categories"))

        intake = PatientIntake.from_mapping(case_input)

        structured_payload = structuring.run(intake)
        structured = StructuredIntake(**structured_payload)

        # -----------------
        # Variant: baseline
        # -----------------
        baseline_tier, baseline_cats = baseline_predict(case_input)
        baseline_red_flags = sorted(baseline_cats)
        baseline_diff: list[str] = []
        baseline_actions: list[str] = []
        baseline_summary = ""
        baseline_citations: list[dict[str, Any]] = []

        # -----------------------
        # Variant: reasoning_only
        # -----------------------
        reasoning_payload = reasoning_agent.run(structured, intake.vitals, image_data_urls=intake.image_data_urls)
        diff = [str(x).strip() for x in (reasoning_payload.get("differential_considerations") or []) if str(x).strip()]
        ro_tier, ro_cats = _reasoning_only_predict(diff)
        ro_red_flags = sorted(ro_cats)
        ro_actions: list[str] = []
        ro_summary = ""
        ro_citations: list[dict[str, Any]] = []

        # --------------------
        # Variant: safety_only
        # --------------------
        safety_payload = safety_agent.run(structured, intake.vitals, [])
        so_tier = str(safety_payload.get("risk_tier") or "").strip().lower() or "routine"
        so_red_flags = [str(x).strip() for x in (safety_payload.get("red_flags") or []) if str(x).strip()]
        so_cats = categories_from_red_flags(so_red_flags)
        so_diff: list[str] = []
        so_actions = [str(x).strip() for x in (safety_payload.get("recommended_next_actions") or []) if str(x).strip()]
        so_summary = ""
        so_citations: list[dict[str, Any]] = []

        # --------------
        # Variant: full
        # --------------
        full = pipeline.run(intake)
        full_tier = str(getattr(full, "risk_tier", "") or "").strip().lower() or "routine"
        full_red_flags = [str(x).strip() for x in (getattr(full, "red_flags", []) or []) if str(x).strip()]
        full_cats = categories_from_red_flags(full_red_flags)
        full_diff = [str(x).strip() for x in (getattr(full, "differential_considerations", []) or []) if str(x).strip()]
        full_actions = [str(x).strip() for x in (getattr(full, "recommended_next_actions", []) or []) if str(x).strip()]
        full_summary = str(getattr(full, "patient_summary", "") or "").strip()
        evidence_out = _trace_output(full, "evidence_policy")
        full_citations_raw = evidence_out.get("protocol_citations") or []
        full_citations = full_citations_raw if isinstance(full_citations_raw, list) else []

        outputs = {
            "baseline": {
                "tier": baseline_tier,
                "cats": set(baseline_cats),
                "red_flags": baseline_red_flags,
                "differential": baseline_diff,
                "actions": baseline_actions,
                "patient_summary": baseline_summary,
                "citations": baseline_citations,
            },
            "reasoning_only": {
                "tier": ro_tier,
                "cats": set(ro_cats),
                "red_flags": ro_red_flags,
                "differential": diff,
                "actions": ro_actions,
                "patient_summary": ro_summary,
                "citations": ro_citations,
            },
            "safety_only": {
                "tier": so_tier,
                "cats": set(so_cats),
                "red_flags": so_red_flags,
                "differential": so_diff,
                "actions": so_actions,
                "patient_summary": so_summary,
                "citations": so_citations,
            },
            "full": {
                "tier": full_tier,
                "cats": set(full_cats),
                "red_flags": full_red_flags,
                "differential": full_diff,
                "actions": full_actions,
                "patient_summary": full_summary,
                "citations": full_citations,
            },
        }

        for variant, out in outputs.items():
            pred_tier = str(out["tier"] or "").strip().lower()
            pred_cats = set(out["cats"] or set())

            # Red-flag recall (category-level).
            if gold_cats:
                agg[variant]["gold_has_flags"] += 1
                agg[variant]["flag_hit"] += int(bool(pred_cats & gold_cats))

            # Under-triage.
            if gold_tier in {"urgent", "critical"}:
                agg[variant]["gold_urgent_critical"] += 1
                agg[variant]["under"] += int(pred_tier == "routine")

            # Over-triage.
            if gold_tier == "routine":
                agg[variant]["gold_routine"] += 1
                agg[variant]["over"] += int(pred_tier != "routine")

            agg[variant]["actions"].append(len(out["actions"] or []))
            agg[variant]["citations"].append(len(out["citations"] or []))
            agg[variant]["completeness"].append(
                completeness_score(
                    risk_tier=pred_tier,
                    red_flags=list(out["red_flags"] or []),
                    differential=list(out["differential"] or []),
                    actions=list(out["actions"] or []),
                    patient_summary=str(out["patient_summary"] or ""),
                )
            )

        per_case.append(
            {
                "id": case_id,
                "gold": {"risk_tier": gold_tier, "categories": sorted(gold_cats)},
                "baseline": {"risk_tier": baseline_tier, "categories": sorted(baseline_cats)},
                "reasoning_only": {"risk_tier": ro_tier, "categories": sorted(ro_cats), "differential": diff},
                "safety_only": {"risk_tier": so_tier, "categories": sorted(so_cats), "actions": so_actions},
                "full": {
                    "risk_tier": full_tier,
                    "categories": sorted(full_cats),
                    "actions": full_actions,
                    "citations": len(full_citations),
                    "completeness": completeness_score(
                        risk_tier=full_tier,
                        red_flags=full_red_flags,
                        differential=full_diff,
                        actions=full_actions,
                        patient_summary=full_summary,
                    ),
                },
            }
        )

    def safe_pct(n: int, d: int) -> float:
        return round(100.0 * n / max(1, d), 1)

    variant_summaries: list[AblationVariantSummary] = []
    for variant in variants:
        meta = agg[variant]
        avg_actions = float(statistics.mean(meta["actions"])) if meta["actions"] else 0.0
        avg_citations = float(statistics.mean(meta["citations"])) if meta["citations"] else 0.0
        avg_comp = float(statistics.mean(meta["completeness"])) if meta["completeness"] else 0.0
        variant_summaries.append(
            AblationVariantSummary(
                variant=variant,
                n_cases=len(rows),
                red_flag_recall=safe_pct(int(meta["flag_hit"]), int(meta["gold_has_flags"])),
                under_triage_rate=safe_pct(int(meta["under"]), int(meta["gold_urgent_critical"])),
                over_triage_rate=safe_pct(int(meta["over"]), int(meta["gold_routine"])),
                avg_actions=round(avg_actions, 2),
                avg_citations=round(avg_citations, 2),
                avg_completeness=round(avg_comp, 2),
            )
        )

    summary = AblationSummary(set_name=set_name, n_cases=len(rows), variants=variant_summaries)
    return summary, per_case


def main() -> None:
    args = build_parser().parse_args()
    rows: list[dict[str, Any]] = []
    for p in load_default_vignette_paths(args.set):
        rows.extend(load_vignettes(p))

    summary, per_case = run_ablation_rows(rows, set_name=args.set)

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


if __name__ == "__main__":
    main()
