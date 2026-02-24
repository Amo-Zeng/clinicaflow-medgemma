from __future__ import annotations

from collections import deque
import hashlib
import io
import json
import logging
import math
import os
import statistics
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
from clinicaflow.rules import SAFETY_RULES_VERSION
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

RESET_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>ClinicaFlow Console Reset</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #0b1020;
        --panel: rgba(255, 255, 255, 0.06);
        --text: #e5e7eb;
        --muted: rgba(229, 231, 235, 0.72);
        --border: rgba(229, 231, 235, 0.18);
        --shadow: 0 1px 2px rgba(0,0,0,0.25), 0 18px 40px rgba(0,0,0,0.35);
        --radius: 14px;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: radial-gradient(1200px 600px at 20% 10%, rgba(79,70,229,0.16), transparent 60%), var(--bg);
        color: var(--text);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      }
      main { max-width: 880px; margin: 0 auto; padding: 22px; }
      .card {
        border: 1px solid var(--border);
        background: var(--panel);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
        padding: 18px 16px;
      }
      h1 { margin: 0; font-size: 18px; font-weight: 950; }
      p { margin: 10px 0 0; color: var(--muted); line-height: 1.45; }
      .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 14px; }
      .btn {
        border: 1px solid var(--border);
        background: rgba(255,255,255,0.06);
        color: var(--text);
        padding: 9px 12px;
        border-radius: 12px;
        cursor: pointer;
        font-weight: 900;
        text-decoration: none;
      }
      .btn.primary { background: rgba(79,70,229,0.35); border-color: rgba(79,70,229,0.55); }
      pre {
        margin: 14px 0 0;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: rgba(0,0,0,0.35);
        color: #d1d5db;
        overflow: auto;
        max-height: 340px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        font-size: 12px;
        white-space: pre-wrap;
      }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 12px; }
    </style>
  </head>
  <body>
    <main>
      <div class="card">
        <h1>Resetting ClinicaFlow Console cache…</h1>
        <p>
          This page clears <b>service workers</b>, <b>cache storage</b>, and local-only demo data to fix a common issue:
          the browser can get stuck on an old cached UI where buttons (like <code>Start 3-minute demo</code>) don't respond.
        </p>
        <div class="row">
          <button id="go" class="btn primary" type="button">Go to Console</button>
          <a class="btn" href="/" rel="noreferrer">Open /</a>
        </div>
        <pre id="log">Starting reset…</pre>
      </div>
    </main>
    <script>
      const log = (msg) => {
        const el = document.getElementById("log");
        if (!el) return;
        el.textContent = String(el.textContent || "").trim() + "\\n" + String(msg);
      };

      async function clear() {
        try {
          const keys = [];
          const n = Number(localStorage?.length || 0);
          for (let i = 0; i < n; i += 1) {
            const k = localStorage.key(i);
            if (k) keys.push(k);
          }
          keys.forEach((k) => {
            if (String(k || "").startsWith("clinicaflow.")) localStorage.removeItem(k);
          });
          log("localStorage: cleared clinicaflow.* keys");
        } catch (e) {
          log("localStorage: skip (" + e + ")");
        }

        try {
          if (window.caches && typeof window.caches.keys === "function") {
            const keys = await window.caches.keys();
            await Promise.all(keys.map((k) => window.caches.delete(k)));
            log("CacheStorage: deleted " + keys.length + " cache(s)");
          } else {
            log("CacheStorage: not available");
          }
        } catch (e) {
          log("CacheStorage: skip (" + e + ")");
        }

        try {
          if ("serviceWorker" in navigator && typeof navigator.serviceWorker.getRegistrations === "function") {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((r) => r.unregister()));
            log("ServiceWorker: unregistered " + regs.length + " registration(s)");
          } else {
            log("ServiceWorker: not available");
          }
        } catch (e) {
          log("ServiceWorker: skip (" + e + ")");
        }

        log("Done. Redirecting…");
        setTimeout(() => {
          try { window.location.replace("/?welcome=1"); } catch (e) { window.location.href = "/?welcome=1"; }
        }, 450);
      }

      document.getElementById("go")?.addEventListener("click", () => {
        try { window.location.replace("/?welcome=1"); } catch (e) { window.location.href = "/?welcome=1"; }
      });

      clear();
    </script>
  </body>
</html>
"""


def _static_asset_fingerprint(web_assets: dict[str, tuple[bytes, str]]) -> str:
    """Return a short fingerprint of the bundled UI assets.

    Used to avoid "stuck on stale UI" bugs when a browser keeps an old cached
    `app.js`/`app.css` while the server has been updated.
    """

    h = hashlib.sha256()
    # Intentionally do NOT include index.html here since we patch it with the
    # fingerprint (would create a circular dependency).
    for name in ("app.css", "app.js"):
        item = web_assets.get(name)
        if not item:
            continue
        h.update(item[0])
    return h.hexdigest()[:12]


def _patch_index_html(index_html: bytes, *, fingerprint: str) -> bytes:
    try:
        text = index_html.decode("utf-8")
    except UnicodeDecodeError:
        text = index_html.decode("utf-8", errors="replace")

    fp = str(fingerprint or "").strip()
    if not fp:
        return index_html

    # Cache-bust the two hot assets that tend to get stuck in browser HTTP cache.
    out = text.replace("/static/app.css", f"/static/app.css?v={fp}")
    out = out.replace("/static/app.js", f"/static/app.js?v={fp}")

    if out == text:
        return index_html

    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out.encode("utf-8")


def _patch_sw_cache_name(sw_js: bytes, *, fingerprint: str) -> bytes:
    try:
        text = sw_js.decode("utf-8")
    except UnicodeDecodeError:
        text = sw_js.decode("utf-8", errors="replace")

    cache_name = f"clinicaflow-static-{__version__}-{fingerprint}"
    out_lines: list[str] = []
    replaced = False
    fp = str(fingerprint or "").strip()

    for line in text.splitlines():
        if line.strip().startswith("const CACHE_NAME ="):
            out_lines.append(f'const CACHE_NAME = "{cache_name}";')
            replaced = True
            continue
        if fp and line.strip() == '"/static/app.css",':
            out_lines.append(f'  "/static/app.css?v={fp}",')
            continue
        if fp and line.strip() == '"/static/app.js",':
            out_lines.append(f'  "/static/app.js?v={fp}",')
            continue
        out_lines.append(line)

    if not replaced:
        return sw_js

    out = "\n".join(out_lines)
    if text.endswith("\n"):
        out += "\n"
    return out.encode("utf-8")


def _load_web_assets() -> dict[str, tuple[bytes, str]]:
    """Load bundled web assets (UI) from package resources."""

    assets = {
        "index.html": "text/html; charset=utf-8",
        "app.css": "text/css; charset=utf-8",
        "app.js": "application/javascript; charset=utf-8",
        "manifest.webmanifest": "application/manifest+json; charset=utf-8",
        "sw.js": "application/javascript; charset=utf-8",
        "icon.svg": "image/svg+xml; charset=utf-8",
    }

    # 1) Preferred: importlib.resources (works for normal installs and editable installs).
    try:
        from importlib.resources import files

        root = files("clinicaflow.resources").joinpath("web")
        out: dict[str, tuple[bytes, str]] = {}
        for name, content_type in assets.items():
            out[name] = (root.joinpath(name).read_bytes(), content_type)
        fp = _static_asset_fingerprint(out)
        if "index.html" in out:
            data, ct = out["index.html"]
            out["index.html"] = (_patch_index_html(data, fingerprint=fp), ct)
        if "sw.js" in out:
            data, ct = out["sw.js"]
            out["sw.js"] = (_patch_sw_cache_name(data, fingerprint=fp), ct)
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
            fp = _static_asset_fingerprint(out)
            if "index.html" in out:
                data, ct = out["index.html"]
                out["index.html"] = (_patch_index_html(data, fingerprint=fp), ct)
            if "sw.js" in out:
                data, ct = out["sw.js"]
                out["sw.js"] = (_patch_sw_cache_name(data, fingerprint=fp), ct)
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
        fp = _static_asset_fingerprint(out)
        if "index.html" in out:
            data, ct = out["index.html"]
            out["index.html"] = (_patch_index_html(data, fingerprint=fp), ct)
        if "sw.js" in out:
            data, ct = out["sw.js"]
            out["sw.js"] = (_patch_sw_cache_name(data, fingerprint=fp), ct)
        return out
    except Exception:  # noqa: BLE001
        return {}


WEB_ASSETS = _load_web_assets()
WEB_ASSETS_FINGERPRINT = _static_asset_fingerprint(WEB_ASSETS) if WEB_ASSETS else ""
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
        "judge_pack_requests_total": 0,
        "judge_pack_success_total": 0,
        "judge_pack_errors_total": 0,
        "fhir_bundle_requests_total": 0,
        "fhir_bundle_success_total": 0,
        "fhir_bundle_errors_total": 0,
        "triage_risk_tier_total": {"routine": 0, "urgent": 0, "critical": 0},
        "triage_reasoning_backend_total": {"deterministic": 0, "external": 0},
        "triage_communication_backend_total": {"deterministic": 0, "external": 0},
        "triage_evidence_backend_total": {"local": 0},
        "triage_latency_ms_sum": 0.0,
        "triage_latency_ms_count": 0,
        "triage_agent_latency_ms_sum": {a: 0.0 for a in agents},
        "triage_agent_latency_ms_count": {a: 0 for a in agents},
        "triage_agent_errors_total": {a: 0 for a in agents},
    }


def _metrics_window_size() -> int:
    raw = str(os.environ.get("CLINICAFLOW_METRICS_WINDOW", "200") or "").strip()
    try:
        value = int(raw or "200")
    except ValueError:
        value = 200
    return max(20, min(value, 5000))


def _new_recent_metrics(window: int) -> dict[str, object]:
    return {
        "triage_ok": deque(maxlen=window),
        "triage_latency_ms": deque(maxlen=window),
        "triage_agent_latency_ms": {},
    }


def _record_recent_triage(
    server: object,
    *,
    ok: bool,
    latency_ms: float | None = None,
    trace_rows: list[dict] | None = None,
) -> None:
    """Record best-effort rolling-window metrics (non-JSON)."""

    recent = getattr(server, "recent", None)
    if not isinstance(recent, dict):
        return

    try:
        okq = recent.get("triage_ok")
        if isinstance(okq, deque):
            okq.append(1 if ok else 0)

        if ok and latency_ms is not None:
            lq = recent.get("triage_latency_ms")
            if isinstance(lq, deque) and isinstance(latency_ms, (int, float)) and math.isfinite(float(latency_ms)):
                lq.append(float(latency_ms))

        if ok and trace_rows and isinstance(trace_rows, list):
            agent_lat = recent.get("triage_agent_latency_ms")
            if not isinstance(agent_lat, dict):
                agent_lat = {}
                recent["triage_agent_latency_ms"] = agent_lat
            window = int(getattr(server, "metrics_window", 200) or 200)
            for step in trace_rows:
                if not isinstance(step, dict):
                    continue
                agent = str(step.get("agent") or "").strip()
                if not agent:
                    continue
                v = step.get("latency_ms")
                if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                    continue
                dq = agent_lat.get(agent)
                if not isinstance(dq, deque):
                    dq = deque(maxlen=window)
                    agent_lat[agent] = dq
                dq.append(float(v))
    except Exception:  # noqa: BLE001
        return


def _finite_floats(values: object) -> list[float]:
    out: list[float] = []
    if not values:
        return out
    try:
        for item in values:
            if not isinstance(item, (int, float)):
                continue
            value = float(item)
            if math.isfinite(value):
                out.append(value)
    except TypeError:
        return out
    return out


def _percentile_nearest_rank(values: list[float], p: float) -> float | None:
    vals = _finite_floats(values)
    if not vals:
        return None
    pp = float(p)
    if pp <= 0.0:
        return float(min(vals))
    if pp >= 1.0:
        return float(max(vals))
    vals.sort()
    idx = max(0, min(len(vals) - 1, int(math.ceil(pp * len(vals))) - 1))
    return float(vals[idx])


def _safe_median(values: list[float]) -> float | None:
    vals = _finite_floats(values)
    if not vals:
        return None
    return float(statistics.median(vals))


def _compute_recent_metrics(server: object) -> dict[str, object]:
    recent = getattr(server, "recent", None)
    if not isinstance(recent, dict):
        return {}

    ok_hist = recent.get("triage_ok")
    ok_list = list(ok_hist) if isinstance(ok_hist, deque) else []
    recent_total = len(ok_list)
    recent_errors = sum(1 for x in ok_list if not x)
    err_rate = (float(recent_errors) / float(recent_total)) if recent_total else None

    lat_hist = recent.get("triage_latency_ms")
    lats = list(lat_hist) if isinstance(lat_hist, deque) else []

    agent_lat = recent.get("triage_agent_latency_ms")
    agent_p50: dict[str, float] = {}
    agent_p95: dict[str, float] = {}
    agent_avg: dict[str, float] = {}
    agent_n: dict[str, int] = {}
    if isinstance(agent_lat, dict):
        for agent, dq in agent_lat.items():
            if not isinstance(dq, deque) or not dq:
                continue
            agent_name = str(agent)
            values = list(dq)
            agent_n[agent_name] = len(values)
            try:
                agent_avg[agent_name] = round(float(statistics.mean(_finite_floats(values))), 2)
            except statistics.StatisticsError:
                pass
            p50 = _safe_median(values)
            p95 = _percentile_nearest_rank(values, 0.95)
            if p50 is not None:
                agent_p50[agent_name] = round(float(p50), 2)
            if p95 is not None:
                agent_p95[agent_name] = round(float(p95), 2)

    p50_total = _safe_median(lats)
    p95_total = _percentile_nearest_rank(lats, 0.95)
    avg_window = None
    try:
        avg_window = round(float(statistics.mean(_finite_floats(lats))), 2) if lats else None
    except statistics.StatisticsError:
        avg_window = None

    return {
        "triage_recent_window_n": recent_total,
        "triage_recent_error_rate": round(float(err_rate), 4) if isinstance(err_rate, float) else None,
        "triage_latency_ms_window_n": len(lats),
        "triage_latency_ms_avg_window": avg_window,
        "triage_latency_ms_p50": round(float(p50_total), 2) if p50_total is not None else None,
        "triage_latency_ms_p95": round(float(p95_total), 2) if p95_total is not None else None,
        "triage_agent_latency_ms_window_n": agent_n,
        "triage_agent_latency_ms_avg_window": agent_avg,
        "triage_agent_latency_ms_p50": agent_p50,
        "triage_agent_latency_ms_p95": agent_p95,
    }


def _build_metrics_payload(server: object) -> dict[str, object]:
    stats = getattr(server, "stats", None)
    start = getattr(server, "start_time", None)

    uptime_s = int(time.time() - float(start or time.time()))
    count = int((stats or {}).get("triage_latency_ms_count") or 0) if isinstance(stats, dict) else 0
    total = float((stats or {}).get("triage_latency_ms_sum") or 0.0) if isinstance(stats, dict) else 0.0
    avg = round(total / count, 2) if count else 0.0

    payload: dict[str, object] = {
        "uptime_s": uptime_s,
        "version": __version__,
        "metrics_window_max_n": int(getattr(server, "metrics_window", 0) or 0),
        "triage_latency_ms_avg": avg,
    }
    if isinstance(stats, dict):
        payload.update(stats)
    payload.update(_compute_recent_metrics(server))
    return payload


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
        self.metrics_window = _metrics_window_size()
        self.recent = _new_recent_metrics(self.metrics_window)


class ClinicaFlowHandler(BaseHTTPRequestHandler):
    server_version = "ClinicaFlowHTTP/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: N802
        # Suppress BaseHTTPRequestHandler's default access logs; we emit structured logs instead.
        return

    def _content_security_policy(self, *, ui: str) -> str:
        ui = str(ui or "").strip().lower() or "console"
        script_src = "'self'" if ui == "console" else "'self' 'unsafe-inline'"
        # Keep the policy compatible with:
        # - data/blob images (synthetic uploads)
        # - service worker
        # - inline style attributes (small UI tweaks); prefer removing over time.
        return (
            "default-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            f"script-src {script_src}; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "manifest-src 'self'; "
            "worker-src 'self'"
        )

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
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Permitted-Cross-Domain-Policies", "none")
        if str(content_type or "").lower().startswith("text/html"):
            ui = "console"
            if extra_headers and isinstance(extra_headers, dict):
                ui = str(extra_headers.get("X-ClinicaFlow-UI") or ui)
            self.send_header("Content-Security-Policy", self._content_security_policy(ui=ui))
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
                reset_raw = str(query.get("reset", [""])[0]).strip().lower()
                if reset_raw in {"1", "true", "yes", "y", "on"}:
                    data, content_type = (RESET_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    ui = "reset"
                elif HAS_CONSOLE_UI:
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
                cache_control = "public, max-age=3600"
                if name in {"sw.js", "manifest.webmanifest"}:
                    # Browsers aggressively cache service-workers; keep it fresh.
                    cache_control = "no-store"
                self._write_bytes(
                    data,
                    content_type=content_type,
                    request_id=request_id,
                    extra_headers={"Cache-Control": cache_control, "X-ClinicaFlow-Static-Version": WEB_ASSETS_FINGERPRINT},
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

            if path == "/ping":
                # Deep ping: runs a tiny inference call (no PHI) to verify the
                # configured backend can actually serve requests. This can be
                # slower than `/doctor` (which is mostly a config/connectivity check).
                if self.server.settings.api_key and not is_authorized(headers=self.headers, expected_api_key=self.server.settings.api_key):
                    self._write_json(
                        {"error": {"code": "unauthorized"}},
                        code=HTTPStatus.UNAUTHORIZED,
                        request_id=request_id,
                        extra_headers={"WWW-Authenticate": "Bearer"},
                    )
                    status_code = HTTPStatus.UNAUTHORIZED
                    return

                which_raw = str(query.get("which", ["all"])[0]).strip().lower() or "all"
                if which_raw not in {"reasoning", "communication", "all"}:
                    self._write_json(
                        {"error": {"code": "bad_request", "message": "which must be reasoning|communication|all"}},
                        code=HTTPStatus.BAD_REQUEST,
                        request_id=request_id,
                    )
                    status_code = HTTPStatus.BAD_REQUEST
                    return

                from clinicaflow.inference.ping import ping_inference_backend

                payload: dict[str, object] = {"ok": True, "which": which_raw, "version": __version__}
                ok = True
                if which_raw in {"reasoning", "all"}:
                    res = ping_inference_backend(env_prefix="CLINICAFLOW_REASONING")
                    payload["reasoning"] = res
                    ok = ok and bool(res.get("ok"))
                if which_raw in {"communication", "all"}:
                    res = ping_inference_backend(env_prefix="CLINICAFLOW_COMMUNICATION")
                    payload["communication"] = res
                    ok = ok and bool(res.get("ok"))
                payload["ok"] = ok

                self._write_json(payload, request_id=request_id)
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
                payload = _build_metrics_payload(self.server)
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
                        {
                            "id": str(row.get("id", "")),
                            "chief_complaint": str((row.get("input") or {}).get("chief_complaint", "")),
                            "source_type": str((row.get("source") or {}).get("type") or "") if isinstance(row.get("source"), dict) else "",
                            "source_url": str((row.get("source") or {}).get("url") or "") if isinstance(row.get("source"), dict) else "",
                        }
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
                out = {
                    "id": vid,
                    "set": set_name,
                    "input": dict(row.get("input") or {}),
                    "source": dict(row.get("source") or {}) if isinstance(row.get("source"), dict) else None,
                    "rationale": str(row.get("rationale") or "").strip(),
                }
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

            if path == "/review_packet":
                from clinicaflow.benchmarks.review_packet import build_review_packet_markdown

                set_name = _normalize_vignette_set(str(query.get("set", ["standard"])[0]))
                include_gold = str(query.get("include_gold", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                limit_raw = str(query.get("limit", ["30"])[0]).strip()
                try:
                    limit = int(limit_raw or "30")
                except ValueError:
                    limit = 30
                limit = max(1, min(limit, 200))

                rows = _load_vignettes(set_name)[:limit]
                md = build_review_packet_markdown(
                    rows=rows,
                    set_name=set_name,
                    include_gold=include_gold,
                    pipeline=self.server.pipeline,
                )
                filename = f"clinicaflow_clinician_review_packet_{set_name}.md"
                self._write_bytes(
                    md.encode("utf-8"),
                    content_type="text/markdown; charset=utf-8",
                    request_id=request_id,
                    extra_headers={
                        "Cache-Control": "no-store",
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    },
                )
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

            if path not in {"/triage", "/triage_stream", "/audit_bundle", "/judge_pack", "/fhir_bundle"}:
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
                if path in {"/triage", "/triage_stream"}:
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                elif path == "/judge_pack":
                    self.server.stats["judge_pack_errors_total"] += 1
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
                if path in {"/triage", "/triage_stream"}:
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                elif path == "/judge_pack":
                    self.server.stats["judge_pack_errors_total"] += 1
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
                intake_payload, result_payload, checklist, case_meta = _unwrap_intake_payload(payload)
            except ValueError as exc:
                if path in {"/triage", "/triage_stream"}:
                    self.server.stats["triage_errors_total"] += 1
                elif path == "/audit_bundle":
                    self.server.stats["audit_bundle_errors_total"] += 1
                elif path == "/judge_pack":
                    self.server.stats["judge_pack_errors_total"] += 1
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

            if path == "/triage_stream":
                self.server.stats["triage_requests_total"] += 1
                triage_started = time.perf_counter()

                self._set_headers(
                    HTTPStatus.OK,
                    content_type="application/x-ndjson; charset=utf-8",
                    request_id=request_id,
                    extra_headers={
                        "Cache-Control": "no-store",
                        # Helpful when users run behind reverse proxies that buffer responses.
                        "X-Accel-Buffering": "no",
                    },
                )
                if getattr(self, "_head_only", False):
                    status_code = HTTPStatus.OK
                    return

                def emit(event: dict) -> None:
                    self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                    try:
                        self.wfile.flush()
                    except Exception:  # noqa: BLE001
                        pass

                try:
                    result_obj = self.server.pipeline.run(intake, request_id=request_id, emit=emit)
                except (BrokenPipeError, ConnectionResetError):  # pragma: no cover
                    # Client disconnected; stop work quietly.
                    logger.info("triage_stream_client_disconnected", extra={"event": "triage_stream_client_disconnected", "request_id": request_id})
                    status_code = HTTPStatus.OK
                    return
                except Exception as exc:  # noqa: BLE001
                    self.server.stats["triage_errors_total"] += 1
                    _record_recent_triage(self.server, ok=False)
                    logger.exception("triage_stream_error", extra={"event": "triage_stream_error", "request_id": request_id})
                    msg = str(exc) if self.server.settings.debug else ""
                    try:
                        emit({"type": "error", "error": {"code": "internal_error", "message": msg}})
                    except Exception:  # noqa: BLE001
                        pass
                    status_code = HTTPStatus.OK
                    return

                result = result_obj.to_dict()
                result["server_latency_ms"] = round((time.perf_counter() - triage_started) * 1000, 2)
                emit({"type": "final", "result": result})

                self.server.stats["triage_success_total"] += 1
                risk_tier = str(result.get("risk_tier") or "")
                if risk_tier in self.server.stats["triage_risk_tier_total"]:
                    self.server.stats["triage_risk_tier_total"][risk_tier] += 1

                backend = _extract_reasoning_backend(result)
                if backend in self.server.stats["triage_reasoning_backend_total"]:
                    self.server.stats["triage_reasoning_backend_total"][backend] += 1

                comm_backend = _extract_communication_backend(result)
                if comm_backend in self.server.stats["triage_communication_backend_total"]:
                    self.server.stats["triage_communication_backend_total"][comm_backend] += 1

                evidence_backend = _extract_evidence_backend(result)
                if evidence_backend:
                    self.server.stats["triage_evidence_backend_total"][evidence_backend] = (
                        int(self.server.stats["triage_evidence_backend_total"].get(evidence_backend) or 0) + 1
                    )

                latency = float(result.get("total_latency_ms") or 0.0)
                self.server.stats["triage_latency_ms_sum"] += latency
                self.server.stats["triage_latency_ms_count"] += 1

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
                        else:
                            out = step.get("output") or {}
                            derived = ""
                            if isinstance(out, dict) and agent == "multimodal_reasoning":
                                derived = str(out.get("reasoning_backend_error") or "").strip()
                            elif isinstance(out, dict) and agent == "communication":
                                derived = str(out.get("communication_backend_error") or "").strip()
                            if derived:
                                self.server.stats["triage_agent_errors_total"][agent] += 1

                _record_recent_triage(
                    self.server,
                    ok=True,
                    latency_ms=latency,
                    trace_rows=trace_rows if isinstance(trace_rows, list) else None,
                )

                logger.info(
                    "triage_stream_complete",
                    extra={
                        "event": "triage_stream_complete",
                        "request_id": request_id,
                        "risk_tier": result.get("risk_tier"),
                        "escalation_required": result.get("escalation_required"),
                        "latency_ms": result.get("total_latency_ms"),
                        "reasoning_backend": backend,
                        "communication_backend": comm_backend,
                        "evidence_backend": evidence_backend,
                    },
                )

                status_code = HTTPStatus.OK
                return

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

                comm_backend = _extract_communication_backend(result)
                if comm_backend in self.server.stats["triage_communication_backend_total"]:
                    self.server.stats["triage_communication_backend_total"][comm_backend] += 1

                evidence_backend = _extract_evidence_backend(result)
                if evidence_backend:
                    self.server.stats["triage_evidence_backend_total"][evidence_backend] = (
                        int(self.server.stats["triage_evidence_backend_total"].get(evidence_backend) or 0) + 1
                    )

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
                        else:
                            # Some agent failures are recorded in output fields rather than the trace-level
                            # `error` field (e.g., external inference fallback). Count these as errors so
                            # ops dashboards reflect backend instability.
                            out = step.get("output") or {}
                            derived = ""
                            if isinstance(out, dict) and agent == "multimodal_reasoning":
                                derived = str(out.get("reasoning_backend_error") or "").strip()
                            elif isinstance(out, dict) and agent == "communication":
                                derived = str(out.get("communication_backend_error") or "").strip()
                            if derived:
                                self.server.stats["triage_agent_errors_total"][agent] += 1

                _record_recent_triage(
                    self.server,
                    ok=True,
                    latency_ms=latency,
                    trace_rows=trace_rows if isinstance(trace_rows, list) else None,
                )

                logger.info(
                    "triage_complete",
                    extra={
                        "event": "triage_complete",
                        "request_id": request_id,
                        "risk_tier": result.get("risk_tier"),
                        "escalation_required": result.get("escalation_required"),
                        "latency_ms": result.get("total_latency_ms"),
                        "reasoning_backend": backend,
                        "communication_backend": comm_backend,
                        "evidence_backend": evidence_backend,
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
                files = build_audit_bundle_files(
                    intake=intake,
                    result=result_obj,
                    redact=redact,
                    checklist=checklist,
                    case_meta=case_meta,
                )

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

            if path == "/judge_pack":
                self.server.stats["judge_pack_requests_total"] += 1
                set_name = _normalize_vignette_set(str(query.get("set", ["mega"])[0]))
                redact = str(query.get("redact", ["1"])[0]).strip().lower() in {"1", "true", "yes"}
                include_synthetic = str(query.get("include_synthetic", ["1"])[0]).strip().lower() in {"1", "true", "yes"}

                result_obj = existing_result or self.server.pipeline.run(intake, request_id=request_id)
                pack_request_id = result_obj.request_id or request_id

                from clinicaflow.audit import build_audit_bundle_files

                files: dict[str, bytes] = {}

                readme_lines = [
                    "# ClinicaFlow — Judge Pack (synthetic)",
                    "",
                    "- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.",
                    f"- request_id: `{pack_request_id}`",
                    f"- redacted: `{redact}`",
                    f"- vignette_set: `{set_name}`",
                    f"- include_synthetic_proxy: `{include_synthetic}`",
                    "",
                    "## Contents",
                    "",
                    "- `triage/`: audit bundle (intake/result/note/report + manifest)",
                    "- `system/`: runtime diagnostics and metrics snapshot",
                    "- `resources/`: policy pack + deterministic safety rules",
                    "- `benchmarks/`: vignette summary (+ optional synthetic proxy)",
                    "- `governance/`: governance report + failure analysis packet",
                    "",
                    "## Reproduce",
                    "",
                    "- Run demo UI: `bash scripts/demo_one_click.sh`",
                    "- Governance gate: `clinicaflow benchmark governance --set mega --gate`",
                    "",
                ]
                files["README.md"] = ("\n".join(readme_lines).strip() + "\n").encode("utf-8")

                # Optional: include competition-facing docs when running from a source checkout.
                try:
                    from pathlib import Path

                    repo_root = Path(__file__).resolve().parent.parent
                    candidates = [
                        (repo_root / "champion_writeup_medgemma.md", "submission/champion_writeup_medgemma.md"),
                        (repo_root / "README.md", "submission/REPO_README.md"),
                        (repo_root / "docs" / "JUDGES.md", "submission/JUDGES.md"),
                        (repo_root / "docs" / "VIDEO_SCRIPT.md", "submission/VIDEO_SCRIPT.md"),
                        (repo_root / "docs" / "VIGNETTE_REGRESSION.md", "submission/VIGNETTE_REGRESSION.md"),
                        (repo_root / "docs" / "MEDGEMMA_INTEGRATION.md", "submission/MEDGEMMA_INTEGRATION.md"),
                        (repo_root / "docs" / "SAFETY.md", "submission/SAFETY.md"),
                    ]
                    for src, dst in candidates:
                        if src.is_file():
                            files[dst] = src.read_bytes()
                except Exception:  # noqa: BLE001
                    pass

                audit_files = build_audit_bundle_files(
                    intake=intake,
                    result=result_obj,
                    redact=redact,
                    checklist=checklist,
                    case_meta=case_meta,
                )
                for name, data in audit_files.items():
                    files[f"triage/{name}"] = data

                from clinicaflow.diagnostics import collect_diagnostics

                files["system/doctor.json"] = json.dumps(collect_diagnostics(), indent=2, ensure_ascii=False).encode("utf-8")

                metrics_payload = _build_metrics_payload(self.server)
                files["system/metrics.json"] = json.dumps(metrics_payload, indent=2, ensure_ascii=False).encode("utf-8")

                from clinicaflow.rules import safety_rules_catalog

                files["resources/safety_rules.json"] = json.dumps(safety_rules_catalog(), indent=2, ensure_ascii=False).encode("utf-8")

                from importlib.resources import files as pkg_files

                from clinicaflow.policy_pack import load_policy_pack, policy_pack_sha256

                if self.server.settings.policy_pack_path:
                    policy_source = self.server.settings.policy_pack_path
                    policy_path: object = self.server.settings.policy_pack_path
                else:
                    policy_source = "package:clinicaflow.resources/policy_pack.json"
                    policy_path = pkg_files("clinicaflow.resources").joinpath("policy_pack.json")

                policies = load_policy_pack(policy_path)
                policy_payload = {
                    "source": str(policy_source),
                    "sha256": policy_pack_sha256(policy_path),
                    "n_policies": len(policies),
                    "policies": [p.to_dict() for p in policies],
                }
                files["resources/policy_pack.json"] = json.dumps(policy_payload, indent=2, ensure_ascii=False).encode("utf-8")

                from clinicaflow.benchmarks.vignettes import run_benchmark_rows

                vignette_rows = _load_vignettes(set_name)
                summary, per_case = run_benchmark_rows(vignette_rows)
                bench_payload = {"set": set_name, "summary": summary.to_dict(), "per_case": per_case}
                files[f"benchmarks/vignettes_{set_name}.json"] = json.dumps(bench_payload, indent=2, ensure_ascii=False).encode("utf-8")
                files[f"benchmarks/vignettes_{set_name}.md"] = (summary.to_markdown_table().strip() + "\n").encode("utf-8")

                from clinicaflow.benchmarks.governance import (
                    compute_action_provenance,
                    compute_gate,
                    compute_ops_slo,
                    compute_trigger_coverage,
                    to_failure_packet_markdown,
                    to_governance_markdown,
                )

                gate = compute_gate(summary, min_red_flag_recall=99.9)
                provenance = compute_action_provenance(per_case)
                triggers = compute_trigger_coverage(per_case, top_k=20)
                ops = compute_ops_slo(per_case)
                files[f"governance/governance_report_{set_name}.md"] = to_governance_markdown(
                    set_name=set_name,
                    summary=summary,
                    gate=gate,
                    provenance=provenance,
                    triggers=triggers,
                    ops=ops,
                ).encode("utf-8")
                files[f"governance/failure_packet_{set_name}.md"] = to_failure_packet_markdown(
                    set_name=set_name,
                    rows=vignette_rows,
                    per_case=per_case,
                    summary=summary,
                    gate=gate,
                    limit=25,
                ).encode("utf-8")

                if include_synthetic:
                    from clinicaflow.benchmarks.synthetic import run_benchmark

                    syn = run_benchmark(seed=17, n_cases=220)
                    files["benchmarks/synthetic_proxy.json"] = json.dumps(
                        {"seed": 17, "n_cases": 220, "summary": syn.to_dict()},
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8")
                    files["benchmarks/synthetic_proxy.md"] = (syn.to_markdown_table().strip() + "\n").encode("utf-8")

                files["judge_pack_manifest.json"] = json.dumps(
                    {
                        "request_id": pack_request_id,
                        "redacted": redact,
                        "vignette_set": set_name,
                        "include_synthetic_proxy": include_synthetic,
                        **({"case_meta": case_meta} if isinstance(case_meta, dict) and case_meta else {}),
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8")

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for name, data in files.items():
                        zf.writestr(name, data)

                self.server.stats["judge_pack_success_total"] += 1
                filename = f"clinicaflow_judge_pack_{pack_request_id}.zip"
                self._write_bytes(
                    buf.getvalue(),
                    content_type="application/zip",
                    request_id=pack_request_id,
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
            if urlparse(self.path).path in {"/triage", "/triage_stream"}:
                self.server.stats["triage_errors_total"] += 1
                _record_recent_triage(self.server, ok=False)
            elif urlparse(self.path).path == "/audit_bundle":
                self.server.stats["audit_bundle_errors_total"] += 1
            elif urlparse(self.path).path == "/judge_pack":
                self.server.stats["judge_pack_errors_total"] += 1
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


def _unwrap_intake_payload(payload: dict) -> tuple[dict, dict | None, Any, dict | None]:
    """Support both legacy and UI-export payload formats.

    - Legacy: {chief_complaint: ..., vitals: ...}
    - UI export: {intake: {...}, result: {...}, checklist: [...]}
    """

    if "intake" not in payload:
        intake_payload = dict(payload)
        case_meta = intake_payload.pop("case_meta", None)
        return intake_payload, None, None, (case_meta if isinstance(case_meta, dict) else None)

    intake = payload.get("intake")
    if not isinstance(intake, dict):
        raise ValueError("Expected `intake` to be a JSON object.")

    result = payload.get("result")
    result_payload = result if isinstance(result, dict) else None
    case_meta = payload.get("case_meta")
    return dict(intake), result_payload, payload.get("checklist"), (case_meta if isinstance(case_meta, dict) else None)


def _normalize_vignette_set(value: str) -> str:
    key = str(value or "").strip().lower()
    if key in {"standard", "adversarial", "extended", "realworld", "case_reports", "all", "mega", "ultra"}:
        return key
    return "standard"


def _openapi_spec() -> dict:
    intake_example = SAMPLE_INTAKE
    triage_example = {
        "run_id": "example_run_id",
        "request_id": "example_request_id",
        "created_at": "2026-02-21T00:00:00+00:00",
        "pipeline_version": __version__,
        "total_latency_ms": 123.4,
        "risk_tier": "critical",
        "escalation_required": True,
        "differential_considerations": ["Acute coronary syndrome", "Pulmonary embolism", "GERD"],
        "red_flags": ["Potential acute coronary syndrome", "Hypotension", "Respiratory compromise risk"],
        "recommended_next_actions": ["Emergency evaluation now (ED / call local emergency services).", "Urgent clinician review"],
        "clinician_handoff": "Clinician handoff (SBAR draft):\\n…",
        "patient_summary": "Decision support only — this is not a diagnosis.\\n…",
        "confidence": 0.72,
        "uncertainty_reasons": ["High-acuity case requires clinician confirmation"],
        "trace": [
            {"agent": "intake_structuring", "output": {}, "latency_ms": 4.1, "error": None},
            {"agent": "multimodal_reasoning", "output": {"reasoning_backend": "deterministic"}, "latency_ms": 22.5, "error": None},
            {"agent": "evidence_policy", "output": {}, "latency_ms": 1.7, "error": None},
            {"agent": "safety_escalation", "output": {"safety_rules_version": SAFETY_RULES_VERSION}, "latency_ms": 2.2, "error": None},
            {"agent": "communication", "output": {}, "latency_ms": 1.4, "error": None},
        ],
    }

    return {
        "openapi": "3.0.0",
        "info": {
            "title": "ClinicaFlow Demo API",
            "version": __version__,
            "description": (
                "ClinicaFlow is a demo/competition scaffold for agentic triage decision support. "
                "It is NOT a diagnostic device. Use synthetic data only (no PHI)."
            ),
        },
        "components": {
            "securitySchemes": {
                "ApiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            },
            "schemas": {
                "Vitals": {
                    "type": "object",
                    "properties": {
                        "heart_rate": {"type": "number", "nullable": True},
                        "systolic_bp": {"type": "number", "nullable": True},
                        "diastolic_bp": {"type": "number", "nullable": True},
                        "temperature_c": {"type": "number", "nullable": True},
                        "spo2": {"type": "number", "nullable": True},
                        "respiratory_rate": {"type": "number", "nullable": True},
                    },
                },
                "PatientIntake": {
                    "type": "object",
                    "required": ["chief_complaint"],
                    "properties": {
                        "chief_complaint": {"type": "string"},
                        "history": {"type": "string"},
                        "demographics": {"type": "object"},
                        "vitals": {"$ref": "#/components/schemas/Vitals"},
                        "image_descriptions": {"type": "array", "items": {"type": "string"}},
                        "prior_notes": {"type": "array", "items": {"type": "string"}},
                        # Multimodal demo support: data URLs (data:image/...;base64,...)
                        "image_data_urls": {"type": "array", "items": {"type": "string"}},
                    },
                    "example": intake_example,
                },
                "AgentTrace": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string"},
                        "output": {"type": "object"},
                        "latency_ms": {"type": "number", "nullable": True},
                        "error": {"type": "string", "nullable": True},
                    },
                    "required": ["agent", "output"],
                },
                "TriageResult": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "request_id": {"type": "string"},
                        "created_at": {"type": "string"},
                        "pipeline_version": {"type": "string"},
                        "total_latency_ms": {"type": "number"},
                        "risk_tier": {"type": "string", "enum": ["routine", "urgent", "critical"]},
                        "escalation_required": {"type": "boolean"},
                        "differential_considerations": {"type": "array", "items": {"type": "string"}},
                        "red_flags": {"type": "array", "items": {"type": "string"}},
                        "recommended_next_actions": {"type": "array", "items": {"type": "string"}},
                        "clinician_handoff": {"type": "string"},
                        "patient_summary": {"type": "string"},
                        "confidence": {"type": "number"},
                        "uncertainty_reasons": {"type": "array", "items": {"type": "string"}},
                        "trace": {"type": "array", "items": {"$ref": "#/components/schemas/AgentTrace"}},
                    },
                    "required": [
                        "run_id",
                        "request_id",
                        "created_at",
                        "pipeline_version",
                        "total_latency_ms",
                        "risk_tier",
                        "escalation_required",
                        "differential_considerations",
                        "red_flags",
                        "recommended_next_actions",
                        "clinician_handoff",
                        "patient_summary",
                        "confidence",
                        "uncertainty_reasons",
                        "trace",
                    ],
                    "example": triage_example,
                },
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string", "nullable": True},
                            },
                            "required": ["code"],
                        }
                    },
                    "required": ["error"],
                },
                "TriageStreamEvent": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "index": {"type": "integer", "nullable": True},
                        "agent": {"type": "string", "nullable": True},
                        "trace": {"$ref": "#/components/schemas/AgentTrace"},
                        "result": {"$ref": "#/components/schemas/TriageResult"},
                        "error": {"type": "object", "nullable": True},
                    },
                    "required": ["type"],
                },
            },
        },
        "paths": {
            "/health": {"get": {"summary": "Liveness probe", "responses": {"200": {"description": "ok"}}}},
            "/ready": {"get": {"summary": "Readiness probe", "responses": {"200": {"description": "ok"}}}},
            "/live": {"get": {"summary": "Liveness probe alias", "responses": {"200": {"description": "ok"}}}},
            "/version": {"get": {"summary": "Server version", "responses": {"200": {"description": "version"}}}},
            "/doctor": {
                "get": {
                    "summary": "Diagnostics (no secrets)",
                    "description": "Safe runtime diagnostics (no API keys, no PHI).",
                    "responses": {"200": {"description": "diagnostics payload"}},
                }
            },
            "/ping": {
                "get": {
                    "summary": "Deep ping (inference backends)",
                    "description": "Runs a tiny no-PHI inference call to validate the configured backends can serve requests.",
                    "responses": {"200": {"description": "ping JSON"}},
                    "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}],
                }
            },
            "/policy_pack": {"get": {"summary": "Policy pack", "responses": {"200": {"description": "policy pack JSON"}}}},
            "/safety_rules": {"get": {"summary": "Safety rulebook", "responses": {"200": {"description": "rulebook JSON"}}}},
            "/metrics": {
                "get": {
                    "summary": "Metrics",
                    "description": "JSON metrics by default; use `?format=prometheus` for Prometheus exposition.",
                    "responses": {"200": {"description": "metrics"}},
                }
            },
            "/example": {
                "get": {
                    "summary": "Sample intake (synthetic)",
                    "responses": {
                        "200": {"description": "patient intake", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PatientIntake"}}}}
                    },
                }
            },
            "/vignettes": {"get": {"summary": "List vignettes", "responses": {"200": {"description": "list"}}}},
            "/vignettes/{id}": {"get": {"summary": "Get vignette input", "responses": {"200": {"description": "input"}}}},
            "/bench/vignettes": {"get": {"summary": "Run vignette benchmark", "responses": {"200": {"description": "benchmark"}}}},
            "/review_packet": {
                "get": {
                    "summary": "Clinician review packet (markdown)",
                    "description": "Generates a markdown packet for qualitative review of synthetic vignettes (no PHI).",
                    "responses": {"200": {"description": "markdown (text/markdown)"}},
                }
            },
            "/bench/synthetic": {"get": {"summary": "Run synthetic proxy benchmark", "responses": {"200": {"description": "benchmark"}}}},
            "/triage": {
                "post": {
                    "summary": "Run triage pipeline",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PatientIntake"}}},
                    },
                    "responses": {
                        "200": {"description": "triage result", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/TriageResult"}}}},
                        "400": {"description": "bad request", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}},
                        "401": {"description": "unauthorized", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}},
                    },
                    "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}],
                }
            },
            "/triage_stream": {
                "post": {
                    "summary": "Run triage pipeline (streaming)",
                    "description": "Returns an NDJSON stream of agent events ending with a final TriageResult.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PatientIntake"}}},
                    },
                    "responses": {
                        "200": {
                            "description": "NDJSON stream (one JSON object per line)",
                            "content": {
                                "application/x-ndjson": {
                                    "schema": {"type": "string"},
                                    "example": (
                                        '{"type":"meta","request_id":"example"}\\n'
                                        '{"type":"step_start","index":0,"agent":"intake_structuring"}\\n'
                                        '{"type":"step_end","index":0,"agent":"intake_structuring","trace":{...}}\\n'
                                        '{"type":"final","result":{...}}\\n'
                                    ),
                                }
                            },
                        },
                        "400": {"description": "bad request", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}},
                        "401": {"description": "unauthorized", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}},
                    },
                    "security": [{"ApiKeyHeader": []}, {"BearerAuth": []}],
                }
            },
            "/audit_bundle": {"post": {"summary": "Audit bundle zip", "responses": {"200": {"description": "zip (binary)"}}}},
            "/judge_pack": {"post": {"summary": "Judge pack zip", "responses": {"200": {"description": "zip (binary)"}}}},
            "/fhir_bundle": {"post": {"summary": "FHIR bundle JSON", "responses": {"200": {"description": "FHIR Bundle"}}}},
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


def _extract_communication_backend(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "communication":
                output = step.get("output") or {}
                backend = output.get("communication_backend")
                if backend in {"deterministic", "external"}:
                    return backend
    except Exception:  # noqa: BLE001
        return "deterministic"
    return "deterministic"


def _extract_evidence_backend(result_payload: dict) -> str:
    try:
        for step in result_payload.get("trace", []):
            if step.get("agent") == "evidence_policy":
                output = step.get("output") or {}
                backend = str(output.get("evidence_backend") or "").strip().lower()
                return backend or "local"
    except Exception:  # noqa: BLE001
        return "local"
    return "local"


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
    metric("clinicaflow_judge_pack_requests_total", payload.get("judge_pack_requests_total"))
    metric("clinicaflow_judge_pack_success_total", payload.get("judge_pack_success_total"))
    metric("clinicaflow_judge_pack_errors_total", payload.get("judge_pack_errors_total"))
    metric("clinicaflow_fhir_bundle_requests_total", payload.get("fhir_bundle_requests_total"))
    metric("clinicaflow_fhir_bundle_success_total", payload.get("fhir_bundle_success_total"))
    metric("clinicaflow_fhir_bundle_errors_total", payload.get("fhir_bundle_errors_total"))

    metric("clinicaflow_triage_latency_ms_avg", payload.get("triage_latency_ms_avg"))
    metric("clinicaflow_triage_latency_ms_avg_window", payload.get("triage_latency_ms_avg_window"))
    metric("clinicaflow_triage_latency_ms_p50", payload.get("triage_latency_ms_p50"))
    metric("clinicaflow_triage_latency_ms_p95", payload.get("triage_latency_ms_p95"))
    metric("clinicaflow_triage_latency_ms_window_n", payload.get("triage_latency_ms_window_n"))
    metric("clinicaflow_triage_recent_error_rate", payload.get("triage_recent_error_rate"))
    metric("clinicaflow_triage_recent_window_n", payload.get("triage_recent_window_n"))

    # Nested breakdowns
    for tier, count in dict(payload.get("triage_risk_tier_total") or {}).items():
        metric("clinicaflow_triage_risk_tier_total", count, {"tier": str(tier)})
    for backend, count in dict(payload.get("triage_reasoning_backend_total") or {}).items():
        metric("clinicaflow_triage_reasoning_backend_total", count, {"backend": str(backend)})
    for backend, count in dict(payload.get("triage_communication_backend_total") or {}).items():
        metric("clinicaflow_triage_communication_backend_total", count, {"backend": str(backend)})
    for backend, count in dict(payload.get("triage_evidence_backend_total") or {}).items():
        metric("clinicaflow_triage_evidence_backend_total", count, {"backend": str(backend)})

    for agent, total in dict(payload.get("triage_agent_latency_ms_sum") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_sum", total, {"agent": str(agent)})
    for agent, count in dict(payload.get("triage_agent_latency_ms_count") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_count", count, {"agent": str(agent)})
    for agent, count in dict(payload.get("triage_agent_errors_total") or {}).items():
        metric("clinicaflow_triage_agent_errors_total", count, {"agent": str(agent)})

    for agent, value in dict(payload.get("triage_agent_latency_ms_avg_window") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_avg_window", value, {"agent": str(agent)})
    for agent, value in dict(payload.get("triage_agent_latency_ms_p50") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_p50", value, {"agent": str(agent)})
    for agent, value in dict(payload.get("triage_agent_latency_ms_p95") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_p95", value, {"agent": str(agent)})
    for agent, value in dict(payload.get("triage_agent_latency_ms_window_n") or {}).items():
        metric("clinicaflow_triage_agent_latency_ms_window_n", value, {"agent": str(agent)})

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
    # Deployment-friendly defaults: many free hosting platforms provide the
    # listening port via the `PORT` env var. We only respect it when `run()` is
    # invoked with the module defaults (e.g., `python -m clinicaflow.demo_server`),
    # so CLI users who pass `--port ...` keep explicit control.
    if port == 8000:
        raw_port = str(os.environ.get("PORT") or "").strip()
        if raw_port:
            try:
                port = int(raw_port)
            except ValueError:
                port = 8000

    settings = load_settings_from_env()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    server = make_server(host, port, settings=settings)
    print(f"ClinicaFlow demo server running at http://{host}:{port}")
    print("Open / in your browser for the demo UI")
    print(
        "API: POST /triage, POST /audit_bundle, POST /judge_pack, POST /fhir_bundle, GET /doctor, GET /vignettes, GET /bench/vignettes"
    )
    print("Ops: GET /health, GET /metrics, GET /openapi.json")
    server.serve_forever()


if __name__ == "__main__":
    run()
