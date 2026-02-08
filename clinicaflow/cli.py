from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ClinicaFlow triage pipeline on a JSON intake file.")
    parser.add_argument("--input", required=True, help="Path to intake JSON file")
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--request-id", help="Optional request ID for trace correlation")
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"serve", "server"}:
        serve_parser = argparse.ArgumentParser(description="Run ClinicaFlow demo HTTP server.")
        serve_parser.add_argument("--host", default="0.0.0.0")
        serve_parser.add_argument("--port", type=int, default=8000)
        args = serve_parser.parse_args(sys.argv[2:])
        from clinicaflow.demo_server import run

        run(host=args.host, port=args.port)
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"benchmark", "bench"}:
        from clinicaflow.benchmarks.synthetic import main as bench_main

        original_argv = sys.argv
        try:
            sys.argv = ["clinicaflow.benchmarks.synthetic", *sys.argv[2:]]
            bench_main()
        finally:
            sys.argv = original_argv
        return

    triage_argv = sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1] == "triage" else sys.argv[1:]
    args = build_parser().parse_args(triage_argv)

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    intake = PatientIntake.from_mapping(payload)
    result = ClinicaFlowPipeline().run(intake, request_id=args.request_id)
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
