from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
import unittest

from clinicaflow.demo_server import make_server
from clinicaflow.pipeline import ClinicaFlowPipeline
from clinicaflow.settings import Settings


def _start_server(*, settings: Settings):
    server = make_server("127.0.0.1", 0, settings=settings, pipeline=ClinicaFlowPipeline())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    return server, thread, base_url


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None):
    headers = headers or {}
    req = urllib.request.Request(url=url, method=method, data=body, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _sockets_permitted() -> bool:
    # Some sandboxes disable socket syscalls. Keep tests runnable in those environments.
    try:
        s = socket.socket()
        s.close()
        return True
    except PermissionError:
        return False


@unittest.skipUnless(_sockets_permitted(), "Sockets are not permitted in this execution environment")
class DemoServerTests(unittest.TestCase):
    def test_health_and_request_id_echo(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, headers, raw = _http("GET", base_url + "/health", headers={"X-Request-ID": "req123"})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "req123")
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
        finally:
            _stop_server(server, thread)

    def test_triage_happy_path(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            case = {
                "chief_complaint": "Chest tightness and can't catch breath for 30 minutes",
                "history": "history of diabetes",
                "vitals": {"heart_rate": 142, "systolic_bp": 82, "spo2": 90, "temperature_c": 37.2},
            }
            body = json.dumps(case).encode("utf-8")
            status, headers, raw = _http(
                "POST",
                base_url + "/triage",
                body=body,
                headers={"Content-Type": "application/json", "X-Request-ID": "triage1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "triage1")
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["request_id"], "triage1")
            self.assertIn(payload["risk_tier"], {"urgent", "critical"})
            self.assertTrue(isinstance(payload.get("trace"), list))
            self.assertGreaterEqual(len(payload["trace"]), 5)
        finally:
            _stop_server(server, thread)

    def test_triage_unsupported_media_type(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, _, raw = _http(
                "POST",
                base_url + "/triage",
                body=b"{}",
                headers={"Content-Type": "text/plain"},
            )
            self.assertEqual(status, 415)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "unsupported_media_type")
        finally:
            _stop_server(server, thread)

    def test_triage_invalid_json(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, _, raw = _http(
                "POST",
                base_url + "/triage",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "bad_json")
        finally:
            _stop_server(server, thread)

    def test_payload_too_large(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=50,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            big = json.dumps({"chief_complaint": "x" * 200}).encode("utf-8")
            status, _, raw = _http(
                "POST",
                base_url + "/triage",
                body=big,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 413)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "payload_too_large")
        finally:
            _stop_server(server, thread)


if __name__ == "__main__":
    unittest.main()
