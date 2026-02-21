/* ClinicaFlow service worker (no deps). */

const CACHE_NAME = "clinicaflow-static-v1";

const STATIC_ASSETS = [
  "/",
  "/static/app.css",
  "/static/app.js",
  "/static/icon.svg",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (!req) return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Cache-first for static assets.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return resp;
        });
      }),
    );
    return;
  }

  // Network-first for HTML navigation; fall back to cached "/" for offline demos.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/", copy));
          return resp;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Default: network (do not cache API responses).
});

