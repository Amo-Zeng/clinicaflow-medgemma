from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinicaflow.diagnostics import collect_diagnostics
from clinicaflow.models import PatientIntake, TriageResult


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

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    intake_payload = asdict(intake)
    if redact:
        intake_payload["demographics"] = {}
        intake_payload["prior_notes"] = []
        intake_payload["image_descriptions"] = []

    file_hashes: dict[str, str] = {}
    file_hashes["intake.json"] = _write_json(out_path / "intake.json", intake_payload)
    file_hashes["triage_result.json"] = _write_json(out_path / "triage_result.json", result.to_dict())

    diagnostics = collect_diagnostics()
    file_hashes["doctor.json"] = _write_json(out_path / "doctor.json", diagnostics)

    manifest = {
        "created_at": created_at,
        "run_id": result.run_id,
        "request_id": result.request_id,
        "pipeline_version": result.pipeline_version,
        "redacted": redact,
        "file_hashes_sha256": file_hashes,
        "policy_pack_sha256": _extract_policy_pack_sha256(result.to_dict()),
    }
    _write_json(out_path / "manifest.json", manifest)

    return out_path


def _write_json(path: Path, payload: Any) -> str:
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
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
