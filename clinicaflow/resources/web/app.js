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

function renderList(el, items, { ordered, emptyText } = {}) {
  el.innerHTML = "";
  (items || []).forEach((x) => {
    const li = document.createElement("li");
    li.textContent = String(x);
    el.appendChild(li);
  });
  if ((items || []).length === 0) {
    const li = document.createElement("li");
    li.textContent =
      emptyText != null ? String(emptyText) : ordered ? "No actions suggested." : "No explicit red flags detected.";
    el.appendChild(li);
  }
}

function traceOutput(result, agentName) {
  try {
    const steps = result.trace || [];
    for (const s of steps) {
      if (s.agent === agentName) return s.output || {};
    }
  } catch (e) {
    // ignore
  }
  return {};
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
  const backend = extractBackend(result);
  setText(
    "metaLine",
    `request_id: ${state.lastRequestId || "—"} • latency: ${result.total_latency_ms ?? "—"} ms • backend: ${backend}`,
  );

  const escalation = result.escalation_required ? "required" : "not required";
  setText("escalationPill", `escalation: ${escalation}`);

  const safety = traceOutput(result, "safety_escalation");
  const tierRationale = safety.risk_tier_rationale || "—";
  setText(
    "tierRationale",
    safety.safety_rules_version ? `${tierRationale} • rules: ${safety.safety_rules_version}` : tierRationale,
  );

  renderList($("differential"), result.differential_considerations, {
    ordered: false,
    emptyText: "No differential suggestions.",
  });
  renderList($("uncertainty"), result.uncertainty_reasons, { ordered: false, emptyText: "No uncertainty flags." });
  renderList($("redFlags"), result.red_flags, { ordered: false, emptyText: "No explicit red flags detected." });
  renderList($("actions"), result.recommended_next_actions, { ordered: true, emptyText: "No actions suggested." });

  const conf = typeof result.confidence === "number" ? result.confidence : null;
  setText("confidenceVal", conf == null ? "—" : `confidence: ${(conf * 100).toFixed(0)}%`);
  $("confidenceBar").style.width = conf == null ? "0%" : `${Math.max(0, Math.min(1, conf)) * 100}%`;

  const structured = traceOutput(result, "intake_structuring");
  $("structuredOut").textContent = fmtJson(structured || {});

  const reasoning = traceOutput(result, "multimodal_reasoning");
  const model = reasoning.reasoning_backend_model || "";
  const pv = reasoning.reasoning_prompt_version || "";
  const reasoningBits = [];
  if (reasoning.reasoning_backend) reasoningBits.push(`backend=${reasoning.reasoning_backend}`);
  if (model) reasoningBits.push(`model=${model}`);
  if (pv) reasoningBits.push(`prompt=${pv}`);
  setText("reasoningInfo", reasoningBits.length ? reasoningBits.join(" • ") : "—");
  setText("rationale", reasoning.reasoning_rationale || "—");

  const evidence = traceOutput(result, "evidence_policy");
  renderCitations(evidence);

  $("handoff").textContent = result.clinician_handoff || "—";
  $("patientSummary").textContent = result.patient_summary || "—";

  renderTrace(result.trace || []);

  $("rawResult").textContent = fmtJson(result);
}

function renderCitations(evidenceOut) {
  const root = $("citations");
  if (!root) return;

  const citations = (evidenceOut || {}).protocol_citations || [];
  const sha = (evidenceOut || {}).policy_pack_sha256 || "";
  const src = (evidenceOut || {}).policy_pack_source || "";

  if (!Array.isArray(citations) || citations.length === 0) {
    root.textContent = sha ? `No matched citations. policy_pack_sha256=${sha.slice(0, 12)}…` : "No matched citations.";
    return;
  }

  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Policy</th>
        <th>Title</th>
        <th>Citation</th>
        <th>Recommended actions</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector("tbody");

  citations.forEach((c) => {
    const tr = document.createElement("tr");
    const actions = Array.isArray(c.recommended_actions) ? c.recommended_actions.join("; ") : "";
    tr.innerHTML = `
      <td class="mono">${escapeHtml(String(c.policy_id || ""))}</td>
      <td>${escapeHtml(String(c.title || ""))}</td>
      <td class="mono">${escapeHtml(String(c.citation || ""))}</td>
      <td>${escapeHtml(actions)}</td>
    `;
    tbody.appendChild(tr);
  });

  root.innerHTML = "";
  if (sha || src) {
    const meta = document.createElement("div");
    meta.className = "small muted";
    const bits = [];
    if (sha) bits.push(`policy_pack_sha256=${sha.slice(0, 12)}…`);
    if (src) bits.push(`source=${src}`);
    meta.textContent = bits.join(" • ");
    root.appendChild(meta);
  }
  root.appendChild(table);
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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
  await copyText(text, "Copied JSON to clipboard.");
}

async function copyText(text, okMessage) {
  try {
    await navigator.clipboard.writeText(String(text));
    if (okMessage) setText("statusLine", okMessage);
    return;
  } catch (e) {
    // ignore
  }

  const ta = document.createElement("textarea");
  ta.value = String(text);
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    document.execCommand("copy");
    if (okMessage) setText("statusLine", okMessage);
  } catch (e) {
    setText("statusLine", "Copy failed. Please select and copy manually.");
  } finally {
    ta.remove();
  }
}

function downloadText(filename, text, mime) {
  const blob = new Blob([String(text)], { type: mime || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function buildNoteMarkdown(intake, result) {
  const reasoning = traceOutput(result, "multimodal_reasoning");
  const evidence = traceOutput(result, "evidence_policy");
  const safety = traceOutput(result, "safety_escalation");

  const vitals = (intake || {}).vitals || {};
  const vitalsParts = [];
  if (vitals.heart_rate != null) vitalsParts.push(`HR ${vitals.heart_rate}`);
  if (vitals.systolic_bp != null) vitalsParts.push(`BP ${vitals.systolic_bp}/${vitals.diastolic_bp ?? "?"}`);
  if (vitals.temperature_c != null) vitalsParts.push(`Temp ${vitals.temperature_c}°C`);
  if (vitals.spo2 != null) vitalsParts.push(`SpO₂ ${vitals.spo2}%`);
  if (vitals.respiratory_rate != null) vitalsParts.push(`RR ${vitals.respiratory_rate}`);

  const lines = [];
  lines.push("# ClinicaFlow — Triage Note (Demo)");
  lines.push("");
  lines.push("**DISCLAIMER:** Decision support only. Not a diagnosis. Clinician confirmation required.");
  lines.push("");
  lines.push("## Metadata");
  lines.push(`- request_id: ${state.lastRequestId || result.request_id || "—"}`);
  lines.push(`- created_at: ${result.created_at || "—"}`);
  lines.push(`- pipeline_version: ${result.pipeline_version || "—"}`);
  if (reasoning.reasoning_backend) lines.push(`- reasoning_backend: ${reasoning.reasoning_backend}`);
  if (reasoning.reasoning_backend_model) lines.push(`- reasoning_model: ${reasoning.reasoning_backend_model}`);
  if (reasoning.reasoning_prompt_version) lines.push(`- reasoning_prompt_version: ${reasoning.reasoning_prompt_version}`);
  if (evidence.policy_pack_sha256) lines.push(`- policy_pack_sha256: ${evidence.policy_pack_sha256}`);
  if (safety.safety_rules_version) lines.push(`- safety_rules_version: ${safety.safety_rules_version}`);
  lines.push("");
  lines.push("## Intake (synthetic/demo)");
  lines.push(`- chief_complaint: ${(intake.chief_complaint || "").trim()}`);
  if ((intake.history || "").trim()) lines.push(`- history: ${(intake.history || "").trim()}`);
  if (vitalsParts.length) lines.push(`- vitals: ${vitalsParts.join(", ")}`);
  lines.push("");
  lines.push("## Triage");
  lines.push(`- risk_tier: ${result.risk_tier}`);
  lines.push(`- escalation_required: ${result.escalation_required}`);
  if (safety.risk_tier_rationale) lines.push(`- rationale: ${safety.risk_tier_rationale}`);
  lines.push("");
  lines.push("## Red flags");
  (result.red_flags || []).forEach((x) => lines.push(`- ${x}`));
  if (!result.red_flags || result.red_flags.length === 0) lines.push("- (none)");
  lines.push("");
  lines.push("## Differential (top)");
  (result.differential_considerations || []).forEach((x) => lines.push(`- ${x}`));
  lines.push("");
  if (reasoning.reasoning_rationale) {
    lines.push("## Reasoning rationale");
    lines.push(reasoning.reasoning_rationale);
    lines.push("");
  }
  lines.push("## Recommended next actions");
  (result.recommended_next_actions || []).forEach((x) => lines.push(`- ${x}`));
  lines.push("");
  lines.push("## Uncertainty");
  lines.push(`- confidence: ${result.confidence}`);
  (result.uncertainty_reasons || []).forEach((x) => lines.push(`- ${x}`));
  if (!result.uncertainty_reasons || result.uncertainty_reasons.length === 0) lines.push("- (none)");
  lines.push("");
  lines.push("## Clinician handoff");
  lines.push(result.clinician_handoff || "");
  lines.push("");
  lines.push("## Patient return precautions");
  lines.push(result.patient_summary || "");
  lines.push("");
  const citations = evidence.protocol_citations || [];
  if (Array.isArray(citations) && citations.length) {
    lines.push("## Protocol citations (demo policy pack)");
    citations.forEach((c) => {
      lines.push(`- ${c.policy_id || ""}: ${c.title || ""}`.trim());
      if (c.citation) lines.push(`  - citation: ${c.citation}`);
    });
    lines.push("");
  }

  return lines.join("\n").trim() + "\n";
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

  const filters = getBenchFilters();
  const rows = (perCase || []).filter((row) => {
    const goldTier = row.gold?.risk_tier || "";
    const cfTier = row.clinicaflow?.risk_tier || "";
    const under = (goldTier === "urgent" || goldTier === "critical") && cfTier === "routine";
    const over = goldTier === "routine" && cfTier !== "routine";
    const mismatch = goldTier && cfTier && goldTier !== cfTier;

    if (filters.under && !under) return false;
    if (filters.over && !over) return false;
    if (filters.mismatch && !mismatch) return false;
    return true;
  });

  rows.forEach((row) => {
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
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => loadVignetteById(row.id));
    body.appendChild(tr);
  });
}

function getBenchFilters() {
  return {
    mismatch: $("filterMismatch")?.checked || false,
    under: $("filterUnder")?.checked || false,
    over: $("filterOver")?.checked || false,
  };
}

async function loadVignetteById(caseId) {
  try {
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(caseId)}`);
    const intake = resp.input || resp;
    state.lastIntake = intake;
    fillFormFromIntake(intake);
    $("intakeJson").value = fmtJson(intake);
    setTab("triage");
    setMode("form");
    setText("statusLine", `Loaded vignette: ${caseId}`);
  } catch (e) {
    setError("runError", e);
  }
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
  $("copyHandoff").addEventListener("click", () => copyText($("handoff").textContent || "", "Copied handoff."));
  $("copyPatient").addEventListener("click", () => copyText($("patientSummary").textContent || "", "Copied precautions."));
  $("downloadNote").addEventListener("click", () => {
    if (!state.lastIntake || !state.lastResult) return;
    const md = buildNoteMarkdown(state.lastIntake, state.lastResult);
    const req = state.lastRequestId || state.lastResult.request_id || "run";
    downloadText(`clinicaflow_note_${req}.md`, md, "text/markdown");
    setText("statusLine", "Downloaded note.md");
  });
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
  ["filterMismatch", "filterUnder", "filterOver"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("change", () => {
      if (!state.lastBench) return;
      renderBenchCases(state.lastBench.per_case);
    });
  });
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
