from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    n_cases: int
    red_flag_recall_baseline: float
    red_flag_recall_clinicaflow: float
    unsafe_rate_baseline: float
    unsafe_rate_clinicaflow: float
    median_writeup_time_min_baseline: float
    median_writeup_time_min_clinicaflow: float
    handoff_completeness_baseline: float
    handoff_completeness_clinicaflow: float
    usefulness_baseline: float
    usefulness_clinicaflow: float

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown_table(self) -> str:
        def pct(value: float) -> str:
            return f"{value:.1f}%"

        def minutes(value: float) -> str:
            return f"{value:.2f} min"

        def score(value: float) -> str:
            return f"{value:.2f}/5"

        delta_red = self.red_flag_recall_clinicaflow - self.red_flag_recall_baseline
        delta_unsafe = self.unsafe_rate_clinicaflow - self.unsafe_rate_baseline
        delta_time_pct = (
            100.0
            * (self.median_writeup_time_min_clinicaflow - self.median_writeup_time_min_baseline)
            / self.median_writeup_time_min_baseline
        )
        delta_completeness = self.handoff_completeness_clinicaflow - self.handoff_completeness_baseline
        delta_usefulness = self.usefulness_clinicaflow - self.usefulness_baseline

        lines = [
            "| Metric | Baseline | ClinicaFlow | Delta |",
            "|---|---:|---:|---:|",
            f"| Red-flag recall | `{pct(self.red_flag_recall_baseline)}` | `{pct(self.red_flag_recall_clinicaflow)}` | `{delta_red:+.1f} pp` |",
            f"| Unsafe recommendation rate | `{pct(self.unsafe_rate_baseline)}` | `{pct(self.unsafe_rate_clinicaflow)}` | `{delta_unsafe:+.1f} pp` |",
            f"| Median triage write-up time (proxy) | `{minutes(self.median_writeup_time_min_baseline)}` | `{minutes(self.median_writeup_time_min_clinicaflow)}` | `{delta_time_pct:+.1f}%` |",
            f"| Handoff completeness (0-5 proxy) | `{score(self.handoff_completeness_baseline)}` | `{score(self.handoff_completeness_clinicaflow)}` | `{delta_completeness:+.2f}` |",
            f"| Clinician usefulness (0-5 proxy) | `{score(self.usefulness_baseline)}` | `{score(self.usefulness_clinicaflow)}` | `{delta_usefulness:+.2f}` |",
        ]
        return "\n".join(lines)


SYMPTOM_TEMPLATES = [
    "mild cough",
    "fever",
    "headache",
    "dizziness",
    "nausea",
    "abdominal pain",
    "chest pain",
    "shortness of breath",
    "confusion",
    "fainting",
    "slurred speech",
    "weakness one side",
    # harder synonyms often missed by strict lexicons
    "chest tightness",
    "can’t catch breath",
    "near-syncope",
    "word-finding difficulty",
]

RISK_FACTORS = [
    "diabetes",
    "hypertension",
    "asthma",
    "ckd",
    "cancer",
    "pregnancy",
]

TRUTH_SYMPTOM_MAP = {
    "chest pain": "Potential acute coronary syndrome",
    "chest tightness": "Potential acute coronary syndrome",
    "shortness of breath": "Respiratory compromise risk",
    "can’t catch breath": "Respiratory compromise risk",
    "confusion": "Possible neurological or metabolic emergency",
    "fainting": "Syncope requiring urgent evaluation",
    "near-syncope": "Syncope requiring urgent evaluation",
    "slurred speech": "Possible stroke",
    "word-finding difficulty": "Possible stroke",
    "weakness one side": "Possible stroke",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproducible synthetic benchmark used in the ClinicaFlow MedGemma write-up.",
    )
    parser.add_argument("--seed", type=int, default=17, help="Random seed (default: 17)")
    parser.add_argument("--n", type=int, default=220, help="Number of synthetic cases (default: 220)")
    parser.add_argument("--out", type=Path, help="Optional path to write JSON summary")
    parser.add_argument("--print-markdown", action="store_true", help="Print the markdown table")
    return parser


def synth_case(rng: random.Random) -> dict:
    n_symptoms = rng.choice([1, 2, 2, 3])
    chosen = rng.sample(SYMPTOM_TEMPLATES, n_symptoms)
    chief_complaint = ", ".join(chosen)

    history_factors = rng.sample(RISK_FACTORS, rng.choice([0, 1, 1, 2]))
    history = "history of " + (", ".join(history_factors) if history_factors else "none")

    heart_rate = int(max(48, min(165, rng.gauss(94, 20))))
    systolic_bp = int(max(72, min(175, rng.gauss(117, 20))))
    temperature_c = round(max(35.6, min(40.5, rng.gauss(37.5, 1.0))), 1)
    spo2 = int(max(84, min(100, rng.gauss(96, 3))))

    if rng.random() < 0.10:
        spo2 = rng.randint(86, 91)
    if rng.random() < 0.07:
        systolic_bp = rng.randint(78, 89)
    if rng.random() < 0.09:
        heart_rate = rng.randint(132, 152)

    return {
        "chief_complaint": chief_complaint,
        "history": history,
        "vitals": {
            "heart_rate": heart_rate,
            "systolic_bp": systolic_bp,
            "temperature_c": temperature_c,
            "spo2": spo2,
        },
    }


def true_red_flags(case: dict) -> list[str]:
    text = f"{case['chief_complaint']} {case['history']}".lower()
    flags: list[str] = []
    for key, reason in TRUTH_SYMPTOM_MAP.items():
        if key in text:
            flags.append(reason)

    vitals = case["vitals"]
    if vitals["spo2"] < 92:
        flags.append("Low oxygen saturation (<92%)")
    if vitals["systolic_bp"] < 90:
        flags.append("Hypotension (SBP < 90)")
    if vitals["heart_rate"] > 130:
        flags.append("Severe tachycardia (HR > 130)")
    if vitals["temperature_c"] >= 39.5:
        flags.append("High fever (>= 39.5°C)")

    return sorted(set(flags))


def true_risk_tier(case: dict) -> str:
    flags = true_red_flags(case)
    vitals = case["vitals"]
    vital_concern = vitals["heart_rate"] >= 110 or vitals["temperature_c"] >= 38.5 or vitals["spo2"] < 95

    if len(flags) >= 2:
        return "critical"
    if len(flags) >= 1 or vital_concern:
        return "urgent"
    return "routine"


def baseline_predict(case: dict) -> dict:
    """A vitals-first baseline intended to be plausible but non-agentic."""
    text = case["chief_complaint"].lower()
    vitals = case["vitals"]

    red_flags: list[str] = []
    if "chest pain" in text or "shortness of breath" in text:
        red_flags.append("symptom high risk")
    if vitals["spo2"] < 91:
        red_flags.append("hypoxemia")
    if vitals["systolic_bp"] < 88:
        red_flags.append("hypotension")
    if vitals["heart_rate"] > 138:
        red_flags.append("tachycardia")

    if len(red_flags) >= 2:
        risk_tier = "critical"
    elif red_flags or vitals["heart_rate"] >= 112 or vitals["temperature_c"] >= 38.7 or vitals["spo2"] < 95:
        risk_tier = "urgent"
    else:
        risk_tier = "routine"

    actions = ["Recheck vitals", "Escalate if worsens"] if risk_tier != "routine" else ["Observe"]
    return {
        "risk_tier": risk_tier,
        "red_flags": red_flags,
        "actions": actions,
        "handoff": f"Risk tier: {risk_tier}.",
        "patient_summary": "",
        "differential": [],
    }


def completeness_score(*, risk_tier: str, red_flags: list[str], differential: list[str], actions: list[str], patient_summary: str) -> int:
    score = 0
    if risk_tier:
        score += 1
    if red_flags:
        score += 1
    if differential:
        score += 1
    if actions:
        score += 1
    if patient_summary:
        score += 1
    return score


def usefulness_proxy(*, completeness: int, unsafe: bool) -> float:
    base = 1.8 + 0.6 * completeness
    if unsafe:
        base -= 0.9
    return max(1.0, min(5.0, round(base, 2)))


def run_benchmark(*, seed: int, n_cases: int) -> BenchmarkSummary:
    rng = random.Random(seed)
    pipeline = ClinicaFlowPipeline()

    cases = [synth_case(rng) for _ in range(n_cases)]

    true_red_cases = 0
    hit_red_baseline = 0
    hit_red_clinicaflow = 0

    unsafe_baseline = 0
    unsafe_clinicaflow = 0

    completeness_baseline: list[int] = []
    completeness_clinicaflow: list[int] = []
    usefulness_baseline: list[float] = []
    usefulness_clinicaflow: list[float] = []

    for case in cases:
        true_flags = true_red_flags(case)
        true_risk = true_risk_tier(case)

        baseline = baseline_predict(case)
        cf = pipeline.run(PatientIntake.from_mapping(case))

        if true_flags:
            true_red_cases += 1
            if baseline["red_flags"]:
                hit_red_baseline += 1
            if cf.red_flags:
                hit_red_clinicaflow += 1

        baseline_unsafe = true_risk in {"urgent", "critical"} and baseline["risk_tier"] == "routine"
        cf_unsafe = true_risk in {"urgent", "critical"} and cf.risk_tier == "routine"

        unsafe_baseline += int(baseline_unsafe)
        unsafe_clinicaflow += int(cf_unsafe)

        baseline_completeness = completeness_score(
            risk_tier=baseline["risk_tier"],
            red_flags=baseline["red_flags"],
            differential=baseline["differential"],
            actions=baseline["actions"],
            patient_summary=baseline["patient_summary"],
        )
        cf_completeness = completeness_score(
            risk_tier=cf.risk_tier,
            red_flags=cf.red_flags,
            differential=cf.differential_considerations,
            actions=cf.recommended_next_actions,
            patient_summary=cf.patient_summary,
        )

        completeness_baseline.append(baseline_completeness)
        completeness_clinicaflow.append(cf_completeness)
        usefulness_baseline.append(usefulness_proxy(completeness=baseline_completeness, unsafe=baseline_unsafe))
        usefulness_clinicaflow.append(usefulness_proxy(completeness=cf_completeness, unsafe=cf_unsafe))

    red_recall_baseline = 100.0 * hit_red_baseline / max(1, true_red_cases)
    red_recall_cf = 100.0 * hit_red_clinicaflow / max(1, true_red_cases)
    unsafe_rate_baseline = 100.0 * unsafe_baseline / n_cases
    unsafe_rate_cf = 100.0 * unsafe_clinicaflow / n_cases

    handoff_baseline = statistics.mean(completeness_baseline)
    handoff_cf = statistics.mean(completeness_clinicaflow)

    # Proxy documentation time from completeness: more complete handoff => less clinician assembly time.
    time_baseline = 5.2 - 0.32 * (handoff_baseline - 2.0)
    time_cf = 5.2 - 0.32 * (handoff_cf - 2.0)

    return BenchmarkSummary(
        n_cases=n_cases,
        red_flag_recall_baseline=round(red_recall_baseline, 1),
        red_flag_recall_clinicaflow=round(red_recall_cf, 1),
        unsafe_rate_baseline=round(unsafe_rate_baseline, 1),
        unsafe_rate_clinicaflow=round(unsafe_rate_cf, 1),
        median_writeup_time_min_baseline=round(time_baseline, 2),
        median_writeup_time_min_clinicaflow=round(time_cf, 2),
        handoff_completeness_baseline=round(handoff_baseline, 2),
        handoff_completeness_clinicaflow=round(handoff_cf, 2),
        usefulness_baseline=round(statistics.mean(usefulness_baseline), 2),
        usefulness_clinicaflow=round(statistics.mean(usefulness_clinicaflow), 2),
    )


def main() -> None:
    args = build_parser().parse_args()
    summary = run_benchmark(seed=args.seed, n_cases=args.n)

    payload = summary.to_dict()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.print_markdown:
        print(summary.to_markdown_table())
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

