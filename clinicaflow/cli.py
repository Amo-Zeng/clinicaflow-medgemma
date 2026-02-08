from __future__ import annotations

import argparse
import json
from pathlib import Path

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ClinicaFlow triage pipeline on a JSON intake file.")
    parser.add_argument("--input", required=True, help="Path to intake JSON file")
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    intake = PatientIntake.from_mapping(payload)
    result = ClinicaFlowPipeline().run(intake)
    result_dict = result.to_dict()

    if args.output:
        Path(args.output).write_text(
            json.dumps(result_dict, indent=2 if args.pretty else None, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        print(json.dumps(result_dict, indent=2 if args.pretty else None, ensure_ascii=False))


if __name__ == "__main__":
    main()
