from __future__ import annotations

import base64
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
    image_files: dict[str, bytes] = {}
    if redact:
        intake_payload["demographics"] = {}
        intake_payload["prior_notes"] = []
        intake_payload["image_descriptions"] = []
        intake_payload["image_data_urls"] = []
    else:
        intake_payload, image_files = _extract_inline_images(intake_payload)

    intake_bytes = _json_bytes(intake_payload)
    result_bytes = _json_bytes(result.to_dict())
    diagnostics_bytes = _json_bytes(collect_diagnostics())

    checklist_payload = _normalize_checklist(checklist, fallback=result.recommended_next_actions)
    checklist_bytes = _json_bytes(checklist_payload)
    note_bytes = _note_markdown_bytes(intake_payload=intake_payload, result_payload=result.to_dict(), checklist=checklist_payload)
    report_bytes = _report_html_bytes(intake_payload=intake_payload, result_payload=result.to_dict(), checklist=checklist_payload)

    files: dict[str, bytes] = {
        "intake.json": intake_bytes,
        "triage_result.json": result_bytes,
        "doctor.json": diagnostics_bytes,
        "actions_checklist.json": checklist_bytes,
        "note.md": note_bytes,
        "report.html": report_bytes,
        **image_files,
    }

    file_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}

    manifest = {
        "created_at": created_at,
        "run_id": result.run_id,
        "request_id": result.request_id,
        "pipeline_version": result.pipeline_version,
        "redacted": redact,
        "file_hashes_sha256": file_hashes,
        "policy_pack_sha256": _extract_policy_pack_sha256(result.to_dict()),
        "policy_pack_source": _extract_policy_pack_source(result.to_dict()),
        "safety_rules_version": _extract_safety_rules_version(result.to_dict()),
        "reasoning": _extract_reasoning_meta(result.to_dict()),
        "communication": _extract_communication_meta(result.to_dict()),
    }
    manifest_bytes = _json_bytes(manifest)

    files["manifest.json"] = manifest_bytes
    return files


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
        path = out_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    return out_path


def _extract_inline_images(intake_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Extract `image_data_urls` into separate files for audit bundles.

    Returns (updated intake_payload, image_files).
    """

    raw = intake_payload.get("image_data_urls")
    if not isinstance(raw, list):
        return intake_payload, {}

    image_files: dict[str, bytes] = {}
    images_meta: list[dict[str, Any]] = []

    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s.startswith("data:image/"):
            continue
        try:
            header, b64 = s.split(",", 1)
            mime = header.split(":", 1)[1].split(";", 1)[0].strip().lower()
            ext = {
                "image/jpeg": "jpg",
                "image/jpg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }.get(mime, "bin")
            data = base64.b64decode(b64.encode("utf-8"), validate=False)
        except Exception:  # noqa: BLE001
            continue

        filename = f"images/image_{idx}.{ext}"
        image_files[filename] = data
        images_meta.append({"filename": filename, "mime_type": mime})

    # Always strip inline image payloads from intake.json to keep it small.
    intake_payload["image_data_urls"] = []
    if images_meta:
        intake_payload["images"] = images_meta

    return intake_payload, image_files


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


def _extract_policy_pack_source(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "evidence_policy":
                output = step.get("output") or {}
                value = output.get("policy_pack_source")
                return str(value or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _extract_safety_rules_version(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "safety_escalation":
                output = step.get("output") or {}
                value = output.get("safety_rules_version")
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


def _extract_communication_meta(result_payload: dict) -> dict[str, Any]:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "communication":
                output = step.get("output") or {}
                return {
                    "backend": str(output.get("communication_backend") or ""),
                    "model": str(output.get("communication_backend_model") or ""),
                    "prompt_version": str(output.get("communication_prompt_version") or ""),
                    "error": str(output.get("communication_backend_error") or ""),
                }
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _trace_output(result_payload: dict, agent: str) -> dict[str, Any]:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == agent:
                return dict(step.get("output") or {})
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _format_risk_scores(payload: dict[str, Any]) -> str:
    scores = dict(payload.get("risk_scores") or {})
    parts: list[str] = []
    si = scores.get("shock_index")
    if isinstance(si, (int, float)):
        hi = " (high)" if scores.get("shock_index_high") else ""
        parts.append(f"shock_index={float(si):.2f}{hi}")
    q = scores.get("qsofa")
    if isinstance(q, int):
        hi = " (≥2)" if scores.get("qsofa_high_risk") else ""
        parts.append(f"qSOFA={q}{hi}")
    return " • ".join(parts)


def _note_markdown_bytes(
    *,
    intake_payload: dict[str, Any],
    result_payload: dict[str, Any],
    checklist: list[dict[str, Any]],
) -> bytes:
    request_id = str(result_payload.get("request_id") or "").strip()
    run_id = str(result_payload.get("run_id") or "").strip()
    created_at = str(result_payload.get("created_at") or "").strip()
    pipeline_version = str(result_payload.get("pipeline_version") or "").strip()
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

    safety = _trace_output(result_payload, "safety_escalation")
    evidence = _trace_output(result_payload, "evidence_policy")
    reasoning = _trace_output(result_payload, "multimodal_reasoning")
    structured = _trace_output(result_payload, "intake_structuring")
    communication = _trace_output(result_payload, "communication")

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
    if pipeline_version:
        lines.append(f"- pipeline_version: `{pipeline_version}`")
    if safety.get("safety_rules_version"):
        lines.append(f"- safety_rules_version: `{str(safety.get('safety_rules_version'))}`")
    if reasoning.get("reasoning_backend"):
        lines.append(f"- reasoning_backend: `{str(reasoning.get('reasoning_backend'))}`")
    if reasoning.get("reasoning_backend_model"):
        lines.append(f"- reasoning_model: `{str(reasoning.get('reasoning_backend_model'))}`")
    if reasoning.get("reasoning_prompt_version"):
        lines.append(f"- reasoning_prompt_version: `{str(reasoning.get('reasoning_prompt_version'))}`")
    if reasoning.get("reasoning_backend_skipped_reason"):
        lines.append(f"- reasoning_backend_skipped_reason: `{str(reasoning.get('reasoning_backend_skipped_reason'))}`")
    if reasoning.get("reasoning_backend_error"):
        lines.append(f"- reasoning_backend_error: `{str(reasoning.get('reasoning_backend_error'))}`")
    if evidence.get("policy_pack_sha256"):
        lines.append(f"- policy_pack_sha256: `{str(evidence.get('policy_pack_sha256'))}`")
    if communication.get("communication_backend"):
        lines.append(f"- communication_backend: `{str(communication.get('communication_backend'))}`")
    if communication.get("communication_backend_model"):
        lines.append(f"- communication_model: `{str(communication.get('communication_backend_model'))}`")
    if communication.get("communication_prompt_version"):
        lines.append(f"- communication_prompt_version: `{str(communication.get('communication_prompt_version'))}`")
    if communication.get("communication_backend_skipped_reason"):
        lines.append(f"- communication_backend_skipped_reason: `{str(communication.get('communication_backend_skipped_reason'))}`")
    if communication.get("communication_backend_error"):
        lines.append(f"- communication_backend_error: `{str(communication.get('communication_backend_error'))}`")
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

    if intake_payload.get("images"):
        lines.append("- images:")
        for item in intake_payload.get("images") or []:
            if isinstance(item, dict):
                name = str(item.get("filename") or "").strip()
                mime = str(item.get("mime_type") or "").strip()
                label = f"{name} ({mime})".strip()
                if label.strip():
                    lines.append(f"  - {label}")

    if intake_payload.get("prior_notes"):
        lines.append("- prior_notes:")
        for item in intake_payload.get("prior_notes") or []:
            lines.append(f"  - {item}")
    symptoms = structured.get("symptoms") or []
    risk_factors = structured.get("risk_factors") or []
    if isinstance(symptoms, list) and symptoms:
        lines.append("- extracted_symptoms:")
        for item in symptoms:
            s = str(item).strip()
            if s:
                lines.append(f"  - {s}")
    if isinstance(risk_factors, list) and risk_factors:
        lines.append("- extracted_risk_factors:")
        for item in risk_factors:
            s = str(item).strip()
            if s:
                lines.append(f"  - {s}")

    phi_hits = structured.get("phi_hits") or []
    if isinstance(phi_hits, list) and phi_hits:
        lines.append("- phi_hits (heuristic; do not include actual identifiers):")
        for item in phi_hits:
            s = str(item).strip()
            if s:
                lines.append(f"  - {s}")

    quality = structured.get("data_quality_warnings") or []
    if isinstance(quality, list) and quality:
        lines.append("- data_quality_warnings:")
        for item in quality:
            s = str(item).strip()
            if s:
                lines.append(f"  - {s}")

    lines.append("")
    lines.append("## Triage")
    lines.append(f"- risk_tier: **{tier}**")
    lines.append(f"- escalation_required: **{escalation}**")
    if safety.get("risk_tier_rationale"):
        lines.append(f"- rationale: {str(safety.get('risk_tier_rationale')).strip()}")
    rs = _format_risk_scores(safety)
    if rs:
        lines.append(f"- risk_scores: {rs}")
    if isinstance(confidence, (int, float)):
        lines.append(f"- confidence (proxy): {float(confidence):.2f}")
    lines.append("")

    lines.append("## Safety triggers (deterministic)")
    triggers = safety.get("safety_triggers") or []
    if isinstance(triggers, list) and triggers:
        for t in triggers:
            if not isinstance(t, dict):
                continue
            label = str(t.get("label") or t.get("id") or "").strip()
            detail = str(t.get("detail") or "").strip()
            if not label:
                continue
            lines.append(f"- {label}{(' — ' + detail) if detail else ''}")
    else:
        lines.append("- (none)")
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
    safety_actions = [str(x) for x in (safety.get("actions_added_by_safety") or []) if str(x).strip()]
    safety_set = set(safety_actions)
    if safety_set:
        lines.append("- tags: SAFETY=rules, POLICY=policy pack")
    for item in checklist:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        mark = "x" if item.get("checked") else " "
        tag = ""
        if safety_set:
            tag = "[SAFETY] " if text in safety_set else "[POLICY] "
        lines.append(f"- [{mark}] {tag}{text}")
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

    safety = _trace_output(result_payload, "safety_escalation")
    evidence = _trace_output(result_payload, "evidence_policy")
    reasoning = _trace_output(result_payload, "multimodal_reasoning")
    communication = _trace_output(result_payload, "communication")
    risk_scores = _format_risk_scores(safety)
    structured = _trace_output(result_payload, "intake_structuring")

    done = sum(1 for x in checklist if x.get("checked"))
    total = len(checklist)

    safety_actions = [str(x) for x in (safety.get("actions_added_by_safety") or []) if str(x).strip()]
    safety_set = set(safety_actions)

    triggers_raw = safety.get("safety_triggers") or []
    trigger_li = "<li>(none)</li>"
    if isinstance(triggers_raw, list) and triggers_raw:
        items: list[str] = []
        for t in triggers_raw:
            if not isinstance(t, dict):
                continue
            label = str(t.get("label") or t.get("id") or "").strip()
            detail = str(t.get("detail") or "").strip()
            sev = str(t.get("severity") or "").strip().lower()
            if not label:
                continue
            klass = "risk-routine"
            if sev == "critical":
                klass = "risk-critical"
            elif sev == "urgent":
                klass = "risk-urgent"
            items.append(
                f"<li><span class=\"pill {klass}\">{html.escape(label)}</span>"
                f"{(' ' + html.escape(detail)) if detail else ''}</li>"
            )
        if items:
            trigger_li = "".join(items)

    symptoms = structured.get("symptoms") or []
    if not isinstance(symptoms, list):
        symptoms = []
    risk_factors = structured.get("risk_factors") or []
    if not isinstance(risk_factors, list):
        risk_factors = []
    quality_warnings = structured.get("data_quality_warnings") or []
    if not isinstance(quality_warnings, list):
        quality_warnings = []
    phi_hits = structured.get("phi_hits") or []
    if not isinstance(phi_hits, list):
        phi_hits = []

    def li(items: list[str]) -> str:
        if not items:
            return "<li>(none)</li>"
        return "".join(f"<li>{html.escape(x)}</li>" for x in items)

    action_li = "".join(
        (
            f"<li class=\"{'done' if x.get('checked') else ''}\">"
            f"{'☑' if x.get('checked') else '☐'} "
            + (
                f"<span class=\"tag {'safety' if str(x.get('text') or '').strip() in safety_set else 'policy'}\">"
                f"{'SAFETY' if str(x.get('text') or '').strip() in safety_set else 'POLICY'}</span> "
                if safety_set
                else ""
            )
            + f"{html.escape(str(x.get('text') or ''))}</li>"
        )
        for x in checklist
        if str(x.get("text") or "").strip()
    ) or "<li>(none)</li>"

    risk_class = "risk-routine"
    if tier == "critical":
        risk_class = "risk-critical"
    elif tier == "urgent":
        risk_class = "risk-urgent"

    banner_title = f"Triage: {tier.upper()}" if tier else "Triage"
    banner_subtitle = "Decision support only — clinician confirmation required."
    if tier == "critical":
        banner_title = "CRITICAL — emergency evaluation now"
        banner_subtitle = "Escalation required. Do not delay clinician review."
    elif tier == "urgent":
        banner_title = "URGENT — same-day evaluation"
        banner_subtitle = "Escalation required. Ensure clinician review today."
    elif tier == "routine":
        banner_title = "ROUTINE — stable (with return precautions)"
        banner_subtitle = "No explicit red flags detected in provided intake."

    top_action = ""
    try:
        top_action = str((result_payload.get("recommended_next_actions") or [])[0] or "").strip()
    except Exception:  # noqa: BLE001
        top_action = ""

    meta_bits: list[str] = []
    if safety.get("risk_tier_rationale"):
        meta_bits.append(f"Why: {str(safety.get('risk_tier_rationale')).strip()}")
    if red_flags:
        preview = " • ".join(red_flags[:2])
        ell = " • …" if len(red_flags) > 2 else ""
        meta_bits.append(f"Red flags: {preview}{ell}")
    if top_action:
        meta_bits.append(f"Top action: {top_action}")
    banner_meta = "  |  ".join(meta_bits) if meta_bits else "—"

    trace_rows = result_payload.get("trace") or []
    workflow_rows = ""
    if isinstance(trace_rows, list):
        for step in trace_rows:
            if not isinstance(step, dict):
                continue
            agent = str(step.get("agent") or "").strip() or "agent"
            latency = step.get("latency_ms")
            err = str(step.get("error") or "").strip()
            if not err:
                out = step.get("output") or {}
                if isinstance(out, dict) and agent == "multimodal_reasoning":
                    derived = str(out.get("reasoning_backend_error") or "").strip()
                    skipped = str(out.get("reasoning_backend_skipped_reason") or "").strip()
                    if derived:
                        err = f"fallback: {derived}"
                    elif skipped:
                        err = f"skipped: {skipped}"
                elif isinstance(out, dict) and agent == "communication":
                    derived = str(out.get("communication_backend_error") or "").strip()
                    skipped = str(out.get("communication_backend_skipped_reason") or "").strip()
                    if derived:
                        err = f"fallback: {derived}"
                    elif skipped:
                        err = f"skipped: {skipped}"
                if err:
                    err = err[:160]
            latency_str = ""
            if isinstance(latency, (int, float)):
                latency_str = f"{float(latency):.2f} ms"
            workflow_rows += (
                "<tr>"
                f"<td class=\"mono\">{html.escape(agent)}</td>"
                f"<td class=\"mono\">{html.escape(latency_str)}</td>"
                f"<td>{html.escape(err) if err else ''}</td>"
                "</tr>"
            )

    citations = evidence.get("protocol_citations") or []
    citation_rows = ""
    if isinstance(citations, list):
        for c in citations:
            if not isinstance(c, dict):
                continue
            pid = str(c.get("policy_id") or "").strip()
            title = str(c.get("title") or "").strip()
            cite = str(c.get("citation") or "").strip()
            acts = c.get("recommended_actions") or []
            acts_str = "; ".join(str(x) for x in acts if str(x).strip()) if isinstance(acts, list) else ""
            citation_rows += (
                "<tr>"
                f"<td class=\"mono\">{html.escape(pid)}</td>"
                f"<td>{html.escape(title)}</td>"
                f"<td class=\"mono\">{html.escape(cite)}</td>"
                f"<td>{html.escape(acts_str)}</td>"
                "</tr>"
            )

    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>ClinicaFlow — Triage Report ({html.escape(request_id)})</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f6f7f9;
        --panel: #ffffff;
        --text: #111827;
        --muted: #6b7280;
        --border: #e5e7eb;
        --shadow: 0 1px 2px rgba(16, 24, 40, 0.08), 0 8px 28px rgba(16, 24, 40, 0.06);
        --radius: 14px;
        --green-bg: #ecfdf5;
        --green: #065f46;
        --amber-bg: #fffbeb;
        --amber: #92400e;
        --red-bg: #fef2f2;
        --red: #991b1b;
        --blue-bg: #eef2ff;
        --blue: #3730a3;
      }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; background: var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif; }}
      code, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }}
      header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); background: rgba(255,255,255,0.7); backdrop-filter: blur(8px); position: sticky; top: 0; z-index: 5; }}
      .brand-title {{ font-size: 18px; font-weight: 950; }}
      .brand-subtitle {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
      .container {{ max-width: 1200px; margin: 0 auto; padding: 18px; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }}
      @media (max-width: 980px) {{ .grid {{ grid-template-columns: 1fr; }} }}
      .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; box-shadow: var(--shadow); }}
      .k {{ font-size: 12px; font-weight: 900; color: #374151; margin-bottom: 6px; }}
      .small {{ font-size: 12px; color: var(--muted); }}
      ul, ol {{ margin: 0; padding-left: 18px; }}
      li {{ margin: 6px 0; }}
      .done {{ opacity: 0.75; text-decoration: line-through; }}
      .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); font-weight: 950; font-size: 12px; background: #fff; color: #374151; }}
      .risk-critical {{ background: var(--red-bg); border-color: rgba(153, 27, 27, 0.25); color: var(--red); }}
      .risk-urgent {{ background: var(--amber-bg); border-color: rgba(146, 64, 14, 0.25); color: var(--amber); }}
      .risk-routine {{ background: var(--green-bg); border-color: rgba(6, 95, 70, 0.25); color: var(--green); }}
      .banner {{ border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; background: #fff; margin-bottom: 14px; box-shadow: var(--shadow); }}
      .banner-title {{ font-weight: 950; letter-spacing: 0.2px; }}
      .banner-subtitle {{ margin-top: 4px; font-size: 12px; opacity: 0.92; }}
      .banner-meta {{ margin-top: 8px; font-size: 12px; color: rgba(17, 24, 39, 0.72); }}
      .banner.routine {{ background: var(--green-bg); color: var(--green); border-color: rgba(6, 95, 70, 0.25); }}
      .banner.urgent {{ background: var(--amber-bg); color: var(--amber); border-color: rgba(146, 64, 14, 0.25); }}
      .banner.critical {{ background: var(--red-bg); color: var(--red); border-color: rgba(153, 27, 27, 0.25); }}
      .tag {{ display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); background: #f3f4f6; color: #374151; font-size: 11px; font-weight: 950; letter-spacing: 0.2px; }}
      .tag.safety {{ background: var(--red-bg); color: var(--red); border-color: rgba(153, 27, 27, 0.25); }}
      .tag.policy {{ background: var(--blue-bg); color: var(--blue); border-color: rgba(55, 48, 163, 0.2); }}
      table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
      th, td {{ padding: 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
      th {{ background: #f9fafb; font-weight: 950; }}
      pre {{ white-space: pre-wrap; background: #0b1020; color: #e5e7eb; padding: 10px; border-radius: 12px; overflow: auto; }}
      @media print {{
        header {{ position: static; }}
        body {{ margin: 0; }}
        .container {{ padding: 12mm; }}
      }}
    </style>
  </head>
  <body>
    <header>
      <div>
        <div class="brand-title">ClinicaFlow — Triage Report</div>
        <div class="brand-subtitle"><span class="mono">{html.escape(request_id)}</span> • {html.escape(created_at)}</div>
      </div>
      <div>
        <span class="pill {risk_class}">risk_tier: {html.escape(tier)}</span>
      </div>
    </header>

    <main class="container">
      <div class="banner {html.escape(tier.lower() if tier else '')}">
        <div class="banner-title">{html.escape(banner_title)}</div>
        <div class="banner-subtitle">{html.escape(banner_subtitle)}</div>
        <div class="banner-meta">{html.escape(banner_meta)}</div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="k">Metadata</div>
          <ul>
            <li><span class="mono">request_id</span>: <span class="mono">{html.escape(request_id)}</span></li>
            <li>created_at: <span class="mono">{html.escape(created_at)}</span></li>
            <li>pipeline_version: <span class="mono">{html.escape(str(result_payload.get('pipeline_version') or ''))}</span></li>
            <li>reasoning_backend: <span class="mono">{html.escape(str(reasoning.get('reasoning_backend') or ''))}</span></li>
            <li>reasoning_model: <span class="mono">{html.escape(str(reasoning.get('reasoning_backend_model') or ''))}</span></li>
            <li>reasoning_prompt_version: <span class="mono">{html.escape(str(reasoning.get('reasoning_prompt_version') or ''))}</span></li>
            <li>reasoning_skipped: <span class="mono">{html.escape(str(reasoning.get('reasoning_backend_skipped_reason') or ''))}</span></li>
            <li>reasoning_error: <span class="mono">{html.escape(str(reasoning.get('reasoning_backend_error') or ''))}</span></li>
            <li>policy_pack_sha256: <span class="mono">{html.escape(str(evidence.get('policy_pack_sha256') or ''))}</span></li>
            <li>policy_pack_source: <span class="mono">{html.escape(str(evidence.get('policy_pack_source') or ''))}</span></li>
            <li>safety_rules_version: <span class="mono">{html.escape(str(safety.get('safety_rules_version') or ''))}</span></li>
            <li>communication_backend: <span class="mono">{html.escape(str(communication.get('communication_backend') or ''))}</span></li>
            <li>communication_model: <span class="mono">{html.escape(str(communication.get('communication_backend_model') or ''))}</span></li>
            <li>communication_prompt_version: <span class="mono">{html.escape(str(communication.get('communication_prompt_version') or ''))}</span></li>
            <li>communication_skipped: <span class="mono">{html.escape(str(communication.get('communication_backend_skipped_reason') or ''))}</span></li>
            <li>communication_error: <span class="mono">{html.escape(str(communication.get('communication_backend_error') or ''))}</span></li>
          </ul>
          <div class="small" style="margin-top: 8px;">
            DISCLAIMER: Decision support only. Not a diagnosis. Clinician confirmation required.
          </div>
        </div>
        <div class="card">
          <div class="k">Triage</div>
          <ul>
            <li>risk_tier: <b>{html.escape(tier)}</b></li>
            <li>escalation_required: <b>{html.escape(str(escalation))}</b></li>
            <li>rationale: {html.escape(str(safety.get('risk_tier_rationale') or ''))}</li>
            {f'<li>risk_scores: <span class="mono">{html.escape(risk_scores)}</span></li>' if risk_scores else ''}
            <li>confidence (proxy): <span class="mono">{html.escape(str(confidence))}</span></li>
          </ul>
          <div class="k" style="margin-top: 10px;">Safety triggers (deterministic)</div>
          <ul>{trigger_li}</ul>
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
            {f"<li>images: <span class='mono'>{html.escape(str(len(intake_payload.get('images') or [])))}</span></li>" if intake_payload.get("images") else ""}
          </ul>
        </div>
        <div class="card">
          <div class="k">Extracted signals</div>
          <div class="small">Symptoms</div>
          <ul>{li([str(x) for x in symptoms if str(x).strip()])}</ul>
          <div class="small" style="margin-top: 8px;">Risk factors</div>
          <ul>{li([str(x) for x in risk_factors if str(x).strip()])}</ul>
          <div class="small" style="margin-top: 8px;">Data quality warnings</div>
          <ul>{li([str(x) for x in quality_warnings if str(x).strip()])}</ul>
          <div class="small" style="margin-top: 8px;">PHI patterns (heuristic)</div>
          <ul>{li([str(x) for x in phi_hits if str(x).strip()])}</ul>
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
        <div class="small">progress: <span class="mono">{done}/{total}</span></div>
        {('<div class="small" style="margin-top: 6px;">Tags: <span class="tag safety">SAFETY</span> = deterministic rules; <span class="tag policy">POLICY</span> = policy pack / evidence agent</div>' if safety_set else '')}
        <ul style="margin-top: 8px;">{action_li}</ul>
      </div>

      <div style="height:14px"></div>

      <div class="grid">
        <div class="card">
          <div class="k">Agent workflow (audit trace)</div>
          <div class="tablewrap" style="overflow:auto; border: 1px solid var(--border); border-radius: 12px;">
            <table>
              <thead><tr><th>Agent</th><th>Latency</th><th>Error</th></tr></thead>
              <tbody>{workflow_rows or '<tr><td colspan=\"3\">(none)</td></tr>'}</tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="k">Protocol citations (demo policy pack)</div>
          <div class="small">policy_pack_sha256: <span class="mono">{html.escape(str(evidence.get('policy_pack_sha256') or ''))}</span></div>
          <div class="tablewrap" style="overflow:auto; border: 1px solid var(--border); border-radius: 12px; margin-top: 8px;">
            <table>
              <thead><tr><th>Policy</th><th>Title</th><th>Citation</th><th>Recommended actions</th></tr></thead>
              <tbody>{citation_rows or '<tr><td colspan=\"4\">(none)</td></tr>'}</tbody>
            </table>
          </div>
        </div>
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
    </main>
  </body>
</html>
"""

    return html_doc.encode("utf-8")
