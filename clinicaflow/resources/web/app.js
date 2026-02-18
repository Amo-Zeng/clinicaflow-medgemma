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
  review: {
    lastCaseId: null,
    lastIntake: null,
    lastLabels: null,
    lastResult: null,
  },
  workspace: {
    selectedId: null,
  },
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

function careSettingFromTier(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "critical") return "Suggested care setting: Emergency evaluation now (ED / call emergency services).";
  if (t === "urgent") return "Suggested care setting: Same-day urgent clinician evaluation.";
  if (t === "routine") return "Suggested care setting: Routine evaluation / self-care with return precautions.";
  return "—";
}

function renderVitalsSummary(intake) {
  const root = $("vitalsSummary");
  if (!root) return;

  const demo = (intake || {}).demographics || {};
  const vitals = (intake || {}).vitals || {};

  const chips = document.createElement("div");
  chips.className = "chips";

  function addChip(text, level) {
    const span = document.createElement("span");
    span.className = `chip ${level || "ok"}`;
    span.textContent = text;
    chips.appendChild(span);
  }

  if (demo.age != null) addChip(`Age ${demo.age}`, "ok");
  if (demo.sex) addChip(`Sex ${demo.sex}`, "ok");

  const hr = vitals.heart_rate;
  if (hr != null) addChip(`HR ${hr}`, hr >= 130 || hr < 45 ? "bad" : hr >= 110 || hr < 50 ? "warn" : "ok");

  const sbp = vitals.systolic_bp;
  const dbp = vitals.diastolic_bp;
  if (sbp != null) {
    const bpText = dbp != null ? `BP ${sbp}/${dbp}` : `SBP ${sbp}`;
    addChip(bpText, sbp < 90 ? "bad" : sbp < 100 || sbp >= 180 ? "warn" : "ok");
  }

  const temp = vitals.temperature_c;
  if (temp != null) addChip(`Temp ${temp}°C`, temp >= 39.5 ? "bad" : temp >= 38.0 ? "warn" : "ok");

  const spo2 = vitals.spo2;
  if (spo2 != null) addChip(`SpO₂ ${spo2}%`, spo2 < 92 ? "bad" : spo2 < 95 ? "warn" : "ok");

  const rr = vitals.respiratory_rate;
  if (rr != null) addChip(`RR ${rr}`, rr >= 30 ? "bad" : rr >= 22 ? "warn" : "ok");

  root.innerHTML = "";
  if (chips.childNodes.length === 0) {
    root.textContent = "No vitals provided.";
    return;
  }
  root.appendChild(chips);
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
  setText("careSetting", careSettingFromTier(result.risk_tier));
  renderVitalsSummary(state.lastIntake);
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
  const missing = structured?.missing_fields || [];
  const missingEl = $("missingFields");
  if (missingEl) renderList(missingEl, missing, { ordered: false, emptyText: "None." });

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
    const ok = (d.reasoning_backend || {}).connectivity_ok;
    const status = ok === true ? "ok" : ok === false ? "unreachable" : "";
    const label = model ? `${backend} • ${model}` : backend;
    const fullLabel = status ? `${label} • ${status}` : label;
    setText("backendBadge", `backend: ${fullLabel}`);

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

// ---------------------------
// Workspace (UI-local)
// ---------------------------

const WORKSPACE_STORAGE_KEY = "clinicaflow.workspace.v1";

function newLocalId() {
  try {
    if (crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  } catch (e) {
    // ignore
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadWorkspaceItems() {
  try {
    const raw = localStorage.getItem(WORKSPACE_STORAGE_KEY) || "";
    if (!raw.trim()) return [];
    const payload = JSON.parse(raw);
    return Array.isArray(payload) ? payload : [];
  } catch (e) {
    return [];
  }
}

function saveWorkspaceItems(items) {
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(items || []));
  } catch (e) {
    // ignore
  }
}

function fmtShortTs(iso) {
  const s = String(iso || "").trim();
  if (!s) return "—";
  // ISO: 2026-02-18T22:12:34Z → 2026-02-18 22:12
  return s.replace("T", " ").replace("Z", "").slice(0, 16);
}

function workspaceSelectedItem() {
  const items = loadWorkspaceItems();
  return items.find((x) => x && x.id === state.workspace.selectedId) || null;
}

function renderWorkspaceSelected() {
  const pre = $("wsSelected");
  if (!pre) return;
  const item = workspaceSelectedItem();
  pre.textContent = fmtJson(item || {});
}

function renderWorkspaceTable() {
  const body = $("wsTableBody");
  if (!body) return;
  body.innerHTML = "";

  const items = loadWorkspaceItems();
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted" colspan="5">No saved items yet.</td>`;
    body.appendChild(tr);
    renderWorkspaceSelected();
    return;
  }

  items
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .forEach((item) => {
      const tr = document.createElement("tr");
      const intake = item.intake || {};
      const result = item.result || null;
      const tier = result ? result.risk_tier || "" : "—";
      const backend = result ? extractBackend(result) : "—";

      tr.innerHTML = `
        <td class="mono">${escapeHtml(fmtShortTs(item.created_at))}</td>
        <td>${escapeHtml(String(intake.chief_complaint || "").slice(0, 120))}</td>
        <td><b>${escapeHtml(String(tier))}</b></td>
        <td class="mono">${escapeHtml(String(backend))}</td>
        <td></td>
      `;

      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => {
        state.workspace.selectedId = item.id;
        renderWorkspaceSelected();
        setText("wsStatus", `Selected: ${item.id}`);
        setError("wsError", "");
      });

      const actionsTd = tr.querySelector("td:last-child");
      const btnDel = document.createElement("button");
      btnDel.className = "btn subtle";
      btnDel.type = "button";
      btnDel.textContent = "Delete";
      btnDel.addEventListener("click", (ev) => {
        ev.stopPropagation();
        workspaceDelete(item.id);
      });
      actionsTd.appendChild(btnDel);

      body.appendChild(tr);
    });

  renderWorkspaceSelected();
}

function getIntakeFromUiForWorkspace() {
  if (state.mode === "json") {
    return JSON.parse($("intakeJson").value || "{}");
  }
  return buildIntakeFromForm();
}

function workspaceAdd({ intake, result }) {
  const items = loadWorkspaceItems();
  const now = new Date().toISOString();
  const id = newLocalId();
  items.push({
    id,
    created_at: now,
    intake: intake || {},
    result: result || null,
  });
  saveWorkspaceItems(items);
  state.workspace.selectedId = id;
  renderWorkspaceTable();
  renderWorkspaceSelected();
  setText("wsStatus", `Saved: ${id}`);
}

function workspaceDelete(id) {
  const ok = confirm("Delete this workspace item? This cannot be undone.");
  if (!ok) return;
  const items = loadWorkspaceItems().filter((x) => x && x.id !== id);
  saveWorkspaceItems(items);
  if (state.workspace.selectedId === id) state.workspace.selectedId = null;
  renderWorkspaceTable();
  setText("wsStatus", "Deleted.");
}

async function workspaceExport() {
  const items = loadWorkspaceItems();
  downloadText("clinicaflow_workspace.json", fmtJson(items), "application/json");
  setText("wsStatus", "Exported clinicaflow_workspace.json");
}

async function workspaceImportFromFile(file) {
  setError("wsError", "");
  if (!file) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!Array.isArray(payload)) throw new Error("Invalid file: expected a JSON array.");
    const sanitized = payload
      .filter((x) => x && typeof x === "object")
      .map((x) => ({
        id: String(x.id || newLocalId()),
        created_at: String(x.created_at || new Date().toISOString()),
        intake: x.intake || {},
        result: x.result || null,
      }));
    saveWorkspaceItems(sanitized);
    state.workspace.selectedId = sanitized.length ? sanitized[0].id : null;
    renderWorkspaceTable();
    setText("wsStatus", `Imported ${sanitized.length} items.`);
  } catch (e) {
    setError("wsError", e);
  }
}

// ---------------------------
// Clinician review (UI-local)
// ---------------------------

const REVIEW_STORAGE_KEY = "clinicaflow.reviews.v1";

function todayISODate() {
  const d = new Date();
  const yyyy = String(d.getFullYear());
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function loadStoredReviews() {
  try {
    const raw = localStorage.getItem(REVIEW_STORAGE_KEY) || "";
    if (!raw.trim()) return [];
    const payload = JSON.parse(raw);
    return Array.isArray(payload) ? payload : [];
  } catch (e) {
    return [];
  }
}

function saveStoredReviews(reviews) {
  try {
    localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(reviews || []));
  } catch (e) {
    // ignore
  }
}

function readReviewForm() {
  return {
    reviewer: {
      role: String($("reviewRole")?.value || "").trim(),
      years_in_practice: toNum($("reviewYears")?.value),
      setting: String($("reviewSetting")?.value || "").trim(),
      date: String($("reviewDate")?.value || "").trim(),
    },
    ratings: {
      risk_tier_safety: String($("reviewRiskSafety")?.value || "").trim(),
      actionability: toNum($("reviewActionability")?.value),
      handoff_quality: toNum($("reviewHandoff")?.value),
    },
    notes: {
      feedback: String($("reviewFeedback")?.value || "").trim(),
      improvement: String($("reviewImprovement")?.value || "").trim(),
    },
  };
}

function clearReviewForm() {
  const ids = [
    "reviewRiskSafety",
    "reviewActionability",
    "reviewHandoff",
    "reviewFeedback",
    "reviewImprovement",
  ];
  ids.forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.value = "";
  });
  setError("reviewError", "");
}

function setReviewIdentityDefaults() {
  const dateEl = $("reviewDate");
  if (dateEl && !String(dateEl.value || "").trim()) dateEl.value = todayISODate();
}

function renderReviewTable() {
  const body = $("reviewTableBody");
  if (!body) return;
  body.innerHTML = "";

  const reviews = loadStoredReviews();
  if (reviews.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted" colspan="6">No saved reviews yet.</td>`;
    body.appendChild(tr);
    return;
  }

  reviews
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .forEach((r) => {
      const tr = document.createElement("tr");
      const safety = r?.ratings?.risk_tier_safety || "";
      const actionability = r?.ratings?.actionability ?? "";
      const handoff = r?.ratings?.handoff_quality ?? "";
      tr.innerHTML = `
        <td class="mono">${escapeHtml(String(r.case_id || ""))}</td>
        <td><b>${escapeHtml(String(r.output_preview?.risk_tier || ""))}</b></td>
        <td class="mono">${escapeHtml(String(safety))}</td>
        <td class="mono">${escapeHtml(String(actionability))}</td>
        <td class="mono">${escapeHtml(String(handoff))}</td>
        <td></td>
      `;

      const actionsTd = tr.querySelector("td:last-child");
      const btnLoad = document.createElement("button");
      btnLoad.className = "btn subtle";
      btnLoad.type = "button";
      btnLoad.textContent = "Load";
      btnLoad.addEventListener("click", () => loadSavedReview(r));

      const btnDel = document.createElement("button");
      btnDel.className = "btn subtle";
      btnDel.type = "button";
      btnDel.textContent = "Delete";
      btnDel.addEventListener("click", () => deleteSavedReview(r));

      const wrap = document.createElement("div");
      wrap.className = "row";
      wrap.style.margin = "0";
      wrap.appendChild(btnLoad);
      wrap.appendChild(btnDel);
      actionsTd.appendChild(wrap);

      body.appendChild(tr);
    });
}

function loadSavedReview(r) {
  if (!r) return;
  state.review.lastCaseId = r.case_id || null;
  state.review.lastIntake = r.intake || null;
  state.review.lastLabels = r.gold_labels || null;
  state.review.lastResult = r.output_preview_full || r.output_preview || null;

  const sel = $("reviewCaseSelect");
  if (sel && r.case_id) sel.value = r.case_id;

  const roleEl = $("reviewRole");
  if (roleEl) roleEl.value = r?.reviewer?.role || "";
  const yrsEl = $("reviewYears");
  if (yrsEl) yrsEl.value = r?.reviewer?.years_in_practice ?? "";
  const settingEl = $("reviewSetting");
  if (settingEl) settingEl.value = r?.reviewer?.setting || "";
  const dateEl = $("reviewDate");
  if (dateEl) dateEl.value = r?.reviewer?.date || "";

  const safetyEl = $("reviewRiskSafety");
  if (safetyEl) safetyEl.value = r?.ratings?.risk_tier_safety || "";
  const actEl = $("reviewActionability");
  if (actEl) actEl.value = r?.ratings?.actionability ?? "";
  const hoEl = $("reviewHandoff");
  if (hoEl) hoEl.value = r?.ratings?.handoff_quality ?? "";

  const fbEl = $("reviewFeedback");
  if (fbEl) fbEl.value = r?.notes?.feedback || "";
  const imEl = $("reviewImprovement");
  if (imEl) imEl.value = r?.notes?.improvement || "";

  $("reviewIntake").textContent = fmtJson(r.intake || {});
  $("reviewOutput").textContent = fmtJson(r.output_preview || {});
  $("reviewGold").textContent = fmtJson(r.gold_labels || {});
  const goldDetails = $("reviewGold")?.closest("details");
  if (goldDetails) goldDetails.classList.toggle("hidden", !($("reviewShowGold")?.checked && r.gold_labels));

  setTab("review");
  setError("reviewError", "");
}

function deleteSavedReview(r) {
  if (!r) return;
  const ok = confirm(`Delete saved review for ${r.case_id || "case"}?`);
  if (!ok) return;
  const reviews = loadStoredReviews().filter((x) => x && x.id !== r.id);
  saveStoredReviews(reviews);
  renderReviewTable();
}

async function loadReviewCases() {
  const select = $("reviewCaseSelect");
  if (!select) return;
  select.innerHTML = "";

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
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Failed to load vignettes";
    select.appendChild(opt);
  }
}

async function reviewLoadCase() {
  setError("reviewError", "");
  const caseId = String($("reviewCaseSelect")?.value || "").trim();
  if (!caseId) return;

  try {
    const include = $("reviewShowGold")?.checked ? "1" : "0";
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(caseId)}?include_labels=${include}`);
    const intake = resp.input || {};
    const labels = resp.labels || null;

    state.review.lastCaseId = caseId;
    state.review.lastIntake = intake;
    state.review.lastLabels = labels;
    state.review.lastResult = null;

    $("reviewIntake").textContent = fmtJson(intake);
    $("reviewOutput").textContent = fmtJson({});
    $("reviewGold").textContent = fmtJson(labels || {});
    const goldDetails = $("reviewGold")?.closest("details");
    if (goldDetails) goldDetails.classList.toggle("hidden", !(labels && $("reviewShowGold")?.checked));
  } catch (e) {
    setError("reviewError", e);
  }
}

async function reviewRunTriage() {
  setError("reviewError", "");
  const caseId = String($("reviewCaseSelect")?.value || "").trim();
  if (!caseId) return;

  try {
    if (!state.review.lastIntake || state.review.lastCaseId !== caseId) {
      await reviewLoadCase();
    }
    const intake = state.review.lastIntake;
    if (!intake) throw new Error("No intake loaded.");

    const { data } = await postJson("/triage", intake, {});
    const reasoning = traceOutput(data, "multimodal_reasoning");
    const evidence = traceOutput(data, "evidence_policy");
    const safety = traceOutput(data, "safety_escalation");

    const preview = {
      risk_tier: data.risk_tier,
      escalation_required: data.escalation_required,
      red_flags: data.red_flags,
      recommended_next_actions: data.recommended_next_actions,
      clinician_handoff: data.clinician_handoff,
      confidence: data.confidence,
      uncertainty_reasons: data.uncertainty_reasons,
      reasoning_backend: reasoning.reasoning_backend || "",
      reasoning_backend_model: reasoning.reasoning_backend_model || "",
      reasoning_prompt_version: reasoning.reasoning_prompt_version || "",
      policy_pack_sha256: evidence.policy_pack_sha256 || "",
      safety_rules_version: safety.safety_rules_version || "",
    };

    state.review.lastResult = data;
    $("reviewOutput").textContent = fmtJson(preview);
  } catch (e) {
    setError("reviewError", e);
  }
}

function buildReviewMarkdown(reviews) {
  const lines = [];
  lines.push("# ClinicaFlow — Clinician Review Notes (No PHI)");
  lines.push("");
  lines.push(
    "These notes were collected on a **synthetic** vignette regression set. Do not include any real patient identifiers.",
  );
  lines.push("");

  (reviews || []).forEach((r) => {
    lines.push(`## ${r.case_id || "case"}`);
    lines.push("");
    if (r.reviewer?.role || r.reviewer?.setting || r.reviewer?.date) {
      const bits = [];
      if (r.reviewer?.role) bits.push(`role: ${r.reviewer.role}`);
      if (r.reviewer?.setting) bits.push(`setting: ${r.reviewer.setting}`);
      if (r.reviewer?.date) bits.push(`date: ${r.reviewer.date}`);
      if (r.reviewer?.years_in_practice != null) bits.push(`years: ${r.reviewer.years_in_practice}`);
      lines.push(`- ${bits.join(" • ")}`);
    }
    if (r.ratings?.risk_tier_safety) lines.push(`- risk_tier_safety: ${r.ratings.risk_tier_safety}`);
    if (r.ratings?.actionability != null) lines.push(`- actionability: ${r.ratings.actionability}/5`);
    if (r.ratings?.handoff_quality != null) lines.push(`- handoff_quality: ${r.ratings.handoff_quality}/5`);
    lines.push("");

    if (r.output_preview) {
      lines.push("**Output preview:**");
      lines.push("");
      lines.push("```json");
      lines.push(JSON.stringify(r.output_preview, null, 2));
      lines.push("```");
      lines.push("");
    }

    if (r.notes?.feedback) {
      lines.push("**Qualitative feedback:**");
      lines.push("");
      lines.push(r.notes.feedback);
      lines.push("");
    }
    if (r.notes?.improvement) {
      lines.push("**Top improvement suggestion:**");
      lines.push("");
      lines.push(r.notes.improvement);
      lines.push("");
    }
  });

  return lines.join("\n").trim() + "\n";
}

function buildWriteupParagraph() {
  const reviews = loadStoredReviews();
  const caseCount = reviews.length;
  const role = String($("reviewRole")?.value || "").trim();
  const setting = String($("reviewSetting")?.value || "").trim();
  const date = String($("reviewDate")?.value || "").trim();

  const noted = [
    String($("writeupNoted1")?.value || "").trim(),
    String($("writeupNoted2")?.value || "").trim(),
    String($("writeupNoted3")?.value || "").trim(),
  ].filter((x) => x);
  const helpful = String($("writeupHelpful")?.value || "").trim();
  const improve = String($("writeupImprove")?.value || "").trim();

  const bits = [];
  if (role) bits.push(role);
  if (setting) bits.push(setting);
  const who = bits.length ? bits.join(", ") : "a clinician reviewer";
  const when = date ? ` on ${date}` : "";

  const lines = [];
  lines.push(
    `Clinician review (qualitative): We collected structured feedback from ${who}${when} using the built-in synthetic vignette set (n=${caseCount}).`,
  );
  if (noted.length) lines.push(`Key notes: ${noted.map((x) => `“${x}”`).join("; ")}.`);
  if (helpful) lines.push(`Most helpful aspect: “${helpful}”.`);
  if (improve) lines.push(`Top improvement suggestion: “${improve}”.`);
  lines.push("We do not fabricate reviewer feedback; exportable review notes are generated from recorded inputs.");

  return lines.join(" ");
}

function updateReviewParagraph() {
  const out = $("reviewParagraph");
  if (!out) return;
  out.textContent = buildWriteupParagraph();
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
  $("copyNote")?.addEventListener("click", () => {
    if (!state.lastIntake || !state.lastResult) return;
    const md = buildNoteMarkdown(state.lastIntake, state.lastResult);
    copyText(md, "Copied note.md");
  });
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

  // Review tab (optional; UI-local storage)
  const reviewLoad = $("reviewLoadCase");
  if (reviewLoad) reviewLoad.addEventListener("click", () => reviewLoadCase());
  const reviewRun = $("reviewRunTriage");
  if (reviewRun) reviewRun.addEventListener("click", () => reviewRunTriage());
  const reviewGold = $("reviewShowGold");
  if (reviewGold)
    reviewGold.addEventListener("change", () => {
      reviewLoadCase();
    });

  const reviewSave = $("reviewSave");
  if (reviewSave)
    reviewSave.addEventListener("click", () => {
      setError("reviewError", "");
      const caseId = String($("reviewCaseSelect")?.value || "").trim();
      if (!caseId) {
        setError("reviewError", "Select a case first.");
        return;
      }
      if (!state.review.lastResult) {
        setError("reviewError", "Run triage first so the output can be reviewed.");
        return;
      }

      const form = readReviewForm();
      if (!form.ratings.risk_tier_safety) {
        setError("reviewError", "Please select Risk tier safety (safe/borderline/unsafe).");
        return;
      }

      const reviews = loadStoredReviews();
      const now = new Date().toISOString();
      const reasoning = traceOutput(state.review.lastResult, "multimodal_reasoning");
      const evidence = traceOutput(state.review.lastResult, "evidence_policy");
      const safety = traceOutput(state.review.lastResult, "safety_escalation");

      const outputPreview = {
        risk_tier: state.review.lastResult.risk_tier,
        escalation_required: state.review.lastResult.escalation_required,
        red_flags: state.review.lastResult.red_flags,
        recommended_next_actions: state.review.lastResult.recommended_next_actions,
        clinician_handoff: state.review.lastResult.clinician_handoff,
        confidence: state.review.lastResult.confidence,
        uncertainty_reasons: state.review.lastResult.uncertainty_reasons,
      };

      reviews.push({
        id: `${caseId}-${now}-${Math.random().toString(16).slice(2)}`,
        created_at: now,
        case_id: caseId,
        reviewer: form.reviewer,
        ratings: form.ratings,
        notes: form.notes,
        intake: state.review.lastIntake,
        gold_labels: state.review.lastLabels,
        output_preview: outputPreview,
        output_preview_full: {
          ...outputPreview,
          reasoning_backend: reasoning.reasoning_backend || "",
          reasoning_backend_model: reasoning.reasoning_backend_model || "",
          reasoning_prompt_version: reasoning.reasoning_prompt_version || "",
          policy_pack_sha256: evidence.policy_pack_sha256 || "",
          safety_rules_version: safety.safety_rules_version || "",
        },
      });
      saveStoredReviews(reviews);
      renderReviewTable();
      updateReviewParagraph();
      setText("statusLine", "Saved review locally.");
    });

  const reviewClear = $("reviewClear");
  if (reviewClear) reviewClear.addEventListener("click", () => clearReviewForm());

  const reviewDownloadJson = $("reviewDownloadJson");
  if (reviewDownloadJson)
    reviewDownloadJson.addEventListener("click", () => {
      const reviews = loadStoredReviews();
      downloadText("clinician_reviews.json", fmtJson(reviews), "application/json");
      setText("statusLine", "Downloaded clinician_reviews.json");
    });

  const reviewDownloadMd = $("reviewDownloadMd");
  if (reviewDownloadMd)
    reviewDownloadMd.addEventListener("click", () => {
      const reviews = loadStoredReviews();
      downloadText("clinician_review_notes.md", buildReviewMarkdown(reviews), "text/markdown");
      setText("statusLine", "Downloaded clinician_review_notes.md");
    });

  const reviewReset = $("reviewReset");
  if (reviewReset)
    reviewReset.addEventListener("click", () => {
      const ok = confirm("Reset local clinician reviews? This cannot be undone.");
      if (!ok) return;
      saveStoredReviews([]);
      renderReviewTable();
      updateReviewParagraph();
      setText("statusLine", "Reset local reviews.");
    });

  const reviewCaseSel = $("reviewCaseSelect");
  if (reviewCaseSel)
    reviewCaseSel.addEventListener("change", () => {
      // Keep state aligned with selection.
      state.review.lastCaseId = null;
      state.review.lastIntake = null;
      state.review.lastLabels = null;
      state.review.lastResult = null;
      $("reviewIntake").textContent = "{}";
      $("reviewOutput").textContent = "{}";
      $("reviewGold").textContent = "{}";
      const goldDetails = $("reviewGold")?.closest("details");
      if (goldDetails) goldDetails.classList.add("hidden");
    });

  const reviewCopyParagraph = $("reviewCopyParagraph");
  if (reviewCopyParagraph)
    reviewCopyParagraph.addEventListener("click", async () => {
      updateReviewParagraph();
      await copyText($("reviewParagraph")?.textContent || "", "Copied writeup paragraph.");
    });

  // Update paragraph live when inputs change.
  const paragraphInputs = [
    "reviewRole",
    "reviewSetting",
    "reviewDate",
    "writeupNoted1",
    "writeupNoted2",
    "writeupNoted3",
    "writeupHelpful",
    "writeupImprove",
  ];
  paragraphInputs.forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("input", () => updateReviewParagraph());
    el.addEventListener("change", () => updateReviewParagraph());
  });

  // Workspace tab (local-only)
  $("wsSaveIntake")?.addEventListener("click", () => {
    setError("wsError", "");
    try {
      const intake = getIntakeFromUiForWorkspace();
      if (!String(intake.chief_complaint || "").trim()) throw new Error("Chief complaint is required.");
      workspaceAdd({ intake, result: null });
    } catch (e) {
      setError("wsError", e);
    }
  });

  $("wsSaveRun")?.addEventListener("click", () => {
    setError("wsError", "");
    if (!state.lastIntake || !state.lastResult) {
      setError("wsError", "Run triage first so the output can be saved.");
      return;
    }
    workspaceAdd({ intake: state.lastIntake, result: state.lastResult });
  });

  $("wsExport")?.addEventListener("click", () => workspaceExport());

  $("wsImport")?.addEventListener("click", () => {
    const input = $("wsImportFile");
    if (!input) return;
    input.value = "";
    input.click();
  });

  $("wsImportFile")?.addEventListener("change", (ev) => {
    const file = ev?.target?.files?.[0] || null;
    workspaceImportFromFile(file);
  });

  $("wsReset")?.addEventListener("click", () => {
    const ok = confirm("Reset workspace items? This cannot be undone.");
    if (!ok) return;
    saveWorkspaceItems([]);
    state.workspace.selectedId = null;
    renderWorkspaceTable();
    setText("wsStatus", "Reset workspace.");
  });

  $("wsLoadIntoTriage")?.addEventListener("click", () => {
    setError("wsError", "");
    const item = workspaceSelectedItem();
    if (!item) {
      setError("wsError", "Select an item first.");
      return;
    }
    const intake = item.intake || {};
    state.lastIntake = intake;
    fillFormFromIntake(intake);
    $("intakeJson").value = fmtJson(intake);
    setTab("triage");
    setMode("form");
    if (item.result) {
      renderResult(item.result, item.result.request_id || null);
      setText("statusLine", `Loaded saved run: ${item.id}`);
    } else {
      setText("statusLine", `Loaded saved intake: ${item.id}`);
    }
  });

  $("wsDeleteSelected")?.addEventListener("click", () => {
    const item = workspaceSelectedItem();
    if (!item) return;
    workspaceDelete(item.id);
  });
}

async function init() {
  wireEvents();
  setMode("form");
  await loadDoctor();
  await loadPresets();
  await loadPreset();
  await loadReviewCases();
  setReviewIdentityDefaults();
  renderReviewTable();
  updateReviewParagraph();
  renderWorkspaceTable();
}

init().catch((e) => {
  setError("runError", e);
});
