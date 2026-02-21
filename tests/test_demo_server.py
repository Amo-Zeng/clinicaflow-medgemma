from __future__ import annotations

import json
import io
import socket
import threading
import urllib.error
import urllib.request
import unittest
import zipfile

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
            api_key="",
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

    def test_policy_pack_endpoint(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, headers, raw = _http("GET", base_url + "/policy_pack", headers={"X-Request-ID": "pol1"})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "pol1")
            payload = json.loads(raw.decode("utf-8"))
            self.assertIn("sha256", payload)
            self.assertIn("source", payload)
            self.assertIn("n_policies", payload)
            self.assertIsInstance(payload.get("policies"), list)
            self.assertGreater(int(payload.get("n_policies") or 0), 0)
        finally:
            _stop_server(server, thread)

    def test_safety_rules_endpoint(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, headers, raw = _http("GET", base_url + "/safety_rules", headers={"X-Request-ID": "rules1"})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "rules1")
            payload = json.loads(raw.decode("utf-8"))
            self.assertIn("safety_rules_version", payload)
            self.assertIn("red_flag_keywords", payload)
            self.assertIn("safety_trigger_catalog", payload)
            self.assertIsInstance(payload.get("safety_trigger_catalog"), list)
            self.assertGreater(len(payload.get("safety_trigger_catalog") or []), 0)
        finally:
            _stop_server(server, thread)

    def test_synthetic_benchmark_endpoint(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, _, raw = _http("GET", base_url + "/bench/synthetic?seed=17&n=25")
            self.assertEqual(status, 200)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload.get("seed"), 17)
            self.assertEqual(payload.get("n_cases"), 25)
            self.assertIn("summary", payload)
            self.assertIn("markdown", payload)
            self.assertIn("| Metric | Baseline | ClinicaFlow |", str(payload.get("markdown") or ""))
        finally:
            _stop_server(server, thread)

    def test_judge_pack_endpoint(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            case = {
                "chief_complaint": "Chest pain and dizziness for 30 minutes",
                "history": "history of hypertension",
                "vitals": {"heart_rate": 122, "systolic_bp": 92, "spo2": 96, "temperature_c": 37.0},
            }
            body = json.dumps(case).encode("utf-8")
            status, headers, raw = _http(
                "POST",
                base_url + "/judge_pack?set=standard&redact=1&include_synthetic=0",
                body=body,
                headers={"Content-Type": "application/json", "X-Request-ID": "judge1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "judge1")
            cd = headers.get("Content-Disposition") or ""
            self.assertIn("clinicaflow_judge_pack_", cd)

            buf = io.BytesIO(raw)
            with zipfile.ZipFile(buf) as zf:
                names = set(zf.namelist())
                self.assertIn("README.md", names)
                self.assertIn("judge_pack_manifest.json", names)
                self.assertIn("triage/intake.json", names)
                self.assertIn("triage/triage_result.json", names)
                self.assertIn("system/doctor.json", names)
                self.assertIn("system/metrics.json", names)
                self.assertIn("resources/policy_pack.json", names)
                self.assertIn("resources/safety_rules.json", names)
                self.assertIn("benchmarks/vignettes_standard.json", names)
                self.assertIn("benchmarks/vignettes_standard.md", names)
                self.assertIn("governance/governance_report_standard.md", names)
                self.assertIn("governance/failure_packet_standard.md", names)
                self.assertNotIn("benchmarks/synthetic_proxy.md", names)
        finally:
            _stop_server(server, thread)

    def test_head_supported_for_ui_and_static(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            status, headers, raw = _http("HEAD", base_url + "/", headers={"X-Request-ID": "head1"})
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "head1")
            self.assertIn(headers.get("X-ClinicaFlow-UI"), {"console", "legacy"})
            self.assertEqual(raw, b"")

            status, headers, raw = _http("HEAD", base_url + "/static/app.js")
            self.assertEqual(status, 200)
            self.assertIn("javascript", (headers.get("Content-Type") or "").lower())
            self.assertEqual(raw, b"")
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
            api_key="",
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
            api_key="",
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
            api_key="",
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
            api_key="",
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

    def test_fhir_bundle_accepts_wrapped_payload_without_rerun(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            case = {
                "chief_complaint": "Chest tightness and can't catch breath for 30 minutes",
                "history": "history of diabetes",
                "vitals": {"heart_rate": 142, "systolic_bp": 82, "spo2": 90, "temperature_c": 37.2},
            }

            # Run once to get a real result payload.
            triage_body = json.dumps(case).encode("utf-8")
            status, _, raw = _http(
                "POST",
                base_url + "/triage",
                body=triage_body,
                headers={"Content-Type": "application/json", "X-Request-ID": "triage-wrap-1"},
            )
            self.assertEqual(status, 200)
            triage_payload = json.loads(raw.decode("utf-8"))

            # Tamper the risk tier; the bundle should reflect the provided result (no rerun).
            triage_payload["risk_tier"] = "routine"

            wrapped = {"intake": case, "result": triage_payload, "checklist": [{"text": "Urgent clinician review", "checked": True}]}
            body = json.dumps(wrapped).encode("utf-8")
            status, headers, raw = _http(
                "POST",
                base_url + "/fhir_bundle?redact=1",
                body=body,
                headers={"Content-Type": "application/json", "X-Request-ID": "triage-wrap-1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "triage-wrap-1")
            bundle = json.loads(raw.decode("utf-8"))
            self.assertEqual(bundle.get("resourceType"), "Bundle")
            self.assertEqual(bundle.get("identifier", {}).get("value"), "triage-wrap-1")

            entries = bundle.get("entry") or []
            impressions = [e.get("resource") for e in entries if (e.get("resource") or {}).get("resourceType") == "ClinicalImpression"]
            self.assertTrue(impressions)
            summary = str(impressions[0].get("summary") or "")
            self.assertIn("routine", summary)

            tasks = [e.get("resource") for e in entries if (e.get("resource") or {}).get("resourceType") == "Task"]
            self.assertTrue(tasks)
        finally:
            _stop_server(server, thread)

    def test_audit_bundle_accepts_wrapped_payload_without_rerun(self) -> None:
        settings = Settings(
            debug=False,
            log_level="INFO",
            json_logs=False,
            max_request_bytes=262144,
            policy_top_k=2,
            policy_pack_path="",
            cors_allow_origin="*",
            api_key="",
        )
        server, thread, base_url = _start_server(settings=settings)
        try:
            case = {
                "chief_complaint": "Chest tightness and can't catch breath for 30 minutes",
                "history": "history of diabetes",
                "vitals": {"heart_rate": 142, "systolic_bp": 82, "spo2": 90, "temperature_c": 37.2},
            }

            triage_body = json.dumps(case).encode("utf-8")
            status, _, raw = _http(
                "POST",
                base_url + "/triage",
                body=triage_body,
                headers={"Content-Type": "application/json", "X-Request-ID": "triage-audit-1"},
            )
            self.assertEqual(status, 200)
            triage_payload = json.loads(raw.decode("utf-8"))
            triage_payload["risk_tier"] = "routine"

            wrapped = {"intake": case, "result": triage_payload, "checklist": [{"text": "Urgent clinician review", "checked": True}]}
            body = json.dumps(wrapped).encode("utf-8")

            status, headers, raw = _http(
                "POST",
                base_url + "/audit_bundle?redact=1",
                body=body,
                headers={"Content-Type": "application/json", "X-Request-ID": "triage-audit-1"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("X-Request-ID"), "triage-audit-1")
            self.assertEqual(headers.get("Content-Type"), "application/zip")

            buf = io.BytesIO(raw)
            with zipfile.ZipFile(buf, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("triage_result.json", names)
                self.assertIn("actions_checklist.json", names)
                self.assertIn("note.md", names)
                self.assertIn("report.html", names)
                triage_result = json.loads(zf.read("triage_result.json").decode("utf-8"))
                self.assertEqual(triage_result.get("risk_tier"), "routine")
        finally:
            _stop_server(server, thread)


if __name__ == "__main__":
    unittest.main()
