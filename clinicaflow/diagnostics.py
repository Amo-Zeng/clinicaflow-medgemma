from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from clinicaflow.policy_pack import load_policy_pack, policy_pack_sha256
from clinicaflow.settings import load_settings_from_env
from clinicaflow.version import __version__
from clinicaflow.inference.openai_compatible import circuit_breaker_status
from clinicaflow.privacy import phi_guard_enabled


def resolve_policy_pack_path() -> tuple[object, str]:
    """Return (path-like, human-readable source label)."""
    settings = load_settings_from_env()
    if settings.policy_pack_path:
        return settings.policy_pack_path, str(settings.policy_pack_path)

    from importlib.resources import files

    policy_path = files("clinicaflow.resources").joinpath("policy_pack.json")
    return policy_path, "package:clinicaflow.resources/policy_pack.json"


def collect_diagnostics() -> dict[str, Any]:
    """Collect safe runtime diagnostics (no secrets)."""
    settings = load_settings_from_env()
    policy_path, policy_source = resolve_policy_pack_path()

    try:
        policy_sha256 = policy_pack_sha256(policy_path)
        n_policies = len(load_policy_pack(policy_path))
    except Exception:  # noqa: BLE001
        policy_sha256 = ""
        n_policies = 0

    reasoning_backend = os.environ.get("CLINICAFLOW_REASONING_BACKEND", "deterministic").strip()
    reasoning_base_url = os.environ.get("CLINICAFLOW_REASONING_BASE_URL", "").strip()
    if not reasoning_base_url:
        raw_urls = os.environ.get("CLINICAFLOW_REASONING_BASE_URLS", "").strip()
        if raw_urls:
            reasoning_base_url = raw_urls.split(",", 1)[0].split("|", 1)[0].strip()
    reasoning_model = os.environ.get("CLINICAFLOW_REASONING_MODEL", "").strip()
    if reasoning_backend.strip().lower() == "gradio_space" and not reasoning_model:
        reasoning_model = os.environ.get("CLINICAFLOW_REASONING_GRADIO_API_NAME", "chat").strip() or "chat"
    if reasoning_backend.strip().lower() == "hf_inference" and not reasoning_base_url:
        from clinicaflow.inference.hf_inference import DEFAULT_HF_ROUTER_BASE_URL

        reasoning_base_url = DEFAULT_HF_ROUTER_BASE_URL
    reasoning_timeout_s = os.environ.get("CLINICAFLOW_REASONING_TIMEOUT_S", "").strip()
    reasoning_max_retries = os.environ.get("CLINICAFLOW_REASONING_MAX_RETRIES", "").strip()
    reasoning_api_key = os.environ.get("CLINICAFLOW_REASONING_API_KEY")

    connectivity = _check_reasoning_connectivity(
        backend=reasoning_backend,
        base_url=reasoning_base_url,
        model=reasoning_model,
        timeout_s=_safe_float(reasoning_timeout_s, default=1.2),
        api_key=reasoning_api_key,
    )

    comm_backend = os.environ.get("CLINICAFLOW_COMMUNICATION_BACKEND", "deterministic").strip()
    comm_base_url = os.environ.get("CLINICAFLOW_COMMUNICATION_BASE_URL", "").strip()
    if not comm_base_url:
        raw_urls = os.environ.get("CLINICAFLOW_COMMUNICATION_BASE_URLS", "").strip()
        if raw_urls:
            comm_base_url = raw_urls.split(",", 1)[0].split("|", 1)[0].strip()
    comm_base_url = comm_base_url or reasoning_base_url
    comm_model = os.environ.get("CLINICAFLOW_COMMUNICATION_MODEL", "").strip() or reasoning_model
    if comm_backend.strip().lower() == "gradio_space" and not comm_model:
        comm_model = os.environ.get("CLINICAFLOW_COMMUNICATION_GRADIO_API_NAME", "chat").strip() or "chat"
    if comm_backend.strip().lower() == "hf_inference" and not comm_base_url:
        from clinicaflow.inference.hf_inference import DEFAULT_HF_ROUTER_BASE_URL

        comm_base_url = DEFAULT_HF_ROUTER_BASE_URL
    comm_timeout_s = os.environ.get("CLINICAFLOW_COMMUNICATION_TIMEOUT_S", "").strip() or reasoning_timeout_s
    comm_max_retries = os.environ.get("CLINICAFLOW_COMMUNICATION_MAX_RETRIES", "").strip() or reasoning_max_retries
    comm_api_key = os.environ.get("CLINICAFLOW_COMMUNICATION_API_KEY")
    if comm_api_key is None:
        comm_api_key = reasoning_api_key
    comm_connectivity = _check_reasoning_connectivity(
        backend=comm_backend,
        base_url=comm_base_url,
        model=comm_model,
        timeout_s=_safe_float(comm_timeout_s, default=_safe_float(reasoning_timeout_s, default=1.2)),
        api_key=comm_api_key,
    )

    evidence_backend = os.environ.get("CLINICAFLOW_EVIDENCE_BACKEND", "local").strip().lower() or "local"
    evidence_timeout_s = os.environ.get("CLINICAFLOW_EVIDENCE_TIMEOUT_S", "").strip()
    evidence_max_results = os.environ.get("CLINICAFLOW_EVIDENCE_MAX_RESULTS", "").strip()
    evidence_connectivity = _check_evidence_connectivity(
        backend=evidence_backend,
        timeout_s=_safe_float(evidence_timeout_s, default=0.9),
    )

    payload: dict[str, Any] = {
        "version": __version__,
        "settings": {
            "debug": settings.debug,
            "log_level": settings.log_level,
            "json_logs": settings.json_logs,
            "max_request_bytes": settings.max_request_bytes,
            "policy_top_k": settings.policy_top_k,
            "cors_allow_origin": settings.cors_allow_origin,
            "api_key_configured": bool(settings.api_key),
        },
        "privacy": {
            "phi_guard_enabled": phi_guard_enabled(),
        },
        "policy_pack": {
            "source": policy_source,
            "sha256": policy_sha256,
            "n_policies": n_policies,
        },
        "evidence_backend": {
            "backend": evidence_backend,
            "timeout_s": evidence_timeout_s,
            "max_results": evidence_max_results,
            **evidence_connectivity,
        },
        "reasoning_backend": {
            "backend": reasoning_backend,
            "base_url": reasoning_base_url,
            "model": reasoning_model,
            "timeout_s": reasoning_timeout_s,
            "max_retries": reasoning_max_retries,
            **connectivity,
            "circuit_breaker": circuit_breaker_status(base_url=reasoning_base_url, model=reasoning_model)
            if reasoning_backend.strip().lower() in {"openai", "openai_compatible"}
            else {"configured": False, "open": False, "failures": 0, "remaining_s": 0.0, "last_error": ""},
        },
        "communication_backend": {
            "backend": comm_backend,
            "base_url": comm_base_url,
            "model": comm_model,
            "timeout_s": comm_timeout_s,
            "max_retries": comm_max_retries,
            **comm_connectivity,
            "circuit_breaker": circuit_breaker_status(base_url=comm_base_url, model=comm_model)
            if comm_backend.strip().lower() in {"openai", "openai_compatible"}
            else {"configured": False, "open": False, "failures": 0, "remaining_s": 0.0, "last_error": ""},
        },
    }

    return payload


def _safe_float(value: str, *, default: float) -> float:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _check_reasoning_connectivity(
    *,
    backend: str,
    base_url: str,
    model: str,
    timeout_s: float,
    api_key: str | None,
) -> dict[str, Any]:
    """Best-effort connectivity check for optional inference backends.

    Kept intentionally lightweight: short timeout, never raises, no secrets emitted.
    """

    backend = (backend or "").strip().lower()
    if backend == "hf_inference":
        if not base_url:
            from clinicaflow.inference.hf_inference import DEFAULT_HF_ROUTER_BASE_URL

            base_url = DEFAULT_HF_ROUTER_BASE_URL
        if not model:
            return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_MODEL"}

        url = base_url.rstrip("/") + "/models/" + urllib.parse.quote(model, safe="")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url=url, method="GET", headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=max(0.2, min(timeout_s, 2.0))) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw_preview": raw[:200]}
            return {"connectivity_ok": True, "hf": {"status_preview": payload}}
        except urllib.error.HTTPError as exc:
            try:
                body_preview = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:  # noqa: BLE001
                body_preview = ""
            return {"connectivity_ok": False, "connectivity_error": f"HTTP {exc.code}: {body_preview}".strip()}
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"connectivity_ok": False, "connectivity_error": str(exc)[:200]}

    if backend == "gradio_space":
        if not base_url:
            return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_BASE_URL"}
        url = base_url.rstrip("/") + "/config"
        headers = {"Accept": "application/json"}
        req = urllib.request.Request(url=url, method="GET", headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=max(0.2, min(timeout_s, 2.0))) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return {"connectivity_ok": False, "connectivity_error": "Invalid /config payload"}
            api_prefix = str(payload.get("api_prefix") or "").strip()
            mode = str(payload.get("mode") or "").strip()
            version = str(payload.get("version") or "").strip()
            deps = payload.get("dependencies")
            api_names: list[str] = []
            if isinstance(deps, list):
                for d in deps:
                    if isinstance(d, dict):
                        name = d.get("api_name")
                        if isinstance(name, str) and name.strip():
                            api_names.append(name.strip())
            return {
                "connectivity_ok": True,
                "gradio": {
                    "mode": mode,
                    "version": version,
                    "api_prefix": api_prefix,
                    "api_names_preview": api_names[:10],
                    "api_name_found": bool(model and model in api_names) if api_names else None,
                },
            }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            return {"connectivity_ok": False, "connectivity_error": str(exc)[:200]}

    if backend not in {"openai", "openai_compatible"}:
        return {"connectivity_ok": None}
    if not base_url:
        return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_BASE_URL"}
    if not model:
        return {"connectivity_ok": False, "connectivity_error": "Missing CLINICAFLOW_REASONING_MODEL"}

    url = base_url.rstrip("/") + "/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url=url, method="GET", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=max(0.2, min(timeout_s, 2.0))) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        models = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            mid = item.get("id")
            if isinstance(mid, str) and mid.strip():
                models.append(mid.strip())
        return {
            "connectivity_ok": True,
            "models_preview": models[:10],
            "model_found": bool(model and model in models) if models else None,
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {"connectivity_ok": False, "connectivity_error": str(exc)[:200]}


def _check_evidence_connectivity(*, backend: str, timeout_s: float) -> dict[str, Any]:
    """Best-effort connectivity check for free evidence APIs (no PHI)."""

    backend = (backend or "").strip().lower()
    if backend in {"", "local", "policy", "policy_pack", "none", "off", "disabled"}:
        return {"connectivity_ok": None}

    timeout_s = max(0.2, min(float(timeout_s), 2.0))

    def pubmed_ok() -> tuple[bool, str]:
        try:
            from clinicaflow.evidence import PUBMED_ESEARCH_URL

            params = {"db": "pubmed", "term": "triage", "retmode": "json", "retmax": "1"}
            url = PUBMED_ESEARCH_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            es = payload.get("esearchresult") if isinstance(payload, dict) else None
            idlist = es.get("idlist") if isinstance(es, dict) else None
            ok = isinstance(idlist, list)
            return ok, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    def medlineplus_ok() -> tuple[bool, str]:
        try:
            from clinicaflow.evidence import MEDLINEPLUS_WSEARCH_URL

            params = {"db": "healthTopics", "term": "Chest pain", "retmax": "1", "rettype": "brief"}
            url = MEDLINEPLUS_WSEARCH_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/xml"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                raw = resp.read()
            # A minimal parse check (structure can change).
            ET.fromstring(raw.decode("utf-8", errors="replace"))
            return True, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    def crossref_ok() -> tuple[bool, str]:
        try:
            from clinicaflow.evidence import CROSSREF_WORKS_URL

            params = {"query": "triage", "rows": "1"}
            url = CROSSREF_WORKS_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": "clinicaflow"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            msg = payload.get("message") if isinstance(payload, dict) else None
            items = msg.get("items") if isinstance(msg, dict) else None
            ok = isinstance(items, list)
            return ok, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    def openalex_ok() -> tuple[bool, str]:
        try:
            from clinicaflow.evidence import OPENALEX_WORKS_URL

            params = {"search": "triage", "per-page": "1"}
            email = str(os.environ.get("CLINICAFLOW_EVIDENCE_PUBMED_EMAIL", "") or "").strip()
            if email:
                params["mailto"] = email

            url = OPENALEX_WORKS_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": "clinicaflow"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            results = payload.get("results") if isinstance(payload, dict) else None
            ok = isinstance(results, list)
            return ok, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    def clinicaltrials_ok() -> tuple[bool, str]:
        try:
            from clinicaflow.evidence import CLINICALTRIALS_V2_STUDIES_URL

            params = {"query.term": "triage", "pageSize": "1"}
            url = CLINICALTRIALS_V2_STUDIES_URL + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json", "User-Agent": "clinicaflow"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            studies = payload.get("studies") if isinstance(payload, dict) else None
            ok = isinstance(studies, list)
            return ok, ""
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:200]

    if backend == "pubmed":
        ok, err = pubmed_ok()
        return {"connectivity_ok": ok, "connectivity_error": err}
    if backend == "medlineplus":
        ok, err = medlineplus_ok()
        return {"connectivity_ok": ok, "connectivity_error": err}
    if backend == "crossref":
        ok, err = crossref_ok()
        return {"connectivity_ok": ok, "connectivity_error": err}
    if backend == "openalex":
        ok, err = openalex_ok()
        return {"connectivity_ok": ok, "connectivity_error": err}
    if backend == "clinicaltrials":
        ok, err = clinicaltrials_ok()
        return {"connectivity_ok": ok, "connectivity_error": err}
    if backend == "auto":
        ok1, err1 = pubmed_ok()
        if ok1:
            return {"connectivity_ok": True, "connectivity_error": ""}
        ok2, err2 = medlineplus_ok()
        if ok2:
            return {"connectivity_ok": True, "connectivity_error": ""}
        ok3, err3 = crossref_ok()
        if ok3:
            return {"connectivity_ok": True, "connectivity_error": ""}
        ok4, err4 = openalex_ok()
        if ok4:
            return {"connectivity_ok": True, "connectivity_error": ""}
        ok5, err5 = clinicaltrials_ok()
        if ok5:
            return {"connectivity_ok": True, "connectivity_error": ""}
        err = "; ".join([x for x in [err1, err2, err3, err4, err5] if x])[:200]
        return {"connectivity_ok": False, "connectivity_error": err}

    return {"connectivity_ok": False, "connectivity_error": f"Unsupported backend: {backend}"}
