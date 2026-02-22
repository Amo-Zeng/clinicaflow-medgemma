from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from clinicaflow.benchmarks.vignettes import load_default_vignette_paths, load_vignettes
from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a clinician review packet from the vignette set.")
    parser.add_argument("--out", type=Path, required=True, help="Output markdown path")
    parser.add_argument("--path", type=Path, help="Optional vignettes JSONL path (default: packaged resource)")
    parser.add_argument(
        "--set",
        choices=["standard", "adversarial", "extended", "all", "mega"],
        default="standard",
        help=(
            "Which packaged vignette set to use when --path is not provided (default: standard). "
            "`all` = standard + adversarial; `mega` = standard + adversarial + extended."
        ),
    )
    parser.add_argument("--limit", type=int, default=30, help="Limit number of cases (default: 30)")
    parser.add_argument("--include-gold", action="store_true", help="Include gold labels in the packet")
    return parser


def build_review_packet_markdown(
    *,
    rows: list[dict[str, Any]],
    set_name: str,
    include_gold: bool,
    pipeline: ClinicaFlowPipeline,
) -> str:
    rows = rows or []
    lines: list[str] = []
    lines.append("# ClinicaFlow — Clinician Review Packet (No PHI)")
    lines.append("")
    lines.append(
        "This packet is generated from a **synthetic** vignette regression set (not real patients). "
        "Please do not add any real patient identifiers when providing feedback."
    )
    lines.append("")
    lines.append(f"- Vignette set: `{set_name}`")
    lines.append(f"- Cases included: `{len(rows)}`")
    lines.append("")
    lines.append("## Quick questions (fill in)")
    lines.append("")
    lines.append("- Reviewer role / specialty (optional):")
    lines.append("- Practice setting (optional):")
    lines.append("- Date:")
    lines.append("")
    lines.append("## Cases")
    lines.append("")

    for row in rows:
        case_id = str(row.get("id", "")).strip()
        case_input = dict(row.get("input") or {})
        labels = dict(row.get("labels") or {})

        intake = PatientIntake.from_mapping(case_input)
        req_id = f"review-{case_id}" if case_id else None
        result = pipeline.run(intake, request_id=req_id)

        lines.append(f"### {case_id}")
        lines.append("")
        lines.append("**Intake (synthetic):**")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(case_input, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
        if include_gold:
            lines.append("**Gold label (for regression):**")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(labels, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

        lines.append("**ClinicaFlow output (key fields):**")
        lines.append("")
        preview = {
            "risk_tier": result.risk_tier,
            "escalation_required": result.escalation_required,
            "red_flags": result.red_flags,
            "recommended_next_actions": result.recommended_next_actions,
            "clinician_handoff": result.clinician_handoff,
            "confidence": result.confidence,
            "uncertainty_reasons": result.uncertainty_reasons,
        }
        lines.append("```json")
        lines.append(json.dumps(preview, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
        lines.append("**Reviewer feedback (free text):**")
        lines.append("")
        lines.append("- Is the risk tier appropriate? If not, what would you choose and why?")
        lines.append("- Any missing red flags or unsafe next actions?")
        lines.append("- Any wording that could confuse patients/clinicians?")
        lines.append("")
        lines.append("----")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = build_parser().parse_args()
    if args.path:
        rows = load_vignettes(args.path)
        set_name = "custom"
    else:
        set_name = args.set
        rows: list[dict[str, Any]] = []
        for p in load_default_vignette_paths(args.set):
            rows.extend(load_vignettes(p))
    rows = rows[: max(0, args.limit)]

    pipeline = ClinicaFlowPipeline()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    md = build_review_packet_markdown(
        rows=rows,
        set_name=set_name,
        include_gold=bool(args.include_gold),
        pipeline=pipeline,
    )
    args.out.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
