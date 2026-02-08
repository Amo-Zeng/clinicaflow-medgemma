from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline

PIPELINE = ClinicaFlowPipeline()

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
      <span class="hint">Endpoints: <code>GET /health</code>, <code>POST /triage</code>, <code>GET /example</code></span>
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
    def _set_headers(self, code: int = HTTPStatus.OK, *, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/demo"}:
            self._set_headers(content_type="text/html; charset=utf-8")
            self.wfile.write(DEMO_HTML.encode("utf-8"))
            return

        if self.path == "/health":
            self._set_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        if self.path == "/example":
            self._set_headers()
            self.wfile.write(json.dumps(SAMPLE_INTAKE, ensure_ascii=False).encode("utf-8"))
            return

        self._set_headers(HTTPStatus.NOT_FOUND)
        self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/triage":
            self._set_headers(HTTPStatus.NOT_FOUND)
            self.wfile.write(json.dumps({"error": "not found"}).encode("utf-8"))
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            intake = PatientIntake.from_mapping(payload)
            result = PIPELINE.run(intake).to_dict()
        except Exception as exc:  # noqa: BLE001
            self._set_headers(HTTPStatus.BAD_REQUEST)
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))
            return

        self._set_headers(HTTPStatus.OK)
        self.wfile.write(json.dumps(result).encode("utf-8"))


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    server = ThreadingHTTPServer((host, port), ClinicaFlowHandler)
    print(f"ClinicaFlow demo server running at http://{host}:{port}")
    print("Open / in your browser for the demo UI")
    print("POST /triage, GET /health, and GET /example are available")
    server.serve_forever()


if __name__ == "__main__":
    run()
