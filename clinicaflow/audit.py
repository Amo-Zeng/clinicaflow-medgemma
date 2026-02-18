from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinicaflow.diagnostics import collect_diagnostics
from clinicaflow.models import PatientIntake, TriageResult


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def build_audit_bundle_files(
    *,
    intake: PatientIntake,
    result: TriageResult,
    redact: bool = False,
) -> dict[str, bytes]:
    """Build an audit bundle as in-memory files.

    Useful for UI download flows. The on-disk `write_audit_bundle()` is implemented
    in terms of this function to keep outputs consistent.
    """

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    intake_payload = asdict(intake)
    if redact:
        intake_payload["demographics"] = {}
        intake_payload["prior_notes"] = []
        intake_payload["image_descriptions"] = []

    intake_bytes = _json_bytes(intake_payload)
    result_bytes = _json_bytes(result.to_dict())
    diagnostics_bytes = _json_bytes(collect_diagnostics())

    file_hashes = {
        "intake.json": hashlib.sha256(intake_bytes).hexdigest(),
        "triage_result.json": hashlib.sha256(result_bytes).hexdigest(),
        "doctor.json": hashlib.sha256(diagnostics_bytes).hexdigest(),
    }

    manifest = {
        "created_at": created_at,
        "run_id": result.run_id,
        "request_id": result.request_id,
        "pipeline_version": result.pipeline_version,
        "redacted": redact,
        "file_hashes_sha256": file_hashes,
        "policy_pack_sha256": _extract_policy_pack_sha256(result.to_dict()),
    }
    manifest_bytes = _json_bytes(manifest)

    return {
        "intake.json": intake_bytes,
        "triage_result.json": result_bytes,
        "doctor.json": diagnostics_bytes,
        "manifest.json": manifest_bytes,
    }


def write_audit_bundle(
    *,
    out_dir: str | Path,
    intake: PatientIntake,
    result: TriageResult,
    redact: bool = False,
) -> Path:
    """Write an auditable bundle for QA/compliance reviews.

    WARNING: This may contain sensitive patient information depending on inputs.
    Store securely and follow site policy.
    """

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    files = build_audit_bundle_files(intake=intake, result=result, redact=redact)
    for name, data in files.items():
        (out_path / name).write_bytes(data)

    return out_path


def _write_json(path: Path, payload: Any) -> str:
    data = _json_bytes(payload)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _extract_policy_pack_sha256(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "evidence_policy":
                output = step.get("output") or {}
                value = output.get("policy_pack_sha256")
                return str(value or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""
