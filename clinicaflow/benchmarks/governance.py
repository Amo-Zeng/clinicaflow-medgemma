from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinicaflow.benchmarks.vignettes import (
    VignetteBenchmarkSummary,
    load_default_vignette_paths,
    load_vignettes,
    run_benchmark_rows,
)


@dataclass(frozen=True, slots=True)
class GovernanceGate:
    ok: bool
    under_triage_rate: float
    over_triage_rate: float
    red_flag_recall: float
    min_red_flag_recall: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GovernanceProvenance:
    total_actions: int
    safety_actions: int
    policy_actions: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TriggerCoverage:
    id: str
    label: str
    severity: str
    n_cases: int
    sample_cases: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_gate(summary: VignetteBenchmarkSummary, *, min_red_flag_recall: float) -> GovernanceGate:
    under = float(summary.under_triage_rate_clinicaflow)
    over = float(summary.over_triage_rate_clinicaflow)
    recall = float(summary.red_flag_recall_clinicaflow)
    ok = under == 0.0 and recall >= float(min_red_flag_recall)
    return GovernanceGate(
        ok=ok,
        under_triage_rate=under,
        over_triage_rate=over,
        red_flag_recall=recall,
        min_red_flag_recall=float(min_red_flag_recall),
    )


def compute_action_provenance(per_case: list[dict[str, Any]]) -> GovernanceProvenance:
    total = 0
    safety = 0
    policy = 0

    for row in per_case or []:
        cf = dict(row.get("clinicaflow") or {})
        prov = cf.get("action_provenance")
        if isinstance(prov, list) and prov:
            for item in prov:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("source") or "").strip().upper()
                if src not in {"SAFETY", "POLICY"}:
                    continue
                total += 1
                if src == "SAFETY":
                    safety += 1
                else:
                    policy += 1
            continue

        # Fallback for older payloads: compare safety action list to recommended actions.
        rec_actions = cf.get("recommended_next_actions") or []
        safety_actions = cf.get("actions_added_by_safety") or []
        if not isinstance(rec_actions, list) or not rec_actions:
            continue

        safety_set = {str(x).strip() for x in safety_actions if str(x).strip()} if isinstance(safety_actions, list) else set()
        for action in rec_actions:
            text = str(action).strip()
            if not text:
                continue
            total += 1
            if text in safety_set:
                safety += 1
            else:
                policy += 1

    return GovernanceProvenance(total_actions=total, safety_actions=safety, policy_actions=policy)


def compute_trigger_coverage(per_case: list[dict[str, Any]], *, top_k: int = 20) -> list[TriggerCoverage]:
    index: dict[str, TriggerCoverage] = {}
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    for row in per_case or []:
        case_id = str(row.get("id") or "").strip()
        cf = dict(row.get("clinicaflow") or {})
        triggers = cf.get("safety_triggers") or []
        if not isinstance(triggers, list) or not triggers:
            continue

        seen: set[str] = set()
        for trig in triggers:
            if not isinstance(trig, dict):
                continue
            trig_id = str(trig.get("id") or trig.get("label") or "").strip()
            if not trig_id or trig_id in seen:
                continue
            seen.add(trig_id)

            counts[trig_id] = counts.get(trig_id, 0) + 1
            if case_id and len(samples.get(trig_id, [])) < 3:
                samples.setdefault(trig_id, []).append(case_id)

            if trig_id not in index:
                index[trig_id] = TriggerCoverage(
                    id=trig_id,
                    label=str(trig.get("label") or trig_id).strip() or trig_id,
                    severity=str(trig.get("severity") or "info").strip().lower() or "info",
                    n_cases=0,
                    sample_cases=[],
                )

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[TriggerCoverage] = []
    for trig_id, n_cases in ranked[: max(0, int(top_k))]:
        base = index.get(trig_id)
        if not base:
            continue
        out.append(
            TriggerCoverage(
                id=base.id,
                label=base.label,
                severity=base.severity,
                n_cases=int(n_cases),
                sample_cases=samples.get(trig_id, []),
            )
        )
    return out


def to_governance_markdown(
    *,
    set_name: str,
    summary: VignetteBenchmarkSummary,
    gate: GovernanceGate,
    provenance: GovernanceProvenance,
    triggers: list[TriggerCoverage],
) -> str:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def pct(v: float) -> str:
        return f"{float(v):.1f}%"

    def pct2(n: int, d: int) -> str:
        if d <= 0:
            return "—"
        return f"{(100.0 * float(n) / float(d)):.1f}%"

    lines: list[str] = []
    lines.append("# ClinicaFlow — Safety governance report (synthetic)")
    lines.append("")
    lines.append("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.")
    lines.append(f"- vignette_set: `{set_name}`")
    lines.append(f"- generated_at: `{generated_at}`")
    lines.append("")

    lines.append("## Safety gate")
    lines.append("")
    lines.append(f"- gate_status: `{'PASS' if gate.ok else 'FAIL'}`")
    lines.append(f"- under-triage (ClinicaFlow): `{pct(gate.under_triage_rate)}`")
    lines.append(f"- red-flag recall (ClinicaFlow): `{pct(gate.red_flag_recall)}` (threshold ≥ {pct(gate.min_red_flag_recall)})")
    lines.append(f"- over-triage (ClinicaFlow): `{pct(gate.over_triage_rate)}`")
    lines.append("")

    lines.append("## Benchmark summary")
    lines.append("")
    lines.append(summary.to_markdown_table())
    lines.append("")

    lines.append("## Action provenance")
    lines.append("")
    lines.append(f"- total_actions: `{provenance.total_actions}`")
    lines.append(f"- safety_actions: `{provenance.safety_actions}` ({pct2(provenance.safety_actions, provenance.total_actions)})")
    lines.append(f"- policy_actions: `{provenance.policy_actions}` ({pct2(provenance.policy_actions, provenance.total_actions)})")
    lines.append("")

    lines.append("## Top safety triggers (case coverage)")
    lines.append("")
    if not triggers:
        lines.append("- (no safety triggers in benchmark output)")
    else:
        lines.append("| Trigger | Severity | Cases | Samples |")
        lines.append("|---|---:|---:|---|")
        for item in triggers:
            samples = ", ".join(item.sample_cases[:3])
            lines.append(f"| `{item.label}` | `{item.severity}` | `{item.n_cases}` | `{samples}` |")
    lines.append("")

    lines.append("## Under-triage cases (should be empty)")
    lines.append("")
    if gate.under_triage_rate == 0.0:
        lines.append("- PASS — no under-triage cases detected.")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _format_safety_triggers(triggers: Any) -> list[str]:
    if not isinstance(triggers, list):
        return []
    lines: list[str] = []
    for trig in triggers:
        if not isinstance(trig, dict):
            continue
        label = str(trig.get("label") or trig.get("id") or "").strip()
        if not label:
            continue
        sev = str(trig.get("severity") or "").strip().lower() or "info"
        detail = str(trig.get("detail") or "").strip()
        tail = f" — {detail}" if detail else ""
        lines.append(f"- [{sev}] {label}{tail}")
    return lines


def _format_actions_with_provenance(cf: dict[str, Any]) -> list[str]:
    prov = cf.get("action_provenance")
    if isinstance(prov, list) and prov:
        out = []
        for item in prov:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            src = str(item.get("source") or "").strip().upper()
            if not text or src not in {"SAFETY", "POLICY"}:
                continue
            out.append(f"- [{src}] {text}")
        return out

    rec = cf.get("recommended_next_actions") or []
    safety = cf.get("actions_added_by_safety") or []
    if not isinstance(rec, list) or not rec:
        return []
    safety_set = {str(x).strip() for x in safety if str(x).strip()} if isinstance(safety, list) else set()
    out = []
    for action in rec:
        text = str(action).strip()
        if not text:
            continue
        out.append(f"- [{'SAFETY' if text in safety_set else 'POLICY'}] {text}")
    return out


def _format_workflow(cf: dict[str, Any]) -> str:
    wf = cf.get("workflow") or []
    if not isinstance(wf, list) or not wf:
        return ""
    parts: list[str] = []
    for step in wf:
        if not isinstance(step, dict):
            continue
        agent = str(step.get("agent") or "").strip()
        if not agent:
            continue
        latency = step.get("latency_ms")
        latency_str = "—"
        if isinstance(latency, (int, float)):
            latency_str = f"{float(latency):.2f}ms"
        err = str(step.get("error") or "").strip()
        mark = "(!)" if err else ""
        parts.append(f"{agent}={latency_str}{mark}")
    return " • ".join(parts)


def to_failure_packet_markdown(
    *,
    set_name: str,
    rows: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    summary: VignetteBenchmarkSummary,
    gate: GovernanceGate,
    limit: int = 25,
) -> str:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    index = {str(r.get("id") or "").strip(): r for r in rows if str(r.get("id") or "").strip()}

    def tier(row: dict[str, Any], key: str) -> str:
        return str(((row.get(key) or {}).get("risk_tier") or "")).strip().lower()

    def categories(row: dict[str, Any], key: str) -> str:
        cats = ((row.get(key) or {}).get("categories") or [])
        if isinstance(cats, list):
            return ", ".join(str(x) for x in cats if str(x).strip())
        return str(cats)

    def section(title: str, selected: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        lines.append(f"## {title}")
        lines.append("")
        if not selected:
            lines.append("- (none)")
            lines.append("")
            return lines

        for item in selected[: max(0, int(limit))]:
            case_id = str(item.get("id") or "").strip()
            gold_tier = tier(item, "gold")
            pred_tier = tier(item, "clinicaflow")
            cf = dict(item.get("clinicaflow") or {})

            lines.append(f"### {case_id}")
            lines.append("")
            lines.append(f"- gold: tier=`{gold_tier}` categories=`{categories(item, 'gold') or '(none)'}`")
            lines.append(f"- pred: tier=`{pred_tier}` categories=`{categories(item, 'clinicaflow') or '(none)'}`")

            rationale = str(cf.get("risk_tier_rationale") or "").strip()
            if rationale:
                lines.append(f"- rationale: {rationale}")

            missing = cf.get("missing_fields") or []
            if isinstance(missing, list) and missing:
                lines.append(f"- missing_fields: `{', '.join(str(x) for x in missing if str(x).strip())}`")

            policy_sha = str(cf.get("policy_pack_sha256") or "").strip()
            if policy_sha:
                lines.append(f"- policy_pack_sha256: `{policy_sha[:12]}…`")

            rules_ver = str(cf.get("safety_rules_version") or "").strip()
            if rules_ver:
                lines.append(f"- safety_rules_version: `{rules_ver}`")

            risk_scores = cf.get("risk_scores") or {}
            if isinstance(risk_scores, dict) and risk_scores:
                bits: list[str] = []
                if isinstance(risk_scores.get("shock_index"), (int, float)):
                    bits.append(
                        f"shock_index={risk_scores.get('shock_index')}{' (high)' if risk_scores.get('shock_index_high') else ''}"
                    )
                if isinstance(risk_scores.get("qsofa"), (int, float)):
                    bits.append(f"qSOFA={risk_scores.get('qsofa')}{' (≥2)' if risk_scores.get('qsofa_high_risk') else ''}")
                if bits:
                    lines.append(f"- risk_scores: `{' • '.join(bits)}`")

            lines.append("")
            trig_lines = _format_safety_triggers(cf.get("safety_triggers"))
            if trig_lines:
                lines.append("Safety triggers:")
                lines.extend(trig_lines[:10])
                if len(trig_lines) > 10:
                    lines.append(f"- … ({len(trig_lines) - 10} more)")
                lines.append("")

            action_lines = _format_actions_with_provenance(cf)
            if action_lines:
                lines.append("Recommended next actions (tagged):")
                lines.extend(action_lines[:10])
                if len(action_lines) > 10:
                    lines.append(f"- … ({len(action_lines) - 10} more)")
                lines.append("")

            wf = _format_workflow(cf)
            if wf:
                lines.append(f"- workflow: `{wf}`")
                lines.append("")

            source = index.get(case_id) or {}
            intake = source.get("input")
            labels = source.get("labels")
            if isinstance(labels, dict) and labels:
                lines.append("Gold labels:")
                lines.append("```json")
                lines.append(json.dumps(labels, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("")

            if isinstance(intake, dict) and intake:
                lines.append("Intake:")
                lines.append("```json")
                lines.append(json.dumps(intake, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("")

        if len(selected) > max(0, int(limit)):
            lines.append(f"- Note: truncated to first {int(limit)} cases.")
            lines.append("")

        return lines

    under = []
    mismatch = []
    over = []
    for row in per_case or []:
        gold_tier = tier(row, "gold")
        pred_tier = tier(row, "clinicaflow")
        if not gold_tier or not pred_tier:
            continue
        if gold_tier in {"urgent", "critical"} and pred_tier == "routine":
            under.append(row)
        if gold_tier != pred_tier:
            mismatch.append(row)
        if gold_tier == "routine" and pred_tier in {"urgent", "critical"}:
            over.append(row)

    lines: list[str] = []
    lines.append("# ClinicaFlow — Vignette failure analysis packet (synthetic)")
    lines.append("")
    lines.append("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.")
    lines.append(f"- vignette_set: `{set_name}`")
    lines.append(f"- generated_at: `{generated_at}`")
    lines.append(f"- gate_status: `{'PASS' if gate.ok else 'FAIL'}` (under-triage={gate.under_triage_rate:.1f}%, recall={gate.red_flag_recall:.1f}%)")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(summary.to_markdown_table())
    lines.append("")

    lines.extend(section("Under-triage (gold urgent/critical → predicted routine)", under))
    lines.extend(section("Tier mismatches (gold ≠ pred)", mismatch))
    lines.extend(section("Over-triage (gold routine → predicted urgent/critical)", over))

    return "\n".join(lines).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safety governance report + failure packet for ClinicaFlow vignettes benchmark.")
    parser.add_argument("--path", type=Path, help="Path to vignettes JSONL (default: packaged resource)")
    parser.add_argument(
        "--set",
        choices=["standard", "adversarial", "extended", "all", "mega"],
        default="mega",
        help="Which packaged vignette set to use when --path is not provided (default: mega).",
    )
    parser.add_argument("--out", type=Path, help="Optional markdown output path for the governance report")
    parser.add_argument("--bench-out", type=Path, help="Optional JSON output path for the raw benchmark payload (summary + per_case)")
    parser.add_argument("--failure-out", type=Path, help="Optional markdown output path for the failure packet")
    parser.add_argument("--max-failures", type=int, default=25, help="Max cases per failure section (default: 25)")
    parser.add_argument("--min-recall", type=float, default=99.9, help="Minimum acceptable red-flag recall for gate (default: 99.9)")
    parser.add_argument("--gate", action="store_true", help="Exit non-zero if safety gate fails (under-triage > 0 or recall below threshold)")
    parser.add_argument("--quiet", action="store_true", help="Do not print the governance report to stdout")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.path:
        rows = load_vignettes(args.path)
        set_name = args.path.stem
    else:
        rows = []
        for p in load_default_vignette_paths(args.set):
            rows.extend(load_vignettes(p))
        set_name = args.set

    summary, per_case = run_benchmark_rows(rows)
    gate = compute_gate(summary, min_red_flag_recall=float(args.min_recall))
    provenance = compute_action_provenance(per_case)
    triggers = compute_trigger_coverage(per_case, top_k=20)

    report_md = to_governance_markdown(
        set_name=set_name,
        summary=summary,
        gate=gate,
        provenance=provenance,
        triggers=triggers,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_md, encoding="utf-8")

    if args.bench_out:
        args.bench_out.parent.mkdir(parents=True, exist_ok=True)
        args.bench_out.write_text(
            json.dumps(
                {"set": set_name, "summary": summary.to_dict(), "gate": gate.to_dict(), "per_case": per_case},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if args.failure_out:
        md = to_failure_packet_markdown(
            set_name=set_name,
            rows=rows,
            per_case=per_case,
            summary=summary,
            gate=gate,
            limit=int(args.max_failures),
        )
        args.failure_out.parent.mkdir(parents=True, exist_ok=True)
        args.failure_out.write_text(md, encoding="utf-8")

    if not args.quiet:
        print(report_md)

    if args.gate and not gate.ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

