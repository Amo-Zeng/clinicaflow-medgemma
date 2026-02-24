from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from dataclasses import asdict
from typing import Any

import streamlit as st

from clinicaflow.audit import build_audit_bundle_files
from clinicaflow.benchmarks.vignettes import (
    categories_from_red_flags,
    load_default_vignette_paths,
    load_vignettes,
    run_benchmark_rows,
)
from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline
from clinicaflow.privacy import detect_phi_hits
from clinicaflow.rules import SAFETY_RULES_VERSION
from clinicaflow.version import __version__


SAMPLE_INTAKE: dict[str, Any] = {
    "chief_complaint": "Chest pain and shortness of breath for 20 minutes",
    "history": "Patient has diabetes and hypertension.",
    "demographics": {"age": 61, "sex": "female"},
    "vitals": {
        "heart_rate": 128,
        "systolic_bp": 92,
        "diastolic_bp": 58,
        "temperature_c": 37.9,
        "spo2": 93,
        "respiratory_rate": 24,
    },
    "image_descriptions": ["Portable chest image: mild bilateral interstitial opacities"],
    "prior_notes": ["Prior episode of exertional chest tightness last week"],
}

DEMO_VIGNETTES: dict[str, tuple[str, str]] = {
    "Critical — chest pain + hypotension (ACS pathway)": ("standard", "v01_chest_pain_hypotension"),
    "Urgent — slurred speech + weakness (stroke pathway)": ("standard", "v05_slurred_speech_weakness"),
    "Routine — sore throat + runny nose (low acuity)": ("standard", "v21_sore_throat_routine"),
    "Adversarial — CP abbrev + prompt injection": ("adversarial", "a01_cp_abbrev_hypotension"),
}


def _badge(label: str, tier: str) -> None:
    tier = (tier or "").strip().lower()
    palette = {
        "routine": ("#065f46", "#ecfdf5"),
        "urgent": ("#92400e", "#fffbeb"),
        "critical": ("#991b1b", "#fef2f2"),
    }
    fg, bg = palette.get(tier, ("#111827", "#f3f4f6"))
    st.markdown(
        f"""
        <div style="display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;
                    font-weight:800;border:1px solid rgba(17,24,39,0.15);background:{bg};color:{fg}">
          <span style="letter-spacing:0.2px">{label}</span>
          <span style="opacity:0.85">{tier or '-'}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _to_data_url(mime: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@st.cache_resource(show_spinner=False)
def _pipeline() -> ClinicaFlowPipeline:
    return ClinicaFlowPipeline()


@st.cache_data(show_spinner=False)
def _load_vignette_rows(set_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in load_default_vignette_paths(set_name):
        rows.extend(load_vignettes(path))
    return rows


def _emit_status(placeholders: dict[str, Any], event: dict[str, Any]) -> None:
    if event.get("type") == "meta":
        placeholders["meta"].json(event)
        return
    if event.get("type") == "step_start":
        idx = int(event.get("index") or 0)
        placeholders["progress"].progress(min((idx + 0.1) / 5.0, 1.0))
        placeholders["status"].info(f"Running: {event.get('agent')}")
        return
    if event.get("type") == "step_end":
        idx = int(event.get("index") or 0)
        placeholders["progress"].progress(min((idx + 1) / 5.0, 1.0))
        return


def _trace_step_output(result: Any, agent: str) -> dict[str, Any]:
    for step in list(getattr(result, "trace", []) or []):
        if getattr(step, "agent", "") != agent:
            continue
        output = getattr(step, "output", None)
        if isinstance(output, dict):
            return dict(output)
    return {}


def _render_case_result(intake: PatientIntake, result: Any) -> None:
    _badge("Risk tier", getattr(result, "risk_tier", ""))
    st.caption(f"pipeline={__version__} · safety_rules={SAFETY_RULES_VERSION} · run_id={getattr(result, 'run_id', '')}")

    phi = detect_phi_hits(intake.combined_text())
    if phi:
        st.warning(f"Possible PHI patterns detected (demo guard): {', '.join(phi[:6])}")

    reasoning = _trace_step_output(result, "multimodal_reasoning")
    evidence = _trace_step_output(result, "evidence_policy")
    communication = _trace_step_output(result, "communication")

    top = st.columns(4)
    with top[0]:
        st.metric("Escalation required", "Yes" if bool(getattr(result, "escalation_required", False)) else "No")
    with top[1]:
        st.metric("Confidence", f"{float(getattr(result, 'confidence', 0.0)):.2f}")
    with top[2]:
        st.metric("Latency (ms)", f"{float(getattr(result, 'total_latency_ms', 0.0)):.0f}")
    with top[3]:
        st.metric("Reasoning backend", str(reasoning.get("reasoning_backend") or "deterministic"))

    st.subheader("Patient summary")
    summary = str(getattr(result, "patient_summary", "") or "").strip()
    st.text_area("Patient summary", value=summary, height=120, label_visibility="collapsed")

    cols = st.columns(2, gap="large")
    with cols[0]:
        st.subheader("Red flags")
        flags = list(getattr(result, "red_flags", []) or [])
        if flags:
            st.text("\n".join([f"• {x}" for x in flags]))
        else:
            st.caption("None detected.")

        st.subheader("Recommended actions")
        actions = list(getattr(result, "recommended_next_actions", []) or [])
        if actions:
            st.text("\n".join([f"• {x}" for x in actions]))
        else:
            st.caption("No actions returned.")

    with cols[1]:
        st.subheader("Differential considerations")
        diff = list(getattr(result, "differential_considerations", []) or [])
        if diff:
            st.text("\n".join([f"• {x}" for x in diff]))
        else:
            st.caption("No differential returned.")

        st.subheader("Handoff (clinician)")
        handoff = str(getattr(result, "clinician_handoff", "") or "").strip()
        st.text_area("Clinician handoff", value=handoff, height=180, label_visibility="collapsed")

    with st.expander("Evidence & policy citations"):
        backend_line = str(evidence.get("evidence_backend") or "local").strip() or "local"
        ok = evidence.get("evidence_backend_ok")
        status = "unknown" if ok is None else ("ok" if bool(ok) else "error")
        st.caption(f"evidence_backend={backend_line} · status={status}")

        skipped = str(evidence.get("evidence_backend_skipped_reason") or "").strip()
        if skipped:
            st.info(skipped)
        err = str(evidence.get("evidence_backend_error") or "").strip()
        if err:
            st.warning(err)

        citations = list(evidence.get("protocol_citations") or [])
        if not citations:
            st.caption("No citations returned.")
        else:
            for item in citations[:12]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("policy_id") or "Citation").strip()
                cite = str(item.get("citation") or "").strip()
                url = str(item.get("url") or "").strip()
                if url:
                    st.markdown(f"- [{title}]({url})")
                else:
                    st.markdown(f"- **{title}**")
                if cite:
                    st.caption(cite)

    with st.expander("Trace (per-agent)"):
        rows = []
        for step in list(getattr(result, "trace", []) or []):
            rows.append(
                {
                    "agent": getattr(step, "agent", ""),
                    "latency_ms": getattr(step, "latency_ms", None),
                    "error": getattr(step, "error", "") or "",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption(
            "communication_backend="
            + str(communication.get("communication_backend") or "deterministic")
            + " · evidence_backend="
            + str(evidence.get("evidence_backend") or "local")
        )

    with st.expander("Raw JSON result"):
        st.json(getattr(result, "to_dict", lambda: asdict(result))())


def _render_audit_downloads(intake: PatientIntake, result: Any) -> None:
    st.subheader("Audit downloads")
    cols = st.columns(2)
    with cols[0]:
        files = build_audit_bundle_files(intake=intake, result=result, redact=True)
        st.download_button(
            "Download redacted audit bundle (zip)",
            data=_zip_bytes(files),
            file_name=f"clinicaflow_audit_redacted_{getattr(result, 'run_id', 'run')}.zip",
            mime="application/zip",
            use_container_width=True,
        )
    with cols[1]:
        files = build_audit_bundle_files(intake=intake, result=result, redact=False)
        st.download_button(
            "Download full audit bundle (zip)",
            data=_zip_bytes(files),
            file_name=f"clinicaflow_audit_full_{getattr(result, 'run_id', 'run')}.zip",
            mime="application/zip",
            use_container_width=True,
        )


def _demo_runbook() -> None:
    st.markdown(
        """
        <div style="padding:10px 12px;border-radius:14px;border:1px solid rgba(17,24,39,0.10);background:#f9fafb">
          <b>3-minute demo runbook:</b> pick a vignette → run triage → inspect outputs → download audit bundle.
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(2, gap="large")
    with cols[0]:
        label = st.selectbox("Demo vignette", list(DEMO_VIGNETTES), index=0)
        set_name, case_id = DEMO_VIGNETTES[label]
        rows = _load_vignette_rows(set_name)
        row = next((r for r in rows if str(r.get("id") or "").strip() == case_id), {})
        st.caption(f"set={set_name} · id={case_id}")
        st.json(dict(row.get("input") or {}))

        if st.button("Run this demo vignette", type="primary", use_container_width=True):
            intake = PatientIntake.from_mapping(dict(row.get("input") or {}))
            placeholders = {
                "progress": st.progress(0.0),
                "status": st.empty(),
                "meta": st.empty(),
            }

            def emit(evt: dict[str, Any]) -> None:
                _emit_status(placeholders, evt)

            with st.spinner("Running 5-agent workflow…"):
                result = _pipeline().run(intake, emit=emit)
            placeholders["status"].success("Done.")
            st.session_state["last_intake"] = intake
            st.session_state["last_result"] = result

    with cols[1]:
        st.subheader("Latest run")
        intake = st.session_state.get("last_intake")
        result = st.session_state.get("last_result")
        if intake is None or result is None:
            st.caption("No run yet.")
        else:
            _render_case_result(intake, result)
            _render_audit_downloads(intake, result)


def _case_console() -> None:
    st.markdown(
        """
        <div style="padding:10px 12px;border-radius:14px;border:1px solid rgba(17,24,39,0.12);background:#fff7ed;color:#7c2d12">
          <b>Demo safety:</b> Use <b>synthetic</b> vignettes only. Do not enter PHI.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([0.52, 0.48], gap="large")

    if "intake_payload" not in st.session_state:
        st.session_state["intake_payload"] = json.dumps(SAMPLE_INTAKE, indent=2, ensure_ascii=False)

    with col_left:
        st.subheader("Case library")
        set_name = st.selectbox("Vignette set", ["standard", "adversarial", "realworld"], index=0, key="console_set")
        rows = _load_vignette_rows(set_name)
        ids = [str(r.get("id") or "").strip() for r in rows]
        selected = st.selectbox("Case id", ids, index=0, key="console_case_id")
        row = next((r for r in rows if str(r.get("id") or "").strip() == selected), {})
        case_input = dict(row.get("input") or {})
        labels = dict(row.get("labels") or {})

        actions = st.columns(2)
        with actions[0]:
            if st.button("Load into editor", use_container_width=True):
                st.session_state["intake_payload"] = json.dumps(case_input, indent=2, ensure_ascii=False)
        with actions[1]:
            if st.button("Load 3-minute demo sample", use_container_width=True):
                st.session_state["intake_payload"] = json.dumps(SAMPLE_INTAKE, indent=2, ensure_ascii=False)

        with st.expander("Gold labels (for regression)", expanded=False):
            st.json(labels)
            rationale = str(row.get("rationale") or "").strip()
            if rationale:
                st.caption(rationale)

        st.subheader("Manual form (writes into JSON editor)")
        with st.expander("Open manual form"):
            demo = st.checkbox("Use demo vitals", value=True, help="Pre-fills vitals with a plausible demo pattern.")
            chief = st.text_area("Chief complaint", value="Chest pain for 20 minutes" if demo else "", height=90)
            history = st.text_area("History (brief)", value="History of diabetes and hypertension." if demo else "", height=90)

            f1, f2 = st.columns(2)
            with f1:
                age = st.number_input("Age", min_value=0, max_value=120, value=61 if demo else 0)
            with f2:
                sex = st.selectbox("Sex", ["", "female", "male", "other"], index=1 if demo else 0)

            v1, v2, v3 = st.columns(3)
            with v1:
                hr = st.number_input("Heart rate", min_value=0, value=128 if demo else 0)
                rr = st.number_input("Resp rate", min_value=0, value=24 if demo else 0)
            with v2:
                sbp = st.number_input("Systolic BP", min_value=0, value=92 if demo else 0)
                dbp = st.number_input("Diastolic BP", min_value=0, value=58 if demo else 0)
            with v3:
                temp = st.number_input("Temp (°C)", value=37.9 if demo else 0.0, step=0.1, format="%.1f")
                spo2 = st.number_input("SpO₂ (%)", min_value=0, max_value=100, value=93 if demo else 0)

            if st.button("Apply manual form → JSON editor", use_container_width=True):
                payload: dict[str, Any] = {
                    "chief_complaint": chief,
                    "history": history,
                    "demographics": {"age": int(age), "sex": sex},
                    "vitals": {
                        "heart_rate": int(hr) if hr else None,
                        "systolic_bp": int(sbp) if sbp else None,
                        "diastolic_bp": int(dbp) if dbp else None,
                        "temperature_c": float(temp) if temp else None,
                        "spo2": int(spo2) if spo2 else None,
                        "respiratory_rate": int(rr) if rr else None,
                    },
                }
                st.session_state["intake_payload"] = json.dumps(payload, indent=2, ensure_ascii=False)

        st.subheader("JSON editor")

        st.caption("Tip: edit the JSON directly to match your demo script.")
        payload_text = st.text_area("Patient intake JSON", key="intake_payload", height=260)

        upload = st.file_uploader("Optional: attach 1 image (demo only)", type=["png", "jpg", "jpeg", "webp"])
        run = st.button("Run ClinicaFlow triage", type="primary", use_container_width=True)

        if run:
            try:
                payload = json.loads(payload_text)
                if not isinstance(payload, dict):
                    raise ValueError("Intake JSON must be an object.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Invalid JSON: {exc}")
            else:
                if upload is not None:
                    mime = upload.type or "image/png"
                    payload = dict(payload)
                    payload.setdefault("image_data_urls", [])
                    payload["image_data_urls"] = list(payload.get("image_data_urls") or [])
                    payload["image_data_urls"].append(_to_data_url(mime, upload.getvalue()))

                intake = PatientIntake.from_mapping(payload)
                pipe = _pipeline()

                placeholders = {
                    "progress": st.progress(0.0),
                    "status": st.empty(),
                    "meta": st.empty(),
                }

                def emit(evt: dict[str, Any]) -> None:
                    _emit_status(placeholders, evt)

                with st.spinner("Running 5-agent workflow…"):
                    result = pipe.run(intake, emit=emit)

                placeholders["status"].success("Done.")
                st.session_state["last_intake"] = intake
                st.session_state["last_result"] = result

    with col_right:
        st.subheader("Latest run")
        intake = st.session_state.get("last_intake")
        result = st.session_state.get("last_result")
        if intake is None or result is None:
            st.caption("No run yet.")
        else:
            _render_case_result(intake, result)
            _render_audit_downloads(intake, result)


def _vignette_regression() -> None:
    st.markdown(
        """
        <div style="padding:10px 12px;border-radius:14px;border:1px solid rgba(17,24,39,0.10);background:#f9fafb">
          Built-in <b>clinical vignette regression</b> sets catch under-triage regressions:
          red-flag recall + under-triage rate (urgent/critical → predicted routine).
          See <code>docs/VIGNETTE_REGRESSION.md</code> for labeling rules.
        </div>
        """,
        unsafe_allow_html=True,
    )

    set_name = st.selectbox("Vignette set", ["standard", "adversarial", "realworld"], index=0)
    rows = _load_vignette_rows(set_name)
    st.caption(f"Loaded {len(rows)} cases.")

    ids = [str(r.get("id") or "").strip() for r in rows]
    selected = st.selectbox("Pick a case", ids, index=0)
    row = next((r for r in rows if str(r.get("id") or "").strip() == selected), {})
    case_input = dict(row.get("input") or {})
    labels = dict(row.get("labels") or {})

    cols = st.columns(2, gap="large")
    with cols[0]:
        st.subheader("Case input")
        st.json(case_input)
    with cols[1]:
        st.subheader("Gold labels")
        st.json(labels)
        rationale = str(row.get("rationale") or "").strip()
        if rationale:
            st.caption(rationale)

    if st.button("Run ClinicaFlow on this case", type="primary", use_container_width=True):
        intake = PatientIntake.from_mapping(case_input)
        result = _pipeline().run(intake)
        _render_case_result(intake, result)

        gold_tier = str(labels.get("gold_risk_tier") or "").strip().lower()
        pred_tier = str(getattr(result, "risk_tier", "") or "").strip().lower()
        if gold_tier in {"urgent", "critical"} and pred_tier == "routine":
            st.error("Under-triage: gold is urgent/critical but model predicted routine.")
        elif gold_tier == "routine" and pred_tier in {"urgent", "critical"}:
            st.warning("Over-triage: gold is routine but model predicted urgent/critical.")
        else:
            st.success("Risk tier matches gold directionally (no under/over-triage).")

        gold_cats = set(labels.get("gold_red_flag_categories") or [])
        pred_cats = categories_from_red_flags(list(getattr(result, "red_flags", []) or []))
        if gold_cats:
            if gold_cats & pred_cats:
                st.success(f"Red-flag recall hit: {sorted(gold_cats & pred_cats)}")
            else:
                st.error(f"Red-flag recall miss. gold={sorted(gold_cats)} pred={sorted(pred_cats)}")

    st.divider()
    st.subheader("Quick benchmark (this set)")
    st.caption("Runs the full set locally (deterministic backend by default).")
    if st.button("Run benchmark", use_container_width=True):
        with st.spinner("Benchmarking…"):
            summary, _ = run_benchmark_rows(rows)
        st.markdown(summary.to_markdown_table())


def _about() -> None:
    st.markdown(
        """
        **ClinicaFlow / MedGemma Impact Challenge**

        - Repo: https://github.com/Amo-Zeng/clinicaflow-medgemma
        - Kaggle writeup: https://www.kaggle.com/competitions/med-gemma-impact-challenge/writeups/new-writeup-1768960611416
        - 3-minute demo video: https://youtu.be/dDdy8LIowQI
        - Static live demo (GitHub Pages): https://2agi.me/clinicaflow-medgemma/

        This Streamlit app is a lightweight judge-friendly UI wrapper around the same `clinicaflow` pipeline.
        """,
    )

    with st.expander("Environment (selected)"):
        keys = [
            "CLINICAFLOW_REASONING_BACKEND",
            "CLINICAFLOW_REASONING_BASE_URL",
            "CLINICAFLOW_REASONING_BASE_URLS",
            "CLINICAFLOW_REASONING_MODEL",
            "CLINICAFLOW_EVIDENCE_BACKEND",
        ]
        st.json({k: os.environ.get(k, "") for k in keys})


def main() -> None:
    st.set_page_config(
        page_title="ClinicaFlow Console (Streamlit)",
        page_icon="🩺",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("ClinicaFlow Console (Streamlit)")
    st.caption(f"version {__version__} · safety_rules {SAFETY_RULES_VERSION}")

    tab_demo, tab_console, tab_regression, tab_about = st.tabs(
        ["3-minute demo", "Console", "Vignette regression", "About"]
    )
    with tab_demo:
        _demo_runbook()
    with tab_console:
        _case_console()
    with tab_regression:
        _vignette_regression()
    with tab_about:
        _about()


if __name__ == "__main__":
    main()
