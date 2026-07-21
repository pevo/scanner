// Plate Scanner service worker: offline-first for models/runtime, network-first for pages.
// Also injects the cross-origin isolation headers (COOP/COEP/CORP) onto every
// response it serves. serve_https.py already sends them, but a service-worker-
// controlled navigation on WebKit/iOS can be served from cache or otherwise not
// carry them through — which leaves the page NOT cross-origin isolated, so
// SharedArrayBuffer (and thus multi-threaded wasm) stays disabled. Re-stamping
// the headers here guarantees isolation regardless of the server or the cache
// (the well-known "coi-serviceworker" technique).
const CACHE = 'alpr-v17';
const SHELL = ['./index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png',
               './geocode-us.json'];

// Return a copy of `res` with the isolation headers set. Skips opaque responses
// (cross-origin no-cors) whose body/headers can't be read or rebuilt.
function withIsolation(res) {
  if (!res || res.type === 'opaque' || res.type === 'opaqueredirect' || res.status === 0) return res;
  const h = new Headers(res.headers);
  h.set('Cross-Origin-Opener-Policy', 'same-origin');
  h.set('Cross-Origin-Embedder-Policy', 'require-corp');
  h.set('Cross-Origin-Resource-Policy', 'same-origin');
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const isPage = req.mode === 'navigate' || url.pathname.endsWith('.html');

  if (isPage) {
    // network-first so page updates propagate; cache as offline fallback.
    // withIsolation() re-stamps COOP/COEP so the document is cross-origin
    // isolated even when this response comes from cache.
    e.respondWith(
      fetch(req).then(res => {
        caches.open(CACHE).then(c => c.put(req, res.clone()));
        return withIsolation(res);
      }).catch(() => caches.match(req).then(r => r ? withIsolation(r) : fetch(req)))
    );
    return;
  }

  // models, wasm, runtime, icons: cache-first (they are versioned by filename).
  // Same-origin assets are re-stamped too (harmless, and keeps CORP present so
  // COEP:require-corp never blocks them).
  e.respondWith(
    caches.match(req).then(hit => hit ? withIsolation(hit) : fetch(req).then(res => {
      if (res.ok && (url.origin === location.origin || url.hostname === 'cdn.jsdelivr.net')) {
        caches.open(CACHE).then(c => c.put(req, res.clone()));
      }
      return url.origin === location.origin ? withIsolation(res) : res;
    }))
  );
});
