from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clinicaflow.diagnostics import collect_diagnostics
from clinicaflow.models import PatientIntake, TriageResult


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _normalize_checklist(checklist: Any, *, fallback: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(checklist, list):
        for raw in checklist:
            if isinstance(raw, str):
                text = raw.strip()
                checked = False
            elif isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("action") or "").strip()
                checked = bool(raw.get("checked"))
            else:
                continue
            if not text:
                continue
            items.append({"text": text, "checked": checked})

    if items:
        return items

    return [{"text": str(x).strip(), "checked": False} for x in (fallback or []) if str(x).strip()]


def build_audit_bundle_files(
    *,
    intake: PatientIntake,
    result: TriageResult,
    redact: bool = False,
    checklist: list[dict[str, Any]] | list[str] | None = None,
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

    checklist_payload = _normalize_checklist(checklist, fallback=result.recommended_next_actions)
    checklist_bytes = _json_bytes(checklist_payload)
    note_bytes = _note_markdown_bytes(intake_payload=intake_payload, result_payload=result.to_dict(), checklist=checklist_payload)
    report_bytes = _report_html_bytes(intake_payload=intake_payload, result_payload=result.to_dict(), checklist=checklist_payload)

    file_hashes = {
        "intake.json": hashlib.sha256(intake_bytes).hexdigest(),
        "triage_result.json": hashlib.sha256(result_bytes).hexdigest(),
        "doctor.json": hashlib.sha256(diagnostics_bytes).hexdigest(),
        "actions_checklist.json": hashlib.sha256(checklist_bytes).hexdigest(),
        "note.md": hashlib.sha256(note_bytes).hexdigest(),
        "report.html": hashlib.sha256(report_bytes).hexdigest(),
    }

    manifest = {
        "created_at": created_at,
        "run_id": result.run_id,
        "request_id": result.request_id,
        "pipeline_version": result.pipeline_version,
        "redacted": redact,
        "file_hashes_sha256": file_hashes,
        "policy_pack_sha256": _extract_policy_pack_sha256(result.to_dict()),
        "reasoning": _extract_reasoning_meta(result.to_dict()),
    }
    manifest_bytes = _json_bytes(manifest)

    return {
        "intake.json": intake_bytes,
        "triage_result.json": result_bytes,
        "doctor.json": diagnostics_bytes,
        "actions_checklist.json": checklist_bytes,
        "note.md": note_bytes,
        "report.html": report_bytes,
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


def _extract_reasoning_meta(result_payload: dict) -> dict[str, Any]:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "multimodal_reasoning":
                output = step.get("output") or {}
                return {
                    "backend": str(output.get("reasoning_backend") or ""),
                    "model": str(output.get("reasoning_backend_model") or ""),
                    "prompt_version": str(output.get("reasoning_prompt_version") or ""),
                    "error": str(output.get("reasoning_backend_error") or ""),
                }
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _note_markdown_bytes(
    *,
    intake_payload: dict[str, Any],
    result_payload: dict[str, Any],
    checklist: list[dict[str, Any]],
) -> bytes:
    request_id = str(result_payload.get("request_id") or "").strip()
    run_id = str(result_payload.get("run_id") or "").strip()
    created_at = str(result_payload.get("created_at") or "").strip()
    tier = str(result_payload.get("risk_tier") or "").strip()
    escalation = bool(result_payload.get("escalation_required"))
    confidence = result_payload.get("confidence")
    red_flags = result_payload.get("red_flags") or []
    differential = result_payload.get("differential_considerations") or []
    uncertainty = result_payload.get("uncertainty_reasons") or []
    handoff = str(result_payload.get("clinician_handoff") or "").strip()
    patient = str(result_payload.get("patient_summary") or "").strip()

    done = sum(1 for x in checklist if x.get("checked"))
    total = len(checklist)

    lines: list[str] = []
    lines.append("# ClinicaFlow triage note (demo)")
    lines.append("")
    lines.append("- DISCLAIMER: Decision support only. Not a diagnosis. Clinician confirmation required.")
    lines.append("")
    if request_id:
        lines.append(f"- request_id: `{request_id}`")
    if run_id:
        lines.append(f"- run_id: `{run_id}`")
    if created_at:
        lines.append(f"- created_at: `{created_at}`")
    lines.append("")

    lines.append("## Intake (as provided)")
    lines.append(f"- chief_complaint: {str(intake_payload.get('chief_complaint') or '').strip()}")
    history = str(intake_payload.get("history") or "").strip()
    if history:
        lines.append(f"- history: {history}")

    vitals = dict(intake_payload.get("vitals") or {})
    if vitals:
        vitals_bits = [f"{k}={v}" for k, v in vitals.items() if v not in (None, "")]
        if vitals_bits:
            lines.append(f"- vitals: {', '.join(vitals_bits)}")

    if intake_payload.get("image_descriptions"):
        lines.append("- image_descriptions:")
        for item in intake_payload.get("image_descriptions") or []:
            lines.append(f"  - {item}")

    if intake_payload.get("prior_notes"):
        lines.append("- prior_notes:")
        for item in intake_payload.get("prior_notes") or []:
            lines.append(f"  - {item}")

    lines.append("")
    lines.append("## Triage")
    lines.append(f"- risk_tier: **{tier}**")
    lines.append(f"- escalation_required: **{escalation}**")
    if isinstance(confidence, (int, float)):
        lines.append(f"- confidence (proxy): {float(confidence):.2f}")
    lines.append("")

    lines.append("## Red flags")
    if red_flags:
        for item in red_flags:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Differential (top)")
    if differential:
        for item in differential:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Recommended next actions (checklist)")
    lines.append(f"- progress: {done}/{total}")
    for item in checklist:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        mark = "x" if item.get("checked") else " "
        lines.append(f"- [{mark}] {text}")
    lines.append("")

    lines.append("## Uncertainty")
    if uncertainty:
        for item in uncertainty:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Clinician handoff")
    lines.append("")
    lines.append(handoff or "(empty)")
    lines.append("")

    lines.append("## Patient return precautions")
    lines.append("")
    lines.append(patient or "(empty)")
    lines.append("")

    return ("\n".join(lines).strip() + "\n").encode("utf-8")


def _report_html_bytes(
    *,
    intake_payload: dict[str, Any],
    result_payload: dict[str, Any],
    checklist: list[dict[str, Any]],
) -> bytes:
    request_id = str(result_payload.get("request_id") or "").strip() or "run"
    created_at = str(result_payload.get("created_at") or "").strip()
    tier = str(result_payload.get("risk_tier") or "").strip()
    escalation = bool(result_payload.get("escalation_required"))
    confidence = result_payload.get("confidence")

    vitals = dict(intake_payload.get("vitals") or {})
    vitals_bits = [f"{k}={v}" for k, v in vitals.items() if v not in (None, "")]
    red_flags = [str(x) for x in (result_payload.get("red_flags") or []) if str(x).strip()]
    differential = [str(x) for x in (result_payload.get("differential_considerations") or []) if str(x).strip()]
    uncertainty = [str(x) for x in (result_payload.get("uncertainty_reasons") or []) if str(x).strip()]

    done = sum(1 for x in checklist if x.get("checked"))
    total = len(checklist)

    def li(items: list[str]) -> str:
        if not items:
            return "<li>(none)</li>"
        return "".join(f"<li>{html.escape(x)}</li>" for x in items)

    action_li = (
        "".join(
            (
                f"<li class=\"{'done' if x.get('checked') else ''}\">"
                f"{'☑' if x.get('checked') else '☐'} {html.escape(str(x.get('text') or ''))}</li>"
            )
            for x in checklist
            if str(x.get("text") or "").strip()
        )
        or "<li>(none)</li>"
    )

    risk_class = "risk-routine"
    if tier == "critical":
        risk_class = "risk-critical"
    elif tier == "urgent":
        risk_class = "risk-urgent"

    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>ClinicaFlow — Triage Report ({html.escape(request_id)})</title>
    <style>
      :root {{ color-scheme: light; }}
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif; margin: 24px; color: #111827; }}
      h1 {{ margin: 0 0 6px; font-size: 22px; }}
      .sub {{ color: #6b7280; margin: 0 0 18px; font-size: 13px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }}
      .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; background: #fff; }}
      .k {{ font-weight: 900; font-size: 12px; color: #374151; margin-bottom: 6px; }}
      ul, ol {{ margin: 0; padding-left: 18px; }}
      li {{ margin: 6px 0; }}
      .done {{ opacity: 0.75; text-decoration: line-through; }}
      .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }}
      .pill {{ display: inline-block; padding: 3px 10px; border-radius: 999px; border: 1px solid #e5e7eb; font-weight: 900; font-size: 12px; }}
      .risk-critical {{ background: #fef2f2; border-color: #ef444433; color: #991b1b; }}
      .risk-urgent {{ background: #fffbeb; border-color: #f59e0b44; color: #92400e; }}
      .risk-routine {{ background: #ecfdf5; border-color: #10b98133; color: #065f46; }}
      pre {{ white-space: pre-wrap; background: #0b1020; color: #e5e7eb; padding: 10px; border-radius: 12px; overflow: auto; }}
      @media print {{
        body {{ margin: 12mm; }}
      }}
    </style>
  </head>
  <body>
    <h1>ClinicaFlow — Triage Report <span class="mono">{html.escape(request_id)}</span></h1>
    <p class="sub"><b>DISCLAIMER:</b> Decision support only. Not a diagnosis. Clinician confirmation required.</p>

    <div class="grid">
      <div class="card">
        <div class="k">Metadata</div>
        <ul>
          <li><span class="mono">request_id</span>: <span class="mono">{html.escape(request_id)}</span></li>
          <li>created_at: <span class="mono">{html.escape(created_at)}</span></li>
        </ul>
      </div>
      <div class="card">
        <div class="k">Triage</div>
        <div class="pill {risk_class}">risk_tier: {html.escape(tier)}</div>
        <div style="height:10px"></div>
        <ul>
          <li>escalation_required: <b>{html.escape(str(escalation))}</b></li>
          <li>confidence (proxy): <span class="mono">{html.escape(str(confidence))}</span></li>
        </ul>
      </div>
    </div>

    <div style="height:14px"></div>

    <div class="grid">
      <div class="card">
        <div class="k">Intake (demo)</div>
        <ul>
          <li>chief_complaint: {html.escape(str(intake_payload.get('chief_complaint') or ''))}</li>
          <li>history: {html.escape(str(intake_payload.get('history') or ''))}</li>
          <li>vitals: <span class="mono">{html.escape(', '.join(vitals_bits))}</span></li>
        </ul>
      </div>
      <div class="card">
        <div class="k">Red flags</div>
        <ul>{li(red_flags)}</ul>
      </div>
      <div class="card">
        <div class="k">Differential (top)</div>
        <ul>{li(differential)}</ul>
      </div>
      <div class="card">
        <div class="k">Uncertainty</div>
        <ul>{li(uncertainty)}</ul>
      </div>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div class="k">Next actions (checklist)</div>
      <div class="sub">progress: <span class="mono">{done}/{total}</span></div>
      <ul>{action_li}</ul>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div class="k">Clinician handoff</div>
      <pre>{html.escape(str(result_payload.get('clinician_handoff') or ''))}</pre>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div class="k">Patient return precautions</div>
      <pre>{html.escape(str(result_payload.get('patient_summary') or ''))}</pre>
    </div>
  </body>
</html>
"""

    return html_doc.encode("utf-8")
