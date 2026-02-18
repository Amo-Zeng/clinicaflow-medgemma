from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    n_reviews: int
    n_cases: int
    safety_counts: dict[str, int]
    avg_actionability: float | None
    avg_handoff: float | None
    reviewer_roles: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("## Clinician review (qualitative; no PHI)")
        lines.append("")
        lines.append(f"- Reviews: **{self.n_reviews}** (cases: **{self.n_cases}**)")
        if self.reviewer_roles:
            lines.append(f"- Reviewer roles (as entered): {', '.join(self.reviewer_roles)}")
        if self.safety_counts:
            parts = [f"{k}={v}" for k, v in sorted(self.safety_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
            lines.append(f"- Risk-tier safety: {', '.join(parts)}")
        if self.avg_actionability is not None:
            lines.append(f"- Avg actionability: **{self.avg_actionability:.2f}/5**")
        if self.avg_handoff is not None:
            lines.append(f"- Avg handoff quality: **{self.avg_handoff:.2f}/5**")
        return "\n".join(lines).strip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize clinician review JSON exported from the demo UI.")
    parser.add_argument("--in", dest="in_path", type=Path, required=True, help="Path to clinician_reviews.json")
    parser.add_argument("--out", type=Path, help="Optional markdown output path")
    parser.add_argument("--print-markdown", action="store_true", help="Print markdown summary to stdout")
    parser.add_argument("--max-quotes", type=int, default=3, help="Max number of feedback quotes to include (default: 3)")
    return parser


def load_reviews(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array of review objects.")
    return [dict(x) for x in payload if isinstance(x, dict)]


def summarize_reviews(reviews: list[dict[str, Any]]) -> tuple[ReviewSummary, list[str]]:
    safety = Counter()
    actionability: list[float] = []
    handoff: list[float] = []
    roles: set[str] = set()
    case_ids: set[str] = set()
    quotes: list[str] = []

    for r in reviews:
        case_id = str(r.get("case_id") or "").strip()
        if case_id:
            case_ids.add(case_id)

        reviewer = dict(r.get("reviewer") or {})
        role = str(reviewer.get("role") or "").strip()
        if role:
            roles.add(role)

        ratings = dict(r.get("ratings") or {})
        safety_raw = str(ratings.get("risk_tier_safety") or "").strip().lower()
        if safety_raw:
            safety[safety_raw] += 1

        a = ratings.get("actionability")
        if isinstance(a, (int, float)):
            actionability.append(float(a))

        h = ratings.get("handoff_quality")
        if isinstance(h, (int, float)):
            handoff.append(float(h))

        notes = dict(r.get("notes") or {})
        fb = str(notes.get("feedback") or "").strip()
        if fb:
            quotes.append(fb)

    def mean_or_none(values: list[float]) -> float | None:
        return round(statistics.mean(values), 2) if values else None

    summary = ReviewSummary(
        n_reviews=len(reviews),
        n_cases=len(case_ids),
        safety_counts=dict(safety),
        avg_actionability=mean_or_none(actionability),
        avg_handoff=mean_or_none(handoff),
        reviewer_roles=sorted(roles),
    )
    return summary, quotes


def render_quotes(quotes: list[str], *, limit: int) -> str:
    q = [x for x in quotes if x][: max(0, limit)]
    if not q:
        return ""

    lines: list[str] = []
    lines.append("")
    lines.append("### Selected feedback (verbatim)")
    lines.append("")
    for item in q:
        lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = build_parser().parse_args()
    reviews = load_reviews(args.in_path)
    summary, quotes = summarize_reviews(reviews)

    md = summary.to_markdown()
    md += render_quotes(quotes, limit=args.max_quotes)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")

    if args.print_markdown or not args.out:
        print(md.strip())


if __name__ == "__main__":
    main()

