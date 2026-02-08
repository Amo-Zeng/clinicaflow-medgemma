from __future__ import annotations

import logging
import json
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline
from clinicaflow.settings import load_settings_from_env
from clinicaflow.version import __version__

PIPELINE = ClinicaFlowPipeline()
SETTINGS = load_settings_from_env()
START_TIME = time.time()
STATS = {
    "requests_total": 0,
    "triage_requests_total": 0,
    "triage_errors_total": 0,
}

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
    <title>ClinicaFlow Demo</title>
    <style>
      :root { color-scheme: light; }
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; max-width: 1100px; }
      h1 { margin: 0 0 6px; font-size: 22px; }
      .sub { color: #555; margin: 0 0 18px; }
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


class ClinicaFlowHandler(BaseHTTPRequestHandler):
    server_version = "ClinicaFlowHTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
        logger.info("http_access %s", fmt % args)

    def _get_request_id(self) -> str:
        existing = self.headers.get("X-Request-ID") or self.headers.get("X-Request-Id")
        return str(existing).strip() if existing and str(existing).strip() else uuid.uuid4().hex

    def _set_headers(
        self,
        code: int = HTTPStatus.OK,
        *,
        content_type: str = "application/json; charset=utf-8",
        request_id: str | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if request_id:
            self.send_header("X-Request-ID", request_id)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _write_json(self, payload: dict, *, code: int = HTTPStatus.OK, request_id: str | None = None) -> None:
        self._set_headers(code, request_id=request_id)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802
        request_id = self._get_request_id()
        STATS["requests_total"] += 1

        if self.path in {"/", "/demo"}:
            self._set_headers(content_type="text/html; charset=utf-8", request_id=request_id)
            self.wfile.write(DEMO_HTML.encode("utf-8"))
            return

        if self.path == "/health":
            self._write_json({"status": "ok"}, request_id=request_id)
            return

        if self.path == "/version":
            self._write_json({"version": __version__}, request_id=request_id)
            return

        if self.path == "/metrics":
            uptime_s = int(time.time() - START_TIME)
            payload = {
                "uptime_s": uptime_s,
                "version": __version__,
                **STATS,
            }
            self._write_json(payload, request_id=request_id)
            return

        if self.path == "/openapi.json":
            self._write_json(_openapi_spec(), request_id=request_id)
            return

        if self.path == "/example":
            self._write_json(SAMPLE_INTAKE, request_id=request_id)
            return

        self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)

    def do_POST(self) -> None:  # noqa: N802
        request_id = self._get_request_id()
        STATS["requests_total"] += 1

        if self.path != "/triage":
            self._write_json({"error": {"code": "not_found"}}, code=HTTPStatus.NOT_FOUND, request_id=request_id)
            return

        STATS["triage_requests_total"] += 1
        content_type = (self.headers.get("Content-Type") or "").lower()
        if "application/json" not in content_type:
            self._write_json(
                {"error": {"code": "unsupported_media_type", "message": "Expected application/json"}},
                code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                request_id=request_id,
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > SETTINGS.max_request_bytes:
                self._write_json(
                    {"error": {"code": "payload_too_large", "max_bytes": SETTINGS.max_request_bytes}},
                    code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    request_id=request_id,
                )
                return
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            intake = PatientIntake.from_mapping(payload)
            started = time.perf_counter()
            result = PIPELINE.run(intake, request_id=request_id).to_dict()
            result["server_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        except Exception as exc:  # noqa: BLE001
            STATS["triage_errors_total"] += 1
            logger.exception("triage_error request_id=%s", request_id)
            error_payload = {"error": {"code": "bad_request"}}
            if SETTINGS.debug:
                error_payload["error"]["message"] = str(exc)
            self._write_json(error_payload, code=HTTPStatus.BAD_REQUEST, request_id=request_id)
            return

        self._write_json(result, request_id=request_id)


def _openapi_spec() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "ClinicaFlow Demo API", "version": __version__},
        "paths": {
            "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/version": {"get": {"responses": {"200": {"description": "version"}}}},
            "/metrics": {"get": {"responses": {"200": {"description": "metrics"}}}},
            "/example": {"get": {"responses": {"200": {"description": "sample intake"}}}},
            "/triage": {"post": {"responses": {"200": {"description": "triage result"}}}},
        },
    }


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    logging.basicConfig(level=getattr(logging, SETTINGS.log_level, logging.INFO))
    server = ThreadingHTTPServer((host, port), ClinicaFlowHandler)
    print(f"ClinicaFlow demo server running at http://{host}:{port}")
    print("Open / in your browser for the demo UI")
    print("POST /triage, GET /health, GET /metrics, and GET /openapi.json are available")
    server.serve_forever()


if __name__ == "__main__":
    run()
