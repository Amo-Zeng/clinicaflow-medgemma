from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline
from clinicaflow.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ClinicaFlow triage pipeline on a JSON intake file.")
    parser.add_argument("--input", required=True, help="Path to intake JSON file")
    parser.add_argument("--output", help="Optional output JSON path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--request-id", help="Optional request ID for trace correlation")
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"validate", "check"}:
        validate_parser = argparse.ArgumentParser(description="Validate packaged ClinicaFlow resources (policy pack, vignettes).")
        validate_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
        args = validate_parser.parse_args(sys.argv[2:])

        from clinicaflow.validators import validate_all

        report = validate_all().to_dict()
        print(json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=False))
        raise SystemExit(0 if report.get("ok") else 2)

    if len(sys.argv) > 1 and sys.argv[1] in {"serve", "server"}:
        serve_parser = argparse.ArgumentParser(description="Run ClinicaFlow demo HTTP server.")
        serve_parser.add_argument("--host", default="0.0.0.0")
        serve_parser.add_argument("--port", type=int, default=8000)
        args = serve_parser.parse_args(sys.argv[2:])
        from clinicaflow.demo_server import run

        run(host=args.host, port=args.port)
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"fhir", "fhir_bundle", "fhir-bundle"}:
        fhir_parser = argparse.ArgumentParser(description="Export a minimal FHIR Bundle for a triage run (demo).")
        fhir_parser.add_argument("--input", required=True, help="Path to intake JSON file")
        fhir_parser.add_argument("--output", help="Optional output JSON path")
        fhir_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
        fhir_parser.add_argument("--request-id", help="Optional request ID for trace correlation")
        fhir_parser.add_argument("--redact", action="store_true", help="Redact demographics/notes in export")
        args = fhir_parser.parse_args(sys.argv[2:])

        input_path = Path(args.input)
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        intake = PatientIntake.from_mapping(payload)

        result = ClinicaFlowPipeline().run(intake, request_id=args.request_id)

        from clinicaflow.fhir_export import build_fhir_bundle

        bundle = build_fhir_bundle(intake=intake, result=result, redact=args.redact)

        out_json = json.dumps(bundle, indent=2 if args.pretty else None, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(out_json, encoding="utf-8")
        else:
            print(out_json)
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"doctor", "diag"}:
        from clinicaflow.diagnostics import collect_diagnostics

        print(json.dumps(collect_diagnostics(), indent=2, ensure_ascii=False))
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"audit", "bundle"}:
        audit_parser = argparse.ArgumentParser(description="Write an audit bundle for a triage run.")
        audit_parser.add_argument("--input", required=True, help="Path to intake JSON file")
        audit_parser.add_argument("--out-dir", required=True, help="Output directory for the audit bundle")
        audit_parser.add_argument("--request-id", help="Optional request ID for trace correlation")
        audit_parser.add_argument("--redact", action="store_true", help="Redact demographics/notes/image descriptions")
        args = audit_parser.parse_args(sys.argv[2:])

        input_path = Path(args.input)
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        intake = PatientIntake.from_mapping(payload)

        result = ClinicaFlowPipeline().run(intake, request_id=args.request_id)

        from clinicaflow.audit import write_audit_bundle

        out_path = write_audit_bundle(out_dir=args.out_dir, intake=intake, result=result, redact=args.redact)
        print(
            json.dumps(
                {"out_dir": str(out_path), "run_id": result.run_id, "request_id": result.request_id},
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"benchmark", "bench"}:
        explicit_sub = len(sys.argv) > 2 and not sys.argv[2].startswith("-")
        sub = sys.argv[2] if explicit_sub else ""

        if explicit_sub and sub in {"synthetic", "proxy"}:
            from clinicaflow.benchmarks.synthetic import main as bench_main

            argv = sys.argv[3:]
            module = "clinicaflow.benchmarks.synthetic"
        elif explicit_sub and sub in {"vignettes", "vignette"}:
            from clinicaflow.benchmarks.vignettes import main as bench_main

            argv = sys.argv[3:]
            module = "clinicaflow.benchmarks.vignettes"
        elif explicit_sub and sub in {"governance", "gate"}:
            from clinicaflow.benchmarks.governance import main as bench_main

            argv = sys.argv[3:]
            module = "clinicaflow.benchmarks.governance"
        elif explicit_sub and sub in {"review_packet", "review-packet", "review"}:
            from clinicaflow.benchmarks.review_packet import main as bench_main

            argv = sys.argv[3:]
            module = "clinicaflow.benchmarks.review_packet"
        elif explicit_sub and sub in {"review_summary", "review-summary", "review_sum", "review-sum"}:
            from clinicaflow.benchmarks.review_summary import main as bench_main

            argv = sys.argv[3:]
            module = "clinicaflow.benchmarks.review_summary"
        elif explicit_sub:
            raise SystemExit(
                f"Unknown benchmark subcommand: {sub} (expected: synthetic|vignettes|governance|review_packet|review_summary)"
            )
        else:
            from clinicaflow.benchmarks.synthetic import main as bench_main

            argv = sys.argv[2:]
            module = "clinicaflow.benchmarks.synthetic"

        original_argv = sys.argv
        try:
            sys.argv = [module, *argv]
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
