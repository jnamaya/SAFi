// sw.js - minimal offline + background refresh
const STATIC_CACHE = 'safi-static-v1';
const API_CACHE = 'safi-api-v1';

// App shell to precache (adjust paths if your structure differs)
// In sw.js (at the root of your project)
const APP_SHELL = [
  './',              // The root of the application (where sw.js is now located)
  'index.html',      // index.html is in the same directory
  'css/styles.css',
  'js/main.js',      // Target the js/ folder directly
  'js/ui.js',
  'js/api.js',
  'js/cache.js',
  'js/utils.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => 
      Promise.all(keys.filter(k => ![STATIC_CACHE, API_CACHE].includes(k)).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin requests for offline shell and GET JSON API
  const sameOrigin = url.origin === location.origin;

  // App shell: cache-first
  if (sameOrigin && APP_SHELL.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then(cached => cached || fetch(req))
    );
    return;
  }

  // JSON GET API: network-first with cache fallback
  const isJSONGet = req.method === 'GET' && (req.headers.get('accept') || '').includes('application/json');
  if (isJSONGet) {
    event.respondWith((async () => {
      try {
        const net = await fetch(req);
        const copy = net.clone();
        const cache = await caches.open(API_CACHE);
        cache.put(req, copy);
        return net;
      } catch (e) {
        const cached = await caches.match(req);
        if (cached) return cached;
        throw e;
      }
    })());
    return;
  }

  // Everything else: pass-through
});