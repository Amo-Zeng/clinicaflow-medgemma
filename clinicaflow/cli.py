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
    if len(sys.argv) > 1 and sys.argv[1] in {"serve", "server"}:
        serve_parser = argparse.ArgumentParser(description="Run ClinicaFlow demo HTTP server.")
        serve_parser.add_argument("--host", default="0.0.0.0")
        serve_parser.add_argument("--port", type=int, default=8000)
        args = serve_parser.parse_args(sys.argv[2:])
        from clinicaflow.demo_server import run

        run(host=args.host, port=args.port)
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"doctor", "diag"}:
        from clinicaflow.settings import load_settings_from_env
        from clinicaflow.policy_pack import load_policy_pack, policy_pack_sha256

        settings = load_settings_from_env()

        # Resolve the policy pack source the same way the agents do.
        source_label = settings.policy_pack_path
        policy_path: object
        if settings.policy_pack_path:
            policy_path = settings.policy_pack_path
        else:
            from importlib.resources import files

            policy_path = files("clinicaflow.resources").joinpath("policy_pack.json")
            source_label = "package:clinicaflow.resources/policy_pack.json"

        # Avoid printing secrets like API keys.
        payload = {
            "version": __version__,
            "settings": {
                "debug": settings.debug,
                "log_level": settings.log_level,
                "json_logs": settings.json_logs,
                "max_request_bytes": settings.max_request_bytes,
                "policy_top_k": settings.policy_top_k,
                "cors_allow_origin": settings.cors_allow_origin,
            },
            "policy_pack": {
                "source": source_label,
                "sha256": policy_pack_sha256(policy_path),
                "n_policies": len(load_policy_pack(policy_path)),
            },
            "reasoning_backend": {
                "backend": os.environ.get("CLINICAFLOW_REASONING_BACKEND", "deterministic").strip(),
                "base_url": os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip(),
                "model": os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip(),
                "timeout_s": os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "").strip(),
                "max_retries": os.environ.get("CLINICAFLOW_REASONING_MAX_RETRIES", "").strip(),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
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
