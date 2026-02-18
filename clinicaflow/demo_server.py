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
    <title>ClinicaFlow Demo (Legacy UI)</title>
    <style>
      :root { color-scheme: light; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; max-width: 1100px; }
      h1 { margin: 0 0 6px; font-size: 22px; }
      .sub { color: #555; margin: 0 0 18px; }
      .warn { background: #fffbeb; border: 1px solid #f59e0b44; border-radius: 10px; padding: 10px; margin: 14px 0; color: #92400e; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      textarea { width: 100%; height: 520px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; padding: 10px; border: 1px solid #ccc; border-radius: 8px; }
      pre { height: 520px; overflow: auto; padding: 10px; border: 1px solid #ccc; border-radius: 8px; background: #fafafa; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; margin: 0; }
      .row { display: flex; gap: 10px; align-items: center; margin: 10px 0 14px; }
      button { border: 1px solid #222; background: #222; color: #fff; padding: 8px 10px; border-radius: 10px; cursor: pointer; }
      button.secondary { background: #fff; color: #222; }
      .hint { color: #666; font-size: 12px; }
      .badge { display:inline-block; padding: 3px 8px; border-radius: 999px; background:#eef; color:#223; font-size: 12px; }
    </style>
  </head>
  <body>
    <h1>ClinicaFlow Demo <span class="badge">local</span></h1>
    <p class="sub">Agentic triage workflow scaffold with an auditable 5-step trace.</p>

    <div class="warn">
      <b>Note:</b> You are seeing the <b>legacy fallback UI</b>. The full “ClinicaFlow Console” UI is served from bundled
      web assets under <code>/static/</code>. If this page looks too minimal, restart the server after reinstalling
      (e.g. <code>pip install -e .</code>), or run <code>bash scripts/demo_one_click.sh</code>.
    </div>

    <div class="row">
      <button id="load">Load sample</button>
      <button class="secondary" id="run">Run triage</button>
      <span class="hint">Endpoints: <code>GET /health</code>, <code>GET /openapi.json</code>, <code>GET /metrics</code>, <code>POST /triage</code></span>
    </div>

    <div class="grid">
      <div>
        <div class="hint" style="margin: 0 0 6px;">Input JSON</div>
        <textarea id="input"></textarea>
      </div>
      <div>
        <div class="hint" style="margin: 0 0 6px;">Output</div>
        <pre id="output">{}</pre>
      </div>
    </div>

    <script>
      const $input = document.getElementById('input');
      const $output = document.getElementById('output');
      const pretty = (obj) => JSON.stringify(obj, null, 2);

      async function loadSample() {
        const resp = await fetch('/example');
        const data = await resp.json();
        $input.value = pretty(data);
      }

      async function runTriage() {
        let payload;
        try {
          payload = JSON.parse($input.value);
        } catch (e) {
          $output.textContent = 'Invalid JSON: ' + e;
          return;
        }
        $output.textContent = 'Running...';
        const resp = await fetch('/triage', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        $output.textContent = pretty(data);
      }

      document.getElementById('load').addEventListener('click', loadSample);
      document.getElementById('run').addEventListener('click', runTriage);
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
    try:
        from importlib.resources import files

        root = files("clinicaflow.resources").joinpath("web")
        return {name: (root.joinpath(name).read_bytes(), content_type) for name, content_type in assets.items()}
    except Exception:  # noqa: BLE001
        return {}


WEB_ASSETS = _load_web_assets()

VIGNETTE_CACHE: list[dict] | None = None


def _load_vignettes() -> list[dict]:
    global VIGNETTE_CACHE  # noqa: PLW0603
    if VIGNETTE_CACHE is not None:
        return VIGNETTE_CACHE

    try:
        from clinicaflow.benchmarks.vignettes import load_default_vignette_path, load_vignettes

        VIGNETTE_CACHE = load_vignettes(load_default_vignette_path())
    except Exception:  # noqa: BLE001
        VIGNETTE_CACHE = []
    return VIGNETTE_CACHE


def _new_stats() -> dict:
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
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(HTTPStatus.NO_CONTENT)

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
                data, content_type = WEB_ASSETS.get("index.html", (DEMO_HTML.encode("utf-8"), "text/html; charset=utf-8"))
                ui = "console" if "index.html" in WEB_ASSETS else "legacy"
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
                rows = _load_vignettes()
                payload = {
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

                rows = _load_vignettes()
                row = next((r for r in rows if str(r.get("id", "")).strip() == vid), None)
                if not row:
                    self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
                    status_code = HTTPStatus.NOT_FOUND
                    return

                include_labels = str(query.get("include_labels", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                out = {"id": vid, "input": dict(row.get("input") or {})}
                if include_labels:
                    out["labels"] = dict(row.get("labels") or {})
                self._write_json(out, request_id=request_id)
                status_code = HTTPStatus.OK
                return

            if path == "/bench/vignettes":
                from clinicaflow.benchmarks.vignettes import load_default_vignette_path, run_benchmark

                summary, per_case = run_benchmark(load_default_vignette_path())
                self._write_json({"summary": summary.to_dict(), "per_case": per_case}, request_id=request_id)
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
                    "method": "GET",
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
            "/metrics": {"get": {"responses": {"200": {"description": "metrics"}}}},
            "/example": {"get": {"responses": {"200": {"description": "sample intake"}}}},
            "/vignettes": {"get": {"responses": {"200": {"description": "list vignettes"}}}},
            "/vignettes/{id}": {"get": {"responses": {"200": {"description": "get vignette input"}}}},
            "/bench/vignettes": {"get": {"responses": {"200": {"description": "run vignette benchmark"}}}},
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
