/* eslint-disable no-console */
/* global WebSocket, fetch */

"use strict";

const DEVTOOLS_HTTP = "http://127.0.0.1:9222";
const STREAMLIT_DEPLOY_URL = "https://share.streamlit.io/deploy";
const GITHUB_APP_URL = "https://github.com/Amo-Zeng/clinicaflow-medgemma/blob/main/streamlit_app.py";
const DESIRED_SLUG = "clinicaflow-medgemma-console-2026";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function createTarget(url) {
  const resp = await fetch(`${DEVTOOLS_HTTP}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(`createTarget failed: ${resp.status} ${body}`);
  }
  return await resp.json();
}

async function closeTarget(id) {
  try {
    // `/json/close/<id>` exists on most Chrome builds (GET).
    await fetch(`${DEVTOOLS_HTTP}/json/close/${id}`).catch(() => {});
  } catch {
    // ignore
  }
}

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let nextId = 0;
  const pending = new Map();

  ws.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!payload.id) {
      return;
    }
    const waiter = pending.get(payload.id);
    if (!waiter) {
      return;
    }
    pending.delete(payload.id);
    if (payload.error) {
      waiter.reject(new Error(JSON.stringify(payload.error)));
      return;
    }
    waiter.resolve(payload.result);
  };

  async function send(method, params = undefined) {
    nextId += 1;
    const id = nextId;
    const message = { id, method };
    if (params !== undefined) {
      message.params = params;
    }
    ws.send(JSON.stringify(message));
    return await new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (!pending.has(id)) return;
        pending.delete(id);
        reject(new Error(`Timeout waiting for ${method}`));
      }, 60_000);
    });
  }

  return { ws, send };
}

async function evalInPage(send, expression, { returnByValue = true, awaitPromise = false } = {}) {
  const res = await send("Runtime.evaluate", {
    expression,
    returnByValue,
    awaitPromise,
  });
  if (res.exceptionDetails) {
    const detail = res.exceptionDetails.exception?.description || res.exceptionDetails.text || "Runtime.evaluate exception";
    throw new Error(detail);
  }
  return res.result?.value;
}

async function waitForReady(send, { timeoutMs = 60_000 } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const state = await evalInPage(send, "document.readyState");
    if (state === "complete") {
      return;
    }
    await sleep(500);
  }
  throw new Error("Timeout waiting for document.readyState=complete");
}

async function deployStreamlitApp(send) {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url: STREAMLIT_DEPLOY_URL });
  await waitForReady(send, { timeoutMs: 90_000 });

  // Best-effort: click "Paste GitHub URL" if the button exists.
  await evalInPage(
    send,
    `(() => {
      const norm = (s) => String(s || "").replace(/\\s+/g, " ").trim().toLowerCase();
      const btn = Array.from(document.querySelectorAll("button")).find((b) => norm(b.textContent) === "paste github url");
      if (btn && !btn.disabled) btn.click();
      return true;
    })()`,
  );

  // Fill GitHub URL + slug using heuristics (placeholder / aria-label).
  const filled = await evalInPage(
    send,
    `(() => {
      function setNativeValue(el, value) {
        const proto = Object.getPrototypeOf(el);
        const desc = Object.getOwnPropertyDescriptor(proto, "value");
        if (desc && desc.set) desc.set.call(el, value);
        else el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }

      const githubUrl = ${JSON.stringify(GITHUB_APP_URL)};
      const desiredSlug = ${JSON.stringify(DESIRED_SLUG)};

      const inputs = Array.from(document.querySelectorAll("input")).filter((i) => !i.disabled);
      const githubInput = inputs.find((i) => (i.placeholder || "").includes("github.com/username/repository"))\n+        || inputs.find((i) => (i.getAttribute("aria-label") || "").toLowerCase().includes("github url"))\n+        || inputs.find((i) => (i.value || "").includes("github.com/"));\n+\n+      if (!githubInput) return { ok: false, error: "GitHub URL input not found" };\n+      setNativeValue(githubInput, githubUrl);\n+\n+      const slugInput = inputs.find((i) => (i.getAttribute("aria-label") || \"\").toLowerCase().includes(\"app url\"))\n+        || inputs.find((i) => (i.placeholder || \"\").toLowerCase().includes(\"app url\"));\n+      if (slugInput) {\n+        setNativeValue(slugInput, desiredSlug);\n+      }\n+\n+      return {\n+        ok: true,\n+        githubValue: githubInput.value,\n+        slugValue: slugInput ? slugInput.value : \"\",\n+      };\n+    })()`,
  );

  if (!filled || !filled.ok) {
    throw new Error(`Failed to fill Streamlit deploy form: ${filled ? filled.error : "unknown"}`);
  }

  // Click "Deploy". If it is disabled, wait a bit for form validation.
  const clickResult = await evalInPage(
    send,
    `(() => {
      const norm = (s) => String(s || "").replace(/\\s+/g, " ").trim().toLowerCase();
      const buttons = Array.from(document.querySelectorAll("button"));\n+      const deploy = buttons.find((b) => norm(b.textContent) === "deploy");\n+      if (!deploy) return { ok: false, error: "Deploy button not found" };\n+      return { ok: true, disabled: !!deploy.disabled };\n+    })()`,
  );

  if (!clickResult.ok) {
    throw new Error(`Cannot deploy: ${clickResult.error}`);
  }

  if (clickResult.disabled) {
    await sleep(2000);
  }

  const clicked = await evalInPage(
    send,
    `(() => {\n+      const norm = (s) => String(s || \"\").replace(/\\s+/g, \" \").trim().toLowerCase();\n+      const deploy = Array.from(document.querySelectorAll(\"button\")).find((b) => norm(b.textContent) === \"deploy\");\n+      if (!deploy || deploy.disabled) return { ok: false, error: \"Deploy button disabled\" };\n+      deploy.click();\n+      return { ok: true };\n+    })()`,
  );

  if (!clicked.ok) {
    throw new Error(`Deploy click failed: ${clicked.error}`);
  }

  // Return the desired slug (may still change server-side; we re-check later via curl).
  return filled.slugValue || DESIRED_SLUG;
}

async function main() {
  const target = await createTarget("about:blank");
  const targetId = target.id;
  try {
    const { ws, send } = await connect(target.webSocketDebuggerUrl);
    try {
      const slug = await deployStreamlitApp(send);
      console.log(JSON.stringify({ ok: true, slug }, null, 2));
    } finally {
      ws.close();
    }
  } finally {
    await closeTarget(targetId);
  }
}

main().catch((err) => {
  console.error(String(err && err.message ? err.message : err));
  process.exit(1);
});
