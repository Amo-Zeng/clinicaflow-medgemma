/* ClinicaFlow service worker (no deps). */

// IMPORTANT: This cache name must change whenever bundled UI assets change,
// otherwise existing installs can remain stuck on stale JS/CSS indefinitely.
// Keep it human-readable so it's easy to instruct judges/users to clear it.
const CACHE_NAME = "clinicaflow-static-0.1.4";

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

  // Stale-while-revalidate for static assets (prevents "stuck on old UI").
  if (url.pathname.startsWith("/static/")) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(req);

      const fetchPromise = fetch(req)
        .then((resp) => {
          if (resp && resp.ok) cache.put(req, resp.clone());
          return resp;
        })
        .catch(() => null);

      if (cached) {
        event.waitUntil(fetchPromise);
        return cached;
      }

      const resp = await fetchPromise;
      return resp || new Response("offline", { status: 503, statusText: "offline" });
    })());
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
