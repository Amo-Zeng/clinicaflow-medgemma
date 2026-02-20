from __future__ import annotations

import io
import logging
import json
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from clinicaflow.auth import is_authorized
from clinicaflow.logging_config import configure_logging
from clinicaflow.models import PatientIntake, TriageResult
from clinicaflow.pipeline import ClinicaFlowPipeline
from clinicaflow.settings import Settings, load_settings_from_env
from clinicaflow.version import __version__

logger = logging.getLogger("clinicaflow.server")

SAMPLE_INTAKE = {
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

DEMO_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>ClinicaFlow Console (Fallback UI)</title>
    <style>
      :root {
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
      }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 12px; }
      header { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); background: rgba(255,255,255,0.7); backdrop-filter: blur(8px); position: sticky; top: 0; z-index: 5; }
      .brand-title { font-size: 18px; font-weight: 900; }
      .brand-subtitle { font-size: 12px; color: var(--muted); margin-top: 2px; }
      .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
      .pill { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); background: #fff; color: #374151; font-weight: 800; }
      .btn { border: 1px solid var(--border); background: #fff; color: #111827; padding: 9px 10px; border-radius: 12px; cursor: pointer; font-weight: 800; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
      .btn.primary { border-color: #111827; background: #111827; color: #fff; }
      .container { max-width: 1200px; margin: 0 auto; padding: 18px; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
      @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
      .panel { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; box-shadow: var(--shadow); }
      h2 { margin: 0; font-size: 16px; }
      .panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
      .small { font-size: 12px; color: var(--muted); }
      .warn { margin-top: 10px; border: 1px solid rgba(146, 64, 14, 0.25); background: var(--amber-bg); color: var(--amber); border-radius: 12px; padding: 10px; font-size: 12px; font-weight: 700; }
      .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
      .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
      .field { display: flex; flex-direction: column; gap: 6px; }
      .field.span-2 { grid-column: span 2; }
      label { font-size: 12px; font-weight: 800; color: #374151; }
      textarea, input, select { border: 1px solid var(--border); border-radius: 12px; padding: 10px; font-size: 13px; background: #fff; }
      textarea { resize: vertical; }
      .risk { display: inline-flex; padding: 6px 10px; border-radius: 999px; font-weight: 900; letter-spacing: 0.2px; border: 1px solid var(--border); background: #fff; }
      .risk.routine { background: var(--green-bg); color: var(--green); border-color: rgba(6, 95, 70, 0.25); }
      .risk.urgent { background: var(--amber-bg); color: var(--amber); border-color: rgba(146, 64, 14, 0.25); }
      .risk.critical { background: var(--red-bg); color: var(--red); border-color: rgba(153, 27, 27, 0.25); }
      .card { border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: #fff; margin-top: 10px; }
      .k { font-size: 12px; font-weight: 900; color: #374151; margin-bottom: 6px; }
      ul, ol { margin: 0; padding-left: 18px; }
      li { margin: 4px 0; }
      pre { margin: 10px 0 0; border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: #0b1020; color: #e5e7eb; overflow: auto; max-height: 420px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 12px; }
      details { border: 1px solid var(--border); border-radius: 12px; padding: 10px; margin-top: 10px; background: #fff; }
      details summary { cursor: pointer; font-weight: 800; color: #111827; }
    </style>
  </head>
  <body>
    <header>
      <div>
        <div class="brand-title">ClinicaFlow Console</div>
        <div class="brand-subtitle">Fallback UI (assets missing) - still demo-friendly</div>
      </div>
      <div class="top-actions">
        <span id="backendBadge" class="pill">backend: loading...</span>
        <a class="btn" href="/openapi.json" target="_blank" rel="noreferrer">OpenAPI</a>
        <a class="btn" href="/metrics" target="_blank" rel="noreferrer">Metrics</a>
        <a class="btn" href="/doctor" target="_blank" rel="noreferrer">Doctor</a>
        <a class="btn" href="/policy_pack" target="_blank" rel="noreferrer">Policy pack</a>
      </div>
    </header>

    <main class="container">
      <div class="warn">
        <b>Note:</b> This is the <b>fallback UI</b> served when bundled web assets under <code>/static/</code> are unavailable.
        For the full Console UI (tabs, regression, review, workspace), reinstall and restart:
        <code>pip install -e .</code> or <code>bash scripts/demo_one_click.sh</code>.
      </div>

      <div class="grid" style="margin-top: 14px;">
        <section class="panel">
          <div class="panel-head">
            <h2>Patient intake</h2>
            <div class="small">Decision support only - use synthetic data (no PHI).</div>
          </div>

          <div class="form-grid">
            <div class="field span-2">
              <label for="chief">Chief complaint</label>
              <textarea id="chief" rows="3" placeholder="e.g., Chest pain for 20 minutes"></textarea>
            </div>
            <div class="field span-2">
              <label for="history">History (brief)</label>
              <textarea id="history" rows="3" placeholder="PMH, onset, progression, key negatives..."></textarea>
            </div>
            <div class="field">
              <label for="age">Age</label>
              <input id="age" type="number" min="0" step="1" placeholder="61" />
            </div>
            <div class="field">
              <label for="sex">Sex</label>
              <select id="sex">
                <option value="">-</option>
                <option value="female">female</option>
                <option value="male">male</option>
                <option value="other">other</option>
              </select>
            </div>
            <div class="field">
              <label for="hr">Heart rate</label>
              <input id="hr" type="number" min="0" step="1" placeholder="128" />
            </div>
            <div class="field">
              <label for="sbp">Systolic BP</label>
              <input id="sbp" type="number" min="0" step="1" placeholder="92" />
            </div>
            <div class="field">
              <label for="temp">Temp (C)</label>
              <input id="temp" type="number" step="0.1" placeholder="37.9" />
            </div>
            <div class="field">
              <label for="spo2">SpO2 (%)</label>
              <input id="spo2" type="number" min="0" max="100" step="1" placeholder="93" />
            </div>
            <div class="field span-2">
              <label for="notes">Prior notes (1 per line)</label>
              <textarea id="notes" rows="3" placeholder="Prior episode of exertional chest tightness last week"></textarea>
            </div>
          </div>

          <div class="row">
            <button id="load" class="btn">Load sample</button>
            <button id="run" class="btn primary">Run triage</button>
            <span id="status" class="small"></span>
          </div>

          <details>
            <summary>Advanced: Intake JSON</summary>
            <div class="small">Edit JSON directly if you prefer. This will override the form inputs.</div>
            <textarea id="intakeJson" rows="14" placeholder="{}"></textarea>
          </details>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>Output</h2>
            <div class="small">Summary + raw JSON</div>
          </div>

          <div class="card">
            <div class="k">Risk tier</div>
            <div class="row" style="margin-top: 0;">
              <div id="riskTier" class="risk">-</div>
              <span id="escalation" class="pill">escalation: -</span>
            </div>
            <div id="meta" class="small">request_id: -</div>
          </div>

          <div class="card">
            <div class="k">Red flags</div>
            <ul id="redFlags"></ul>
          </div>

          <div class="card">
            <div class="k">Next actions</div>
            <ol id="actions"></ol>
          </div>

          <details open>
            <summary>Clinician handoff</summary>
            <pre id="handoff"></pre>
          </details>

          <details>
            <summary>Patient return precautions</summary>
            <pre id="patient"></pre>
          </details>

          <details>
            <summary>Raw triage JSON</summary>
            <pre id="output">{}</pre>
          </details>
        </section>
      </div>
    </main>

    <script>
      const $ = (id) => document.getElementById(id);
      const pretty = (obj) => JSON.stringify(obj, null, 2);

      function setRiskTier(tier) {
        const el = $("riskTier");
        el.classList.remove("routine","urgent","critical");
        const t = String(tier || "").toLowerCase();
        if (t) el.classList.add(t);
        el.textContent = tier || "-";
      }

      function renderList(root, items, emptyText) {
        root.innerHTML = "";
        (items || []).forEach((x) => {
          const li = document.createElement("li");
          li.textContent = String(x);
          root.appendChild(li);
        });
        if (!(items || []).length) {
          const li = document.createElement("li");
          li.textContent = emptyText || "-";
          root.appendChild(li);
        }
      }

      function buildIntakeFromForm() {
        const demographics = {};
        const age = Number($("age").value);
        const sex = String($("sex").value || "").trim();
        if (!Number.isNaN(age) && $("age").value !== "") demographics.age = age;
        if (sex) demographics.sex = sex;

        const vitals = {};
        const addNum = (key, el) => {
          const v = Number($(el).value);
          if (!Number.isNaN(v) && $(el).value !== "") vitals[key] = v;
        };
        addNum("heart_rate", "hr");
        addNum("systolic_bp", "sbp");
        addNum("temperature_c", "temp");
        addNum("spo2", "spo2");

        const notes = String($("notes").value || "").split(/\\r?\\n/g).map(s => s.trim()).filter(Boolean);

        return {
          chief_complaint: String($("chief").value || "").trim(),
          history: String($("history").value || "").trim(),
          demographics,
          vitals,
          prior_notes: notes,
        };
      }

      function fillForm(intake) {
        intake = intake || {};
        $("chief").value = intake.chief_complaint || "";
        $("history").value = intake.history || "";
        const demo = intake.demographics || {};
        $("age").value = demo.age ?? "";
        $("sex").value = demo.sex ?? "";
        const vitals = intake.vitals || {};
        $("hr").value = vitals.heart_rate ?? "";
        $("sbp").value = vitals.systolic_bp ?? "";
        $("temp").value = vitals.temperature_c ?? "";
        $("spo2").value = vitals.spo2 ?? "";
        $("notes").value = (intake.prior_notes || []).join("\\n");
      }

      async function loadDoctor() {
        try {
          const resp = await fetch("/doctor");
          const d = await resp.json();
          const backend = (d.reasoning_backend || {}).backend || "deterministic";
          const model = (d.reasoning_backend || {}).model || "";
          const ok = (d.reasoning_backend || {}).connectivity_ok;
          const status = ok === true ? "ok" : ok === false ? "unreachable" : "";
          const label = model ? `${backend} • ${model}` : backend;
          const full = status ? `${label} • ${status}` : label;
          $("backendBadge").textContent = `backend: ${full}`;
        } catch (e) {
          $("backendBadge").textContent = "backend: unknown";
        }
      }

      async function loadSample() {
        $("status").textContent = "Loading sample...";
        const resp = await fetch("/example");
        const data = await resp.json();
        fillForm(data);
        $("intakeJson").value = pretty(data);
        $("status").textContent = "Loaded sample.";
      }

      async function runTriage() {
        $("status").textContent = "Running triage...";
        let payload = buildIntakeFromForm();
        // If the JSON panel looks edited (not just {}), prefer it.
        try {
          const jsonText = String($("intakeJson").value || "").trim();
          if (jsonText && jsonText !== "{}") payload = JSON.parse(jsonText);
        } catch (e) {
          // ignore and use form payload
        }
        if (!String(payload.chief_complaint || "").trim()) {
          $("status").textContent = "Chief complaint is required.";
          return;
        }
        const resp = await fetch("/triage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        setRiskTier(data.risk_tier);
        $("escalation").textContent = `escalation: ${data.escalation_required ? "required" : "not required"}`;
        $("meta").textContent = `request_id: ${data.request_id || "-"} • latency: ${data.total_latency_ms ?? "-"} ms`;
        renderList($("redFlags"), data.red_flags, "No explicit red flags.");
        renderList($("actions"), data.recommended_next_actions, "No suggested actions.");
        $("handoff").textContent = (data.clinician_handoff || "-");
        $("patient").textContent = (data.patient_summary || "-");
        $("output").textContent = pretty(data);
        $("status").textContent = "Done.";
      }

      $("load").addEventListener("click", loadSample);
      $("run").addEventListener("click", runTriage);

      loadDoctor();
      loadSample();
    </script>
  </body>
</html>
"""


def _load_web_assets() -> dict[str, tuple[bytes, str]]:
    """Load bundled web assets (UI) from package resources."""

    assets = {
        "index.html": "text/html; charset=utf-8",
        "app.css": "text/css; charset=utf-8",
        "app.js": "application/javascript; charset=utf-8",
    }

    # 1) Preferred: importlib.resources (works for normal installs and editable installs).
    try:
        from importlib.resources import files

        root = files("clinicaflow.resources").joinpath("web")
        out: dict[str, tuple[bytes, str]] = {}
        for name, content_type in assets.items():
            out[name] = (root.joinpath(name).read_bytes(), content_type)
        return out
    except Exception:  # noqa: BLE001
        pass

    # 2) Fallback: pkgutil.get_data (works when resources are inside a zip).
    try:
        import pkgutil

        out = {}
        for name, content_type in assets.items():
            data = pkgutil.get_data("clinicaflow.resources", f"web/{name}")
            if isinstance(data, (bytes, bytearray)):
                out[name] = (bytes(data), content_type)
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass

    # 3) Last resort: read from filesystem relative to this module (source checkout).
    try:
        from pathlib import Path

        root = Path(__file__).resolve().parent / "resources" / "web"
        out = {}
        for name, content_type in assets.items():
            p = root / name
            if p.is_file():
                out[name] = (p.read_bytes(), content_type)
        return out
    except Exception:  # noqa: BLE001
        return {}


WEB_ASSETS = _load_web_assets()
REQUIRED_WEB_ASSETS = {"index.html", "app.css", "app.js"}
HAS_CONSOLE_UI = all(name in WEB_ASSETS for name in REQUIRED_WEB_ASSETS)

VIGNETTE_CACHE: dict[str, list[dict]] = {}


def _load_vignettes(set_name: str = "standard") -> list[dict]:
    key = str(set_name or "standard").strip().lower()
    if key in VIGNETTE_CACHE:
        return VIGNETTE_CACHE[key]

    try:
        from clinicaflow.benchmarks.vignettes import load_default_vignette_paths, load_vignettes

        rows: list[dict] = []
        for p in load_default_vignette_paths(key):
            rows.extend(load_vignettes(p))
        VIGNETTE_CACHE[key] = rows
    except Exception:  # noqa: BLE001
        VIGNETTE_CACHE[key] = []
    return VIGNETTE_CACHE[key]


def _new_stats() -> dict:
    agents = [
        "intake_structuring",
        "multimodal_reasoning",
        "evidence_policy",
        "safety_escalation",
        "communication",
    ]
    return {
        "requests_total": 0,
        "triage_requests_total": 0,
        "triage_success_total": 0,
        "triage_errors_total": 0,
        "audit_bundle_requests_total": 0,
        "audit_bundle_success_total": 0,
        "audit_bundle_errors_total": 0,
        "fhir_bundle_requests_total": 0,
        "fhir_bundle_success_total": 0,
        "fhir_bundle_errors_total": 0,
        "triage_risk_tier_total": {"routine": 0, "urgent": 0, "critical": 0},
        "triage_reasoning_backend_total": {"deterministic": 0, "external": 0},
        "triage_latency_ms_sum": 0.0,
        "triage_latency_ms_count": 0,
        "triage_agent_latency_ms_sum": {a: 0.0 for a in agents},
        "triage_agent_latency_ms_count": {a: 0 for a in agents},
        "triage_agent_errors_total": {a: 0 for a in agents},
    }


class ClinicaFlowHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        pipeline: ClinicaFlowPipeline,
        settings: Settings,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.pipeline = pipeline
        self.settings = settings
        self.start_time = time.time()
        self.stats = _new_stats()


class ClinicaFlowHandler(BaseHTTPRequestHandler):
    server_version = "ClinicaFlowHTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
        # Suppress BaseHTTPRequestHandler's default access logs; we emit structured logs instead.
        return

    def _get_request_id(self) -> str:
        existing = self.headers.get("X-Request-ID") or self.headers.get("X-Request-Id")
        return str(existing).strip() if existing and str(existing).strip() else uuid.uuid4().hex

    def _set_headers(
        self,
        code: int = HTTPStatus.OK,
        *,
        content_type: str = "application/json; charset=utf-8",
        request_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._last_status_code = int(code)
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        # Light hardening; safe defaults for a local demo.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if request_id:
            self.send_header("X-Request-ID", request_id)
        allow_origin = getattr(self.server, "settings", None)
        origin = allow_origin.cors_allow_origin if allow_origin else "*"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID, Authorization, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "X-Request-ID, Content-Disposition")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def _write_json(
        self,
        payload: dict,
        *,
        code: int = HTTPStatus.OK,
        request_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._set_headers(code, request_id=request_id, extra_headers=extra_headers)
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _write_bytes(
        self,
        data: bytes,
        *,
        code: int = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
        request_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._set_headers(code, content_type=content_type, request_id=request_id, extra_headers=extra_headers)
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(HTTPStatus.NO_CONTENT)

    def do_HEAD(self) -> None:  # noqa: N802
        # Reuse GET routing while suppressing response bodies. This also enables
        # `curl -I` checks in demo scripts and basic ops tooling.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_GET(self) -> None:  # noqa: N802
        request_id = self._get_request_id()
        started = time.perf_counter()
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            self.server.stats["requests_total"] += 1
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path in {"/", "/demo"}:
                if HAS_CONSOLE_UI:
                    data, content_type = WEB_ASSETS["index.html"]
                    ui = "console"
                else:
                    data, content_type = (DEMO_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    ui = "legacy"
                self._write_bytes(
                    data,
                    content_type=content_type,
                    request_id=request_id,
                    extra_headers={"Cache-Control": "no-store", "X-ClinicaFlow-UI": ui},
                )
                status_code = HTTPStatus.OK
                return

            if path.startswith("/static/"):
                name = path.split("/static/", 1)[1]
                asset = WEB_ASSETS.get(name)
                if not asset:
                    self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
                    status_code = HTTPStatus.NOT_FOUND
                    return
                data, content_type = asset
                self._write_bytes(
                    data,
                    content_type=content_type,
                    request_id=request_id,
                    extra_headers={"Cache-Control": "public, max-age=3600"},
                )
                status_code = HTTPStatus.OK
                return

            if path in {"/health", "/ready", "/live"}:
                self._write_json({"status": "ok"}, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/version":
                self._write_json({"version": __version__}, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/doctor":
                from clinicaflow.diagnostics import collect_diagnostics

                self._write_json(collect_diagnostics(), request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/policy_pack":
                from importlib.resources import files

                from clinicaflow.policy_pack import load_policy_pack, policy_pack_sha256

                limit_raw = str(query.get("limit", ["0"])[0]).strip()
                try:
                    limit = int(limit_raw or "0")
                except ValueError:
                    limit = 0

                if self.server.settings.policy_pack_path:
                    source = self.server.settings.policy_pack_path
                    pack_path: object = self.server.settings.policy_pack_path
                else:
                    source = "package:clinicaflow.resources/policy_pack.json"
                    pack_path = files("clinicaflow.resources").joinpath("policy_pack.json")

                policies = load_policy_pack(pack_path)
                n_total = len(policies)
                if limit > 0:
                    policies = policies[:limit]

                payload = {
                    "source": source,
                    "sha256": policy_pack_sha256(pack_path),
                    "n_policies": n_total,
                    "policies": [p.to_dict() for p in policies],
                }
                self._write_json(payload, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/safety_rules":
                from clinicaflow.rules import safety_rules_catalog

                self._write_json(safety_rules_catalog(), request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/metrics":
                uptime_s = int(time.time() - self.server.start_time)
                count = int(self.server.stats.get("triage_latency_ms_count") or 0)
                total = float(self.server.stats.get("triage_latency_ms_sum") or 0.0)
                avg = round(total / count, 2) if count else 0.0
                payload = {
                    "uptime_s": uptime_s,
                    "version": __version__,
                    "triage_latency_ms_avg": avg,
                    **self.server.stats,
                }
                fmt = str(query.get("format", ["json"])[0]).strip().lower()
                accept = (self.headers.get("Accept") or "").lower()
                wants_prometheus = fmt in {"prometheus", "prom"} or "text/plain" in accept
                if wants_prometheus:
                    metrics = _format_prometheus_metrics(payload)
                    self._write_bytes(
                        metrics.encode("utf-8"),
                        content_type="text/plain; version=0.0.4; charset=utf-8",
                        request_id=request_id,
                    )
                else:
                    self._write_json(payload, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/openapi.json":
                self._write_json(_openapi_spec(), request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/example":
                self._write_json(SAMPLE_INTAKE, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/vignettes":
                set_name = _normalize_vignette_set(str(query.get("set", ["standard"])[0]))
                rows = _load_vignettes(set_name)
                payload = {
                    "set": set_name,
                    "vignettes": [
                        {"id": str(row.get("id", "")), "chief_complaint": str((row.get("input") or {}).get("chief_complaint", ""))}
                        for row in rows
                    ]
                }
                self._write_json(payload, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path.startswith("/vignettes/"):
                vid = unquote(path.split("/vignettes/", 1)[1]).strip()
                if not vid:
                    self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
                    status_code = HTTPStatus.NOT_FOUND
                    return

                set_name = _normalize_vignette_set(str(query.get("set", ["standard"])[0]))
                rows = _load_vignettes(set_name)
                row = next((r for r in rows if str(r.get("id", "")).strip() == vid), None)
                if not row:
                    self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
                    status_code = HTTPStatus.NOT_FOUND
                    return

                include_labels = str(query.get("include_labels", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                out = {"id": vid, "set": set_name, "input": dict(row.get("input") or {})}
                if include_labels:
                    out["labels"] = dict(row.get("labels") or {})
                self._write_json(out, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/bench/vignettes":
                from clinicaflow.benchmarks.vignettes import run_benchmark_rows

                set_name = _normalize_vignette_set(str(query.get("set", ["standard"])[0]))
                summary, per_case = run_benchmark_rows(_load_vignettes(set_name))
                self._write_json({"set": set_name, "summary": summary.to_dict(), "per_case": per_case}, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/bench/synthetic":
                from clinicaflow.benchmarks.synthetic import run_benchmark

                seed_raw = str(query.get("seed", ["17"])[0]).strip()
                n_raw = str(query.get("n", ["220"])[0]).strip()
                try:
                    seed = int(seed_raw or "17")
                except ValueError:
                    seed = 17
                try:
                    n_cases = int(n_raw or "220")
                except ValueError:
                    n_cases = 220
                # Keep runtime bounded for a demo server.
                n_cases = max(1, min(n_cases, 800))

                summary = run_benchmark(seed=seed, n_cases=n_cases)
                self._write_json(
                    {"seed": seed, "n_cases": n_cases, "summary": summary.to_dict(), "markdown": summary.to_markdown_table()},
                    request_id=request_id,
                )
                status_code = HTTPStatus.OK
                return

            self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
            status_code = HTTPStatus.NOT_FOUND
        except Exception:  # noqa: BLE001
            logger.exception("http_unhandled_error", extra={"event": "http_unhandled_error", "request_id": request_id})
            self._write_json(
                {"error": {"code": "internal_error"}},
                code=HTTPStatus.INTERNAL_SERVER_ERROR,
                request_id=request_id,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            status_code_i = int(getattr(self, "_last_status_code", int(status_code)))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "method": getattr(self, "command", "GET"),
                    "path": urlparse(self.path).path,
                    "status_code": status_code_i,
                    "latency_ms": latency_ms,
                    "request_id": request_id,
                },
            )

    def do_POST(self) -> None:  # noqa: N802
        request_id = self._get_request_id()
        started = time.perf_counter()
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            self.server.stats["requests_total"] += 1
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path not in {"/triage", "/audit_bundle", "/fhir_bundle"}:
                self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
                status_code = HTTPStatus.NOT_FOUND
                return

            if not is_authorized(headers=self.headers, expected_api_key=self.server.settings.api_key):
                self._write_json(
                    {"error": {"code": "unauthorized"}},
                    code=HTTPStatus.UNAUTHORIZED,
                    request_id=request_id,
                    extra_headers={"WWW-Authenticate": "Bearer"},
                )
                status_code = HTTPStatus.UNAUTHORIZED
                return

            content_type = (self.headers.get("Content-Type") or "").lower()
            if "application/json" not in content_type:
                self._write_json(
                    {"error": {"code": "unsupported_media_type", "message": "Expected application/json"}},
                    code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    request_id=request_id,
                )
                status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
                return

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self._write_json(
                    {"error": {"code": "bad_request", "message": "Missing Content-Length"}},
                    code=HTTPStatus.BAD_REQUEST,
                    request_id=request_id,
                )
                status_code = HTTPStatus.BAD_REQUEST
                return
            if length > self.server.settings.max_request_bytes:
                self._write_json(
                    {"error": {"code": "payload_too_large", "max_bytes": self.server.settings.max_request_bytes}},
                    code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    request_id=request_id,
                )
                status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                return

            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                if path == "/triage":
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                else:
                    self.server.stats["fhir_bundle_errors_total"] += 1
                self._write_json(
                    {"error": {"code": "bad_json", "message": str(exc)}},
                    code=HTTPStatus.BAD_REQUEST,
                    request_id=request_id,
                )
                status_code = HTTPStatus.BAD_REQUEST
                return

            if not isinstance(payload, dict):
                if path == "/triage":
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                else:
                    self.server.stats["fhir_bundle_errors_total"] += 1
                self._write_json(
                    {"error": {"code": "invalid_payload", "message": "Expected a JSON object"}},
                    code=HTTPStatus.UNPROCESSABLE_ENTITY,
                    request_id=request_id,
                )
                status_code = HTTPStatus.UNPROCESSABLE_ENTITY
                return

            try:
                intake_payload, result_payload, checklist = _unwrap_intake_payload(payload)
            except ValueError as exc:
                if path == "/triage":
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                else:
                    self.server.stats["fhir_bundle_errors_total"] += 1
                self._write_json(
                    {"error": {"code": "invalid_payload", "message": str(exc)[:200]}},
                    code=HTTPStatus.UNPROCESSABLE_ENTITY,
                    request_id=request_id,
                )
                status_code = HTTPStatus.UNPROCESSABLE_ENTITY
                return

            intake = PatientIntake.from_mapping(intake_payload)
            existing_result: TriageResult | None = None
            if isinstance(result_payload, dict):
                existing_result = TriageResult.from_mapping(result_payload)
                if not existing_result.request_id:
                    existing_result.request_id = request_id

            if path == "/triage":
                self.server.stats["triage_requests_total"] += 1
                triage_started = time.perf_counter()
                result = self.server.pipeline.run(intake, request_id=request_id).to_dict()
                result["server_latency_ms"] = round((time.perf_counter() - triage_started) * 1000, 2)

                self.server.stats["triage_success_total"] += 1
                risk_tier = str(result.get("risk_tier") or "")
                if risk_tier in self.server.stats["triage_risk_tier_total"]:
                    self.server.stats["triage_risk_tier_total"][risk_tier] += 1

                backend = _extract_reasoning_backend(result)
                if backend in self.server.stats["triage_reasoning_backend_total"]:
                    self.server.stats["triage_reasoning_backend_total"][backend] += 1

                latency = float(result.get("total_latency_ms") or 0.0)
                self.server.stats["triage_latency_ms_sum"] += latency
                self.server.stats["triage_latency_ms_count"] += 1

                # Per-agent latency/error metrics (production-style observability).
                trace_rows = result.get("trace") or []
                if isinstance(trace_rows, list):
                    for step in trace_rows:
                        if not isinstance(step, dict):
                            continue
                        agent = str(step.get("agent") or "").strip()
                        if not agent:
                            continue

                        if agent not in self.server.stats["triage_agent_latency_ms_sum"]:
                            self.server.stats["triage_agent_latency_ms_sum"][agent] = 0.0
                            self.server.stats["triage_agent_latency_ms_count"][agent] = 0
                            self.server.stats["triage_agent_errors_total"][agent] = 0

                        latency_ms = step.get("latency_ms")
                        if isinstance(latency_ms, (int, float)):
                            self.server.stats["triage_agent_latency_ms_sum"][agent] += float(latency_ms)
                            self.server.stats["triage_agent_latency_ms_count"][agent] += 1

                        err = step.get("error")
                        if isinstance(err, str) and err.strip():
                            self.server.stats["triage_agent_errors_total"][agent] += 1

                logger.info(
                    "triage_complete",
                    extra={
                        "event": "triage_complete",
                        "request_id": request_id,
                        "risk_tier": result.get("risk_tier"),
                        "escalation_required": result.get("escalation_required"),
                        "latency_ms": result.get("total_latency_ms"),
                        "reasoning_backend": backend,
                    },
                )

                self._write_json(result, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/audit_bundle":
                self.server.stats["audit_bundle_requests_total"] += 1
                redact = str(query.get("redact", ["1"])[0]).strip().lower() in {"1", "true", "yes"}

                from clinicaflow.audit import build_audit_bundle_files

                result_obj = existing_result or self.server.pipeline.run(intake, request_id=request_id)
                bundle_request_id = result_obj.request_id or request_id
                files = build_audit_bundle_files(intake=intake, result=result_obj, redact=redact, checklist=checklist)

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for name, data in files.items():
                        zf.writestr(name, data)

                self.server.stats["audit_bundle_success_total"] += 1
                filename = f'clinicaflow_audit_{"redacted" if redact else "full"}_{bundle_request_id}.zip'
                self._write_bytes(
                    buf.getvalue(),
                    content_type="application/zip",
                    request_id=bundle_request_id,
                    extra_headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
                status_code = HTTPStatus.OK
                return

            self.server.stats["fhir_bundle_requests_total"] += 1
            redact = str(query.get("redact", ["1"])[0]).strip().lower() in {"1", "true", "yes"}
            result_obj = existing_result or self.server.pipeline.run(intake, request_id=request_id)
            bundle_request_id = result_obj.request_id or request_id

            from clinicaflow.fhir_export import build_fhir_bundle

            bundle = build_fhir_bundle(intake=intake, result=result_obj, redact=redact, checklist=checklist)
            self.server.stats["fhir_bundle_success_total"] += 1
            self._write_json(bundle, request_id=bundle_request_id)
            status_code = HTTPStatus.OK
        except Exception as exc:  # noqa: BLE001
            if urlparse(self.path).path == "/triage":
                self.server.stats["triage_errors_total"] += 1
            elif urlparse(self.path).path == "/audit_bundle":
                self.server.stats["audit_bundle_errors_total"] += 1
            else:
                self.server.stats["fhir_bundle_errors_total"] += 1
            logger.exception("post_error", extra={"event": "post_error", "request_id": request_id})
            error_payload = {"error": {"code": "bad_request"}}
            if self.server.settings.debug:
                error_payload["error"]["message"] = str(exc)
            self._write_json(error_payload, code=HTTPStatus.BAD_REQUEST, request_id=request_id)
            status_code = HTTPStatus.BAD_REQUEST
        finally:
            status_code_i = int(getattr(self, "_last_status_code", int(status_code)))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "method": "POST",
                    "path": urlparse(self.path).path,
                    "status_code": status_code_i,
                    "latency_ms": latency_ms,
                    "request_id": request_id,
                },
            )


def _unwrap_intake_payload(payload: dict) -> tuple[dict, dict | None, Any]:
    """Support both legacy and UI-export payload formats.

    - Legacy: {chief_complaint: ..., vitals: ...}
    - UI export: {intake: {...}, result: {...}, checklist: [...]}
    """

    if "intake" not in payload:
        return payload, None, None

    intake = payload.get("intake")
    if not isinstance(intake, dict):
        raise ValueError("Expected `intake` to be a JSON object.")

    result = payload.get("result")
    result_payload = result if isinstance(result, dict) else None
    return dict(intake), result_payload, payload.get("checklist")


def _normalize_vignette_set(value: str) -> str:
    key = str(value or "").strip().lower()
    if key in {"standard", "adversarial", "extended", "all", "mega"}:
        return key
    return "standard"


def _openapi_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "ClinicaFlow Demo API", "version": __version__},
        "paths": {
            "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/ready": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/live": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/version": {"get": {"responses": {"200": {"description": "version"}}}},
            "/doctor": {"get": {"responses": {"200": {"description": "diagnostics (no secrets)"}}}},
            "/policy_pack": {"get": {"responses": {"200": {"description": "policy pack (demo/site protocols)"}}}},
            "/safety_rules": {"get": {"responses": {"200": {"description": "deterministic safety rulebook (demo)"}}}},
            "/metrics": {"get": {"responses": {"200": {"description": "metrics"}}}},
            "/example": {"get": {"responses": {"200": {"description": "sample intake"}}}},
            "/vignettes": {"get": {"responses": {"200": {"description": "list vignettes"}}}},
            "/vignettes/{id}": {"get": {"responses": {"200": {"description": "get vignette input"}}}},
            "/bench/vignettes": {"get": {"responses": {"200": {"description": "run vignette benchmark"}}}},
            "/bench/synthetic": {"get": {"responses": {"200": {"description": "run synthetic proxy benchmark"}}}},
            "/triage": {"post": {"responses": {"200": {"description": "triage result"}}}},
            "/audit_bundle": {"post": {"responses": {"200": {"description": "audit bundle zip"}}}},
            "/fhir_bundle": {"post": {"responses": {"200": {"description": "FHIR bundle JSON"}}}},
        },
    }


def _extract_reasoning_backend(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "multimodal_reasoning":
                output = step.get("output") or {}
                backend = output.get("reasoning_backend")
                if backend in {"deterministic", "external"}:
                    return backend
    except Exception:  # noqa: BLE001
        return "deterministic"
    return "deterministic"


def _format_prometheus_metrics(payload: dict) -> str:
    lines: list[str] = []

    def esc(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def metric(name: str, value: object, labels: dict[str, str] | None = None) -> None:
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if labels:
            label_s = ",".join(f'{k}="{esc(vv)}"' for k, vv in labels.items())
            lines.append(f"{name}{{{label_s}}} {v}")
        else:
            lines.append(f"{name} {v}")

    metric("clinicaflow_uptime_seconds", payload.get("uptime_s"))
    version = str(payload.get("version") or "").strip()
    if version:
        metric("clinicaflow_version_info", 1, {"version": version})

    # Top-level counters
    metric("clinicaflow_requests_total", payload.get("requests_total"))
    metric("clinicaflow_triage_requests_total", payload.get("triage_requests_total"))
    metric("clinicaflow_triage_success_total", payload.get("triage_success_total"))
    metric("clinicaflow_triage_errors_total", payload.get("triage_errors_total"))
    metric("clinicaflow_audit_bundle_requests_total", payload.get("audit_bundle_requests_total"))
    metric("clinicaflow_audit_bundle_success_total", payload.get("audit_bundle_success_total"))
    metric("clinicaflow_audit_bundle_errors_total", payload.get("audit_bundle_errors_total"))
    metric("clinicaflow_fhir_bundle_requests_total", payload.get("fhir_bundle_requests_total"))
    metric("clinicaflow_fhir_bundle_success_total", payload.get("fhir_bundle_success_total"))
    metric("clinicaflow_fhir_bundle_errors_total", payload.get("fhir_bundle_errors_total"))

    metric("clinicaflow_triage_latency_ms_avg", payload.get("triage_latency_ms_avg"))

    # Nested breakdowns
    for tier, count in dict(payload.get("triage_risk_tier_total") or {}).items():
        metric("clinicaflow_triage_risk_tier_total", count, {"tier": str(tier)})
    for backend, count in dict(payload.get("triage_reasoning_backend_total") or {}).items():
        metric("clinicaflow_triage_reasoning_backend_total", count, {"backend": str(backend)})

    for agent, total in dict(payload.get("triage_agent_latency_ms_sum") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_sum", total, {"agent": str(agent)})
    for agent, count in dict(payload.get("triage_agent_latency_ms_count") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_count", count, {"agent": str(agent)})
    for agent, count in dict(payload.get("triage_agent_errors_total") or {}).items():
        metric("clinicaflow_triage_agent_errors_total", count, {"agent": str(agent)})

    return "\n".join(lines).strip() + "\n"


def make_server(
    host: str,
    port: int,
    *,
    pipeline: ClinicaFlowPipeline | None = None,
    settings: Settings | None = None,
) -> ClinicaFlowHTTPServer:
    settings = settings or load_settings_from_env()
    pipeline = pipeline or ClinicaFlowPipeline()
    return ClinicaFlowHTTPServer((host, port), ClinicaFlowHandler, pipeline=pipeline, settings=settings)


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    settings = load_settings_from_env()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    server = make_server(host, port, settings=settings)
    print(f"ClinicaFlow demo server running at http://{host}:{port}")
    print("Open / in your browser for the demo UI")
    print("API: POST /triage, POST /audit_bundle, POST /fhir_bundle, GET /doctor, GET /vignettes, GET /bench/vignettes")
    print("Ops: GET /health, GET /metrics, GET /openapi.json")
    server.serve_forever()


if __name__ == "__main__":
    run()
