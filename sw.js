// Service worker for the 22K Gold Price PWA.
//
// Architecture (see README.md):
//   PHONE/PWA -> same-origin data/live.json -> GitHub Pages
//   GitHub Actions -> scrapes LiveChennai + GoodReturns -> updates data/*.json twice daily
//
// That means data/*.json must NEVER be served cache-first -- the whole
// point of this design is that opening the app always sees the latest
// committed rate. Only the app shell (HTML/CSS/JS/icons) is safe to
// cache-first, since it only changes on deploy.

const CACHE_VERSION = "v1";
const CACHE_NAME = `gold-rate-shell-${CACHE_VERSION}`;

// App shell: static, versioned by deploy, safe to cache-first.
const SHELL_ASSETS = [
  "./",
  "./index.html",
  "./icon.svg",
  "./manifest.webmanifest",
];

// Data files: updated by GitHub Actions independently of deploys.
// Always go to the network first so the app reflects the latest
// committed rate; only fall back to cache if the network is
// unavailable (offline).
const DATA_PATH_SEGMENT = "/data/";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only handle same-origin GET requests; let everything else
  // (cross-origin, POST, etc.) pass through untouched.
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Data files: network-first, cache as a fallback for offline use.
  // Never let a cached copy silently win over a fresh fetch.
  if (url.pathname.includes(DATA_PATH_SEGMENT)) {
    event.respondWith(
      fetch(request, { cache: "no-store" })
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // App shell: cache-first for speed and offline support, with a
  // network fallback that refreshes the cache for next time.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => cached);

      return cached || network;
    })
  );
});
