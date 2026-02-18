/* ClinicaFlow Console (vanilla JS, no deps). */

function $(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function show(id, visible) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle("hidden", !visible);
}

function fmtJson(obj) {
  return JSON.stringify(obj, null, 2);
}

function parseLines(value) {
  return String(value || "")
    .split(/\r?\n/g)
    .map((s) => s.trim())
    .filter((s) => s);
}

function toNum(value) {
  const v = String(value ?? "").trim();
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} for ${url}`);
  }
  return await resp.json();
}

async function postJson(url, payload, extraHeaders) {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(extraHeaders || {}),
    },
    body: JSON.stringify(payload),
  });

  let data = null;
  try {
    data = await resp.json();
  } catch (e) {
    // ignore
  }

  if (!resp.ok) {
    const msg = data && data.error ? JSON.stringify(data.error) : `HTTP ${resp.status}`;
    throw new Error(msg);
  }

  return { data, headers: resp.headers };
}

const state = {
  mode: "form",
  lastIntake: null,
  lastResult: null,
  lastRequestId: null,
  lastBench: null,
};

function buildIntakeFromForm() {
  const chief = String($("chiefComplaint").value || "").trim();
  const history = String($("history").value || "").trim();

  const demographics = {};
  const age = toNum($("age").value);
  const sex = String($("sex").value || "").trim();
  if (age !== null) demographics.age = age;
  if (sex) demographics.sex = sex;

  const vitals = {
    heart_rate: toNum($("hr").value),
    systolic_bp: toNum($("sbp").value),
    diastolic_bp: toNum($("dbp").value),
    temperature_c: toNum($("temp").value),
    spo2: toNum($("spo2").value),
    respiratory_rate: toNum($("rr").value),
  };

  // Strip nulls for compactness.
  for (const k of Object.keys(vitals)) {
    if (vitals[k] === null) delete vitals[k];
  }

  const intake = {
    chief_complaint: chief,
    history,
    demographics,
    vitals,
    image_descriptions: parseLines($("imageDesc").value),
    prior_notes: parseLines($("priorNotes").value),
  };

  return intake;
}

function fillFormFromIntake(intake) {
  intake = intake || {};
  $("chiefComplaint").value = intake.chief_complaint || "";
  $("history").value = intake.history || "";

  const demo = intake.demographics || {};
  $("age").value = demo.age ?? "";
  $("sex").value = demo.sex ?? "";

  const vitals = intake.vitals || {};
  $("hr").value = vitals.heart_rate ?? "";
  $("sbp").value = vitals.systolic_bp ?? "";
  $("dbp").value = vitals.diastolic_bp ?? "";
  $("temp").value = vitals.temperature_c ?? "";
  $("spo2").value = vitals.spo2 ?? "";
  $("rr").value = vitals.respiratory_rate ?? "";

  $("imageDesc").value = (intake.image_descriptions || []).join("\n");
  $("priorNotes").value = (intake.prior_notes || []).join("\n");
}

function setMode(mode) {
  state.mode = mode;
  $("mode-form").classList.toggle("hidden", mode !== "form");
  $("mode-json").classList.toggle("hidden", mode !== "json");
  document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
}

function setTab(tab) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tabpanel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));
}

function setRiskTier(tier) {
  const el = $("riskTier");
  el.classList.remove("routine", "urgent", "critical");
  const t = String(tier || "").toLowerCase();
  if (t) el.classList.add(t);
  el.textContent = tier || "—";
}

function renderList(el, items, { ordered } = {}) {
  el.innerHTML = "";
  (items || []).forEach((x) => {
    const li = document.createElement("li");
    li.textContent = String(x);
    el.appendChild(li);
  });
  if ((items || []).length === 0) {
    const li = document.createElement("li");
    li.textContent = ordered ? "No actions suggested." : "No explicit red flags detected.";
    el.appendChild(li);
  }
}

function renderTrace(trace) {
  const root = $("trace");
  root.innerHTML = "";

  (trace || []).forEach((step) => {
    const details = document.createElement("details");
    details.open = false;
    const summary = document.createElement("summary");
    const agent = step.agent || "agent";
    const latency = step.latency_ms != null ? `${step.latency_ms} ms` : "";
    summary.textContent = `${agent}  ${latency}`.trim();
    details.appendChild(summary);

    const pre = document.createElement("pre");
    pre.className = "pre mono";
    pre.style.maxHeight = "340px";
    pre.textContent = fmtJson(step.output || {});
    details.appendChild(pre);

    if (step.error) {
      const err = document.createElement("div");
      err.className = "alert";
      err.textContent = String(step.error);
      details.appendChild(err);
    }

    root.appendChild(details);
  });

  if ((trace || []).length === 0) {
    const empty = document.createElement("div");
    empty.className = "small muted";
    empty.textContent = "No trace available.";
    root.appendChild(empty);
  }
}

function renderResult(result, requestIdFromHeader) {
  state.lastResult = result;
  state.lastRequestId = requestIdFromHeader || result.request_id || null;

  setRiskTier(result.risk_tier);
  setText("metaLine", `request_id: ${state.lastRequestId || "—"} • latency: ${result.total_latency_ms ?? "—"} ms`);

  renderList($("redFlags"), result.red_flags, { ordered: false });
  renderList($("actions"), result.recommended_next_actions, { ordered: true });

  $("handoff").textContent = result.clinician_handoff || "—";
  $("patientSummary").textContent = result.patient_summary || "—";

  renderTrace(result.trace || []);

  $("rawResult").textContent = fmtJson(result);
}

function setError(targetId, msg) {
  const el = $(targetId);
  if (!el) return;
  if (!msg) {
    el.textContent = "";
    el.classList.add("hidden");
    return;
  }
  el.textContent = String(msg);
  el.classList.remove("hidden");
}

async function loadDoctor() {
  try {
    const d = await fetchJson("/doctor");
    const backend = (d.reasoning_backend || {}).backend || "deterministic";
    const model = (d.reasoning_backend || {}).model || "";
    const label = model ? `${backend} • ${model}` : backend;
    setText("backendBadge", `backend: ${label}`);

    const policy = (d.policy_pack || {}).sha256 || "";
    setText("policyBadge", policy ? `policy: ${policy.slice(0, 10)}…` : "policy: (none)");
  } catch (e) {
    setText("backendBadge", "backend: unknown");
    setText("policyBadge", "policy: unknown");
  }
}

async function loadPresets() {
  const select = $("presetSelect");
  select.innerHTML = "";

  const optSample = document.createElement("option");
  optSample.value = "sample";
  optSample.textContent = "Sample case (chest pain)";
  select.appendChild(optSample);

  try {
    const payload = await fetchJson("/vignettes");
    const vignettes = payload.vignettes || [];
    vignettes.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      const cc = String(v.chief_complaint || "").slice(0, 60);
      opt.textContent = `${v.id} — ${cc}`;
      select.appendChild(opt);
    });
  } catch (e) {
    // ignore
  }
}

async function loadPreset() {
  setError("intakeError", "");
  const id = $("presetSelect").value;
  let intake = null;
  if (id === "sample") {
    intake = await fetchJson("/example");
  } else {
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(id)}`);
    intake = resp.input || resp;
  }

  state.lastIntake = intake;
  fillFormFromIntake(intake);
  $("intakeJson").value = fmtJson(intake);
  setText("statusLine", `Loaded preset: ${id}`);
}

async function runTriage() {
  setError("runError", "");
  setError("intakeError", "");
  setText("statusLine", "Running triage…");

  let intake = null;
  try {
    if (state.mode === "json") {
      intake = JSON.parse($("intakeJson").value || "{}");
    } else {
      intake = buildIntakeFromForm();
    }

    if (!intake || typeof intake !== "object") {
      throw new Error("Intake must be a JSON object.");
    }
    if (!String(intake.chief_complaint || "").trim()) {
      throw new Error("Chief complaint is required.");
    }
  } catch (e) {
    setError("intakeError", e);
    setText("statusLine", "Ready.");
    return;
  }

  state.lastIntake = intake;
  $("intakeJson").value = fmtJson(intake);

  try {
    const { data, headers } = await postJson("/triage", intake, {});
    const reqId = headers.get("X-Request-ID") || null;
    renderResult(data, reqId);
    setText("statusLine", `Done. risk=${data.risk_tier} • backend=${extractBackend(data)}`);
  } catch (e) {
    setError("runError", e);
    setText("statusLine", "Error.");
  }
}

function extractBackend(result) {
  try {
    const steps = result.trace || [];
    for (const s of steps) {
      if (s.agent === "multimodal_reasoning") {
        return (s.output || {}).reasoning_backend || "deterministic";
      }
    }
  } catch (e) {
    // ignore
  }
  return "deterministic";
}

async function copyResult() {
  if (!state.lastResult) return;
  const text = fmtJson(state.lastResult);
  try {
    await navigator.clipboard.writeText(text);
    setText("statusLine", "Copied JSON to clipboard.");
  } catch (e) {
    // Fallback: select raw pre.
    const pre = $("rawResult");
    const range = document.createRange();
    range.selectNodeContents(pre);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    setText("statusLine", "Select all + copy (Ctrl/Cmd+C).");
  }
}

async function downloadAuditBundle(redact) {
  setError("runError", "");
  if (!state.lastIntake) {
    setError("runError", "Run a triage case first (so the intake is available).");
    return;
  }

  const qs = redact ? "?redact=1" : "?redact=0";
  const requestId = state.lastRequestId || "";
  setText("statusLine", "Building audit bundle…");

  const resp = await fetch(`/audit_bundle${qs}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(requestId ? { "X-Request-ID": requestId } : {}),
    },
    body: JSON.stringify(state.lastIntake),
  });

  if (!resp.ok) {
    const text = await resp.text();
    setError("runError", `Audit bundle failed: HTTP ${resp.status} ${text}`);
    setText("statusLine", "Error.");
    return;
  }

  const blob = await resp.blob();
  const cd = resp.headers.get("Content-Disposition") || "";
  const m = /filename=\"([^\"]+)\"/.exec(cd);
  const filename = m ? m[1] : `clinicaflow_audit_${redact ? "redacted" : "full"}_${requestId || "run"}.zip`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  setText("statusLine", "Downloaded audit bundle.");
}

function renderBenchSummary(summary) {
  const root = $("benchSummary");
  root.innerHTML = "";
  if (!summary) return;

  const tbl = document.createElement("div");
  tbl.className = "callout";
  tbl.innerHTML = `
    <div class="k">Summary</div>
    <div class="mono">${summary.n_cases} cases • ${summary.n_gold_urgent_critical} gold urgent/critical</div>
    <div class="small muted">
      Red-flag recall: baseline ${summary.red_flag_recall_baseline}% → ClinicaFlow ${summary.red_flag_recall_clinicaflow}%
      • Under-triage: baseline ${summary.under_triage_rate_baseline}% → ClinicaFlow ${summary.under_triage_rate_clinicaflow}%
      • Over-triage: baseline ${summary.over_triage_rate_baseline}% → ClinicaFlow ${summary.over_triage_rate_clinicaflow}%
    </div>
  `;
  root.appendChild(tbl);
}

function renderBenchCases(perCase) {
  const body = $("benchBody");
  body.innerHTML = "";

  (perCase || []).forEach((row) => {
    const tr = document.createElement("tr");
    const goldTier = row.gold?.risk_tier || "";
    const baseTier = row.baseline?.risk_tier || "";
    const cfTier = row.clinicaflow?.risk_tier || "";

    const under = (goldTier === "urgent" || goldTier === "critical") && cfTier === "routine";
    const over = goldTier === "routine" && cfTier !== "routine";
    tr.className = under ? "row-bad" : over ? "row-warn" : "";

    const goldCats = (row.gold?.categories || []).join(", ");
    const cfCats = (row.clinicaflow?.categories || []).join(", ");

    tr.innerHTML = `
      <td class="mono">${row.id}</td>
      <td>${goldTier}</td>
      <td>${baseTier}</td>
      <td><b>${cfTier}</b></td>
      <td class="mono">${goldCats}</td>
      <td class="mono">${cfCats}</td>
    `;
    body.appendChild(tr);
  });
}

async function runBench() {
  $("benchStatus").textContent = "Running…";
  try {
    const payload = await fetchJson("/bench/vignettes");
    state.lastBench = payload;
    renderBenchSummary(payload.summary);
    renderBenchCases(payload.per_case);
    $("benchStatus").textContent = "Done.";
  } catch (e) {
    $("benchStatus").textContent = `Error: ${e}`;
  }
}

async function downloadBench() {
  if (!state.lastBench) return;
  const blob = new Blob([fmtJson(state.lastBench)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "vignette_benchmark.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function wireEvents() {
  document.querySelectorAll(".seg").forEach((b) =>
    b.addEventListener("click", () => {
      setMode(b.dataset.mode);
    }),
  );

  document.querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => {
      setTab(b.dataset.tab);
    }),
  );

  $("loadPreset").addEventListener("click", () => loadPreset().catch((e) => setError("intakeError", e)));
  $("runTriage").addEventListener("click", () => runTriage());
  $("copyResult").addEventListener("click", () => copyResult());
  $("downloadRedacted").addEventListener("click", () => downloadAuditBundle(true));
  $("downloadFull").addEventListener("click", () => downloadAuditBundle(false));

  $("applyJsonToForm").addEventListener("click", () => {
    try {
      const intake = JSON.parse($("intakeJson").value || "{}");
      fillFormFromIntake(intake);
      setText("statusLine", "Applied JSON to form.");
      setError("intakeError", "");
    } catch (e) {
      setError("intakeError", e);
    }
  });

  $("updateJsonFromForm").addEventListener("click", () => {
    try {
      const intake = buildIntakeFromForm();
      $("intakeJson").value = fmtJson(intake);
      setText("statusLine", "Updated JSON from form.");
      setError("intakeError", "");
    } catch (e) {
      setError("intakeError", e);
    }
  });

  $("runBench").addEventListener("click", () => runBench());
  $("downloadBench").addEventListener("click", () => downloadBench());
}

async function init() {
  wireEvents();
  setMode("form");
  await loadDoctor();
  await loadPresets();
  await loadPreset();
}

init().catch((e) => {
  setError("runError", e);
});

