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

// ------------------------------------------------------------
// Lightweight PHI/PII warning (demo only; best-effort heuristics)
// ------------------------------------------------------------

const PHI_PATTERNS = [
  { name: "email", re: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i },
  // Very rough US-centric phone heuristic; intentionally permissive for a warning banner.
  { name: "phone", re: /(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}/ },
  { name: "ssn", re: /\b\d{3}-\d{2}-\d{4}\b/ },
  { name: "mrn", re: /\b(?:mrn|medical\s*record\s*(?:number|no\.?))\b\s*[:#-]?\s*\d{5,}\b/i },
  { name: "dob", re: /\b(?:dob|date\s*of\s*birth)\b\s*[:#-]?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b/i },
];

function detectPhiHits(intake) {
  const hits = [];
  if (!intake || typeof intake !== "object") return hits;

  const fields = [
    { name: "chief_complaint", value: intake.chief_complaint },
    { name: "history", value: intake.history },
    { name: "prior_notes", value: (intake.prior_notes || []).join("\n") },
    { name: "image_descriptions", value: (intake.image_descriptions || []).join("\n") },
  ];

  fields.forEach((f) => {
    const text = String(f.value || "");
    if (!text.trim()) return;
    PHI_PATTERNS.forEach((p) => {
      if (p.re.test(text)) hits.push(`${f.name}:${p.name}`);
    });
  });

  // Dedupe but keep stable ordering.
  return [...new Set(hits)];
}

function updatePhiWarning(intake) {
  const hits = detectPhiHits(intake);
  show("phiWarn", hits.length > 0);
  setText("phiWarnDetail", hits.length ? `Detected: ${hits.join(", ")}` : "");
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
      ...buildAuthHeaders(),
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
  doctor: null,
  metrics: null,
  policyPack: null,
  safetyRules: null,
  imageDataUrls: [],
  lastIntake: null,
  lastResult: null,
  lastRequestId: null,
  lastActionChecklist: null,
  lastSafetyActions: null,
  lastBench: null,
  lastBenchSet: null,
  lastSynthetic: null,
  lastFhirBundle: null,
  review: {
    lastCaseId: null,
    lastIntake: null,
    lastLabels: null,
    lastResult: null,
  },
  workspace: {
    selectedId: null,
    view: "board",
  },
  ops: {
    intervalId: null,
    autoSeconds: 5,
    lastRefreshedAt: null,
    history: [],
  },
  director: {
    enabled: false,
    index: 0,
    startedAt: null,
    timerId: null,
    lastStatus: null,
  },
  auth: {
    apiKey: null,
  },
};

// ---------------------------
// Optional API key auth (UI)
// ---------------------------

const AUTH_API_KEY_STORAGE_KEY = "clinicaflow.auth.api_key.v1";

function loadAuthFromStorage() {
  try {
    const v = sessionStorage.getItem(AUTH_API_KEY_STORAGE_KEY) || "";
    state.auth.apiKey = v.trim() ? v : null;
  } catch (e) {
    state.auth.apiKey = null;
  }
}

function saveAuthToStorage(value) {
  const v = String(value || "").trim();
  state.auth.apiKey = v ? v : null;
  try {
    if (state.auth.apiKey) sessionStorage.setItem(AUTH_API_KEY_STORAGE_KEY, state.auth.apiKey);
    else sessionStorage.removeItem(AUTH_API_KEY_STORAGE_KEY);
  } catch (e) {
    // ignore
  }
  updateAuthBadge();
}

function buildAuthHeaders() {
  const key = String(state.auth?.apiKey || "").trim();
  return key ? { "X-API-Key": key } : {};
}

function updateAuthBadge() {
  const badge = $("authBadge");
  if (!badge) return;
  const required = Boolean(state.doctor?.settings?.api_key_configured);
  const hasKey = Boolean(state.auth?.apiKey);
  if (!required) {
    badge.textContent = "auth: off";
    badge.classList.add("subtle");
    return;
  }
  badge.textContent = hasKey ? "auth: set" : "auth: required";
}

function dataUrlSizeBytes(dataUrl) {
  const s = String(dataUrl || "");
  const idx = s.indexOf(",");
  if (idx === -1) return 0;
  const b64 = s.slice(idx + 1);
  // Rough base64 → bytes estimate.
  return Math.floor((b64.length * 3) / 4);
}

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  return `${(v / (1024 * 1024)).toFixed(2)} MB`;
}

function intakeForJsonView(intake) {
  const out = JSON.parse(JSON.stringify(intake || {}));
  const imgs = out.image_data_urls;
  if (Array.isArray(imgs) && imgs.length) {
    delete out.image_data_urls;
    out.image_data_urls_count = imgs.length;
  }
  return out;
}

function setImages(dataUrls) {
  const arr = Array.isArray(dataUrls)
    ? dataUrls.filter((x) => typeof x === "string" && x.trim().startsWith("data:image/"))
    : [];
  state.imageDataUrls = arr;
  renderImagePreview();
}

function attachImagesToIntake(intake) {
  intake = intake || {};
  // If JSON already includes images, prefer them and hydrate UI state.
  if (Array.isArray(intake.image_data_urls) && intake.image_data_urls.length) {
    setImages(intake.image_data_urls);
    return intake;
  }
  if (Array.isArray(state.imageDataUrls) && state.imageDataUrls.length) {
    return { ...intake, image_data_urls: [...state.imageDataUrls] };
  }
  return intake;
}

function renderImagePreview() {
  const root = $("imagePreview");
  if (!root) return;
  root.innerHTML = "";

  const urls = state.imageDataUrls || [];
  root.classList.toggle("hidden", !urls.length);

  urls.forEach((u, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    const img = document.createElement("img");
    img.src = u;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `image_${idx} • ${formatBytes(dataUrlSizeBytes(u))}`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "×";
    btn.title = "Remove";
    btn.addEventListener("click", () => {
      const next = [...(state.imageDataUrls || [])];
      next.splice(idx, 1);
      setImages(next);
      if ($("intakeJson")) $("intakeJson").value = fmtJson(intakeForJsonView(buildIntakeFromForm()));
    });
    wrap.appendChild(img);
    wrap.appendChild(btn);
    wrap.appendChild(meta);
    root.appendChild(wrap);
  });

  const hint = $("imageHint");
  if (hint) {
    const total = urls.reduce((acc, x) => acc + dataUrlSizeBytes(x), 0);
    const maxBytes = state.doctor?.settings?.max_request_bytes;
    const budget = typeof maxBytes === "number" ? ` • max_request_bytes=${formatBytes(maxBytes)}` : "";
    const warn = typeof maxBytes === "number" && total > maxBytes * 0.75 ? " ⚠ may exceed request limit" : "";
    hint.textContent = `Images in memory: ${urls.length} • approx ${formatBytes(total)}${budget}${warn}`;
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read file."));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
}

function loadImageFromDataUrl(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to decode image."));
    img.src = dataUrl;
  });
}

async function compressImageDataUrl(dataUrl, { maxDim = 512, quality = 0.75 } = {}) {
  // Keep non-image data URLs unchanged.
  if (!String(dataUrl || "").startsWith("data:image/")) return dataUrl;

  const img = await loadImageFromDataUrl(dataUrl);
  const w = img.naturalWidth || img.width || 0;
  const h = img.naturalHeight || img.height || 0;
  if (!w || !h) return dataUrl;

  const scale = Math.min(1, maxDim / Math.max(w, h));
  const outW = Math.max(1, Math.round(w * scale));
  const outH = Math.max(1, Math.round(h * scale));

  const canvas = document.createElement("canvas");
  canvas.width = outW;
  canvas.height = outH;
  const ctx = canvas.getContext("2d");
  if (!ctx) return dataUrl;
  ctx.drawImage(img, 0, 0, outW, outH);

  // JPEG is smaller for demo payloads; acceptable for a synthetic demo.
  return canvas.toDataURL("image/jpeg", quality);
}

async function addUploadedImages(files) {
  const list = Array.from(files || []);
  if (!list.length) return;

  const next = [...(state.imageDataUrls || [])];
  for (const file of list) {
    if (!file || !String(file.type || "").startsWith("image/")) continue;
    const raw = await readFileAsDataUrl(file);
    const compressed = await compressImageDataUrl(raw, { maxDim: 512, quality: 0.75 });
    next.push(compressed);
  }
  setImages(next);
  if ($("intakeJson")) $("intakeJson").value = fmtJson(intakeForJsonView(buildIntakeFromForm()));
}

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
    image_data_urls: [...(state.imageDataUrls || [])],
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

  if (Array.isArray(intake.image_data_urls)) {
    setImages(intake.image_data_urls);
  } else {
    setImages([]);
  }
}

const UI_LAST_TAB_KEY = "clinicaflow.ui.last_tab.v1";
const UI_LAST_MODE_KEY = "clinicaflow.ui.last_mode.v1";

function setMode(mode) {
  state.mode = mode;
  $("mode-form").classList.toggle("hidden", mode !== "form");
  $("mode-json").classList.toggle("hidden", mode !== "json");
  document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));

  try {
    localStorage.setItem(UI_LAST_MODE_KEY, String(mode || ""));
  } catch (e) {
    // ignore
  }
}

function knownTabs() {
  return Array.from(document.querySelectorAll(".tab"))
    .map((b) => String(b.dataset.tab || "").trim())
    .filter((t) => t);
}

function normalizeTabId(tab) {
  const t = String(tab || "").trim();
  if (!t) return "home";
  return knownTabs().includes(t) ? t : "home";
}

function updateTabUrl(tab) {
  const t = normalizeTabId(tab);
  try {
    history.replaceState(null, "", `#${encodeURIComponent(t)}`);
  } catch (e) {
    // ignore
  }
}

function setTab(tab, opts) {
  const options = opts && typeof opts === "object" ? opts : {};
  const t = normalizeTabId(tab);
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  document.querySelectorAll(".tabpanel").forEach((p) => p.classList.toggle("active", p.id === `tab-${t}`));

  try {
    localStorage.setItem(UI_LAST_TAB_KEY, t);
  } catch (e) {
    // ignore
  }

  if (!options.skipUrl) updateTabUrl(t);
}

function loadInitialTab() {
  const raw = String(window.location.hash || "").replace(/^#/, "").trim();
  if (raw) {
    try {
      const decoded = decodeURIComponent(raw);
      if (knownTabs().includes(decoded)) return decoded;
    } catch (e) {
      // ignore
    }
    if (knownTabs().includes(raw)) return raw;
  }

  try {
    const saved = String(localStorage.getItem(UI_LAST_TAB_KEY) || "").trim();
    if (saved && knownTabs().includes(saved)) return saved;
  } catch (e) {
    // ignore
  }

  return "home";
}

function loadInitialMode() {
  try {
    const saved = String(localStorage.getItem(UI_LAST_MODE_KEY) || "").trim();
    if (saved === "form" || saved === "json") return saved;
  } catch (e) {
    // ignore
  }
  return "form";
}

function handleHashChange() {
  const raw = String(window.location.hash || "").replace(/^#/, "").trim();
  if (!raw) return;
  let decoded = raw;
  try {
    decoded = decodeURIComponent(raw);
  } catch (e) {
    // ignore
  }
  if (!knownTabs().includes(decoded)) return;
  setTab(decoded, { skipUrl: true });
}

async function clearLocalDemoData() {
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
  } catch (e) {
    // ignore
  }

  try {
    sessionStorage.removeItem(AUTH_API_KEY_STORAGE_KEY);
  } catch (e) {
    // ignore
  }

  // Best-effort: clear service-worker caches for a "clean slate" demo.
  try {
    if (window.caches && typeof window.caches.keys === "function") {
      const keys = await window.caches.keys();
      await Promise.all(keys.map((k) => window.caches.delete(k)));
    }
  } catch (e) {
    // ignore
  }

  // Some browsers can keep serving stale JS/CSS from an old service-worker
  // even after a backend upgrade. Unregister to force a clean install.
  try {
    if ("serviceWorker" in navigator && typeof navigator.serviceWorker.getRegistrations === "function") {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch (e) {
    // ignore
  }
}

// ---------------------------
// Home dashboard + onboarding
// ---------------------------

const WELCOME_DISMISSED_KEY = "clinicaflow.ui.welcome_dismissed.v1";

let _swHadControllerAtLoad = false;
let _swReloadedForUpdate = false;
let _swControllerListenerAdded = false;

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    _swHadControllerAtLoad = Boolean(navigator.serviceWorker.controller);

    const reg = await navigator.serviceWorker.register("/static/sw.js", { scope: "/" });
    if (reg && typeof reg.update === "function") {
      // Encourage an update check on each load (helps avoid stale UI assets).
      reg.update();
    }
  } catch (e) {
    // ignore
  }

  if (!_swControllerListenerAdded) {
    _swControllerListenerAdded = true;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // Only auto-reload when upgrading from an existing controller.
      if (!_swHadControllerAtLoad) return;
      if (_swReloadedForUpdate) return;
      _swReloadedForUpdate = true;
      try {
        window.location.reload();
      } catch (e) {
        // ignore
      }
    });
  }
}

function closeWelcomeModal() {
  const dontShow = Boolean($("welcomeDontShow")?.checked);
  if (dontShow) {
    try {
      localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    } catch (e) {
      // ignore
    }
  }
  show("welcomeModal", false);
}

function maybeShowWelcomeModal() {
  try {
    const dismissed = localStorage.getItem(WELCOME_DISMISSED_KEY) || "";
    if (dismissed.trim()) return;
  } catch (e) {
    // ignore
  }
  show("welcomeModal", true);
}

// ---------------------------
// Director mode (3-minute demo)
// ---------------------------

function formatClock(ms) {
  const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = String(totalSeconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

const DIRECTOR_STEPS = [
  {
    id: "intro",
    tab: "home",
    title: "Intro + safety posture",
    text: "Confirm synthetic-only + decision-support only. Then show the 5-agent workflow and system status cards.",
    say: [
      "This is ClinicaFlow, a decision-support triage copilot built for the MedGemma Impact Challenge.",
      "",
      "Important: this demo uses synthetic vignettes only (no PHI). ClinicaFlow does not diagnose — it drafts a triage recommendation for clinician review.",
      "",
      "ClinicaFlow runs a 5-agent workflow: structuring → MedGemma reasoning → evidence/policy → deterministic safety gate → communication, with a full audit trace and exportable artifacts.",
    ].join("\n"),
    highlight: ["#homeStartDemo", ".flow", "#homeDownloadAudit", "#homeDownloadJudgePack"],
  },
  {
    id: "ops",
    tab: "ops",
    title: "Ops readiness (/doctor + /metrics)",
    text: "Show which backends are active, policy hash, and per-agent latencies/errors. (No secrets.)",
    say: [
      "First, ops readiness. The console pulls live health and metrics from /doctor and /metrics.",
      "",
      "We can see which reasoning backend is active (MedGemma vs deterministic fallback), the policy pack SHA for governance, and per-agent latency/error breakdowns.",
    ].join("\n"),
    doLabel: "Refresh ops",
    do: async () => {
      await refreshOps();
    },
    highlight: ["#opsRefresh", "#opsChart", "#opsAgentBody", "#opsAlerts"],
  },
  {
    id: "critical",
    tab: "triage",
    title: "Critical vignette (MedGemma + safety gate)",
    text: "Run the high-acuity case and point to risk tier, escalation, safety triggers, and next actions.",
    say: [
      "Now a critical synthetic vignette: chest pain with hypotension.",
      "",
      "MedGemma generates the differential + rationale, but escalation is enforced deterministically by the safety gate. The output includes red flags, safety triggers, next actions, and an SBAR-style clinician handoff.",
    ].join("\n"),
    doLabel: "Load + run critical case",
    do: async () => {
      await demoLoadAndRun("v01_chest_pain_hypotension");
      const traceDetails = $("trace")?.closest("details");
      if (traceDetails) traceDetails.open = true;
    },
    highlight: ["#riskTier", "#safetyTriggers", "#actions", "#traceMini", "#trace"],
  },
  {
    id: "export",
    tab: "triage",
    title: "Audit & report export (redacted)",
    text: "Download a redacted audit bundle and optionally the printable report / note draft.",
    say: [
      "For auditability, we can export a redacted audit bundle: intake + outputs + manifest hashes + trace, without any images or identifiers.",
      "",
      "We also provide a printable report and a note draft for clinician review.",
    ].join("\n"),
    doLabel: "Download audit (redacted)",
    do: async () => {
      await downloadAuditBundle(true);
    },
    highlight: ["#downloadRedacted", "#downloadReport", "#downloadNote"],
  },
  {
    id: "judgepack",
    tab: "triage",
    title: "One-click judge pack.zip",
    text: "Download a single zip bundling triage artifacts + benchmarks + governance + ops snapshots.",
    say: [
      "For judge-friendly inspection, we provide a single judge pack zip.",
      "",
      "It bundles the redacted triage audit artifacts plus regression benchmarks, governance report, safety rules, policy pack metadata, and ops snapshots—ready to attach or inspect offline.",
    ].join("\n"),
    doLabel: "Download judge pack.zip",
    do: async () => {
      await downloadJudgePack();
    },
    highlight: ["#downloadJudgePack"],
  },
  {
    id: "governance",
    tab: "governance",
    title: "Regression + governance gate",
    text: "Run the mega vignette benchmark and show under-triage + red-flag recall metrics.",
    say: [
      "Next, governance. We run a vignette regression set and track red-flag recall and under-triage.",
      "",
      "The key safety objective is to minimize under-triage of urgent/critical cases; the governance view surfaces failures and exports a failure packet for clinician QA.",
    ].join("\n"),
    doLabel: "Run mega benchmark",
    do: async () => {
      if ($("govBenchSet")) $("govBenchSet").value = "mega";
      await runBenchSet("mega", $("govStatus"));
    },
    highlight: ["#govRunBench", "#govGate", "#govUnder", "#govDownloadFailure"],
  },
  {
    id: "rules",
    tab: "rules",
    title: "Deterministic safety rulebook",
    text: "Load and filter the explicit trigger catalog powering the safety agent.",
    say: [
      "Finally, transparency: the safety gate is built on an explicit, versioned rulebook.",
      "",
      "These triggers are inspectable, testable, and replaceable with site protocols; the model can't “talk its way” out of escalation criteria.",
    ].join("\n"),
    doLabel: "Load rulebook",
    do: async () => {
      await loadSafetyRules();
    },
    highlight: ["#rulesRefresh", "#rulesMeta", "#tab-rules .tablewrap"],
  },
  {
    id: "workspace",
    tab: "workspace",
    title: "Shift handoff + wrap-up",
    text: "Export a shift_handoff.md from the local workspace queue, then wrap up.",
    say: [
      "Wrap-up: ClinicaFlow is designed for real clinic workflows.",
      "",
      "Runs can be saved to a local workspace queue, then exported as a shift handoff markdown for the next clinician.",
      "",
      "Again: decision support only — validate on-site with clinician oversight.",
    ].join("\n"),
    doLabel: "Download shift_handoff.md",
    do: async () => {
      await workspaceDownloadShiftHandoff();
    },
    highlight: ["#wsDownloadHandoff", "#wsSummary", "#tab-workspace .tablewrap"],
  },
];

function directorStep() {
  const idx = Math.max(0, Math.min(Number(state.director.index) || 0, DIRECTOR_STEPS.length - 1));
  state.director.index = idx;
  return DIRECTOR_STEPS[idx];
}

function directorElapsedMs() {
  const startedAt = Number(state.director.startedAt) || 0;
  return startedAt ? Date.now() - startedAt : 0;
}

function directorSetStatus(text) {
  state.director.lastStatus = String(text || "");
  setText("directorStatus", state.director.lastStatus || "—");
}

function updateDirectorToggle() {
  const btn = $("directorToggle");
  if (!btn) return;
  const on = Boolean(state.director.enabled);
  btn.textContent = on ? "Director: on" : "Director: off";
  btn.classList.toggle("primary", on);
  btn.classList.toggle("subtle", !on);
}

function directorIsVisible(el) {
  if (!el || !(el instanceof HTMLElement)) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function directorClearHighlights() {
  document.querySelectorAll(".director-highlight").forEach((el) => el.classList.remove("director-highlight"));
}

function directorHighlightTarget(el) {
  if (!el || !(el instanceof HTMLElement)) return null;

  if (el.classList.contains("btn")) {
    el.classList.add("director-highlight");
    return el;
  }

  const tag = String(el.tagName || "").toUpperCase();
  if (tag === "TBODY" || tag === "TR" || tag === "TD" || tag === "TH" || tag === "TABLE") {
    const wrap = el.closest(".tablewrap");
    if (wrap) {
      wrap.classList.add("director-highlight");
      return wrap;
    }
  }

  const card = el.closest(".card");
  if (card) {
    card.classList.add("director-highlight");
    return card;
  }

  const callout = el.closest(".callout");
  if (callout) {
    callout.classList.add("director-highlight");
    return callout;
  }

  el.classList.add("director-highlight");
  return el;
}

function directorApplyHighlights(step) {
  directorClearHighlights();
  if (!step || !step.highlight) return;
  const selectors = Array.isArray(step.highlight) ? step.highlight : [step.highlight];
  let firstVisible = null;

  selectors.forEach((sel) => {
    try {
      document.querySelectorAll(sel).forEach((el) => {
        const target = directorHighlightTarget(el);
        if (!firstVisible && directorIsVisible(target)) firstVisible = target;
      });
    } catch (e) {
      // ignore invalid selectors
    }
  });

  if (firstVisible) {
    try {
      firstVisible.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      // ignore
    }
  }
}

function directorUpdateMeta(step) {
  const total = DIRECTOR_STEPS.length;
  const idx = Number(state.director.index) || 0;
  const tab = step?.tab ? String(step.tab) : "—";
  const elapsed = formatClock(directorElapsedMs());
  setText("directorMeta", `Step ${idx + 1}/${total} • ${tab} • ${elapsed} • N/P/D/Esc`);
}

function directorRender({ resetStatus = true } = {}) {
  if (!state.director.enabled) return;
  const step = directorStep();

  if (step.tab) setTab(step.tab);

  setText("directorStepTitle", step.title || "—");
  setText("directorStepText", step.text || "—");
  setText("directorSay", step.say || "—");
  directorUpdateMeta(step);

  const back = $("directorBack");
  const next = $("directorNext");
  const doBtn = $("directorDo");

  if (back) back.disabled = state.director.index <= 0;
  if (next) next.disabled = state.director.index >= DIRECTOR_STEPS.length - 1;

  const hasDo = typeof step.do === "function";
  if (doBtn) {
    doBtn.disabled = !hasDo;
    doBtn.textContent = step.doLabel || "Do step";
  }

  if (resetStatus) directorSetStatus("Ready.");
  directorApplyHighlights(step);
}

function directorStart() {
  state.director.enabled = true;
  state.director.index = 0;
  state.director.startedAt = Date.now();
  directorSetStatus("Ready.");
  updateDirectorToggle();
  show("directorOverlay", true);
  show("welcomeModal", false);

  if (state.director.timerId) clearInterval(state.director.timerId);
  state.director.timerId = setInterval(() => {
    if (!state.director.enabled) return;
    directorUpdateMeta(directorStep());
  }, 1000);

  directorRender({ resetStatus: false });
}

function directorEnd() {
  state.director.enabled = false;
  updateDirectorToggle();
  show("directorOverlay", false);
  directorClearHighlights();
  if (state.director.timerId) clearInterval(state.director.timerId);
  state.director.timerId = null;
  state.director.startedAt = null;
}

function directorNext() {
  if (!state.director.enabled) return;
  state.director.index = Math.min(DIRECTOR_STEPS.length - 1, Number(state.director.index) + 1);
  directorRender();
}

function directorBack() {
  if (!state.director.enabled) return;
  state.director.index = Math.max(0, Number(state.director.index) - 1);
  directorRender();
}

async function directorDoStep() {
  if (!state.director.enabled) return;
  const step = directorStep();
  if (typeof step.do !== "function") return;

  const doBtn = $("directorDo");
  if (doBtn) doBtn.disabled = true;
  directorSetStatus("Running…");
  try {
    await step.do();
    directorSetStatus("Done.");
  } catch (e) {
    directorSetStatus(`Error: ${e}`);
  } finally {
    if (doBtn) doBtn.disabled = false;
    directorApplyHighlights(step);
    directorUpdateMeta(step);
  }
}

function directorToggle() {
  if (state.director.enabled) directorEnd();
  else directorStart();
}

function directorHandleHotkeys(ev) {
  if (!state.director.enabled) return;
  const tag = String(ev?.target?.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || ev?.target?.isContentEditable) return;

  if (ev.key === "Escape") {
    ev.preventDefault();
    directorEnd();
    return;
  }

  if (ev.key === "n" || ev.key === "N" || ev.key === "ArrowRight") {
    ev.preventDefault();
    directorNext();
    return;
  }

  if (ev.key === "p" || ev.key === "P" || ev.key === "ArrowLeft") {
    ev.preventDefault();
    directorBack();
    return;
  }

  if (ev.key === "d" || ev.key === "D") {
    ev.preventDefault();
    directorDoStep();
  }
}

function renderHome() {
  const back = $("homeBackends");
  const policyRules = $("homePolicyRules");
  const ops = $("homeOps");
  const last = $("homeLastRun");
  if (!back && !policyRules && !ops && !last) return;

  const d = state.doctor || {};
  const rb = d.reasoning_backend || {};
  const cb = d.communication_backend || {};
  const pp = d.policy_pack || {};
  const m = state.metrics || {};

  if (back) {
    const rbBits = [String(rb.backend || "deterministic")];
    if (rb.model) rbBits.push(String(rb.model));
    if (rb.connectivity_ok === true) rbBits.push("ok");
    else if (rb.connectivity_ok === false) rbBits.push("unreachable");

    const cbBits = [String(cb.backend || "deterministic")];
    if (cb.model) cbBits.push(String(cb.model));
    if (cb.connectivity_ok === true) cbBits.push("ok");
    else if (cb.connectivity_ok === false) cbBits.push("unreachable");

    back.textContent = `reasoning: ${rbBits.join(" • ")}  |  comm: ${cbBits.join(" • ")}`;
  }

  if (policyRules) {
    const sha = String(pp.sha256 || "").trim();
    const shaShort = sha ? `${sha.slice(0, 12)}…` : "(none)";
    const rulesVer = String(state.safetyRules?.safety_rules_version || "").trim();
    const rulesText = rulesVer ? rulesVer : "(not loaded — open Rules tab)";
    const phi = d?.privacy?.phi_guard_enabled;
    const phiText = phi === false ? "phi_guard: off" : "phi_guard: on";
    policyRules.textContent = `policy_sha256: ${shaShort}  |  safety_rules: ${rulesText}  |  ${phiText}`;
  }

  if (ops) {
    const uptime = formatUptime(m.uptime_s);
    const req = m.requests_total != null ? String(m.requests_total) : "—";
    const triOk = m.triage_success_total != null ? String(m.triage_success_total) : "—";
    const triErr = m.triage_errors_total != null ? String(m.triage_errors_total) : "—";
    const avg = typeof m.triage_latency_ms_avg === "number" ? `${m.triage_latency_ms_avg} ms` : "—";
    ops.textContent = `uptime: ${uptime} • requests: ${req} • triage ok/err: ${triOk}/${triErr} • avg latency: ${avg}`;
  }

  const hasRun = Boolean(state.lastIntake && state.lastResult);
  const btnAudit = $("homeDownloadAudit");
  if (btnAudit) btnAudit.disabled = !hasRun;
  const btnReport = $("homeDownloadReport");
  if (btnReport) btnReport.disabled = !hasRun;
  const btnJudge = $("homeDownloadJudgePack");
  if (btnJudge) btnJudge.disabled = !hasRun;
  const btnJudge2 = $("downloadJudgePack");
  if (btnJudge2) btnJudge2.disabled = !hasRun;
  const btnOpen = $("homeOpenTrace");
  if (btnOpen) btnOpen.disabled = !Boolean(state.lastResult);

  if (last) {
    if (!state.lastResult) {
      last.textContent = "No run yet.";
    } else {
      const r = state.lastResult || {};
      const rid = state.lastRequestId || r.request_id || "—";
      const tier = r.risk_tier || "—";
      const backend = extractBackend(r);
      const ms = r.total_latency_ms ?? "—";
      last.textContent = `request_id=${rid} • tier=${tier} • backend=${backend} • latency=${ms} ms`;
    }
  }
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

function formatRiskScores(scores) {
  scores = scores || {};
  const parts = [];
  if (typeof scores.shock_index === "number") {
    const hi = scores.shock_index_high ? " (high)" : "";
    parts.push(`shock_index=${scores.shock_index}${hi}`);
  }
  if (typeof scores.qsofa === "number") {
    const hi = scores.qsofa_high_risk ? " (≥2)" : "";
    parts.push(`qSOFA=${scores.qsofa}${hi}`);
  }
  return parts.length ? parts.join(" • ") : "—";
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

function renderSignalsSummary(structured) {
  const root = $("signalsSummary");
  if (!root) return;

  const symptoms = Array.isArray(structured?.symptoms) ? structured.symptoms.map((x) => String(x)).filter((x) => x.trim()) : [];
  const risk = Array.isArray(structured?.risk_factors) ? structured.risk_factors.map((x) => String(x)).filter((x) => x.trim()) : [];

  root.innerHTML = "";
  if (!symptoms.length && !risk.length) {
    root.textContent = "—";
    return;
  }

  function section(label, items) {
    const title = document.createElement("div");
    title.className = "small muted";
    title.textContent = label;
    root.appendChild(title);

    const chips = document.createElement("div");
    chips.className = "chips";
    (items || []).forEach((text) => {
      const span = document.createElement("span");
      span.className = "chip";
      span.textContent = String(text);
      chips.appendChild(span);
    });
    if (!(items || []).length) {
      const span = document.createElement("span");
      span.className = "chip";
      span.textContent = "(none)";
      chips.appendChild(span);
    }
    root.appendChild(chips);
  }

  section("Symptoms", symptoms.slice(0, 8));
  section("Risk factors", risk.slice(0, 8));
}

function renderQualityWarnings(warnings) {
  const root = $("qualityWarnings");
  if (!root) return;

  const rows = Array.isArray(warnings) ? warnings.map((x) => String(x)).filter((x) => x.trim()) : [];
  root.innerHTML = "";
  if (!rows.length) {
    root.textContent = "None.";
    return;
  }

  const chips = document.createElement("div");
  chips.className = "chips";

  rows.slice(0, 8).forEach((text) => {
    const span = document.createElement("span");
    span.className = "chip warn";
    span.textContent = text;
    chips.appendChild(span);
  });

  root.appendChild(chips);
}

function renderSafetyTriggers(triggers) {
  const root = $("safetyTriggers");
  if (!root) return;

  const rows = Array.isArray(triggers) ? triggers.filter((x) => x && typeof x === "object") : [];
  root.innerHTML = "";
  if (!rows.length) {
    root.textContent = "None.";
    return;
  }

  const chips = document.createElement("div");
  chips.className = "chips";

  rows.forEach((t) => {
    const sev = String(t.severity || "").toLowerCase();
    const label = String(t.label || t.id || "").trim();
    const detail = String(t.detail || "").trim();
    if (!label) return;
    const span = document.createElement("span");
    span.className = `chip ${sev === "critical" ? "bad" : sev === "urgent" ? "warn" : "ok"}`;
    span.textContent = label;
    if (detail) span.title = detail;
    chips.appendChild(span);
  });

  if (!chips.childNodes.length) {
    root.textContent = "—";
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

const ACTION_CHECKLIST_KEY_PREFIX = "clinicaflow.action_checklist.v1.";

function _actionChecklistKey(requestId) {
  const rid = String(requestId || "").trim() || "unknown";
  return `${ACTION_CHECKLIST_KEY_PREFIX}${rid}`;
}

function loadActionChecklist(requestId) {
  try {
    const raw = localStorage.getItem(_actionChecklistKey(requestId)) || "";
    if (!raw.trim()) return null;
    const payload = JSON.parse(raw);
    return Array.isArray(payload) ? payload : null;
  } catch (e) {
    return null;
  }
}

function saveActionChecklist(requestId, checklist) {
  const rid = String(requestId || "").trim();
  if (!rid) return;
  try {
    localStorage.setItem(_actionChecklistKey(rid), JSON.stringify(checklist || []));
  } catch (e) {
    // ignore
  }
}

function normalizeChecklist(actions, saved) {
  const byText = new Map();
  (saved || []).forEach((x) => {
    if (!x) return;
    if (typeof x === "string") {
      byText.set(x, false);
      return;
    }
    const text = String(x.text || "").trim();
    if (!text) return;
    byText.set(text, Boolean(x.checked));
  });

  return (actions || [])
    .map((t) => String(t || "").trim())
    .filter((t) => t)
    .map((t) => ({ text: t, checked: byText.get(t) || false }));
}

function updateNotePreview() {
  const el = $("notePreview");
  if (!el) return;
  if (!state.lastIntake || !state.lastResult) {
    el.textContent = "—";
    return;
  }
  try {
    el.textContent = buildNoteMarkdown(state.lastIntake, state.lastResult, state.lastActionChecklist).trim() + "\n";
  } catch (e) {
    el.textContent = `Error building note: ${e}`;
  }
}

function updateActionsProgress(checklist) {
  const el = $("actionsProgress");
  if (!el) return;
  const total = (checklist || []).length;
  const done = (checklist || []).filter((x) => x && x.checked).length;
  const legend =
    state.lastSafetyActions && state.lastSafetyActions.length ? "  •  Tags: SAFETY=rules, POLICY=policy pack" : "";
  el.textContent = total ? `Checklist: ${done}/${total} completed (stored locally).${legend}` : "No actions.";
}

function renderActionChecklist(actions, requestId, opts) {
  const root = $("actions");
  if (!root) return;
  root.innerHTML = "";

  const meta = opts && typeof opts === "object" ? opts : {};
  const safetyRaw = Array.isArray(meta.safetyActions) ? meta.safetyActions : [];
  const safetySet = new Set(safetyRaw.map((x) => String(x || "").trim()).filter((x) => x));
  state.lastSafetyActions = Array.from(safetySet);

  const saved = loadActionChecklist(requestId);
  const checklist = normalizeChecklist(actions, saved);
  state.lastActionChecklist = checklist;

  if (!checklist.length) {
    const li = document.createElement("li");
    li.textContent = "No actions suggested.";
    root.appendChild(li);
    updateActionsProgress([]);
    return;
  }

  checklist.forEach((item, idx) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = `action-check${item.checked ? " done" : ""}`;

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = Boolean(item.checked);
    cb.setAttribute("aria-label", `Action ${idx + 1}`);
    cb.addEventListener("change", () => {
      item.checked = cb.checked;
      label.classList.toggle("done", cb.checked);
      saveActionChecklist(requestId, checklist);
      updateActionsProgress(checklist);
      updateNotePreview();
    });

    const isSafety = safetySet.has(String(item.text || "").trim());
    const tag = document.createElement("span");
    tag.className = `tag ${isSafety ? "safety" : "policy"}`;
    tag.textContent = isSafety ? "SAFETY" : "POLICY";
    tag.title = isSafety ? "Added by deterministic safety rules" : "Suggested by evidence/policy agent";

    const txt = document.createElement("span");
    txt.textContent = item.text;

    label.appendChild(cb);
    if (safetySet.size) label.appendChild(tag);
    label.appendChild(txt);
    li.appendChild(label);
    root.appendChild(li);
  });

  // Persist initial state so later exports are stable.
  saveActionChecklist(requestId, checklist);
  updateActionsProgress(checklist);
  updateNotePreview();
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

  (trace || []).forEach((step, idx) => {
    const details = document.createElement("details");
    details.open = false;
    const summary = document.createElement("summary");
    const agent = step.agent || "agent";
    details.dataset.agent = String(agent);
    details.id = `trace-${String(agent).replaceAll("_", "-")}-${idx}`;
    const latency = step.latency_ms != null ? `${step.latency_ms} ms` : "";
    summary.textContent = `${agent}  ${latency}`.trim();
    details.appendChild(summary);

    const pre = document.createElement("pre");
    pre.className = "pre mono";
    pre.style.maxHeight = "340px";
    pre.textContent = fmtJson(step.output || {});
    details.appendChild(pre);

    const agentName = String(step.agent || "");
    const out = step.output && typeof step.output === "object" ? step.output : {};
    if (!step.error) {
      let derived = "";
      let skipped = "";
      if (agentName === "multimodal_reasoning") {
        derived = String(out.reasoning_backend_error || "").trim();
        skipped = String(out.reasoning_backend_skipped_reason || "").trim();
      } else if (agentName === "communication") {
        derived = String(out.communication_backend_error || "").trim();
        skipped = String(out.communication_backend_skipped_reason || "").trim();
      }

      if (derived) {
        const err = document.createElement("div");
        err.className = "alert";
        err.textContent = `Backend fallback: ${derived}`;
        details.appendChild(err);
      } else if (skipped) {
        const msg = document.createElement("div");
        msg.className = "callout";
        msg.textContent = `External call skipped: ${skipped}`;
        details.appendChild(msg);
      }
    }

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

const WORKFLOW_ORDER = [
  "intake_structuring",
  "multimodal_reasoning",
  "evidence_policy",
  "safety_escalation",
  "communication",
];

const WORKFLOW_LABELS = {
  intake_structuring: "Structuring",
  multimodal_reasoning: "Reasoning",
  evidence_policy: "Policy",
  safety_escalation: "Safety",
  communication: "Handoff",
};

let _runStepperTimerId = null;
let _runStepperIndex = 0;

function stopRunStepper() {
  if (_runStepperTimerId != null) {
    clearInterval(_runStepperTimerId);
    _runStepperTimerId = null;
  }
}

function startRunStepper() {
  stopRunStepper();
  _runStepperIndex = 0;
  renderTraceMini([], { runningIndex: _runStepperIndex });
  _runStepperTimerId = setInterval(() => {
    _runStepperIndex = (_runStepperIndex + 1) % WORKFLOW_ORDER.length;
    renderTraceMini([], { runningIndex: _runStepperIndex });
  }, 650);
}

function renderTraceMini(trace, opts) {
  const root = $("traceMini");
  if (!root) return;

  const steps = Array.isArray(trace) ? trace : [];
  const meta = opts && typeof opts === "object" ? opts : {};
  const runningIndexRaw = meta.runningIndex;
  const runningIndex =
    typeof runningIndexRaw === "number" && Number.isFinite(runningIndexRaw) ? Math.max(0, runningIndexRaw) : null;

  const wrap = document.createElement("div");
  wrap.className = "trace-stepper";

  function jumpTo(agentName) {
    const esc =
      window.CSS && typeof window.CSS.escape === "function"
        ? window.CSS.escape(agentName)
        : String(agentName || "").replaceAll('"', '\\"');
    const selector = `#trace details[data-agent="${esc}"]`;
    const target = document.querySelector(selector);
    if (!target) return;
    target.open = true;
    try {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      target.scrollIntoView();
    }
  }

  if (!steps.length) {
    WORKFLOW_ORDER.forEach((agentName, idx) => {
      const label = WORKFLOW_LABELS[agentName] || agentName.replaceAll("_", " ");
      const isRunning = runningIndex != null && idx === runningIndex;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.disabled = true;
      btn.className = `step ${isRunning ? "running" : "pending"}`;
      btn.title = isRunning ? "Running…" : "Pending…";

      const dot = document.createElement("span");
      dot.className = "dot";

      const body = document.createElement("span");
      const title = document.createElement("div");
      title.className = "step-title";
      title.textContent = label;
      const metaLine = document.createElement("div");
      metaLine.className = "step-meta mono";
      metaLine.textContent = isRunning ? "RUNNING…" : "pending";
      body.appendChild(title);
      body.appendChild(metaLine);

      btn.appendChild(dot);
      btn.appendChild(body);
      wrap.appendChild(btn);
    });

    root.innerHTML = "";
    root.appendChild(wrap);
    return;
  }

  steps.forEach((step) => {
    const agentName = String(step.agent || "agent");
    const label = WORKFLOW_LABELS[agentName] || agentName.replaceAll("_", " ");
    const latency = step.latency_ms != null ? `${step.latency_ms} ms` : "—";
    const hasErr = Boolean(String(step.error || "").trim());
    const out = step.output && typeof step.output === "object" ? step.output : {};
    let derivedErr = "";
    let derivedSkip = "";
    if (agentName === "multimodal_reasoning") {
      derivedErr = String(out.reasoning_backend_error || "").trim();
      derivedSkip = String(out.reasoning_backend_skipped_reason || "").trim();
    } else if (agentName === "communication") {
      derivedErr = String(out.communication_backend_error || "").trim();
      derivedSkip = String(out.communication_backend_skipped_reason || "").trim();
    }
    const hasDerivedErr = Boolean(derivedErr);
    const hasSkip = Boolean(derivedSkip);
    const ms = typeof step.latency_ms === "number" ? step.latency_ms : null;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `step${hasErr || hasDerivedErr ? " bad" : hasSkip || (ms != null && ms > 900) ? " warn" : ""}`;
    btn.title = derivedErr
      ? `Backend fallback: ${derivedErr}`
      : derivedSkip
        ? `External call skipped: ${derivedSkip}`
        : "Jump to full agent output";
    btn.addEventListener("click", () => jumpTo(agentName));

    const dot = document.createElement("span");
    dot.className = "dot";

    const body = document.createElement("span");
    const title = document.createElement("div");
    title.className = "step-title";
    title.textContent = label;
    const meta = document.createElement("div");
    meta.className = "step-meta mono";
    meta.textContent = hasErr
      ? `ERROR • ${latency}`
      : hasDerivedErr
        ? `FALLBACK • ${latency}`
        : hasSkip
          ? `SKIP • ${latency}`
          : latency;
    body.appendChild(title);
    body.appendChild(meta);

    btn.appendChild(dot);
    btn.appendChild(body);
    wrap.appendChild(btn);
  });

  root.innerHTML = "";
  root.appendChild(wrap);
}

function renderDecisionBanner(result) {
  const el = $("decisionBanner");
  if (!el) return;

  const tier = String(result?.risk_tier || "").trim().toLowerCase();
  if (!tier) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }

  el.classList.remove("hidden", "routine", "urgent", "critical");
  if (tier === "routine" || tier === "urgent" || tier === "critical") el.classList.add(tier);

  const safety = traceOutput(result, "safety_escalation");
  const rationale = String(safety?.risk_tier_rationale || "").trim();
  const redFlags = Array.isArray(result?.red_flags) ? result.red_flags.map((x) => String(x)).filter((x) => x.trim()) : [];
  const actions = Array.isArray(result?.recommended_next_actions)
    ? result.recommended_next_actions.map((x) => String(x)).filter((x) => x.trim())
    : [];

  let title = `Triage: ${tier.toUpperCase()}`;
  let subtitle = "Decision support only — clinician confirmation required.";
  if (tier === "critical") {
    title = "CRITICAL — emergency evaluation now";
    subtitle = "Escalation required. Do not delay clinician review.";
  } else if (tier === "urgent") {
    title = "URGENT — same-day evaluation";
    subtitle = "Escalation required. Ensure clinician review today.";
  } else if (tier === "routine") {
    title = "ROUTINE — stable (with return precautions)";
    subtitle = "No explicit red flags detected in provided intake.";
  }

  el.innerHTML = "";

  const t = document.createElement("div");
  t.className = "banner-title";
  t.textContent = title;

  const s = document.createElement("div");
  s.className = "banner-subtitle";
  s.textContent = subtitle;

  el.appendChild(t);
  el.appendChild(s);

  const meta = document.createElement("div");
  meta.className = "banner-meta";

  const topAction = actions.length ? actions[0] : "";
  const topFlags = redFlags.slice(0, 2).join(" • ");
  const bits = [];
  if (rationale) bits.push(`Why: ${rationale}`);
  if (topFlags) bits.push(`Red flags: ${topFlags}${redFlags.length > 2 ? " • …" : ""}`);
  if (topAction) bits.push(`Top action: ${topAction}`);
  meta.textContent = bits.length ? bits.join("  |  ") : "—";

  el.appendChild(meta);
}

function renderResult(result, requestIdFromHeader) {
  state.lastResult = result;
  state.lastRequestId = requestIdFromHeader || result.request_id || null;
  state.lastFhirBundle = null;
  setText("fhirPreview", "{}");

  renderDecisionBanner(result);
  setRiskTier(result.risk_tier);
  setText("careSetting", careSettingFromTier(result.risk_tier));
  renderVitalsSummary(state.lastIntake);
  const backend = extractBackend(result);
  const commBackend = extractCommBackend(result);
  setText(
    "metaLine",
    `request_id: ${state.lastRequestId || "—"} • latency: ${result.total_latency_ms ?? "—"} ms • reasoning: ${backend} • comm: ${commBackend}`,
  );

  const escalation = result.escalation_required ? "required" : "not required";
  setText("escalationPill", `escalation: ${escalation}`);

  const safety = traceOutput(result, "safety_escalation");
  const tierRationale = safety.risk_tier_rationale || "—";
  setText(
    "tierRationale",
    safety.safety_rules_version ? `${tierRationale} • rules: ${safety.safety_rules_version}` : tierRationale,
  );
  setText("riskScores", formatRiskScores(safety.risk_scores || {}));

  renderList($("differential"), result.differential_considerations, {
    ordered: false,
    emptyText: "No differential suggestions.",
  });
  renderList($("uncertainty"), result.uncertainty_reasons, { ordered: false, emptyText: "No uncertainty flags." });
  renderList($("redFlags"), result.red_flags, { ordered: false, emptyText: "No explicit red flags detected." });
  renderActionChecklist(result.recommended_next_actions || [], state.lastRequestId || result.request_id || "", {
    safetyActions: safety.actions_added_by_safety || [],
  });
  updateNotePreview();

  const conf = typeof result.confidence === "number" ? result.confidence : null;
  setText("confidenceVal", conf == null ? "—" : `confidence: ${(conf * 100).toFixed(0)}%`);
  $("confidenceBar").style.width = conf == null ? "0%" : `${Math.max(0, Math.min(1, conf)) * 100}%`;

  const structured = traceOutput(result, "intake_structuring");
  $("structuredOut").textContent = fmtJson(structured || {});
  renderSignalsSummary(structured || {});
  renderQualityWarnings(structured?.data_quality_warnings || []);
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
  if (reasoning.images_present != null) reasoningBits.push(`images=${reasoning.images_sent ?? 0}/${reasoning.images_present}`);
  if (reasoning.reasoning_backend_skipped_reason)
    reasoningBits.push(`skipped=${String(reasoning.reasoning_backend_skipped_reason).slice(0, 80)}`);
  if (reasoning.reasoning_backend_error) reasoningBits.push(`error=${String(reasoning.reasoning_backend_error).slice(0, 80)}`);
  setText("reasoningInfo", reasoningBits.length ? reasoningBits.join(" • ") : "—");
  setText("rationale", reasoning.reasoning_rationale || "—");

  const evidence = traceOutput(result, "evidence_policy");
  renderCitations(evidence);

  $("handoff").textContent = result.clinician_handoff || "—";
  $("patientSummary").textContent = result.patient_summary || "—";

  const comm = traceOutput(result, "communication");
  const commBits = [];
  if (comm.communication_backend) commBits.push(`backend=${comm.communication_backend}`);
  if (comm.communication_backend_model) commBits.push(`model=${comm.communication_backend_model}`);
  if (comm.communication_prompt_version) commBits.push(`prompt=${comm.communication_prompt_version}`);
  if (comm.communication_backend_skipped_reason)
    commBits.push(`skipped=${String(comm.communication_backend_skipped_reason).slice(0, 80)}`);
  if (comm.communication_backend_error) commBits.push(`error=${String(comm.communication_backend_error).slice(0, 80)}`);
  setText("commInfo", commBits.length ? `Communication: ${commBits.join(" • ")}` : "Communication: —");

  renderSafetyTriggers(safety?.safety_triggers || []);
  renderTraceMini(result.trace || []);
  renderTrace(result.trace || []);

  $("rawResult").textContent = fmtJson(result);
  renderHome();
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
    state.doctor = d;
    const backend = (d.reasoning_backend || {}).backend || "deterministic";
    const model = (d.reasoning_backend || {}).model || "";
    const ok = (d.reasoning_backend || {}).connectivity_ok;
    const circuit = (d.reasoning_backend || {}).circuit_breaker || {};
    const status = ok === true ? "ok" : ok === false ? "unreachable" : "";
    const label = model ? `${backend} • ${model}` : backend;
    const circ =
      circuit && circuit.open
        ? `circuit-open${typeof circuit.remaining_s === "number" ? `(${Math.round(circuit.remaining_s)}s)` : ""}`
        : "";
    const fullBits = [label, status, circ].filter((x) => x);
    const fullLabel = fullBits.join(" • ");
    setText("backendBadge", `backend: ${fullLabel}`);

    const commBackend = (d.communication_backend || {}).backend || "deterministic";
    const commModel = (d.communication_backend || {}).model || "";
    const commOk = (d.communication_backend || {}).connectivity_ok;
    const commCircuit = (d.communication_backend || {}).circuit_breaker || {};
    const commStatus = commOk === true ? "ok" : commOk === false ? "unreachable" : "";
    const commLabel = commModel ? `${commBackend} • ${commModel}` : commBackend;
    const commCirc =
      commCircuit && commCircuit.open
        ? `circuit-open${typeof commCircuit.remaining_s === "number" ? `(${Math.round(commCircuit.remaining_s)}s)` : ""}`
        : "";
    const commFullLabel = [commLabel, commStatus, commCirc].filter((x) => x).join(" • ");
    setText("commBadge", `comm: ${commFullLabel}`);

    const policy = (d.policy_pack || {}).sha256 || "";
    setText("policyBadge", policy ? `policy: ${policy.slice(0, 10)}…` : "policy: (none)");
    const ver = String(d.version || "").trim();
    setText("versionBadge", ver ? `v${ver}` : "v—");
    updateAuthBadge();
    const authStatus = $("authStatus");
    const required = Boolean(d?.settings?.api_key_configured);
    if (authStatus) {
      if (!required) authStatus.textContent = "Server auth disabled (no CLINICAFLOW_API_KEY).";
      else authStatus.textContent = state.auth.apiKey ? "API key set for this tab." : "API key required for POST actions.";
    }
    renderImagePreview();
  } catch (e) {
    setText("backendBadge", "backend: unknown");
    setText("commBadge", "comm: unknown");
    setText("policyBadge", "policy: unknown");
    setText("versionBadge", "v—");
    setText("authBadge", "auth: unknown");
  }
}

// ---------------------------
// Ops dashboard (live metrics)
// ---------------------------

function formatUptime(uptimeSeconds) {
  const s = Number(uptimeSeconds);
  if (!Number.isFinite(s) || s < 0) return "—";
  const sec = Math.floor(s % 60);
  const m = Math.floor((s % 3600) / 60);
  const h = Math.floor(s / 3600);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function opsMetric(m, key, fallback) {
  const v = m ? m[key] : null;
  return v == null ? fallback : v;
}

function opsNum(v, { digits = 1 } = {}) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return digits == null ? String(n) : n.toFixed(digits);
}

function recordOpsHistory(metrics) {
  const m = metrics || null;
  if (!m) return;

  const avg = Number(m.triage_latency_ms_avg);
  const entry = {
    ts: Date.now(),
    avg_latency_ms: Number.isFinite(avg) ? avg : null,
    triage_requests_total: Number(m.triage_requests_total || 0) || 0,
    triage_errors_total: Number(m.triage_errors_total || 0) || 0,
    triage_success_total: Number(m.triage_success_total || 0) || 0,
  };

  const hist = Array.isArray(state.ops?.history) ? state.ops.history : [];
  hist.push(entry);
  state.ops.history = hist.slice(-60);
}

function renderOpsChart() {
  const canvas = $("opsChart");
  const legend = $("opsChartLegend");
  if (!canvas) return;

  const histAll = Array.isArray(state.ops?.history) ? state.ops.history : [];
  const hist = histAll.slice(-30);

  const cssWidth = Math.max(320, Math.floor(canvas.getBoundingClientRect().width || 0));
  const cssHeight = Math.max(120, Number(canvas.getAttribute("height") || 140));
  const dpr = Math.max(1, Math.floor(window.devicePixelRatio || 1));
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  canvas.style.height = `${cssHeight}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // background
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  if (!hist.length) {
    ctx.fillStyle = "rgba(17, 24, 39, 0.55)";
    ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial";
    ctx.fillText("No data yet. Click Refresh.", 12, 22);
    if (legend) legend.textContent = "—";
    return;
  }

  const pad = 12;
  const errBand = 28;
  const x0 = pad;
  const x1 = cssWidth - pad;
  const yTop = pad;
  const yLineBottom = cssHeight - pad - errBand;
  const yErrBottom = cssHeight - pad;

  // Collect latency values
  const vals = hist.map((r) => (typeof r.avg_latency_ms === "number" ? r.avg_latency_ms : null)).filter((v) => v != null);
  const minV = vals.length ? Math.min(...vals) : 0;
  const maxV0 = vals.length ? Math.max(...vals) : 1;
  const maxV = maxV0 === minV ? minV + 1 : maxV0;

  const n = hist.length;
  const xFor = (i) => (n <= 1 ? x0 : x0 + (i * (x1 - x0)) / (n - 1));
  const yFor = (v) => {
    const t = (v - minV) / (maxV - minV);
    return yLineBottom - t * (yLineBottom - yTop);
  };

  // grid
  ctx.strokeStyle = "rgba(17, 24, 39, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i += 1) {
    const y = yTop + (i * (yLineBottom - yTop)) / 3;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
  }

  // latency line
  ctx.strokeStyle = "#111827";
  ctx.lineWidth = 2;
  ctx.beginPath();
  hist.forEach((r, i) => {
    const v = typeof r.avg_latency_ms === "number" ? r.avg_latency_ms : null;
    if (v == null) return;
    const x = xFor(i);
    const y = yFor(v);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // points
  ctx.fillStyle = "#111827";
  hist.forEach((r, i) => {
    const v = typeof r.avg_latency_ms === "number" ? r.avg_latency_ms : null;
    if (v == null) return;
    const x = xFor(i);
    const y = yFor(v);
    ctx.beginPath();
    ctx.arc(x, y, 2.6, 0, Math.PI * 2);
    ctx.fill();
  });

  // error delta bars
  const deltas = hist.map((r, i) => {
    if (i === 0) return 0;
    const prev = Number(hist[i - 1].triage_errors_total || 0);
    const cur = Number(r.triage_errors_total || 0);
    const d = cur - prev;
    return Number.isFinite(d) ? d : 0;
  });
  const maxDelta = Math.max(1, ...deltas.map((d) => Math.abs(d)));
  const errH = yErrBottom - yLineBottom - 6;
  hist.forEach((r, i) => {
    if (i === 0) return;
    const d = deltas[i] || 0;
    if (!d) return;
    const x = xFor(i);
    const h = (Math.min(Math.abs(d), maxDelta) / maxDelta) * errH;
    ctx.fillStyle = d > 0 ? "rgba(153, 27, 27, 0.65)" : "rgba(17, 24, 39, 0.22)";
    ctx.fillRect(x - 2, yErrBottom - h, 4, h);
  });

  // labels
  ctx.fillStyle = "rgba(17, 24, 39, 0.55)";
  ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace";
  ctx.fillText(`${Math.round(maxV)} ms`, x0, yTop + 10);
  ctx.fillText(`${Math.round(minV)} ms`, x0, yLineBottom - 2);
  ctx.fillText("Δerrors", x0, yLineBottom + 16);

  const last = hist[hist.length - 1] || {};
  const lastDelta = deltas[deltas.length - 1] || 0;
  if (legend) {
    const bits = [
      `window=${hist.length}`,
      `avg_latency_ms=${typeof last.avg_latency_ms === "number" ? opsNum(last.avg_latency_ms, { digits: 0 }) : "—"}`,
      `range=${Math.round(minV)}–${Math.round(maxV)}ms`,
      `Δerrors(last)=${lastDelta}`,
    ];
    legend.textContent = bits.join(" • ");
  }
}

function renderOpsDashboard() {
  const summary = $("opsSummary");
  const alerts = $("opsAlerts");
  const agentBody = $("opsAgentBody");
  const dist = $("opsDistributions");
  if (!summary && !alerts && !agentBody && !dist) return;

  const m = state.metrics || null;
  const d = state.doctor || null;

  if (summary) summary.innerHTML = "";
  if (alerts) alerts.innerHTML = "";
  if (agentBody) agentBody.innerHTML = "";
  if (dist) dist.textContent = "—";

  if (!m) {
    if (alerts) {
      alerts.innerHTML = `<div class="k">Alerts</div><div class="small muted">No metrics loaded yet. Click Refresh.</div>`;
    }
    return;
  }

  function addCard(title, value, subtitle) {
    if (!summary) return;
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `<div class="k">${escapeHtml(title)}</div><div class="mono">${escapeHtml(
      String(value ?? "—"),
    )}</div>${subtitle ? `<div class="small muted">${escapeHtml(subtitle)}</div>` : ""}`;
    summary.appendChild(c);
  }

  const uptime = formatUptime(opsMetric(m, "uptime_s", null));
  const version = String(opsMetric(m, "version", "—") || "—");
  const triageReq = Number(opsMetric(m, "triage_requests_total", 0)) || 0;
  const triageOk = Number(opsMetric(m, "triage_success_total", 0)) || 0;
  const triageErr = Number(opsMetric(m, "triage_errors_total", 0)) || 0;
  const avgLatency = Number(opsMetric(m, "triage_latency_ms_avg", null));

  const rb = (d || {}).reasoning_backend || {};
  const backend = String(rb.backend || "deterministic");
  const model = String(rb.model || "");
  const ok = rb.connectivity_ok;
  const backendLine = model ? `${backend} • ${model}` : backend;
  const backendHealth = ok === true ? "ok" : ok === false ? "unreachable" : "unknown";
  const circuit = rb.circuit_breaker || {};
  const circOpen = Boolean(circuit?.open);
  const circRemain = typeof circuit?.remaining_s === "number" ? circuit.remaining_s : null;
  const circFails = typeof circuit?.failures === "number" ? circuit.failures : null;

  const cb = (d || {}).communication_backend || {};
  const commCircuit = cb.circuit_breaker || {};
  const commCircOpen = Boolean(commCircuit?.open);
  const commCircRemain = typeof commCircuit?.remaining_s === "number" ? commCircuit.remaining_s : null;
  const commCircFails = typeof commCircuit?.failures === "number" ? commCircuit.failures : null;
  const authRequired = Boolean(d?.settings?.api_key_configured);
  const authHasKey = Boolean(state.auth?.apiKey);

  addCard("Uptime", uptime, `version=${version}`);
  addCard("Triage requests", `${triageReq}`, `success=${triageOk} • errors=${triageErr}`);
  addCard("Avg triage latency", Number.isFinite(avgLatency) ? `${opsNum(avgLatency, { digits: 2 })} ms` : "—", "from pipeline total_latency_ms");
  addCard("Reasoning backend", backendLine, `connectivity=${backendHealth}`);
  if (circOpen || commCircOpen || (circFails != null && circFails > 0) || (commCircFails != null && commCircFails > 0)) {
    const bits = [];
    const fmt = (open, remain, fails) => {
      const left = open ? "open" : "closed";
      const r = remain != null && open ? ` (${Math.round(remain)}s)` : "";
      const f = fails != null && fails > 0 ? ` fails=${fails}` : "";
      return `${left}${r}${f}`;
    };
    bits.push(`reasoning: ${fmt(circOpen, circRemain, circFails)}`);
    bits.push(`comm: ${fmt(commCircOpen, commCircRemain, commCircFails)}`);
    addCard("Circuit breaker", bits.join(" • "), "Prevents cascading timeouts when endpoint is down.");
  }
  addCard(
    "API auth",
    authRequired ? (authHasKey ? "enabled (key set)" : "enabled (key missing)") : "disabled",
    "POST: /triage • /audit_bundle • /fhir_bundle",
  );

  const riskTotals = m.triage_risk_tier_total || {};
  const riskLine = Object.keys(riskTotals)
    .sort()
    .map((k) => `${k}=${riskTotals[k]}`)
    .join(" • ");
  addCard("Risk tier distribution", riskLine || "—", "since server start");

  const backendTotals = m.triage_reasoning_backend_total || {};
  const backendDist = Object.keys(backendTotals)
    .sort()
    .map((k) => `${k}=${backendTotals[k]}`)
    .join(" • ");
  addCard("Backend distribution", backendDist || "—", "deterministic vs external");

  // Alerts
  const issues = [];
  if (ok === false) issues.push({ level: "bad", text: "Reasoning backend unreachable (demo will fall back to deterministic)." });
  if (circOpen)
    issues.push({
      level: "warn",
      text: `Reasoning circuit breaker OPEN${circRemain != null ? ` (${Math.round(circRemain)}s)` : ""} — skipping external calls.`,
    });
  if (commCircOpen)
    issues.push({
      level: "warn",
      text: `Comm circuit breaker OPEN${commCircRemain != null ? ` (${Math.round(commCircRemain)}s)` : ""} — skipping external calls.`,
    });
  if (authRequired && !authHasKey) issues.push({ level: "warn", text: "Server requires API key but none is set (POST actions will 401)." });
  if (triageErr > 0) issues.push({ level: "bad", text: `Triage errors observed: ${triageErr}` });
  if (Number.isFinite(avgLatency) && avgLatency > 1800) issues.push({ level: "warn", text: `High average latency: ${opsNum(avgLatency, { digits: 0 })} ms` });

  const agentErrs = m.triage_agent_errors_total || {};
  Object.keys(agentErrs || {}).forEach((a) => {
    const n = Number(agentErrs[a]) || 0;
    if (n > 0) issues.push({ level: "warn", text: `Agent errors: ${a}=${n}` });
  });

  if (alerts) {
    const title = document.createElement("div");
    title.className = "k";
    title.textContent = "Alerts";
    alerts.appendChild(title);

    const ul = document.createElement("ul");
    ul.className = "list";
    if (!issues.length) {
      const li = document.createElement("li");
      li.textContent = "(none)";
      ul.appendChild(li);
    } else {
      issues.forEach((it) => {
        const li = document.createElement("li");
        const chip = document.createElement("span");
        chip.className = `chip ${it.level === "bad" ? "bad" : it.level === "warn" ? "warn" : "ok"}`;
        chip.textContent = it.level.toUpperCase();
        li.appendChild(chip);
        const text = document.createElement("span");
        text.textContent = ` ${it.text}`;
        li.appendChild(text);
        ul.appendChild(li);
      });
    }
    alerts.appendChild(ul);
  }

  // Per-agent table
  if (agentBody) {
    const sums = m.triage_agent_latency_ms_sum || {};
    const counts = m.triage_agent_latency_ms_count || {};
    const errs = m.triage_agent_errors_total || {};
    const allAgents = new Set([...Object.keys(sums), ...Object.keys(counts), ...Object.keys(errs)]);
    const order = [
      "intake_structuring",
      "multimodal_reasoning",
      "evidence_policy",
      "safety_escalation",
      "communication",
    ];
    function idx(a) {
      const i = order.indexOf(a);
      return i === -1 ? 999 : i;
    }
    const agents = [...allAgents].sort((a, b) => idx(a) - idx(b) || String(a).localeCompare(String(b)));

    agents.forEach((a) => {
      const sum = Number(sums[a]);
      const cnt = Number(counts[a]) || 0;
      const err = Number(errs[a]) || 0;
      const avg = cnt > 0 && Number.isFinite(sum) ? sum / cnt : null;

      const tr = document.createElement("tr");
      if (err > 0) tr.className = "row-bad";
      else if (avg != null && avg > 900) tr.className = "row-warn";

      tr.innerHTML = `
        <td class="mono">${escapeHtml(a)}</td>
        <td class="mono">${avg == null ? "—" : escapeHtml(opsNum(avg, { digits: 2 }))}</td>
        <td class="mono">${escapeHtml(String(cnt))}</td>
        <td class="mono">${escapeHtml(String(err))}</td>
      `;
      agentBody.appendChild(tr);
    });
  }

  if (dist) {
    const bits = [];
    if (riskLine) bits.push(`risk_tier_total: ${riskLine}`);
    if (backendDist) bits.push(`reasoning_backend_total: ${backendDist}`);
    dist.textContent = bits.length ? bits.join(" • ") : "—";
  }

  renderOpsChart();
}

async function loadMetrics() {
  try {
    const payload = await fetchJson("/metrics");
    state.metrics = payload;
    return payload;
  } catch (e) {
    state.metrics = null;
    throw e;
  }
}

async function refreshOps() {
  const status = $("opsStatus");
  if (status) status.textContent = "Refreshing…";
  try {
    await Promise.all([loadDoctor(), loadMetrics()]);
    recordOpsHistory(state.metrics);
    state.ops.lastRefreshedAt = new Date().toISOString();
    renderOpsDashboard();
    renderHome();
    if (status) status.textContent = `Last updated: ${state.ops.lastRefreshedAt.replace("T", " ").replace("Z", "")}`;
  } catch (e) {
    renderOpsDashboard();
    renderHome();
    if (status) status.textContent = `Error: ${e}`;
  }
}

function renderOpsSmokePlaceholder(text) {
  const out = $("opsSmokeOut");
  if (!out) return;
  out.innerHTML = `<div class="k">Smoke check</div><div class="small muted">${escapeHtml(text || "Not run.")}</div>`;
}

async function runOpsSmokeCheck() {
  const out = $("opsSmokeOut");
  if (!out) return;
  out.innerHTML = `<div class="k">Smoke check</div><div class="small muted">Running…</div>`;

  const checks = [
    { name: "/health", fn: () => fetchJson("/health") },
    { name: "/ready", fn: () => fetchJson("/ready") },
    { name: "/live", fn: () => fetchJson("/live") },
    { name: "/openapi.json", fn: () => fetchJson("/openapi.json") },
    { name: "/doctor", fn: () => fetchJson("/doctor") },
    { name: "/policy_pack", fn: () => fetchJson("/policy_pack?limit=1") },
    { name: "/safety_rules", fn: () => fetchJson("/safety_rules") },
    { name: "/metrics", fn: () => fetchJson("/metrics") },
  ];

  const results = [];
  for (const c of checks) {
    try {
      await c.fn();
      results.push({ name: c.name, ok: true });
    } catch (e) {
      results.push({ name: c.name, ok: false, err: String(e) });
    }
  }

  const ok = results.every((r) => r.ok);
  out.innerHTML = "";
  const k = document.createElement("div");
  k.className = "k";
  k.textContent = `Smoke check: ${ok ? "PASS" : "FAIL"}`;
  out.appendChild(k);

  const ul = document.createElement("ul");
  ul.className = "list";
  results.forEach((r) => {
    const li = document.createElement("li");
    const chip = document.createElement("span");
    chip.className = `chip ${r.ok ? "ok" : "bad"}`;
    chip.textContent = r.ok ? "OK" : "FAIL";
    li.appendChild(chip);
    const text = document.createElement("span");
    text.textContent = ` ${r.name}${r.ok ? "" : ` (${r.err})`}`;
    li.appendChild(text);
    ul.appendChild(li);
  });
  out.appendChild(ul);
  setText("statusLine", ok ? "Ops smoke check: PASS" : "Ops smoke check: FAIL");
}

function buildOpsReportMarkdown() {
  const m = state.metrics || {};
  const d = state.doctor || {};
  const rb = d.reasoning_backend || {};
  const cb = d.communication_backend || {};
  const pp = d.policy_pack || {};

  const lines = [];
  lines.push("# ClinicaFlow — Ops report (demo)");
  lines.push("");
  lines.push("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.");
  lines.push(`- generated_at: \`${new Date().toISOString()}\``);
  lines.push("");

  lines.push("## Runtime");
  lines.push("");
  lines.push(`- uptime: \`${formatUptime(m.uptime_s)}\``);
  lines.push(`- version: \`${String(m.version || "")}\``);
  lines.push("");

  lines.push("## Backends");
  lines.push("");
  lines.push(`- reasoning_backend: \`${String(rb.backend || "deterministic")}\``);
  lines.push(`- reasoning_model: \`${String(rb.model || "")}\``);
  lines.push(`- reasoning_connectivity_ok: \`${String(rb.connectivity_ok)}\``);
  lines.push(`- communication_backend: \`${String(cb.backend || "deterministic")}\``);
  lines.push(`- communication_model: \`${String(cb.model || "")}\``);
  lines.push(`- communication_connectivity_ok: \`${String(cb.connectivity_ok)}\``);
  lines.push(`- policy_pack_sha256: \`${String(pp.sha256 || "")}\``);
  lines.push("");

  lines.push("## Requests");
  lines.push("");
  lines.push(`- triage_requests_total: \`${String(m.triage_requests_total ?? "")}\``);
  lines.push(`- triage_success_total: \`${String(m.triage_success_total ?? "")}\``);
  lines.push(`- triage_errors_total: \`${String(m.triage_errors_total ?? "")}\``);
  lines.push(`- audit_bundle_errors_total: \`${String(m.audit_bundle_errors_total ?? "")}\``);
  lines.push(`- fhir_bundle_errors_total: \`${String(m.fhir_bundle_errors_total ?? "")}\``);
  lines.push("");

  lines.push("## Latency");
  lines.push("");
  lines.push(`- triage_latency_ms_avg: \`${opsNum(m.triage_latency_ms_avg, { digits: 2 })}\``);
  lines.push("");

  lines.push("## Per-agent averages");
  lines.push("");
  lines.push("| Agent | Avg latency (ms) | Calls | Errors |");
  lines.push("|---|---:|---:|---:|");

  const sums = m.triage_agent_latency_ms_sum || {};
  const counts = m.triage_agent_latency_ms_count || {};
  const errs = m.triage_agent_errors_total || {};
  const allAgents = new Set([...Object.keys(sums), ...Object.keys(counts), ...Object.keys(errs)]);
  const agents = [...allAgents].sort();
  agents.forEach((a) => {
    const cnt = Number(counts[a]) || 0;
    const sum = Number(sums[a]);
    const err = Number(errs[a]) || 0;
    const avg = cnt > 0 && Number.isFinite(sum) ? sum / cnt : null;
    lines.push(`| \`${a}\` | \`${avg == null ? "—" : opsNum(avg, { digits: 2 })}\` | \`${cnt}\` | \`${err}\` |`);
  });
  lines.push("");

  lines.push("## Distributions");
  lines.push("");
  lines.push(`- triage_risk_tier_total: \`${fmtJson(m.triage_risk_tier_total || {})}\``);
  lines.push(`- triage_reasoning_backend_total: \`${fmtJson(m.triage_reasoning_backend_total || {})}\``);
  lines.push("");

  return lines.join("\n").trim() + "\n";
}

async function downloadOpsReportMd() {
  const md = buildOpsReportMarkdown();
  downloadText("ops_report.md", md, "text/markdown; charset=utf-8");
  setText("statusLine", "Downloaded ops_report.md");
}

function startOpsAutoRefresh() {
  stopOpsAutoRefresh();
  const seconds = Number(state.ops.autoSeconds) || 5;
  state.ops.intervalId = setInterval(() => {
    refreshOps();
  }, Math.max(2, seconds) * 1000);
}

function stopOpsAutoRefresh() {
  const id = state.ops.intervalId;
  if (id) clearInterval(id);
  state.ops.intervalId = null;
}

async function loadPolicyPack() {
  const out = $("policyPackJson");
  if (out) out.textContent = "Loading…";
  try {
    const payload = await fetchJson("/policy_pack");
    state.policyPack = payload;
    if (out) out.textContent = fmtJson(payload);
    setText("statusLine", "Loaded policy pack.");
  } catch (e) {
    state.policyPack = null;
    if (out) out.textContent = "{}";
    setText("statusLine", "Failed to load policy pack.");
  }
}

async function loadSafetyRules() {
  const status = $("rulesStatus");
  if (status) status.textContent = "Loading…";
  try {
    const payload = await fetchJson("/safety_rules");
    state.safetyRules = payload;
    renderRulesTab();
    if (status) status.textContent = "Loaded.";
    setText("statusLine", "Loaded safety rules.");
  } catch (e) {
    state.safetyRules = null;
    renderRulesTab();
    if (status) status.textContent = `Error: ${e}`;
    setText("statusLine", "Failed to load safety rules.");
  }
}

function renderRulesTab() {
  const meta = $("rulesMeta");
  const triggerBody = $("rulesTriggerBody");
  const keywordBody = $("rulesKeywordBody");
  const pre = $("rulesJson");
  if (!meta && !triggerBody && !keywordBody && !pre) return;

  const payload = state.safetyRules;
  const filter = String($("rulesFilter")?.value || "")
    .trim()
    .toLowerCase();

  if (pre) pre.textContent = fmtJson(payload || {});

  if (meta) {
    meta.innerHTML = "";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = "Metadata";
    meta.appendChild(k);

    const lines = [];
    if (payload?.safety_rules_version) lines.push(`safety_rules_version=${payload.safety_rules_version}`);
    const nKeys = payload?.red_flag_keywords ? Object.keys(payload.red_flag_keywords).length : 0;
    const nTriggers = Array.isArray(payload?.safety_trigger_catalog) ? payload.safety_trigger_catalog.length : 0;
    lines.push(`keywords=${nKeys}`);
    lines.push(`triggers=${nTriggers}`);
    const small = document.createElement("div");
    small.className = "small muted";
    small.textContent = payload ? lines.join(" • ") : "Click Load to fetch /safety_rules.";
    meta.appendChild(small);
  }

  if (triggerBody) {
    triggerBody.innerHTML = "";
    const triggers = Array.isArray(payload?.safety_trigger_catalog) ? payload.safety_trigger_catalog : [];
    const rows = triggers.filter((t) => {
      if (!filter) return true;
      const s = `${t?.id || ""} ${t?.label || ""} ${t?.severity || ""} ${t?.detail || ""}`.toLowerCase();
      return s.includes(filter);
    });
    if (!rows.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="muted" colspan="3">${payload ? "(no matching rules)" : "Click Load to fetch rules."}</td>`;
      triggerBody.appendChild(tr);
    } else {
      rows.forEach((t) => {
        const id = String(t?.id || "").trim();
        const label = String(t?.label || "").trim();
        const sev = String(t?.severity || "").trim().toLowerCase();
        const detail = String(t?.detail || "").trim();

        const tr = document.createElement("tr");
        const sevPill = document.createElement("span");
        const riskClass = sev === "critical" ? "critical" : sev === "urgent" ? "urgent" : "routine";
        sevPill.className = `risk ${riskClass}`;
        sevPill.textContent = sev || "info";

        tr.innerHTML = `
          <td class="mono">${escapeHtml(label || id || "(rule)")}${id && label && id !== label ? ` <span class="muted">(${escapeHtml(id)})</span>` : ""}</td>
          <td class="sev"></td>
          <td class="small">${escapeHtml(detail || "—")}</td>
        `;
        tr.querySelector(".sev")?.appendChild(sevPill);
        triggerBody.appendChild(tr);
      });
    }
  }

  if (keywordBody) {
    keywordBody.innerHTML = "";
    const keywords = payload?.red_flag_keywords || {};
    const entries = Object.entries(keywords || {})
      .map(([k, v]) => [String(k), String(v)])
      .filter(([k, v]) => k.trim() && v.trim())
      .filter(([k, v]) => {
        if (!filter) return true;
        return `${k} ${v}`.toLowerCase().includes(filter);
      })
      .sort((a, b) => a[0].localeCompare(b[0]));

    if (!entries.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="muted" colspan="2">${payload ? "(no matching keywords)" : "Click Load to fetch rules."}</td>`;
      keywordBody.appendChild(tr);
    } else {
      entries.forEach(([pattern, redFlag]) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td class="mono">${escapeHtml(pattern)}</td><td>${escapeHtml(redFlag)}</td>`;
        keywordBody.appendChild(tr);
      });
    }
  }
}

function downloadSafetyRulesJson() {
  if (!state.safetyRules) return;
  const version = String(state.safetyRules.safety_rules_version || "demo").trim() || "demo";
  downloadText(`safety_rules_${version}.json`, fmtJson(state.safetyRules), "application/json; charset=utf-8");
  setText("statusLine", "Downloaded safety_rules.json");
}

async function loadPresets() {
  const select = $("presetSelect");
  select.innerHTML = "";

  const optSample = document.createElement("option");
  optSample.value = "sample";
  optSample.textContent = "Sample case (chest pain)";
  select.appendChild(optSample);

  async function addGroup(setName, label) {
    try {
      const payload = await fetchJson(`/vignettes?set=${encodeURIComponent(setName)}`);
      const vignettes = payload.vignettes || [];
      if (!vignettes.length) return;
      const group = document.createElement("optgroup");
      group.label = `${label} (n=${vignettes.length})`;
      vignettes.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = `vignette:${setName}:${v.id}`;
        const cc = String(v.chief_complaint || "").slice(0, 60);
        opt.textContent = `${v.id} — ${cc}`;
        group.appendChild(opt);
      });
      select.appendChild(group);
    } catch (e) {
      // ignore
    }
  }

  await addGroup("standard", "Vignettes (standard)");
  await addGroup("adversarial", "Vignettes (adversarial)");
  await addGroup("extended", "Vignettes (extended)");
}

async function loadPreset() {
  setError("intakeError", "");
  const id = $("presetSelect").value;
  let intake = null;
  if (id === "sample") {
    intake = await fetchJson("/example");
  } else if (id.startsWith("vignette:")) {
    const parts = id.split(":");
    const setName = parts[1] || "standard";
    const vid = parts.slice(2).join(":");
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(vid)}?set=${encodeURIComponent(setName)}`);
    intake = resp.input || resp;
  } else {
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(id)}`);
    intake = resp.input || resp;
  }

  state.lastIntake = intake;
  fillFormFromIntake(intake);
  $("intakeJson").value = fmtJson(intakeForJsonView(intake));
  updatePhiWarning(intake);
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

  updatePhiWarning(intake);
  intake = attachImagesToIntake(intake);
  state.lastIntake = intake;
  $("intakeJson").value = fmtJson(intakeForJsonView(intake));

  const runBtn = $("runTriage");
  const runBtnLabel = runBtn ? runBtn.textContent : "";
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.classList.add("loading");
    runBtn.textContent = "Running…";
  }
  startRunStepper();

  try {
    const { data, headers } = await postJson("/triage", intake, {});
    stopRunStepper();
    const reqId = headers.get("X-Request-ID") || null;
    renderResult(data, reqId);
    setText("statusLine", `Done. risk=${data.risk_tier} • backend=${extractBackend(data)}`);
  } catch (e) {
    stopRunStepper();
    renderTraceMini([]);
    setError("runError", e);
    setText("statusLine", "Error.");
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.classList.remove("loading");
      runBtn.textContent = runBtnLabel || "Run triage";
    }
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

function extractCommBackend(result) {
  try {
    const steps = result.trace || [];
    for (const s of steps) {
      if (s.agent === "communication") {
        return (s.output || {}).communication_backend || "deterministic";
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

function buildNoteMarkdown(intake, result, checklist) {
  const reasoning = traceOutput(result, "multimodal_reasoning");
  const evidence = traceOutput(result, "evidence_policy");
  const safety = traceOutput(result, "safety_escalation");
  const structured = traceOutput(result, "intake_structuring");
  const comm = traceOutput(result, "communication");

  const safetyActionsRaw = Array.isArray(safety?.actions_added_by_safety) ? safety.actions_added_by_safety : [];
  const safetyActions = safetyActionsRaw.map((x) => String(x || "").trim()).filter((x) => x);
  const safetySet = new Set(safetyActions);

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
  if (reasoning.reasoning_backend_skipped_reason)
    lines.push(`- reasoning_backend_skipped_reason: ${String(reasoning.reasoning_backend_skipped_reason).trim()}`);
  if (evidence.policy_pack_sha256) lines.push(`- policy_pack_sha256: ${evidence.policy_pack_sha256}`);
  if (safety.safety_rules_version) lines.push(`- safety_rules_version: ${safety.safety_rules_version}`);
  if (comm.communication_backend) lines.push(`- communication_backend: ${comm.communication_backend}`);
  if (comm.communication_backend_model) lines.push(`- communication_model: ${comm.communication_backend_model}`);
  if (comm.communication_prompt_version) lines.push(`- communication_prompt_version: ${comm.communication_prompt_version}`);
  if (comm.communication_backend_skipped_reason)
    lines.push(`- communication_backend_skipped_reason: ${String(comm.communication_backend_skipped_reason).trim()}`);
  lines.push("");
  lines.push("## Intake (synthetic/demo)");
  lines.push(`- chief_complaint: ${(intake.chief_complaint || "").trim()}`);
  if ((intake.history || "").trim()) lines.push(`- history: ${(intake.history || "").trim()}`);
  if (vitalsParts.length) lines.push(`- vitals: ${vitalsParts.join(", ")}`);
  const phi = Array.isArray(structured?.phi_hits) ? structured.phi_hits.map((x) => String(x)).filter((x) => x.trim()) : [];
  if (phi.length) lines.push(`- phi_hits (heuristic): ${phi.join(", ")}`);
  const qw = Array.isArray(structured?.data_quality_warnings)
    ? structured.data_quality_warnings.map((x) => String(x)).filter((x) => x.trim())
    : [];
  if (qw.length) lines.push(`- data_quality_warnings: ${qw.join(" • ")}`);
  lines.push("");
  lines.push("## Triage");
  lines.push(`- risk_tier: ${result.risk_tier}`);
  lines.push(`- escalation_required: ${result.escalation_required}`);
  if (safety.risk_tier_rationale) lines.push(`- rationale: ${safety.risk_tier_rationale}`);
  const rs = formatRiskScores(safety.risk_scores || {});
  if (rs !== "—") lines.push(`- risk_scores: ${rs}`);
  lines.push("");
  lines.push("## Safety triggers (deterministic)");
  const triggers = Array.isArray(safety?.safety_triggers) ? safety.safety_triggers : [];
  if (triggers.length) {
    triggers.forEach((t) => {
      const label = String(t?.label || t?.id || "").trim();
      const detail = String(t?.detail || "").trim();
      if (!label) return;
      lines.push(`- ${label}${detail ? ` — ${detail}` : ""}`);
    });
  } else {
    lines.push("- (none)");
  }
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
  lines.push("## Recommended next actions (checklist)");
  const merged =
    Array.isArray(checklist) && checklist.length
      ? checklist
      : (result.recommended_next_actions || []).map((x) => ({ text: String(x || ""), checked: false }));
  const total = merged.length;
  const done = merged.filter((x) => x && x.checked).length;
  lines.push(`- progress: ${done}/${total}`);
  if (safetySet.size) lines.push("- tags: SAFETY=rules, POLICY=policy pack");
  merged.forEach((x) => {
    const text = String(x?.text || "").trim();
    if (!text) return;
    const tag = safetySet.size ? (safetySet.has(text) ? "[SAFETY] " : "[POLICY] ") : "";
    lines.push(`- [${x.checked ? "x" : " "}] ${tag}${text}`);
  });
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

function buildReportHtml(intake, result, checklist) {
  const reasoning = traceOutput(result, "multimodal_reasoning");
  const evidence = traceOutput(result, "evidence_policy");
  const safety = traceOutput(result, "safety_escalation");
  const structured = traceOutput(result, "intake_structuring");

  const safetyActionsRaw = Array.isArray(safety?.actions_added_by_safety) ? safety.actions_added_by_safety : [];
  const safetyActions = safetyActionsRaw.map((x) => String(x || "").trim()).filter((x) => x);
  const safetySet = new Set(safetyActions);

  const safetyTriggers = Array.isArray(safety?.safety_triggers) ? safety.safety_triggers : [];
  const triggerLis =
    safetyTriggers
      .map((t) => {
        const label = String(t?.label || t?.id || "").trim();
        const detail = String(t?.detail || "").trim();
        const sev = String(t?.severity || "").trim().toLowerCase();
        if (!label) return "";
        const klass = sev === "critical" ? "risk-critical" : sev === "urgent" ? "risk-urgent" : "risk-routine";
        return `<li><span class="pill ${klass}">${escapeHtml(label)}</span> ${detail ? escapeHtml(detail) : ""}</li>`;
      })
      .filter((x) => x)
      .join("") || "<li>(none)</li>";

  const symptoms = Array.isArray(structured?.symptoms) ? structured.symptoms.map((x) => String(x)) : [];
  const riskFactors = Array.isArray(structured?.risk_factors) ? structured.risk_factors.map((x) => String(x)) : [];

  const requestId = result.request_id || state.lastRequestId || "run";
  const createdAt = result.created_at || new Date().toISOString();
  const title = `ClinicaFlow — Triage Report (${requestId})`;

  const tier = String(result.risk_tier || "").trim().toLowerCase();
  let bannerTitle = `Triage: ${tier.toUpperCase()}`;
  let bannerSubtitle = "Decision support only — clinician confirmation required.";
  if (tier === "critical") {
    bannerTitle = "CRITICAL — emergency evaluation now";
    bannerSubtitle = "Escalation required. Do not delay clinician review.";
  } else if (tier === "urgent") {
    bannerTitle = "URGENT — same-day evaluation";
    bannerSubtitle = "Escalation required. Ensure clinician review today.";
  } else if (tier === "routine") {
    bannerTitle = "ROUTINE — stable (with return precautions)";
    bannerSubtitle = "No explicit red flags detected in provided intake.";
  }

  const topAction = Array.isArray(result.recommended_next_actions) ? String(result.recommended_next_actions[0] || "").trim() : "";
  const bannerBits = [];
  if (String(safety.risk_tier_rationale || "").trim()) bannerBits.push(`Why: ${String(safety.risk_tier_rationale || "").trim()}`);
  if (Array.isArray(result.red_flags) && result.red_flags.length) {
    const rf = result.red_flags.map((x) => String(x)).filter((x) => x.trim());
    if (rf.length) bannerBits.push(`Red flags: ${rf.slice(0, 2).join(" • ")}${rf.length > 2 ? " • …" : ""}`);
  }
  if (topAction) bannerBits.push(`Top action: ${topAction}`);
  const bannerMeta = bannerBits.length ? bannerBits.join("  |  ") : "—";

  const vitals = (intake || {}).vitals || {};
  const vitalsParts = [];
  if (vitals.heart_rate != null) vitalsParts.push(`HR ${vitals.heart_rate}`);
  if (vitals.systolic_bp != null) vitalsParts.push(`BP ${vitals.systolic_bp}/${vitals.diastolic_bp ?? "?"}`);
  if (vitals.temperature_c != null) vitalsParts.push(`Temp ${vitals.temperature_c}°C`);
  if (vitals.spo2 != null) vitalsParts.push(`SpO₂ ${vitals.spo2}%`);
  if (vitals.respiratory_rate != null) vitalsParts.push(`RR ${vitals.respiratory_rate}`);

  const actions =
    Array.isArray(checklist) && checklist.length
      ? checklist
      : (result.recommended_next_actions || []).map((x) => ({ text: String(x || ""), checked: false }));
  const actionLis = actions
    .map((a) => {
      const text = String(a?.text || "").trim();
      if (!text) return "";
      const done = Boolean(a.checked);
      const mark = done ? "☑" : "☐";
      const isSafety = safetySet.has(text);
      const tag = safetySet.size ? `<span class="tag ${isSafety ? "safety" : "policy"}">${isSafety ? "SAFETY" : "POLICY"}</span> ` : "";
      return `<li class="${done ? "done" : ""}">${mark} ${tag}${escapeHtml(text)}</li>`;
    })
    .filter((x) => x)
    .join("");

  const redFlagLis = (result.red_flags || []).map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") || "<li>(none)</li>";
  const diffLis =
    (result.differential_considerations || []).map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") || "<li>(none)</li>";
  const uncLis =
    (result.uncertainty_reasons || []).map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") || "<li>(none)</li>";

  const citations = Array.isArray(evidence.protocol_citations) ? evidence.protocol_citations : [];
  const citationRows = citations
    .map((c) => {
      const actions = Array.isArray(c.recommended_actions) ? c.recommended_actions.join("; ") : "";
      return `<tr>
        <td class="mono">${escapeHtml(String(c.policy_id || ""))}</td>
        <td>${escapeHtml(String(c.title || ""))}</td>
        <td class="mono">${escapeHtml(String(c.citation || ""))}</td>
        <td>${escapeHtml(actions)}</td>
      </tr>`;
    })
    .join("");

  const missing = Array.isArray(structured?.missing_fields) ? structured.missing_fields : [];
  const missingLis = missing.map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") || "<li>(none)</li>";

  const trace = Array.isArray(result.trace) ? result.trace : [];
  const workflowRows =
    trace
      .map((s) => {
        const agent = String(s.agent || "agent");
        const latency = s.latency_ms != null ? `${Number(s.latency_ms).toFixed(2)} ms` : "";
        const err = String(s.error || "").trim();
        return `<tr>
          <td class="mono">${escapeHtml(agent)}</td>
          <td class="mono">${escapeHtml(latency)}</td>
          <td>${escapeHtml(err)}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="3">(none)</td></tr>`;

  const css = `
    :root { color-scheme: light; }
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Inter, Arial, sans-serif; margin: 24px; color: #111827; }
    h1 { margin: 0 0 6px; font-size: 22px; }
    .sub { color: #6b7280; margin: 0 0 18px; font-size: 13px; }
    .banner { border: 1px solid #e5e7eb; border-radius: 14px; padding: 12px; background: #fff; margin: 10px 0 14px; }
    .banner-title { font-weight: 950; letter-spacing: 0.2px; }
    .banner-subtitle { margin-top: 4px; font-size: 12px; opacity: 0.92; }
    .banner-meta { margin-top: 8px; font-size: 12px; color: rgba(17, 24, 39, 0.72); }
    .banner.routine { background: #ecfdf5; color: #065f46; border-color: rgba(6, 95, 70, 0.25); }
    .banner.urgent { background: #fffbeb; color: #92400e; border-color: rgba(146, 64, 14, 0.25); }
    .banner.critical { background: #fef2f2; color: #991b1b; border-color: rgba(153, 27, 27, 0.25); }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
    .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; background: #fff; }
    .k { font-weight: 900; font-size: 12px; color: #374151; margin-bottom: 6px; }
    ul, ol { margin: 0; padding-left: 18px; }
    li { margin: 6px 0; }
    .done { opacity: 0.75; text-decoration: line-through; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; border: 1px solid #e5e7eb; font-weight: 900; font-size: 12px; }
    .risk-critical { background: #fef2f2; border-color: #ef444433; color: #991b1b; }
    .risk-urgent { background: #fffbeb; border-color: #f59e0b44; color: #92400e; }
    .risk-routine { background: #ecfdf5; border-color: #10b98133; color: #065f46; }
    .tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; border: 1px solid #e5e7eb; background: #f3f4f6; color: #374151; font-size: 11px; font-weight: 950; letter-spacing: 0.2px; }
    .tag.safety { background: #fef2f2; color: #991b1b; border-color: #ef444433; }
    .tag.policy { background: #eef2ff; color: #3730a3; border-color: rgba(55, 48, 163, 0.2); }
    .tablewrap { overflow: auto; border: 1px solid #e5e7eb; border-radius: 12px; margin-top: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f9fafb; font-weight: 900; }
    pre { white-space: pre-wrap; background: #0b1020; color: #e5e7eb; padding: 10px; border-radius: 12px; overflow: auto; }
    @media print {
      body { margin: 12mm; }
      .no-print { display: none; }
    }
  `;

  const riskClass =
    result.risk_tier === "critical" ? "risk-critical" : result.risk_tier === "urgent" ? "risk-urgent" : "risk-routine";
  const riskScoreText = formatRiskScores((safety || {}).risk_scores || {});
  const riskScoreLi = riskScoreText !== "—" ? `<li>risk_scores: <span class="mono">${escapeHtml(String(riskScoreText))}</span></li>` : "";

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>${escapeHtml(title)}</title>
    <style>${css}</style>
  </head>
  <body>
    <h1>${escapeHtml(title)}</h1>
    <p class="sub"><b>DISCLAIMER:</b> Decision support only. Not a diagnosis. Clinician confirmation required.</p>

    <div class="banner ${escapeHtml(tier)}">
      <div class="banner-title">${escapeHtml(bannerTitle)}</div>
      <div class="banner-subtitle">${escapeHtml(bannerSubtitle)}</div>
      <div class="banner-meta">${escapeHtml(bannerMeta)}</div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="k">Metadata</div>
        <ul>
          <li><span class="mono">request_id</span>: <span class="mono">${escapeHtml(String(requestId))}</span></li>
          <li>created_at: <span class="mono">${escapeHtml(String(createdAt))}</span></li>
          <li>pipeline_version: <span class="mono">${escapeHtml(String(result.pipeline_version || ""))}</span></li>
          <li>backend: <span class="mono">${escapeHtml(String(reasoning.reasoning_backend || ""))}</span></li>
          <li>model: <span class="mono">${escapeHtml(String(reasoning.reasoning_backend_model || ""))}</span></li>
          <li>prompt_version: <span class="mono">${escapeHtml(String(reasoning.reasoning_prompt_version || ""))}</span></li>
        </ul>
      </div>

      <div class="card">
        <div class="k">Triage</div>
        <div class="pill ${riskClass}">risk_tier: ${escapeHtml(String(result.risk_tier || ""))}</div>
        <div style="height:10px"></div>
        <ul>
          <li>escalation_required: <b>${escapeHtml(String(result.escalation_required))}</b></li>
          <li>rationale: ${escapeHtml(String(safety.risk_tier_rationale || ""))}</li>
          ${riskScoreLi}
          <li>confidence (proxy): <span class="mono">${escapeHtml(String(result.confidence))}</span></li>
        </ul>
      </div>

      <div class="card">
        <div class="k">Intake (synthetic/demo)</div>
        <ul>
          <li>chief_complaint: ${escapeHtml(String(intake?.chief_complaint || ""))}</li>
          ${
            String(intake?.history || "").trim()
              ? `<li>history: ${escapeHtml(String(intake.history || ""))}</li>`
              : ""
          }
          ${vitalsParts.length ? `<li>vitals: <span class="mono">${escapeHtml(vitalsParts.join(", "))}</span></li>` : ""}
        </ul>
      </div>

      <div class="card">
        <div class="k">Missing critical fields</div>
        <ul>${missingLis}</ul>
      </div>

      <div class="card">
        <div class="k">Extracted signals</div>
        <div class="sub">Symptoms</div>
        <ul>${symptoms.length ? symptoms.map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") : "<li>(none)</li>"}</ul>
        <div class="sub" style="margin-top: 10px;">Risk factors</div>
        <ul>${riskFactors.length ? riskFactors.map((x) => `<li>${escapeHtml(String(x))}</li>`).join("") : "<li>(none)</li>"}</ul>
      </div>

      <div class="card">
        <div class="k">Safety triggers (deterministic)</div>
        <ul>${triggerLis}</ul>
      </div>
    </div>

    <div style="height:14px"></div>

    <div class="grid">
      <div class="card">
        <div class="k">Red flags</div>
        <ul>${redFlagLis}</ul>
      </div>
      <div class="card">
        <div class="k">Differential (top)</div>
        <ul>${diffLis}</ul>
      </div>
      <div class="card">
        <div class="k">Uncertainty</div>
        <ul>${uncLis}</ul>
      </div>
    <div class="card">
      <div class="k">Next actions (checklist)</div>
      ${safetySet.size ? `<div class="sub">Tags: <span class="tag safety">SAFETY</span> = deterministic rules; <span class="tag policy">POLICY</span> = policy pack / evidence agent</div>` : ""}
      <ul>${actionLis || "<li>(none)</li>"}</ul>
    </div>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div class="k">Clinician handoff</div>
      <pre>${escapeHtml(String(result.clinician_handoff || ""))}</pre>
    </div>

    <div style="height:14px"></div>

    <div class="card">
      <div class="k">Patient return precautions</div>
      <pre>${escapeHtml(String(result.patient_summary || ""))}</pre>
    </div>

    <div style="height:14px"></div>

    <div class="grid">
      <div class="card">
        <div class="k">Agent workflow (audit trace)</div>
        <div class="tablewrap">
          <table>
            <thead><tr><th>Agent</th><th>Latency</th><th>Error</th></tr></thead>
            <tbody>${workflowRows}</tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="k">Protocol citations (demo policy pack)</div>
        ${
          citationRows
            ? `<div class="sub">policy_pack_sha256: <span class="mono">${escapeHtml(String(evidence.policy_pack_sha256 || ""))}</span></div>
               <div class="tablewrap">
                 <table>
                   <thead><tr><th>Policy</th><th>Title</th><th>Citation</th><th>Recommended actions</th></tr></thead>
                   <tbody>${citationRows}</tbody>
                 </table>
               </div>`
            : "<div class=\"sub\">No matched citations.</div>"
        }
      </div>
    </div>
  </body>
</html>`;
}

function downloadReportHtml() {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }
  const requestId = state.lastRequestId || state.lastResult.request_id || "run";
  const html = buildReportHtml(state.lastIntake, state.lastResult, state.lastActionChecklist);
  downloadText(`clinicaflow_report_${requestId}.html`, html, "text/html; charset=utf-8");
  setText("statusLine", "Downloaded report.html");
}

function printReportHtml() {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }
  const html = buildReportHtml(state.lastIntake, state.lastResult, state.lastActionChecklist);
  const w = window.open("", "_blank");
  if (!w) {
    setError("runError", "Popup blocked. Use Download report.html instead.");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
  w.focus();
  // Some browsers require a delay before print.
  setTimeout(() => {
    try {
      w.print();
    } catch (e) {
      // ignore
    }
  }, 250);
}

async function downloadAuditBundle(redact) {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }

  const qs = redact ? "?redact=1" : "?redact=0";
  const requestId = state.lastRequestId || "";
  setText("statusLine", "Building audit bundle…");

  const payload = {
    intake: state.lastIntake,
    result: state.lastResult,
    checklist: state.lastActionChecklist || [],
  };

  const resp = await fetch(`/audit_bundle${qs}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders(),
      ...(requestId ? { "X-Request-ID": requestId } : {}),
    },
    body: JSON.stringify(payload),
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

async function downloadJudgePack() {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }

  const requestId = state.lastRequestId || "";
  setText("statusLine", "Building judge pack…");

  const payload = {
    intake: state.lastIntake,
    result: state.lastResult,
    checklist: state.lastActionChecklist || [],
  };

  const resp = await fetch(`/judge_pack?set=mega&redact=1&include_synthetic=1`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders(),
      ...(requestId ? { "X-Request-ID": requestId } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const text = await resp.text();
    setError("runError", `Judge pack failed: HTTP ${resp.status} ${text}`);
    setText("statusLine", "Error.");
    return;
  }

  const blob = await resp.blob();
  const cd = resp.headers.get("Content-Disposition") || "";
  const m = /filename=\"([^\"]+)\"/.exec(cd);
  const filename = m ? m[1] : `clinicaflow_judge_pack_${requestId || "run"}.zip`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  setText("statusLine", "Downloaded judge pack.");
}

async function downloadFhirBundle() {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }

  const requestId = state.lastRequestId || "";
  setText("statusLine", "Building FHIR bundle…");

  try {
    const payload = {
      intake: state.lastIntake,
      result: state.lastResult,
      checklist: state.lastActionChecklist || [],
    };
    const { data, headers } = await postJson(
      `/fhir_bundle?redact=1`,
      payload,
      requestId ? { "X-Request-ID": requestId } : {},
    );
    state.lastFhirBundle = data;
    setText("fhirPreview", fmtJson(data));
    const req = headers.get("X-Request-ID") || requestId || (data?.identifier?.value ?? "run");
    downloadText(`clinicaflow_fhir_${req}.json`, fmtJson(data), "application/fhir+json");
    setText("statusLine", "Downloaded FHIR bundle.");
  } catch (e) {
    setError("runError", e);
    setText("statusLine", "Error.");
  }
}

async function buildFhirPreview() {
  setError("runError", "");
  if (!state.lastIntake || !state.lastResult) {
    setError("runError", "Run a triage case first (so intake + result are available).");
    return;
  }

  if (state.lastFhirBundle) {
    setText("fhirPreview", fmtJson(state.lastFhirBundle));
    setText("statusLine", "FHIR preview ready (cached).");
    return;
  }

  const requestId = state.lastRequestId || "";
  setText("statusLine", "Building FHIR preview…");

  try {
    const payload = {
      intake: state.lastIntake,
      result: state.lastResult,
      checklist: state.lastActionChecklist || [],
    };
    const { data } = await postJson(
      `/fhir_bundle?redact=1`,
      payload,
      requestId ? { "X-Request-ID": requestId } : {},
    );
    state.lastFhirBundle = data;
    setText("fhirPreview", fmtJson(data));
    setText("statusLine", "FHIR preview ready.");
  } catch (e) {
    setError("runError", e);
    setText("statusLine", "Error.");
  }
}

const BENCH_TIERS = ["routine", "urgent", "critical"];

function benchTierConfusion(perCase, key) {
  const m = {};
  BENCH_TIERS.forEach((g) => {
    m[g] = {};
    BENCH_TIERS.forEach((p) => (m[g][p] = 0));
  });

  (perCase || []).forEach((row) => {
    const gold = String(row?.gold?.risk_tier || "").trim().toLowerCase();
    const pred = String(row?.[key]?.risk_tier || "").trim().toLowerCase();
    if (!BENCH_TIERS.includes(gold) || !BENCH_TIERS.includes(pred)) return;
    m[gold][pred] += 1;
  });

  let correct = 0;
  let total = 0;
  BENCH_TIERS.forEach((g) => {
    BENCH_TIERS.forEach((p) => {
      const v = m[g][p] || 0;
      total += v;
      if (g === p) correct += v;
    });
  });
  const acc = total ? (100.0 * correct) / total : 0.0;
  return { matrix: m, total, acc: Number(acc.toFixed(1)) };
}

function benchConfusionTable(conf, label) {
  const wrap = document.createElement("div");
  wrap.className = "callout";
  wrap.innerHTML = `<div class="k">${escapeHtml(label)}</div><div class="small muted">Gold rows × predicted columns • accuracy=${conf.acc}%</div>`;

  let maxVal = 0;
  BENCH_TIERS.forEach((g) => {
    BENCH_TIERS.forEach((p) => {
      const v = Number(conf?.matrix?.[g]?.[p] || 0) || 0;
      if (v > maxVal) maxVal = v;
    });
  });

  const tw = document.createElement("div");
  tw.className = "tablewrap";
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr><th>gold \\ pred</th>${BENCH_TIERS.map((t) => `<th>${t}</th>`).join("")}</tr>`;
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  BENCH_TIERS.forEach((g) => {
    const tr = document.createElement("tr");
    const head = document.createElement("td");
    head.className = "mono";
    head.textContent = g;
    tr.appendChild(head);

    BENCH_TIERS.forEach((p) => {
      const td = document.createElement("td");
      td.className = "mono";
      const v = Number(conf?.matrix?.[g]?.[p] || 0) || 0;
      td.textContent = String(v);
      const alpha = maxVal > 0 ? v / maxVal : 0;
      const isDiag = g === p;
      const base = isDiag ? "6,95,70" : "153,27,27";
      const bg = 0.04 + 0.22 * alpha;
      td.style.backgroundColor = `rgba(${base}, ${bg.toFixed(3)})`;
      if (v > 0) td.style.fontWeight = isDiag ? "950" : "800";
      td.title = isDiag ? "correct" : "off-diagonal";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tw.appendChild(table);
  wrap.appendChild(tw);
  return wrap;
}

function benchCategoryStats(perCase) {
  const stats = {};
  (perCase || []).forEach((row) => {
    const gold = row?.gold?.categories || [];
    const base = row?.baseline?.categories || [];
    const cf = row?.clinicaflow?.categories || [];

    (gold || []).forEach((cat) => {
      const c = String(cat || "").trim();
      if (!c) return;
      if (!stats[c]) stats[c] = { denom: 0, base_hit: 0, cf_hit: 0 };
      stats[c].denom += 1;
      if ((base || []).includes(c)) stats[c].base_hit += 1;
      if ((cf || []).includes(c)) stats[c].cf_hit += 1;
    });
  });
  return stats;
}

function renderBenchCategoryRecall(perCase) {
  const stats = benchCategoryStats(perCase);
  const cats = Object.keys(stats).sort();
  if (!cats.length) return null;

  const wrap = document.createElement("div");
  wrap.className = "callout";
  wrap.innerHTML = `<div class="k">Category recall (by red-flag category)</div><div class="small muted">Among cases with category present in gold labels.</div>`;

  const tw = document.createElement("div");
  tw.className = "tablewrap";
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Category</th>
        <th>n</th>
        <th>Baseline</th>
        <th>ClinicaFlow</th>
      </tr>
    </thead>
    <tbody>
      ${cats
        .map((c) => {
          const s = stats[c];
          const denom = Math.max(1, Number(s.denom || 0));
          const base = (100.0 * Number(s.base_hit || 0)) / denom;
          const cf = (100.0 * Number(s.cf_hit || 0)) / denom;
          return `<tr>
            <td class="mono">${escapeHtml(c)}</td>
            <td class="mono">${denom}</td>
            <td class="mono">${base.toFixed(1)}%</td>
            <td class="mono"><b>${cf.toFixed(1)}%</b></td>
          </tr>`;
        })
        .join("")}
    </tbody>
  `;
  tw.appendChild(table);
  wrap.appendChild(tw);
  return wrap;
}

function renderBenchSummary(summary, perCase) {
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

  if (perCase && perCase.length) {
    const baseConf = benchTierConfusion(perCase, "baseline");
    const cfConf = benchTierConfusion(perCase, "clinicaflow");
    root.appendChild(benchConfusionTable(baseConf, "Tier confusion (baseline)"));
    root.appendChild(benchConfusionTable(cfConf, "Tier confusion (ClinicaFlow)"));
    const catTable = renderBenchCategoryRecall(perCase);
    if (catTable) root.appendChild(catTable);
  }
}

// ---------------------------
// Governance dashboard (UI)
// ---------------------------

function computeGovernanceGate(summary) {
  const under = Number(summary?.under_triage_rate_clinicaflow);
  const over = Number(summary?.over_triage_rate_clinicaflow);
  const recall = Number(summary?.red_flag_recall_clinicaflow);
  const okUnder = Number.isFinite(under) && under === 0;
  const okOver = Number.isFinite(over) && over === 0;
  const okRecall = Number.isFinite(recall) && recall >= 99.9;
  return { under, over, recall, okUnder, okOver, okRecall, ok: okUnder && okRecall };
}

function computeActionProvenanceCounts(perCase) {
  let safety = 0;
  let policy = 0;
  let total = 0;
  let casesWithActions = 0;

  (perCase || []).forEach((row) => {
    const rec = row?.clinicaflow?.recommended_next_actions || [];
    const added = row?.clinicaflow?.actions_added_by_safety || [];
    if (!Array.isArray(rec) || !rec.length) return;
    casesWithActions += 1;

    const safetySet = new Set(
      Array.isArray(added)
        ? added
            .map((x) => String(x || "").trim())
            .filter((x) => x)
        : [],
    );

    rec.forEach((a) => {
      const text = String(a || "").trim();
      if (!text) return;
      total += 1;
      if (safetySet.has(text)) safety += 1;
      else policy += 1;
    });
  });

  return { safety, policy, total, casesWithActions };
}

function computeSafetyTriggerIndex(perCase) {
  const out = {};
  (perCase || []).forEach((row) => {
    const triggers = row?.clinicaflow?.safety_triggers;
    if (!Array.isArray(triggers) || !triggers.length) return;

    const seen = new Set();
    triggers.forEach((t) => {
      if (!t || typeof t !== "object") return;
      const id = String(t.id || t.label || "").trim();
      if (!id || seen.has(id)) return;
      seen.add(id);

      if (!out[id]) {
        out[id] = {
          id,
          label: String(t.label || id).trim() || id,
          severity: String(t.severity || "").trim().toLowerCase() || "info",
          n_cases: 0,
          sample_cases: [],
        };
      }
      out[id].n_cases += 1;
      const cid = String(row?.id || "").trim();
      if (cid && out[id].sample_cases.length < 3) out[id].sample_cases.push(cid);
    });
  });

  const arr = Object.values(out);
  arr.sort((a, b) => (b.n_cases || 0) - (a.n_cases || 0));
  return arr;
}

function renderGovernance(summary, perCase) {
  const gate = $("govGate");
  const cards = $("govCards");
  const prov = $("govProvenance");
  const triggers = $("govTriggers");
  const under = $("govUnder");
  if (!gate && !cards && !prov && !triggers && !under) return;

  function fmtPct(v) {
    const n = Number(v);
    return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—";
  }

  if (!summary) {
    if (gate) {
      gate.innerHTML = "";
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = "Safety gate";
      const small = document.createElement("div");
      small.className = "small muted";
      small.textContent = "Run a benchmark to populate governance metrics.";
      gate.appendChild(k);
      gate.appendChild(small);
    }
    if (cards) cards.innerHTML = "";
    if (prov) prov.innerHTML = "";
    if (triggers) triggers.innerHTML = "";
    if (under) under.innerHTML = "";
    return;
  }

  const gateStats = computeGovernanceGate(summary);
  const setName = state.lastBenchSet || "standard";

  if (gate) {
    gate.innerHTML = "";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = "Safety gate (hard stop for under-triage)";
    gate.appendChild(k);

    const row = document.createElement("div");
    row.className = "row";
    row.style.marginTop = "0";
    const chip = document.createElement("span");
    chip.className = `chip ${gateStats.ok ? "ok" : "bad"}`;
    chip.textContent = gateStats.ok ? "PASS" : "FAIL";
    row.appendChild(chip);
    gate.appendChild(row);

    const meta = document.createElement("div");
    meta.className = "small muted";
    meta.textContent = `set=${setName} • under-triage=${fmtPct(gateStats.under)} • red-flag recall=${fmtPct(
      gateStats.recall,
    )} • over-triage=${fmtPct(gateStats.over)}`;
    gate.appendChild(meta);
  }

  if (cards) {
    cards.innerHTML = "";

    function addCard(title, line1, line2) {
      const c = document.createElement("div");
      c.className = "card";
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = title;
      const v = document.createElement("div");
      v.className = "mono";
      v.textContent = line1;
      c.appendChild(k);
      c.appendChild(v);
      if (line2) {
        const s = document.createElement("div");
        s.className = "small muted";
        s.textContent = line2;
        c.appendChild(s);
      }
      cards.appendChild(c);
    }

    addCard("Cases", `${summary.n_cases} total`, `${summary.n_gold_urgent_critical} gold urgent/critical`);
    addCard(
      "Under-triage gate",
      fmtPct(gateStats.under),
      gateStats.okUnder ? "PASS (urgent/critical never predicted routine)" : "FAIL (immediate review required)",
    );
    addCard(
      "Red-flag recall",
      fmtPct(gateStats.recall),
      gateStats.okRecall ? "PASS (category-level recall target ≥ 99.9%)" : "WARN (possible drift)",
    );
    addCard(
      "Over-triage",
      fmtPct(gateStats.over),
      gateStats.okOver ? "OK (routine cases not escalated)" : "WARN (ops load increase)",
    );
  }

  if (prov) {
    prov.innerHTML = "";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = "Action provenance (SAFETY vs POLICY)";
    prov.appendChild(k);

    const stats = computeActionProvenanceCounts(perCase);
    const small = document.createElement("div");
    small.className = "small muted";
    if (!stats.total) {
      small.textContent = "No action provenance available in this benchmark output.";
      prov.appendChild(small);
    } else {
      const pct = (n) => (stats.total ? (100.0 * n) / stats.total : 0.0);
      small.textContent = `${stats.total} actions across ${stats.casesWithActions} cases`;
      prov.appendChild(small);

      function barRow(label, value, klass) {
        const row = document.createElement("div");
        row.className = "bar-row";
        const left = document.createElement("div");
        left.className = "bar-label mono";
        left.textContent = label;
        const bar = document.createElement("div");
        bar.className = "bar";
        const fill = document.createElement("div");
        fill.className = `bar-fill ${klass || ""}`;
        fill.style.width = `${Math.min(100, Math.max(0, pct(value)))}%`;
        bar.appendChild(fill);
        const right = document.createElement("div");
        right.className = "bar-val mono";
        right.textContent = `${pct(value).toFixed(1)}%`;
        row.appendChild(left);
        row.appendChild(bar);
        row.appendChild(right);
        prov.appendChild(row);
      }

      barRow("SAFETY", stats.safety, "safety");
      barRow("POLICY", stats.policy, "policy");
    }
  }

  const triggerIndex = computeSafetyTriggerIndex(perCase);

  if (triggers) {
    triggers.innerHTML = "";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = "Top safety triggers (case coverage)";
    triggers.appendChild(k);

    const small = document.createElement("div");
    small.className = "small muted";
    small.textContent = "Count = number of cases where trigger fired (deduped per case). Click a row to load a sample case.";
    triggers.appendChild(small);

    if (!triggerIndex.length) {
      const empty = document.createElement("div");
      empty.className = "small muted";
      empty.style.marginTop = "8px";
      empty.textContent = "(no safety trigger data in benchmark output)";
      triggers.appendChild(empty);
    } else {
      const tw = document.createElement("div");
      tw.className = "tablewrap";
      const table = document.createElement("table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>Trigger</th>
            <th>Severity</th>
            <th>Cases</th>
            <th>Samples</th>
          </tr>
        </thead>
        <tbody></tbody>
      `;
      const tbody = table.querySelector("tbody");
      triggerIndex.slice(0, 14).forEach((t) => {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";

        const sev = String(t.severity || "").toLowerCase();
        const sevPill = document.createElement("span");
        const riskClass = sev === "critical" ? "critical" : sev === "urgent" ? "urgent" : "routine";
        sevPill.className = `risk ${riskClass}`;
        sevPill.textContent = sev || "info";

        const label = `${t.label}${t.id && t.id !== t.label ? ` (${t.id})` : ""}`.trim();
        const samples = (t.sample_cases || []).join(", ");

        tr.innerHTML = `
          <td>${escapeHtml(label)}</td>
          <td class="sev"></td>
          <td class="mono">${escapeHtml(String(t.n_cases || 0))}</td>
          <td class="mono">${escapeHtml(samples)}</td>
        `;
        tr.querySelector(".sev").appendChild(sevPill);

        const sample = String((t.sample_cases || [])[0] || "").trim();
        if (sample) {
          tr.addEventListener("click", () => loadVignetteById(sample, { set: setName }));
        }
        tbody.appendChild(tr);
      });
      tw.appendChild(table);
      triggers.appendChild(tw);
    }
  }

  if (under) {
    under.innerHTML = "";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = "Under-triage drill-down (should be empty)";
    under.appendChild(k);

    const underRows = (perCase || []).filter((r) => benchRowFlags(r).under);
    if (!underRows.length) {
      const ok = document.createElement("div");
      ok.className = "small muted";
      ok.textContent = "PASS — no under-triage cases detected.";
      under.appendChild(ok);
    } else {
      const tw = document.createElement("div");
      tw.className = "tablewrap";
      const table = document.createElement("table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>Case</th>
            <th>Gold tier</th>
            <th>Pred tier</th>
            <th>Gold categories</th>
            <th>Pred categories</th>
          </tr>
        </thead>
        <tbody></tbody>
      `;
      const tbody = table.querySelector("tbody");
      underRows.forEach((row) => {
        const tr = document.createElement("tr");
        tr.className = "row-bad";
        tr.style.cursor = "pointer";
        tr.innerHTML = `
          <td class="mono">${escapeHtml(String(row.id || ""))}</td>
          <td>${escapeHtml(String(row?.gold?.risk_tier || ""))}</td>
          <td><b>${escapeHtml(String(row?.clinicaflow?.risk_tier || ""))}</b></td>
          <td class="mono">${escapeHtml((row?.gold?.categories || []).join(", "))}</td>
          <td class="mono">${escapeHtml((row?.clinicaflow?.categories || []).join(", "))}</td>
        `;
        tr.addEventListener("click", () => loadVignetteById(row.id, { set: setName }));
        tbody.appendChild(tr);
      });
      tw.appendChild(table);
      under.appendChild(tw);
    }
  }
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

async function loadVignetteById(caseId, opts) {
  try {
    const override = opts && typeof opts === "object" ? String(opts.set || "").trim() : "";
    const setName = override || state.lastBenchSet || $("benchSet")?.value || "standard";
    const resp = await fetchJson(`/vignettes/${encodeURIComponent(caseId)}?set=${encodeURIComponent(setName)}`);
    const intake = resp.input || resp;
    state.lastIntake = intake;
    fillFormFromIntake(intake);
    $("intakeJson").value = fmtJson(intakeForJsonView(intake));
    setTab("triage");
    setMode("form");
    setText("statusLine", `Loaded vignette: ${caseId}`);
  } catch (e) {
    setError("runError", e);
  }
}

async function runBench() {
  await runBenchSet($("benchSet")?.value || "standard", $("benchStatus"));
}

async function runBenchSet(setName, statusEl) {
  if (statusEl) statusEl.textContent = "Running…";
  try {
    const payload = await fetchJson(`/bench/vignettes?set=${encodeURIComponent(setName)}`);
    state.lastBench = payload;
    state.lastBenchSet = payload.set || setName;

    if ($("benchSet")) $("benchSet").value = state.lastBenchSet;
    if ($("govBenchSet")) $("govBenchSet").value = state.lastBenchSet;

    renderBenchSummary(payload.summary, payload.per_case);
    renderBenchCases(payload.per_case);
    renderGovernance(payload.summary, payload.per_case);

    if (statusEl) statusEl.textContent = "Done.";
  } catch (e) {
    if (statusEl) statusEl.textContent = `Error: ${e}`;
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

function benchMarkdownTable(summary) {
  if (!summary) return "";
  const setName = state.lastBenchSet || "standard";
  const pct = (v) => `${Number(v).toFixed(1)}%`;
  return [
    `<!-- vignette_set: ${setName} -->`,
    "| Metric | Baseline | ClinicaFlow |",
    "|---|---:|---:|",
    `| Red-flag recall (category-level) | \`${pct(summary.red_flag_recall_baseline)}\` | \`${pct(summary.red_flag_recall_clinicaflow)}\` |`,
    `| Under-triage rate (gold urgent/critical → predicted routine) | \`${pct(summary.under_triage_rate_baseline)}\` | \`${pct(summary.under_triage_rate_clinicaflow)}\` |`,
    `| Over-triage rate (gold routine → predicted urgent/critical) | \`${pct(summary.over_triage_rate_baseline)}\` | \`${pct(summary.over_triage_rate_clinicaflow)}\` |`,
    "",
  ].join("\n");
}

function benchRowFlags(row) {
  const goldTier = String(row?.gold?.risk_tier || "").trim().toLowerCase();
  const predTier = String(row?.clinicaflow?.risk_tier || "").trim().toLowerCase();
  const under = (goldTier === "urgent" || goldTier === "critical") && predTier === "routine";
  const over = goldTier === "routine" && predTier !== "routine";
  const mismatch = Boolean(goldTier && predTier && goldTier !== predTier);
  return { goldTier, predTier, under, over, mismatch };
}

async function buildFailurePacketMarkdown() {
  if (!state.lastBench) return "";
  const setName = state.lastBenchSet || $("benchSet")?.value || "standard";
  const perCase = state.lastBench.per_case || [];

  const underRows = perCase.filter((r) => benchRowFlags(r).under);
  const mismatchRows = perCase.filter((r) => benchRowFlags(r).mismatch);
  const overRows = perCase.filter((r) => benchRowFlags(r).over);

  const lines = [];
  lines.push("# ClinicaFlow — Vignette failure analysis packet (synthetic)");
  lines.push("");
  lines.push("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.");
  lines.push(`- vignette_set: \`${setName}\``);
  lines.push(`- generated_at: \`${new Date().toISOString()}\``);
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  lines.push(benchMarkdownTable(state.lastBench.summary).trim());
  lines.push("");

  async function addCaseSection(title, rows, { limit = 25 } = {}) {
    lines.push(`## ${title}`);
    lines.push("");
    if (!rows.length) {
      lines.push("- (none)");
      lines.push("");
      return;
    }
    const subset = rows.slice(0, Math.max(0, limit));
    for (const row of subset) {
      const id = String(row?.id || "").trim();
      const goldTier = String(row?.gold?.risk_tier || "").trim();
      const predTier = String(row?.clinicaflow?.risk_tier || "").trim();
      const goldCats = (row?.gold?.categories || []).join(", ");
      const predCats = (row?.clinicaflow?.categories || []).join(", ");
      const redFlags = (row?.clinicaflow?.red_flags || []).join("; ");
      const conf = row?.clinicaflow?.confidence;
      const rationale = String(row?.clinicaflow?.risk_tier_rationale || "").trim();
      const missing = Array.isArray(row?.clinicaflow?.missing_fields) ? row.clinicaflow.missing_fields : [];
      const safetyRulesVersion = String(row?.clinicaflow?.safety_rules_version || "").trim();
      const policySha = String(row?.clinicaflow?.policy_pack_sha256 || "").trim();
      const riskScores = row?.clinicaflow?.risk_scores || {};

      let intake = null;
      try {
        const resp = await fetchJson(
          `/vignettes/${encodeURIComponent(id)}?set=${encodeURIComponent(setName)}&include_labels=1`,
        );
        intake = resp.input || resp;
      } catch (e) {
        intake = null;
      }

      lines.push(`### ${id}`);
      lines.push("");
      lines.push(`- gold: tier=\`${goldTier}\` categories=\`${goldCats || "(none)"}\``);
      lines.push(`- pred: tier=\`${predTier}\` categories=\`${predCats || "(none)"}\``);
      if (typeof conf === "number") lines.push(`- confidence (proxy): \`${conf}\``);
      if (redFlags) lines.push(`- pred_red_flags: ${redFlags}`);
      if (rationale) lines.push(`- rationale: ${rationale}`);
      if (missing.length) lines.push(`- missing_fields: \`${missing.join(", ")}\``);
      if (safetyRulesVersion) lines.push(`- safety_rules_version: \`${safetyRulesVersion}\``);
      if (policySha) lines.push(`- policy_pack_sha256: \`${policySha.slice(0, 12)}…\``);

      try {
        const parts = [];
        if (typeof riskScores.shock_index === "number") {
          const hi = riskScores.shock_index_high ? " (high)" : "";
          parts.push(`shock_index=${riskScores.shock_index}${hi}`);
        }
        if (typeof riskScores.qsofa === "number") {
          const hi = riskScores.qsofa_high_risk ? " (≥2)" : "";
          parts.push(`qSOFA=${riskScores.qsofa}${hi}`);
        }
        if (parts.length) lines.push(`- risk_scores: \`${parts.join(" • ")}\``);
      } catch (e) {
        // ignore
      }

      const triggers = Array.isArray(row?.clinicaflow?.safety_triggers) ? row.clinicaflow.safety_triggers : [];
      if (triggers.length) {
        lines.push("- safety_triggers:");
        triggers.slice(0, 10).forEach((t) => {
          if (!t || typeof t !== "object") return;
          const label = String(t.label || t.id || "").trim();
          if (!label) return;
          const sev = String(t.severity || "").trim().toLowerCase();
          const detail = String(t.detail || "").trim();
          const tail = detail ? ` — ${detail}` : "";
          lines.push(`  - [${sev || "info"}] ${label}${tail}`);
        });
        if (triggers.length > 10) lines.push(`  - … (${triggers.length - 10} more)`);
      }

      const recActions = Array.isArray(row?.clinicaflow?.recommended_next_actions)
        ? row.clinicaflow.recommended_next_actions
        : [];
      const safetyActionsRaw = Array.isArray(row?.clinicaflow?.actions_added_by_safety) ? row.clinicaflow.actions_added_by_safety : [];
      const safetySet = new Set(safetyActionsRaw.map((x) => String(x || "").trim()).filter((x) => x));
      if (recActions.length) {
        lines.push("- recommended_next_actions (tagged):");
        recActions.slice(0, 10).forEach((a) => {
          const text = String(a || "").trim();
          if (!text) return;
          const tag = safetySet.has(text) ? "SAFETY" : "POLICY";
          lines.push(`  - [${tag}] ${text}`);
        });
        if (recActions.length > 10) lines.push(`  - … (${recActions.length - 10} more)`);
      }

      const workflow = Array.isArray(row?.clinicaflow?.workflow) ? row.clinicaflow.workflow : [];
      if (workflow.length) {
        const parts = workflow
          .filter((s) => s && typeof s === "object")
          .map((s) => {
            const agent = String(s.agent || "").trim();
            const lat = typeof s.latency_ms === "number" ? `${s.latency_ms.toFixed(2)}ms` : "—";
            const err = String(s.error || "").trim();
            const mark = err ? "(!)" : "";
            return agent ? `${agent}=${lat}${mark}` : "";
          })
          .filter((x) => x);
        if (parts.length) lines.push(`- workflow: \`${parts.join(" • ")}\``);
      }

      if (intake) {
        lines.push("");
        lines.push("```json");
        lines.push(JSON.stringify(intake, null, 2));
        lines.push("```");
      }
      lines.push("");
    }
    if (rows.length > subset.length) {
      lines.push(`- Note: truncated to first ${subset.length} cases.`);
      lines.push("");
    }
  }

  await addCaseSection("Under-triage (gold urgent/critical → predicted routine)", underRows, { limit: 25 });
  await addCaseSection("Tier mismatches (gold ≠ pred)", mismatchRows, { limit: 25 });
  await addCaseSection("Over-triage (gold routine → pred urgent/critical)", overRows, { limit: 25 });

  return lines.join("\n").trim() + "\n";
}

async function downloadFailurePacketMd() {
  if (!state.lastBench) return;
  const statuses = [$("benchStatus"), $("govStatus")].filter(Boolean);
  statuses.forEach((s) => {
    s.textContent = "Building packet…";
  });
  try {
    const md = await buildFailurePacketMarkdown();
    const setName = state.lastBenchSet || "standard";
    downloadText(`vignette_failure_packet_${setName}.md`, md, "text/markdown; charset=utf-8");
    setText("statusLine", "Downloaded vignette failure packet.");
    statuses.forEach((s) => {
      s.textContent = "Done.";
    });
  } catch (e) {
    statuses.forEach((s) => {
      s.textContent = `Error: ${e}`;
    });
  }
}

function governanceTriggerMarkdownTable(items) {
  const lines = ["| Trigger | Severity | Cases | Samples |", "|---|---:|---:|---|"];
  (items || []).forEach((t) => {
    const label = String(t.label || t.id || "").trim() || "(unknown)";
    const sev = String(t.severity || "").trim().toLowerCase() || "info";
    const n = Number(t.n_cases || 0);
    const samples = (t.sample_cases || []).slice(0, 3).join(", ");
    lines.push(`| \`${label}\` | \`${sev}\` | \`${n}\` | \`${samples}\` |`);
  });
  return lines.join("\n");
}

async function buildGovernanceReportMarkdown() {
  if (!state.lastBench) return "";
  const setName = state.lastBenchSet || "standard";
  const summary = state.lastBench.summary || {};
  const perCase = state.lastBench.per_case || [];
  const gate = computeGovernanceGate(summary);
  const prov = computeActionProvenanceCounts(perCase);
  const triggers = computeSafetyTriggerIndex(perCase).slice(0, 20);

  const pct = (v) => `${Number(v).toFixed(1)}%`;
  const pct2 = (n, d) => (d ? `${((100.0 * n) / d).toFixed(1)}%` : "—");

  const lines = [];
  lines.push("# ClinicaFlow — Safety governance report (synthetic)");
  lines.push("");
  lines.push("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.");
  lines.push(`- vignette_set: \`${setName}\``);
  lines.push(`- generated_at: \`${new Date().toISOString()}\``);
  lines.push("");

  lines.push("## Safety gate");
  lines.push("");
  lines.push(`- gate_status: \`${gate.ok ? "PASS" : "FAIL"}\``);
  lines.push(`- under-triage (ClinicaFlow): \`${pct(gate.under)}\``);
  lines.push(`- red-flag recall (ClinicaFlow): \`${pct(gate.recall)}\``);
  lines.push(`- over-triage (ClinicaFlow): \`${pct(gate.over)}\``);
  lines.push("");

  lines.push("## Benchmark summary");
  lines.push("");
  lines.push(benchMarkdownTable(summary).trim());
  lines.push("");

  lines.push("## Action provenance");
  lines.push("");
  lines.push(`- total_actions: \`${prov.total}\``);
  lines.push(`- safety_actions: \`${prov.safety}\` (${pct2(prov.safety, prov.total)})`);
  lines.push(`- policy_actions: \`${prov.policy}\` (${pct2(prov.policy, prov.total)})`);
  lines.push("");

  lines.push("## Top safety triggers (case coverage)");
  lines.push("");
  if (!triggers.length) {
    lines.push("- (no safety trigger data in benchmark output)");
  } else {
    lines.push(governanceTriggerMarkdownTable(triggers));
  }
  lines.push("");

  const underRows = perCase.filter((r) => benchRowFlags(r).under);
  lines.push("## Under-triage cases (should be empty)");
  lines.push("");
  if (!underRows.length) {
    lines.push("- PASS — no under-triage cases detected.");
  } else {
    underRows.slice(0, 50).forEach((row) => {
      lines.push(`- ${row.id} gold=${row?.gold?.risk_tier} pred=${row?.clinicaflow?.risk_tier}`);
    });
  }
  lines.push("");

  return lines.join("\n").trim() + "\n";
}

async function downloadGovernanceMd() {
  const status = $("govStatus");
  if (status) status.textContent = "Building report…";
  try {
    const md = await buildGovernanceReportMarkdown();
    const setName = state.lastBenchSet || "standard";
    downloadText(`governance_report_${setName}.md`, md, "text/markdown; charset=utf-8");
    if (status) status.textContent = "Done.";
    setText("statusLine", "Downloaded governance report.");
  } catch (e) {
    if (status) status.textContent = `Error: ${e}`;
  }
}

async function runSynthetic() {
  const status = $("syntheticStatus");
  if (status) status.textContent = "Running…";
  const out = $("syntheticMd");
  if (out) out.textContent = "";

  try {
    const payload = await fetchJson("/bench/synthetic?seed=17&n=220");
    state.lastSynthetic = payload;
    if (out) out.textContent = String(payload.markdown || "").trim();
    if (status) status.textContent = "Done.";
  } catch (e) {
    state.lastSynthetic = null;
    if (status) status.textContent = `Error: ${e}`;
  }
}

// ---------------------------
// Workspace (UI-local)
// ---------------------------

const WORKSPACE_STORAGE_KEY = "clinicaflow.workspace.v1";
const WORKSPACE_VIEW_KEY = "clinicaflow.workspace.view.v1";
const WORKSPACE_STATUSES = ["new", "triaged", "needs_review", "closed"];
const WORKSPACE_VIEWS = ["board", "table"];

function loadWorkspaceView() {
  try {
    const raw = String(localStorage.getItem(WORKSPACE_VIEW_KEY) || "").trim();
    if (WORKSPACE_VIEWS.includes(raw)) return raw;
  } catch (e) {
    // ignore
  }
  return "board";
}

function setWorkspaceView(view) {
  const v = view === "table" ? "table" : "board";
  state.workspace.view = v;
  try {
    localStorage.setItem(WORKSPACE_VIEW_KEY, v);
  } catch (e) {
    // ignore
  }

  show("wsBoardWrap", v === "board");
  show("wsTableWrap", v === "table");

  const btnBoard = $("wsViewBoard");
  const btnTable = $("wsViewTable");
  if (btnBoard) btnBoard.classList.toggle("active", v === "board");
  if (btnTable) btnTable.classList.toggle("active", v === "table");
}

function normalizeWorkspaceStatus(value, hasResult) {
  const s = String(value || "").trim();
  if (WORKSPACE_STATUSES.includes(s)) return s;
  return hasResult ? "triaged" : "new";
}

function suggestStatusFromResult(result) {
  const tier = String(result?.risk_tier || "").trim().toLowerCase();
  if (tier === "urgent" || tier === "critical") return "needs_review";
  if (tier) return "triaged";
  return "triaged";
}

function workspaceStatus(item) {
  return normalizeWorkspaceStatus(item?.status, Boolean(item?.result));
}

function workspaceStatusPill(status) {
  const s = String(status || "").trim();
  const span = document.createElement("span");
  span.className = `pill status status-${s || "new"}`;
  span.textContent = s || "new";
  return span;
}

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
  const item = workspaceSelectedItem();
  if (pre) pre.textContent = fmtJson(item || {});

  const sel = $("wsStatusSelect");
  if (sel) sel.value = workspaceStatus(item || {});
  const btnUpdate = $("wsUpdateStatus");
  if (btnUpdate) btnUpdate.disabled = !item;
  const btnRun = $("wsRunTriage");
  if (btnRun) btnRun.disabled = !item;

  const sum = $("wsSelectedSummaryText");
  const rf = $("wsSelectedRedFlags");
  const act = $("wsSelectedActions");
  const hand = $("wsSelectedHandoff");

  const btnLoad = $("wsLoadIntoTriage");
  if (btnLoad) btnLoad.disabled = !item;
  const btnReport = $("wsDownloadReport");
  if (btnReport) btnReport.disabled = !Boolean(item?.result);
  const btnNote = $("wsDownloadNote");
  if (btnNote) btnNote.disabled = !Boolean(item?.result);
  const btnDel = $("wsDeleteSelected");
  if (btnDel) btnDel.disabled = !item;

  if (!item) {
    if (sum) sum.textContent = "Select an item from the table to view details.";
    if (rf) rf.textContent = "red_flags: —";
    if (act) act.textContent = "next_actions: —";
    if (hand) hand.textContent = "handoff: —";
    return;
  }

  const intake = item.intake || {};
  const result = item.result || null;
  const status = workspaceStatus(item);
  const created = fmtShortTs(item.created_at);
  const cc = String(intake.chief_complaint || "").trim() || "(missing chief_complaint)";

  const rid = result ? String(result.request_id || item.id || "").trim() : String(item.id || "").trim();
  const tier = result ? String(result.risk_tier || "—") : "—";
  const backend = result ? extractBackend(result) : "—";

  if (sum) sum.textContent = `id=${item.id} • created=${created} • status=${status} • request_id=${rid || "—"} • tier=${tier} • backend=${backend} • cc=${cc.slice(0, 120)}`;

  if (rf) {
    const flags = result && Array.isArray(result.red_flags) ? result.red_flags.map((x) => String(x || "").trim()).filter((x) => x) : [];
    rf.textContent = flags.length ? `red_flags: ${flags.slice(0, 6).join(" • ")}${flags.length > 6 ? " • …" : ""}` : "red_flags: —";
  }

  if (act) {
    if (!result) {
      act.textContent = "next_actions: (not triaged)";
    } else {
      const safety = traceOutput(result, "safety_escalation") || {};
      const safetyActions = Array.isArray(safety.actions_added_by_safety)
        ? safety.actions_added_by_safety.map((x) => String(x || "").trim()).filter((x) => x)
        : [];
      const safetySet = new Set(safetyActions);
      const actions = Array.isArray(result.recommended_next_actions)
        ? result.recommended_next_actions.map((x) => String(x || "").trim()).filter((x) => x)
        : [];
      const tagged = actions.map((a) => `[${safetySet.has(a) ? "SAFETY" : "POLICY"}] ${a}`);
      act.textContent = tagged.length ? `next_actions: ${tagged.slice(0, 5).join(" • ")}${tagged.length > 5 ? " • …" : ""}` : "next_actions: —";
    }
  }

  if (hand) {
    if (!result) {
      hand.textContent = "handoff: —";
    } else {
      const raw = String(result.clinician_handoff || "").trim();
      if (!raw) {
        hand.textContent = "handoff: —";
      } else {
        const lines = raw.split(/\r?\n/g).slice(0, 10);
        hand.textContent = lines.join("\n") + (raw.split(/\r?\n/g).length > 10 ? "\n…" : "");
      }
    }
  }
}

function renderWorkspaceSummary(items, filteredCount) {
  const el = $("wsSummaryText");
  if (!el) return;

  const total = (items || []).length;
  const filtered = typeof filteredCount === "number" ? filteredCount : null;
  const runs = (items || []).filter((x) => x && x.result).length;

  const tiers = { routine: 0, urgent: 0, critical: 0, unknown: 0 };
  const statuses = { new: 0, triaged: 0, needs_review: 0, closed: 0, unknown: 0 };
  const backends = {};
  const latencies = [];

  (items || []).forEach((item) => {
    const st = workspaceStatus(item);
    if (st in statuses) statuses[st] += 1;
    else statuses.unknown += 1;

    const result = item?.result;
    if (!result) return;
    const tier = String(result.risk_tier || "").toLowerCase();
    if (tier === "routine" || tier === "urgent" || tier === "critical") tiers[tier] += 1;
    else tiers.unknown += 1;

    const backend = extractBackend(result) || "unknown";
    backends[backend] = (backends[backend] || 0) + 1;

    const ms = typeof result.total_latency_ms === "number" ? result.total_latency_ms : null;
    if (ms != null && Number.isFinite(ms)) latencies.push(ms);
  });

  const backendBits = Object.entries(backends)
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .slice(0, 4)
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");

  const avg = latencies.length ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : null;
  const tierBits = `routine=${tiers.routine}, urgent=${tiers.urgent}, critical=${tiers.critical}`;
  const statusBits = `new=${statuses.new}, triaged=${statuses.triaged}, needs_review=${statuses.needs_review}, closed=${statuses.closed}`;
  const filterBits = filtered != null && filtered !== total ? ` • filtered: ${filtered}/${total}` : "";
  el.textContent = `items: ${total} (runs: ${runs})${filterBits} • status: ${statusBits} • tiers: ${tierBits} • backends: ${backendBits || "—"} • avg latency: ${
    avg != null ? `${avg} ms` : "—"
  }`;
}

function workspaceItemChecklist(item) {
  if (!item) return null;
  const req = item?.result?.request_id || "";
  return item.checklist || loadActionChecklist(req) || null;
}

function workspaceDownloadReport(item) {
  if (!item?.intake || !item?.result) return;
  const req = item.result.request_id || item.id || "run";
  const html = buildReportHtml(item.intake, item.result, workspaceItemChecklist(item));
  downloadText(`clinicaflow_report_${req}.html`, html, "text/html; charset=utf-8");
  setText("wsStatus", "Downloaded report.html");
}

function workspaceDownloadNote(item) {
  if (!item?.intake || !item?.result) return;
  const req = item.result.request_id || item.id || "run";
  const md = buildNoteMarkdown(item.intake, item.result, workspaceItemChecklist(item));
  downloadText(`clinicaflow_note_${req}.md`, md, "text/markdown; charset=utf-8");
  setText("wsStatus", "Downloaded note.md");
}

function workspaceFilters() {
  const q = String($("wsSearch")?.value || "").trim().toLowerCase();
  const status = String($("wsFilterStatus")?.value || "all").trim();
  const sort = String($("wsSort")?.value || "newest").trim();
  return { q, status, sort };
}

function workspaceRiskRank(item) {
  const t = String(item?.result?.risk_tier || "").trim().toLowerCase();
  if (t === "critical") return 3;
  if (t === "urgent") return 2;
  if (t === "routine") return 1;
  return 0;
}

function workspaceStatusRank(value) {
  const s = String(value || "").trim();
  if (s === "needs_review") return 3;
  if (s === "new") return 2;
  if (s === "triaged") return 1;
  if (s === "closed") return 0;
  return -1;
}

function workspaceFilterAndSort(itemsAll) {
  const { q, status, sort } = workspaceFilters();
  let items = (itemsAll || []).slice().filter((x) => x && typeof x === "object");

  if (status && status !== "all") {
    items = items.filter((item) => workspaceStatus(item) === status);
  }

  if (q) {
    items = items.filter((item) => {
      const intake = item.intake || {};
      const result = item.result || {};
      const text = [
        item.id,
        item.created_at,
        workspaceStatus(item),
        intake.chief_complaint,
        result.risk_tier,
        (result.red_flags || []).join(" "),
        (result.recommended_next_actions || []).join(" "),
      ]
        .map((x) => String(x || "").toLowerCase())
        .join(" ");
      return text.includes(q);
    });
  }

  function created(item) {
    return String(item?.created_at || "");
  }

  if (sort === "oldest") {
    items.sort((a, b) => created(a).localeCompare(created(b)) || String(a.id).localeCompare(String(b.id)));
  } else if (sort === "severity") {
    items.sort(
      (a, b) =>
        workspaceRiskRank(b) - workspaceRiskRank(a) ||
        created(b).localeCompare(created(a)) ||
        String(a.id).localeCompare(String(b.id)),
    );
  } else if (sort === "status") {
    items.sort(
      (a, b) =>
        workspaceStatusRank(workspaceStatus(b)) - workspaceStatusRank(workspaceStatus(a)) ||
        workspaceRiskRank(b) - workspaceRiskRank(a) ||
        created(b).localeCompare(created(a)) ||
        String(a.id).localeCompare(String(b.id)),
    );
  } else {
    // newest (default)
    items.sort((a, b) => created(b).localeCompare(created(a)) || String(a.id).localeCompare(String(b.id)));
  }

  return { items, filters: { q, status, sort } };
}

function renderWorkspaceBoard(itemsAll, filteredItems) {
  const root = $("wsBoard");
  if (!root) return;

  const all = Array.isArray(itemsAll) ? itemsAll : [];
  const items = Array.isArray(filteredItems) ? filteredItems : [];

  const groups = { needs_review: [], new: [], triaged: [], closed: [] };
  items.forEach((item) => {
    const st = workspaceStatus(item);
    if (st in groups) groups[st].push(item);
  });

  const columns = [
    { key: "needs_review", title: "Needs review" },
    { key: "new", title: "New" },
    { key: "triaged", title: "Triaged" },
    { key: "closed", title: "Closed" },
  ];

  function onCardSelected(id) {
    state.workspace.selectedId = id;
    renderWorkspaceTable();
    renderWorkspaceSelected();
  }

  root.innerHTML = "";

  columns.forEach((col) => {
    const key = col.key;
    const rows = groups[key] || [];

    const wrap = document.createElement("div");
    wrap.className = "kanban-col";
    wrap.dataset.status = key;

    const head = document.createElement("div");
    head.className = "kanban-head";
    const title = document.createElement("div");
    title.className = "kanban-title";
    title.textContent = col.title;
    const count = document.createElement("div");
    count.className = "kanban-count mono";
    count.textContent = String(rows.length);
    head.appendChild(title);
    head.appendChild(count);

    const list = document.createElement("div");
    list.className = "kanban-list";
    list.dataset.status = key;

    function clearDrag() {
      wrap.classList.remove("dragover");
    }

    wrap.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      wrap.classList.add("dragover");
    });
    wrap.addEventListener("dragleave", () => clearDrag());
    wrap.addEventListener("drop", (ev) => {
      ev.preventDefault();
      clearDrag();
      const id = String(ev?.dataTransfer?.getData("text/plain") || "").trim();
      if (!id) return;
      const existing = all.find((x) => x && x.id === id);
      if (!existing) return;
      state.workspace.selectedId = id;
      workspaceUpdateItem(id, { status: key });
      setText("wsStatus", `Moved: ${id} → ${key}`);
    });

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "kanban-empty";
      empty.textContent = "Drop here…";
      list.appendChild(empty);
    } else {
      rows.forEach((item) => {
        const intake = item.intake || {};
        const result = item.result || null;
        const created = fmtShortTs(item.created_at);
        const cc = String(intake.chief_complaint || "").trim() || "(missing chief_complaint)";

        const card = document.createElement("div");
        card.className = "kanban-card";
        card.dataset.id = item.id;
        if (state.workspace.selectedId === item.id) card.classList.add("selected");
        card.draggable = true;
        card.addEventListener("click", () => onCardSelected(item.id));
        card.addEventListener("dragstart", (ev) => {
          try {
            ev.dataTransfer.setData("text/plain", item.id);
            ev.dataTransfer.effectAllowed = "move";
          } catch (e) {
            // ignore
          }
        });

        const top = document.createElement("div");
        top.className = "kanban-top";
        const left = workspaceStatusPill(workspaceStatus(item));

        let right = null;
        if (result) {
          const tier = String(result.risk_tier || "").trim().toLowerCase();
          const okTier = tier === "routine" || tier === "urgent" || tier === "critical" ? tier : "routine";
          const risk = document.createElement("span");
          risk.className = `risk ${okTier}`;
          risk.textContent = okTier;
          right = risk;
        } else {
          const pending = document.createElement("span");
          pending.className = "pill subtle";
          pending.textContent = "not triaged";
          right = pending;
        }

        top.appendChild(left);
        top.appendChild(right);

        const ccEl = document.createElement("div");
        ccEl.className = "kanban-cc";
        ccEl.textContent = cc.slice(0, 160);

        const meta = document.createElement("div");
        meta.className = "kanban-meta";

        const ts = document.createElement("span");
        ts.className = "mono";
        ts.textContent = created;
        meta.appendChild(ts);

        if (result) {
          const backend = extractBackend(result) || "deterministic";
          const backendEl = document.createElement("span");
          backendEl.className = "mono";
          backendEl.textContent = `backend=${backend}`;
          meta.appendChild(backendEl);

          const flags = Array.isArray(result.red_flags) ? result.red_flags.map((x) => String(x || "").trim()).filter((x) => x) : [];
          if (flags.length) {
            const rf = document.createElement("span");
            rf.className = "mono";
            rf.textContent = `flags=${flags.length}`;
            meta.appendChild(rf);
          }
        }

        card.appendChild(top);
        card.appendChild(ccEl);
        card.appendChild(meta);
        list.appendChild(card);
      });
    }

    wrap.appendChild(head);
    wrap.appendChild(list);
    root.appendChild(wrap);
  });
}

function buildShiftHandoffMarkdown(itemsAll) {
  const { items, filters } = workspaceFilterAndSort(itemsAll || []);
  const open = items.filter((item) => workspaceStatus(item) !== "closed");
  const now = new Date().toISOString();

  const lines = [];
  lines.push("# ClinicaFlow — Shift handoff (demo)");
  lines.push("");
  lines.push("- DISCLAIMER: Decision support only. Not a diagnosis. No PHI.");
  lines.push(`- generated_at: \`${now}\``);
  lines.push(`- filters: status=\`${filters.status}\` sort=\`${filters.sort}\` q=\`${filters.q || ""}\``);
  lines.push(`- items_in_view: \`${items.length}\``);
  lines.push(`- open_items_in_view: \`${open.length}\``);
  lines.push("");

  const groups = { needs_review: [], new: [], triaged: [], closed: [] };
  open.forEach((item) => {
    const st = workspaceStatus(item);
    if (st in groups) groups[st].push(item);
  });

  const sections = [
    ["needs_review", "Needs review"],
    ["new", "New (not triaged yet)"],
    ["triaged", "Triaged"],
  ];

  sections.forEach(([key, title]) => {
    const rows = groups[key] || [];
    lines.push(`## ${title} (${rows.length})`);
    lines.push("");
    if (!rows.length) {
      lines.push("- (none)");
      lines.push("");
      return;
    }

    rows
      .slice()
      .sort((a, b) => workspaceRiskRank(b) - workspaceRiskRank(a) || String(b.created_at || "").localeCompare(String(a.created_at || "")))
      .forEach((item) => {
        const intake = item.intake || {};
        const result = item.result || null;
        const st = workspaceStatus(item);
        const created = fmtShortTs(item.created_at);
        const cc = String(intake.chief_complaint || "").trim() || "(missing chief_complaint)";
        lines.push(`### ${item.id}`);
        lines.push("");
        lines.push(`- status: \`${st}\``);
        lines.push(`- created_at: \`${created}\``);
        lines.push(`- chief_complaint: ${cc}`);
        if (result) {
          lines.push(`- request_id: \`${result.request_id || item.id}\``);
          lines.push(`- risk_tier: \`${result.risk_tier || ""}\``);
          lines.push(`- reasoning_backend: \`${extractBackend(result)}\``);
          const flags = Array.isArray(result.red_flags) ? result.red_flags.map((x) => String(x || "").trim()).filter((x) => x) : [];
          if (flags.length) lines.push(`- red_flags: ${flags.slice(0, 8).join("; ")}${flags.length > 8 ? "; …" : ""}`);
          const actions = Array.isArray(result.recommended_next_actions)
            ? result.recommended_next_actions.map((x) => String(x || "").trim()).filter((x) => x)
            : [];
          if (actions.length) lines.push(`- top_actions: ${actions.slice(0, 6).join("; ")}${actions.length > 6 ? "; …" : ""}`);

          const handoff = String(result.clinician_handoff || "").trim();
          if (handoff) {
            const snippet = handoff.split(/\r?\n/g).slice(0, 12).join("\n");
            lines.push("- handoff (snippet):");
            lines.push("");
            lines.push("```");
            lines.push(snippet);
            lines.push("```");
          }
        }
        lines.push("");
      });
  });

  return lines.join("\n").trim() + "\n";
}

function workspaceDownloadShiftHandoff() {
  const itemsAll = loadWorkspaceItems();
  const md = buildShiftHandoffMarkdown(itemsAll);
  downloadText("shift_handoff.md", md, "text/markdown; charset=utf-8");
  setText("wsStatus", "Downloaded shift_handoff.md");
}

function renderWorkspaceTable() {
  const body = $("wsTableBody");
  if (!body) return;
  body.innerHTML = "";

  const all = loadWorkspaceItems();
  const { items } = workspaceFilterAndSort(all);
  renderWorkspaceSummary(all, items.length);
  renderWorkspaceBoard(all, items);

  if (!all.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted" colspan="6">No saved items yet.</td>`;
    body.appendChild(tr);
    renderWorkspaceSelected();
    return;
  }

  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted" colspan="6">No matching items (adjust filters).</td>`;
    body.appendChild(tr);
    renderWorkspaceSelected();
    return;
  }

  items.forEach((item) => {
      const tr = document.createElement("tr");
      const intake = item.intake || {};
      const result = item.result || null;
      const status = workspaceStatus(item);
      const tier = result ? result.risk_tier || "" : "—";
      const backend = result ? extractBackend(result) : "—";

      if (item.id === state.workspace.selectedId) tr.classList.add("row-selected");

      tr.innerHTML = `
        <td class="mono">${escapeHtml(fmtShortTs(item.created_at))}</td>
        <td class="ws-status"></td>
        <td>${escapeHtml(String(intake.chief_complaint || "").slice(0, 120))}</td>
        <td><b>${escapeHtml(String(tier))}</b></td>
        <td class="mono">${escapeHtml(String(backend))}</td>
        <td></td>
      `;
      const statusTd = tr.querySelector("td.ws-status");
      if (statusTd) statusTd.appendChild(workspaceStatusPill(status));

      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => {
        state.workspace.selectedId = item.id;
        renderWorkspaceTable();
        setText("wsStatus", `Selected: ${item.id}`);
        setError("wsError", "");
      });

      const actionsTd = tr.querySelector("td:last-child");
      const wrap = document.createElement("div");
      wrap.className = "row";
      wrap.style.margin = "0";

      const btnTriage = document.createElement("button");
      btnTriage.className = "btn subtle";
      btnTriage.type = "button";
      btnTriage.textContent = item.result ? "Re-run" : "Triage";
      btnTriage.addEventListener("click", (ev) => {
        ev.stopPropagation();
        workspaceRunTriage(item);
      });
      wrap.appendChild(btnTriage);

      if (item.result) {
        const btnReport = document.createElement("button");
        btnReport.className = "btn subtle";
        btnReport.type = "button";
        btnReport.textContent = "Report";
        btnReport.addEventListener("click", (ev) => {
          ev.stopPropagation();
          workspaceDownloadReport(item);
        });
        wrap.appendChild(btnReport);

        const btnNote = document.createElement("button");
        btnNote.className = "btn subtle";
        btnNote.type = "button";
        btnNote.textContent = "Note";
        btnNote.addEventListener("click", (ev) => {
          ev.stopPropagation();
          workspaceDownloadNote(item);
        });
        wrap.appendChild(btnNote);
      }

      const btnDel = document.createElement("button");
      btnDel.className = "btn subtle";
      btnDel.type = "button";
      btnDel.textContent = "Delete";
      btnDel.addEventListener("click", (ev) => {
        ev.stopPropagation();
        workspaceDelete(item.id);
      });
      wrap.appendChild(btnDel);
      actionsTd.appendChild(wrap);

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

function stripImagesForWorkspace(intake) {
  const out = JSON.parse(JSON.stringify(intake || {}));
  const imgs = out.image_data_urls;
  if (Array.isArray(imgs) && imgs.length) {
    delete out.image_data_urls;
    out.image_data_urls_count = imgs.length;
  }
  return out;
}

function workspaceAdd({ intake, result, checklist }) {
  const items = loadWorkspaceItems();
  const now = new Date().toISOString();
  const id = newLocalId();
  const status = result ? suggestStatusFromResult(result) : "new";
  items.push({
    id,
    created_at: now,
    intake: stripImagesForWorkspace(intake || {}),
    result: result || null,
    checklist: checklist || null,
    status,
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

function workspaceUpdateItem(id, patch) {
  const items = loadWorkspaceItems();
  const idx = items.findIndex((x) => x && x.id === id);
  if (idx === -1) return null;
  const next = { ...(items[idx] || {}), ...(patch || {}) };
  next.status = normalizeWorkspaceStatus(next.status, Boolean(next.result));
  items[idx] = next;
  saveWorkspaceItems(items);
  renderWorkspaceTable();
  renderWorkspaceSelected();
  return next;
}

async function workspaceRunTriage(item) {
  setError("wsError", "");
  const status = $("wsStatus");
  if (status) status.textContent = "Running triage…";
  try {
    if (!item || !item.id) throw new Error("Select a workspace item first.");
    const intake = item.intake || {};
    if (!String(intake.chief_complaint || "").trim()) throw new Error("Saved intake is missing chief_complaint.");

    const requestId = String(item?.result?.request_id || item.id || "").trim();
    const { data, headers } = await postJson(
      "/triage",
      intake,
      requestId ? { "X-Request-ID": requestId } : null,
    );
    const rid = headers.get("X-Request-ID") || data?.request_id || requestId || item.id;
    const nextStatus = suggestStatusFromResult(data);
    workspaceUpdateItem(item.id, { result: data, checklist: null, status: nextStatus });
    setText("wsStatus", `Triaged: ${rid} • tier=${data?.risk_tier || "—"} • status=${nextStatus}`);
    // Keep UI state in sync for quick report downloads.
    state.lastIntake = intake;
    state.lastResult = data;
    state.lastRequestId = rid;
  } catch (e) {
    setError("wsError", e);
    if (status) status.textContent = `Error: ${e}`;
  }
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
      .map((x) => {
        const hasResult = Boolean(x.result);
        const rawStatus = String(x.status || "").trim();
        let status = normalizeWorkspaceStatus(rawStatus, hasResult);
        if (!rawStatus && hasResult) status = suggestStatusFromResult(x.result);
        return {
          id: String(x.id || newLocalId()),
          created_at: String(x.created_at || new Date().toISOString()),
          intake: stripImagesForWorkspace(x.intake || {}),
          result: x.result || null,
          checklist: x.checklist || null,
          status,
        };
      });
    saveWorkspaceItems(sanitized);
    // Best-effort: hydrate per-request checklists for later exports.
    sanitized.forEach((item) => {
      const req = item?.result?.request_id || "";
      if (req && item.checklist) saveActionChecklist(req, item.checklist);
    });
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

async function reviewImportFromFile(file) {
  setError("reviewError", "");
  if (!file) return;
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    if (!Array.isArray(payload)) throw new Error("Invalid file: expected a JSON array of review objects.");
    const sanitized = payload
      .filter((x) => x && typeof x === "object")
      .map((x) => ({
        ...x,
        id: String(x.id || `${String(x.case_id || "case")}-${Date.now()}-${Math.random().toString(16).slice(2)}`),
        created_at: String(x.created_at || new Date().toISOString()),
        case_id: String(x.case_id || "").trim(),
        vignette_set: String(x.vignette_set || "standard").trim() || "standard",
      }));
    saveStoredReviews(sanitized);
    renderReviewTable();
    updateReviewParagraph();
    renderReviewSummary();
    setText("statusLine", `Imported ${sanitized.length} reviews.`);
  } catch (e) {
    setError("reviewError", e);
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
    tr.innerHTML = `<td class="muted" colspan="7">No saved reviews yet.</td>`;
    body.appendChild(tr);
    return;
  }

  reviews
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .forEach((r) => {
      const tr = document.createElement("tr");
      const setName = r?.vignette_set || "standard";
      const safety = r?.ratings?.risk_tier_safety || "";
      const actionability = r?.ratings?.actionability ?? "";
      const handoff = r?.ratings?.handoff_quality ?? "";
      tr.innerHTML = `
        <td class="mono">${escapeHtml(String(r.case_id || ""))}</td>
        <td class="mono">${escapeHtml(String(setName))}</td>
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

async function loadSavedReview(r) {
  if (!r) return;
  state.review.lastCaseId = r.case_id || null;
  state.review.lastIntake = r.intake || null;
  state.review.lastLabels = r.gold_labels || null;
  state.review.lastResult = r.output_preview_full || r.output_preview || null;

  const setEl = $("reviewSet");
  if (setEl) {
    setEl.value = r?.vignette_set || "standard";
    await loadReviewCases();
  }

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
  updateReviewParagraph();
  renderReviewSummary();
  setText("statusLine", "Deleted saved review.");
}

async function loadReviewCases() {
  const select = $("reviewCaseSelect");
  if (!select) return;
  select.innerHTML = "";

  const setName = String($("reviewSet")?.value || "standard").trim() || "standard";

  try {
    const payload = await fetchJson(`/vignettes?set=${encodeURIComponent(setName)}`);
    const vignettes = payload.vignettes || [];
    const header = document.createElement("option");
    header.value = "";
    header.textContent = `— select a case (${setName}, n=${vignettes.length}) —`;
    select.appendChild(header);
    vignettes.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      const cc = String(v.chief_complaint || "").slice(0, 60);
      opt.textContent = `${v.id} — ${cc}`;
      select.appendChild(opt);
    });
    select.value = "";
  } catch (e) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `Failed to load vignettes (${setName})`;
    select.appendChild(opt);
  }
}

async function reviewLoadCase() {
  setError("reviewError", "");
  const caseId = String($("reviewCaseSelect")?.value || "").trim();
  if (!caseId) return;

  try {
    const setName = String($("reviewSet")?.value || "standard").trim() || "standard";
    const include = $("reviewShowGold")?.checked ? "1" : "0";
    const resp = await fetchJson(
      `/vignettes/${encodeURIComponent(caseId)}?set=${encodeURIComponent(setName)}&include_labels=${include}`,
    );
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

function summarizeReviews(reviews) {
  const safetyCounts = {};
  const actionability = [];
  const handoff = [];
  const roles = new Set();
  const caseIds = new Set();
  const quotes = [];

  (reviews || []).forEach((r) => {
    const cid = String(r?.case_id || "").trim();
    if (cid) caseIds.add(cid);

    const role = String(r?.reviewer?.role || "").trim();
    if (role) roles.add(role);

    const safety = String(r?.ratings?.risk_tier_safety || "").trim().toLowerCase();
    if (safety) safetyCounts[safety] = (safetyCounts[safety] || 0) + 1;

    const a = r?.ratings?.actionability;
    if (typeof a === "number" && Number.isFinite(a)) actionability.push(a);
    const h = r?.ratings?.handoff_quality;
    if (typeof h === "number" && Number.isFinite(h)) handoff.push(h);

    const fb = String(r?.notes?.feedback || "").trim();
    if (fb) quotes.push(fb);
  });

  function meanOrNull(values) {
    if (!values.length) return null;
    const sum = values.reduce((acc, v) => acc + v, 0);
    return sum / values.length;
  }

  return {
    nReviews: (reviews || []).length,
    nCases: caseIds.size,
    safetyCounts,
    avgActionability: meanOrNull(actionability),
    avgHandoff: meanOrNull(handoff),
    reviewerRoles: [...roles].sort(),
    quotes,
  };
}

function groupReviewsBySet(reviews) {
  const groups = {};
  (reviews || []).forEach((r) => {
    const raw = String(r?.vignette_set || "").trim().toLowerCase();
    const setName = raw || "standard";
    if (!groups[setName]) groups[setName] = [];
    groups[setName].push(r);
  });
  return groups;
}

function reviewSummaryMarkdown(reviews, opts) {
  const options = opts && typeof opts === "object" ? opts : {};
  const maxQuotes = Number.isFinite(Number(options.maxQuotes)) ? Number(options.maxQuotes) : 3;
  const summary = summarizeReviews(reviews);
  const groups = groupReviewsBySet(reviews);

  const lines = [];
  lines.push("## Clinician review (qualitative; no PHI)");
  lines.push("");
  if (!summary.nReviews) {
    lines.push("- No clinician reviews recorded for this submission.");
    return lines.join("\n").trim() + "\n";
  }

  lines.push(`- Reviews: **${summary.nReviews}** (cases: **${summary.nCases}**)`);
  if (summary.reviewerRoles.length) lines.push(`- Reviewer roles (as entered): ${summary.reviewerRoles.join(", ")}`);
  const safetyKeys = Object.keys(summary.safetyCounts || {});
  if (safetyKeys.length) {
    const parts = safetyKeys
      .sort((a, b) => (summary.safetyCounts[b] || 0) - (summary.safetyCounts[a] || 0) || a.localeCompare(b))
      .map((k) => `${k}=${summary.safetyCounts[k]}`);
    lines.push(`- Risk-tier safety: ${parts.join(", ")}`);
  }
  if (summary.avgActionability != null) lines.push(`- Avg actionability: **${summary.avgActionability.toFixed(2)}/5**`);
  if (summary.avgHandoff != null) lines.push(`- Avg handoff quality: **${summary.avgHandoff.toFixed(2)}/5**`);

  const q = (summary.quotes || []).filter((x) => x).slice(0, Math.max(0, maxQuotes));
  if (q.length) {
    lines.push("");
    lines.push("### Selected feedback (verbatim)");
    lines.push("");
    q.forEach((item) => {
      lines.push(`- ${item}`);
    });
  }

  const setNames = Object.keys(groups || {});
  if (setNames.length > 1) {
    lines.push("");
    lines.push("## Breakdown by vignette set");
    lines.push("");
    setNames
      .slice()
      .sort()
      .forEach((setName) => {
        const s = summarizeReviews(groups[setName] || []);
        lines.push(`### \`${setName}\``);
        lines.push("");
        lines.push(`- Reviews: **${s.nReviews}** (cases: **${s.nCases}**)`);
        const ks = Object.keys(s.safetyCounts || {});
        if (ks.length) {
          const parts = ks
            .sort((a, b) => (s.safetyCounts[b] || 0) - (s.safetyCounts[a] || 0) || a.localeCompare(b))
            .map((k) => `${k}=${s.safetyCounts[k]}`);
          lines.push(`- Risk-tier safety: ${parts.join(", ")}`);
        }
        if (s.avgActionability != null) lines.push(`- Avg actionability: **${s.avgActionability.toFixed(2)}/5**`);
        if (s.avgHandoff != null) lines.push(`- Avg handoff quality: **${s.avgHandoff.toFixed(2)}/5**`);
        lines.push("");
      });
  }

  return lines.join("\n").trim() + "\n";
}

function renderReviewSummary() {
  const textEl = $("reviewSummaryText");
  const mdEl = $("reviewSummaryMd");
  if (!textEl && !mdEl) return;

  const reviews = loadStoredReviews();
  const s = summarizeReviews(reviews);
  const md = reviewSummaryMarkdown(reviews, { maxQuotes: 3 });

  if (mdEl) mdEl.textContent = md.trim() ? md : "—";

  if (!textEl) return;
  if (!s.nReviews) {
    textEl.innerHTML = `<div class="small muted">No saved reviews yet.</div>`;
    return;
  }

  const bits = [];
  bits.push(`<div class="mono">reviews=${escapeHtml(String(s.nReviews))} • cases=${escapeHtml(String(s.nCases))}</div>`);
  if (s.reviewerRoles.length) bits.push(`<div class="small muted">roles: ${escapeHtml(s.reviewerRoles.join(", "))}</div>`);

  const safetyKeys = Object.keys(s.safetyCounts || {});
  if (safetyKeys.length) {
    const parts = safetyKeys
      .sort((a, b) => (s.safetyCounts[b] || 0) - (s.safetyCounts[a] || 0) || a.localeCompare(b))
      .map((k) => `${k}=${s.safetyCounts[k]}`);
    bits.push(`<div class="small muted">risk_tier_safety: ${escapeHtml(parts.join(" • "))}</div>`);
  }
  if (s.avgActionability != null) bits.push(`<div class="small muted">avg_actionability: ${escapeHtml(s.avgActionability.toFixed(2))}/5</div>`);
  if (s.avgHandoff != null) bits.push(`<div class="small muted">avg_handoff_quality: ${escapeHtml(s.avgHandoff.toFixed(2))}/5</div>`);

  textEl.innerHTML = bits.join("");
}

function buildWriteupParagraph() {
  const reviews = loadStoredReviews();
  const nReviews = reviews.length;
  const caseIds = new Set();
  const setCounts = {};
  (reviews || []).forEach((r) => {
    const cid = String(r?.case_id || "").trim();
    if (cid) caseIds.add(cid);
    const s = String(r?.vignette_set || "standard").trim() || "standard";
    setCounts[s] = (setCounts[s] || 0) + 1;
  });
  const nCases = caseIds.size;
  const setList = Object.keys(setCounts).sort();
  const role = String($("reviewRole")?.value || "").trim();
  const setting = String($("reviewSetting")?.value || "").trim();
  const date = String($("reviewDate")?.value || "").trim();

  // Strict no-fabrication guard: if nothing was recorded, do not imply that a review happened.
  if (!nReviews) {
    return (
      "Clinician review (qualitative): We provide tooling to collect a lightweight clinician review without PHI, " +
      "but we did not record a clinician review for this submission; therefore we report no clinician feedback here."
    );
  }

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
  const whoParen = bits.length ? ` (${bits.join(", ")})` : "";
  const when = date ? ` on ${date}` : "";
  const setPhrase = setList.length ? ` (sets: ${setList.join(", ")})` : "";

  const lines = [];
  lines.push(
    `Clinician review (qualitative): A clinician reviewer${whoParen} qualitatively reviewed ClinicaFlow outputs${when} on synthetic vignette regression cases (n=${nCases})${setPhrase}.`,
  );
  if (noted.length) lines.push(`Key notes: ${noted.map((x) => `“${x}”`).join("; ")}.`);
  if (helpful) lines.push(`Most helpful aspect: “${helpful}”.`);
  if (improve) lines.push(`Top improvement suggestion: “${improve}”.`);

  const summary = summarizeReviews(reviews);
  const safetyKeys = Object.keys(summary.safetyCounts || {});
  if (safetyKeys.length || summary.avgActionability != null || summary.avgHandoff != null) {
    const parts = [];
    if (safetyKeys.length) {
      const safetyBits = safetyKeys
        .sort((a, b) => (summary.safetyCounts[b] || 0) - (summary.safetyCounts[a] || 0) || a.localeCompare(b))
        .map((k) => `${k}=${summary.safetyCounts[k]}`)
        .join(", ");
      parts.push(`risk_tier_safety: ${safetyBits}`);
    }
    if (summary.avgActionability != null) parts.push(`avg_actionability=${summary.avgActionability.toFixed(2)}/5`);
    if (summary.avgHandoff != null) parts.push(`avg_handoff_quality=${summary.avgHandoff.toFixed(2)}/5`);
    if (parts.length) lines.push(`Ratings (from recorded reviews): ${parts.join(" • ")}.`);
  }
  lines.push(
    "This feedback is qualitative UX/safety input only and does not substitute for site-specific clinical validation. " +
      "We do not fabricate reviewer feedback; exportable review notes are generated from recorded inputs.",
  );

  return lines.join(" ");
}

function updateReviewParagraph() {
  const out = $("reviewParagraph");
  if (!out) return;
  out.textContent = buildWriteupParagraph();
}

async function demoLoadAndRun(caseId, opts) {
  await loadVignetteById(caseId, opts);
  await runTriage();
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

  $("privacyReset")?.addEventListener("click", async () => {
    const ok = confirm(
      "Clear local-only demo data stored in this browser?\n\nThis clears: workspace, action checklist progress, clinician reviews, UI preferences, and the optional API key.\n\nDo not store PHI in this demo UI.",
    );
    if (!ok) return;
    await clearLocalDemoData();
    window.location.reload();
  });

  // Home tab quick actions
  $("homeStartDemo")?.addEventListener("click", () => setTab("demo"));
  $("homeGoTriage")?.addEventListener("click", () => setTab("triage"));
  $("homeGoWorkspace")?.addEventListener("click", () => setTab("workspace"));
  $("homeGoGovernance")?.addEventListener("click", () => setTab("governance"));
  $("homeGoOps")?.addEventListener("click", async () => {
    setTab("ops");
    await refreshOps();
  });
  $("homeRunCritical")?.addEventListener("click", () => demoLoadAndRun("v01_chest_pain_hypotension"));
  $("homeRunAdversarial")?.addEventListener("click", () =>
    demoLoadAndRun("a01_cp_abbrev_hypotension", { set: "adversarial" }),
  );
  $("homeDownloadAudit")?.addEventListener("click", () => downloadAuditBundle(true));
  $("homeDownloadReport")?.addEventListener("click", () => downloadReportHtml());
  $("homeDownloadJudgePack")?.addEventListener("click", () => downloadJudgePack());
  $("homeOpenTrace")?.addEventListener("click", () => setTab("triage"));

  // Welcome modal
  $("welcomeClose")?.addEventListener("click", () => closeWelcomeModal());
  $("welcomeStartDemo")?.addEventListener("click", () => {
    setTab("demo");
    closeWelcomeModal();
  });
  $("welcomeRunTriage")?.addEventListener("click", () => {
    setTab("triage");
    closeWelcomeModal();
  });
  $("welcomeOpenWorkspace")?.addEventListener("click", () => {
    setTab("workspace");
    closeWelcomeModal();
  });
  $("welcomeModal")?.addEventListener("click", (ev) => {
    const isBackdrop = ev?.target?.dataset?.close === "1";
    if (isBackdrop) closeWelcomeModal();
  });

  $("loadPreset").addEventListener("click", () => loadPreset().catch((e) => setError("intakeError", e)));
  $("runTriage").addEventListener("click", () => runTriage());
  $("copyResult").addEventListener("click", () => copyResult());
  $("copyHandoff").addEventListener("click", () => copyText($("handoff").textContent || "", "Copied handoff."));
  $("copyPatient").addEventListener("click", () => copyText($("patientSummary").textContent || "", "Copied precautions."));
  $("copyNote")?.addEventListener("click", () => {
    if (!state.lastIntake || !state.lastResult) return;
    const md = buildNoteMarkdown(state.lastIntake, state.lastResult, state.lastActionChecklist);
    copyText(md, "Copied note.md");
  });
  $("downloadNote").addEventListener("click", () => {
    if (!state.lastIntake || !state.lastResult) return;
    const md = buildNoteMarkdown(state.lastIntake, state.lastResult, state.lastActionChecklist);
    const req = state.lastRequestId || state.lastResult.request_id || "run";
    downloadText(`clinicaflow_note_${req}.md`, md, "text/markdown");
    setText("statusLine", "Downloaded note.md");
  });
  $("downloadFhir")?.addEventListener("click", () => downloadFhirBundle());
  $("buildFhirPreview")?.addEventListener("click", () => buildFhirPreview());
  $("downloadReport")?.addEventListener("click", () => downloadReportHtml());
  $("printReport")?.addEventListener("click", () => printReportHtml());
  $("downloadRedacted").addEventListener("click", () => downloadAuditBundle(true));
  $("downloadFull").addEventListener("click", () => downloadAuditBundle(false));
  $("downloadJudgePack")?.addEventListener("click", () => downloadJudgePack());

  $("applyJsonToForm").addEventListener("click", () => {
    try {
      const beforeImages = [...(state.imageDataUrls || [])];
      const intake = JSON.parse($("intakeJson").value || "{}");
      fillFormFromIntake(intake);
      // If JSON doesn't explicitly include images, preserve current uploads.
      if (!("image_data_urls" in (intake || {})) && !("images" in (intake || {}))) {
        setImages(beforeImages);
      }
      updatePhiWarning(intake);
      setText("statusLine", "Applied JSON to form.");
      setError("intakeError", "");
    } catch (e) {
      setError("intakeError", e);
    }
  });

  $("updateJsonFromForm").addEventListener("click", () => {
    try {
      const intake = buildIntakeFromForm();
      $("intakeJson").value = fmtJson(intakeForJsonView(intake));
      updatePhiWarning(intake);
      setText("statusLine", "Updated JSON from form.");
      setError("intakeError", "");
    } catch (e) {
      setError("intakeError", e);
    }
  });

  $("imageFiles")?.addEventListener("change", async (ev) => {
    try {
      const files = ev?.target?.files || [];
      await addUploadedImages(files);
      setText("statusLine", "Images added.");
    } catch (e) {
      setError("intakeError", e);
    } finally {
      try {
        ev.target.value = "";
      } catch (e) {
        // ignore
      }
    }
  });

  $("runSynthetic")?.addEventListener("click", () => runSynthetic());
  $("copySyntheticMd")?.addEventListener("click", () => {
    const md = String(state.lastSynthetic?.markdown || $("syntheticMd")?.textContent || "").trim();
    if (!md) return;
    copyText(md, "Copied synthetic benchmark markdown.");
  });
  $("downloadSyntheticMd")?.addEventListener("click", () => {
    const md = String(state.lastSynthetic?.markdown || $("syntheticMd")?.textContent || "").trim();
    if (!md) return;
    downloadText("synthetic_proxy_benchmark.md", md + "\n", "text/markdown; charset=utf-8");
    setText("statusLine", "Downloaded synthetic_proxy_benchmark.md");
  });

  $("runBench").addEventListener("click", () => runBench());
  $("downloadBench").addEventListener("click", () => downloadBench());
  $("copyBenchMd")?.addEventListener("click", () => {
    if (!state.lastBench) return;
    copyText(benchMarkdownTable(state.lastBench.summary), "Copied markdown table.");
  });
  $("downloadBenchMd")?.addEventListener("click", () => {
    if (!state.lastBench) return;
    downloadText("vignette_benchmark.md", benchMarkdownTable(state.lastBench.summary), "text/markdown; charset=utf-8");
    setText("statusLine", "Downloaded vignette_benchmark.md");
  });
  $("downloadFailureMd")?.addEventListener("click", () => {
    if (!state.lastBench) return;
    downloadFailurePacketMd();
  });
  ["filterMismatch", "filterUnder", "filterOver"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("change", () => {
      if (!state.lastBench) return;
      renderBenchCases(state.lastBench.per_case);
    });
  });

  // Governance tab
  $("govRunBench")?.addEventListener("click", () => runBenchSet($("govBenchSet")?.value || "mega", $("govStatus")));
  $("govDownloadBench")?.addEventListener("click", () => downloadBench());
  $("govDownloadFailure")?.addEventListener("click", () => {
    if (!state.lastBench) return;
    downloadFailurePacketMd();
  });
  $("govDownloadMd")?.addEventListener("click", () => downloadGovernanceMd());

  // Rules tab
  $("rulesRefresh")?.addEventListener("click", () => loadSafetyRules());
  $("rulesDownloadJson")?.addEventListener("click", () => downloadSafetyRulesJson());
  const rulesFilter = $("rulesFilter");
  if (rulesFilter) {
    rulesFilter.addEventListener("input", () => renderRulesTab());
    rulesFilter.addEventListener("change", () => renderRulesTab());
  }

  // Ops tab
  $("opsRefresh")?.addEventListener("click", () => refreshOps());
  $("opsSmoke")?.addEventListener("click", () => runOpsSmokeCheck());
  $("opsDownloadMd")?.addEventListener("click", () => downloadOpsReportMd());
  const opsAuto = $("opsAuto");
  if (opsAuto) {
    opsAuto.addEventListener("change", () => {
      if (opsAuto.checked) startOpsAutoRefresh();
      else stopOpsAutoRefresh();
    });
  }
  $("authSave")?.addEventListener("click", () => {
    const input = $("authApiKey");
    const status = $("authStatus");
    if (!input) return;
    saveAuthToStorage(input.value);
    input.value = "";
    if (status) status.textContent = state.auth.apiKey ? "Saved for this tab session." : "Cleared.";
  });
  $("authClear")?.addEventListener("click", () => {
    const input = $("authApiKey");
    const status = $("authStatus");
    saveAuthToStorage(null);
    if (input) input.value = "";
    if (status) status.textContent = "Cleared.";
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
      const setName = String($("reviewSet")?.value || "standard").trim() || "standard";

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
        vignette_set: setName,
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
      renderReviewSummary();
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

  const reviewCopySummary = $("reviewCopySummary");
  if (reviewCopySummary)
    reviewCopySummary.addEventListener("click", () => {
      const reviews = loadStoredReviews();
      const md = reviewSummaryMarkdown(reviews, { maxQuotes: 3 });
      copyText(md, "Copied summary.md");
    });

  const reviewDownloadSummary = $("reviewDownloadSummary");
  if (reviewDownloadSummary)
    reviewDownloadSummary.addEventListener("click", () => {
      const reviews = loadStoredReviews();
      const md = reviewSummaryMarkdown(reviews, { maxQuotes: 3 });
      downloadText("clinician_review_summary.md", md, "text/markdown");
      setText("statusLine", "Downloaded clinician_review_summary.md");
    });

  const reviewImportJson = $("reviewImportJson");
  const reviewImportFile = $("reviewImportFile");
  if (reviewImportJson && reviewImportFile) {
    reviewImportJson.addEventListener("click", () => reviewImportFile.click());
    reviewImportFile.addEventListener("change", async () => {
      const file = reviewImportFile.files?.[0];
      if (file) await reviewImportFromFile(file);
      try {
        reviewImportFile.value = "";
      } catch (e) {
        // ignore
      }
    });
  }

  const reviewReset = $("reviewReset");
  if (reviewReset)
    reviewReset.addEventListener("click", () => {
      const ok = confirm("Reset local clinician reviews? This cannot be undone.");
      if (!ok) return;
      saveStoredReviews([]);
      renderReviewTable();
      updateReviewParagraph();
      renderReviewSummary();
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

  const reviewSetSel = $("reviewSet");
  if (reviewSetSel)
    reviewSetSel.addEventListener("change", async () => {
      await loadReviewCases();
      // Reset the view since the case list changed.
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
  $("wsViewBoard")?.addEventListener("click", () => {
    setWorkspaceView("board");
    renderWorkspaceTable();
  });
  $("wsViewTable")?.addEventListener("click", () => {
    setWorkspaceView("table");
    renderWorkspaceTable();
  });

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
    workspaceAdd({ intake: state.lastIntake, result: state.lastResult, checklist: state.lastActionChecklist });
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

  const wsSearch = $("wsSearch");
  if (wsSearch) {
    wsSearch.addEventListener("input", () => renderWorkspaceTable());
    wsSearch.addEventListener("change", () => renderWorkspaceTable());
  }
  $("wsFilterStatus")?.addEventListener("change", () => renderWorkspaceTable());
  $("wsSort")?.addEventListener("change", () => renderWorkspaceTable());
  $("wsDownloadHandoff")?.addEventListener("click", () => workspaceDownloadShiftHandoff());

  $("wsUpdateStatus")?.addEventListener("click", () => {
    setError("wsError", "");
    const item = workspaceSelectedItem();
    if (!item) {
      setError("wsError", "Select an item first.");
      return;
    }
    const sel = $("wsStatusSelect");
    const nextStatus = normalizeWorkspaceStatus(sel?.value, Boolean(item.result));
    workspaceUpdateItem(item.id, { status: nextStatus });
    setText("wsStatus", `Updated status: ${nextStatus}`);
  });

  $("wsRunTriage")?.addEventListener("click", () => {
    const item = workspaceSelectedItem();
    if (!item) return;
    workspaceRunTriage(item);
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
    $("intakeJson").value = fmtJson(intakeForJsonView(intake));
    setTab("triage");
    setMode("form");
    if (item.result) {
      if (item.checklist && item.result.request_id) {
        saveActionChecklist(item.result.request_id, item.checklist);
      }
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

  $("wsDownloadReport")?.addEventListener("click", () => {
    setError("wsError", "");
    const item = workspaceSelectedItem();
    if (!item || !item.result) {
      setError("wsError", "Select a saved run (with result) first.");
      return;
    }
    workspaceDownloadReport(item);
  });

  $("wsDownloadNote")?.addEventListener("click", () => {
    setError("wsError", "");
    const item = workspaceSelectedItem();
    if (!item || !item.result) {
      setError("wsError", "Select a saved run (with result) first.");
      return;
    }
    workspaceDownloadNote(item);
  });

  // About tab
  $("loadPolicyPack")?.addEventListener("click", () => loadPolicyPack());
  $("copyPolicyPack")?.addEventListener("click", () => {
    if (!state.policyPack) return;
    copyText(fmtJson(state.policyPack), "Copied policy pack JSON.");
  });

  // Demo runbook
  $("demoCritical")?.addEventListener("click", () => demoLoadAndRun("v01_chest_pain_hypotension"));
  $("demoNeuro")?.addEventListener("click", () => demoLoadAndRun("v05_slurred_speech_weakness"));
  $("demoRoutine")?.addEventListener("click", () => demoLoadAndRun("v21_sore_throat_routine"));
  $("demoDirectorStart")?.addEventListener("click", () => directorStart());
  $("demoSynthetic")?.addEventListener("click", async () => {
    setTab("regression");
    await runSynthetic();
  });
  $("demoRegression")?.addEventListener("click", async () => {
    setTab("regression");
    await runBench();
  });
  $("demoGoOps")?.addEventListener("click", async () => {
    setTab("ops");
    await refreshOps();
  });
  $("demoGoGovernance")?.addEventListener("click", () => setTab("governance"));
  $("demoGovMega")?.addEventListener("click", async () => {
    setTab("governance");
    if ($("govBenchSet")) $("govBenchSet").value = "mega";
    await runBenchSet("mega", $("govStatus"));
  });
  $("demoGovDownload")?.addEventListener("click", async () => {
    setTab("governance");
    await downloadGovernanceMd();
  });
  $("demoAdversarial")?.addEventListener("click", () => demoLoadAndRun("a01_cp_abbrev_hypotension", { set: "adversarial" }));
  $("demoGoReview")?.addEventListener("click", () => setTab("review"));
  $("demoGoWorkspace")?.addEventListener("click", () => setTab("workspace"));
  $("demoDownloadAudit")?.addEventListener("click", () => downloadAuditBundle(true));
  $("demoDownloadFhir")?.addEventListener("click", () => downloadFhirBundle());
  $("demoDownloadReport")?.addEventListener("click", () => downloadReportHtml());
  $("demoSaveWorkspace")?.addEventListener("click", () => {
    if (!state.lastIntake || !state.lastResult) return;
    workspaceAdd({ intake: state.lastIntake, result: state.lastResult, checklist: state.lastActionChecklist });
    setTab("workspace");
  });

  // Director mode
  $("directorToggle")?.addEventListener("click", () => directorToggle());
  $("directorEnd")?.addEventListener("click", () => directorEnd());
  $("directorBack")?.addEventListener("click", () => directorBack());
  $("directorNext")?.addEventListener("click", () => directorNext());
  $("directorDo")?.addEventListener("click", () => directorDoStep());
  $("directorCopySay")?.addEventListener("click", async () => {
    await copyText($("directorSay")?.textContent || "", "Copied teleprompter.");
  });
  document.addEventListener("keydown", directorHandleHotkeys);
}

async function init() {
  const params = new URLSearchParams(window.location.search || "");
  const wantReset = ["1", "true", "yes"].includes(String(params.get("reset") || "").trim().toLowerCase());
  const wantDirector = ["1", "true", "yes"].includes(String(params.get("director") || "").trim().toLowerCase());
  const wantWelcome = ["1", "true", "yes"].includes(String(params.get("welcome") || "").trim().toLowerCase());

  if (wantReset) {
    await clearLocalDemoData();
    try {
      params.delete("reset");
      const next = params.toString();
      const url = `${window.location.pathname}${next ? `?${next}` : ""}${window.location.hash || ""}`;
      history.replaceState(null, "", url);
    } catch (e) {
      // ignore
    }
  }

  wireEvents();
  window.addEventListener("hashchange", () => handleHashChange());
  setTab(loadInitialTab());
  setMode(loadInitialMode());
  setWorkspaceView(loadWorkspaceView());
  if ($("govBenchSet")) $("govBenchSet").value = "mega";
  if ($("opsAuto")) $("opsAuto").checked = false;
  await registerServiceWorker();
  loadAuthFromStorage();
  updateAuthBadge();
  renderGovernance(null, null);
  renderRulesTab();
  renderOpsSmokePlaceholder("Not run.");
  await refreshOps();
  await loadPresets();
  await loadPreset();
  await loadReviewCases();
  setReviewIdentityDefaults();
  renderReviewTable();
  renderReviewSummary();
  updateReviewParagraph();
  renderWorkspaceTable();
  renderHome();
  renderTraceMini([]);

  if (wantDirector) {
    directorStart();
  } else if (wantWelcome) {
    show("welcomeModal", true);
  } else {
    maybeShowWelcomeModal();
  }
}

init().catch((e) => {
  setError("runError", e);
});
