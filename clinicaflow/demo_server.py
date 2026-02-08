from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from clinicaflow.models import PatientIntake
from clinicaflow.pipeline import ClinicaFlowPipeline

PIPELINE = ClinicaFlowPipeline()


class ClinicaFlowHandler(BaseHTTPRequestHandler):
    def _set_headers(self, code: int = HTTPStatus.OK) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._set_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
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
    print("POST /triage and GET /health are available")
    server.serve_forever()


if __name__ == "__main__":
    run()
