/**
 * offline-manager.js
 * Handles GET caching, POST/PUT/DELETE queuing, and reconnect flush.
 * PWA client (Capacitor retired 2026-08-19): online state comes from the
 * browser's online/offline events and navigator.onLine.
 */

// Simple storage abstraction. Uses localStorage everywhere for simplicity.
const storage = {
  async get(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
  },
  async set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { }
  },
  async remove(key) {
    try { localStorage.removeItem(key); } catch { }
  }
};

const QUEUE_KEY = 'safi_offline_queue_v1';
const CACHE_KEY_PREFIX = 'safi_cache_v1:'; // cache per URL
let isOnline = true;
// Offline/PWA kill switch (Phase F): org admins can forbid local copies of
// org content. When false, nothing is cached or queued, and everything this
// module (or the service worker) previously persisted is purged.
let offlineAllowed = true;

async function setOfflineAllowed(allowed) {
  offlineAllowed = allowed !== false;
  if (offlineAllowed) return;
  // localStorage: GET cache + write queue
  try {
    const doomed = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (k.startsWith(CACHE_KEY_PREFIX) || k.startsWith('safi_cache:') || k === QUEUE_KEY)) doomed.push(k);
    }
    doomed.forEach(k => localStorage.removeItem(k));
  } catch { }
  // Service-worker caches (app shell + GET API cache) and the worker itself
  try {
    if (typeof caches !== 'undefined') {
      const names = await caches.keys();
      await Promise.all(names.filter(n => n.startsWith('safi-')).map(n => caches.delete(n)));
    }
  } catch { }
  try {
    const regs = await navigator.serviceWorker?.getRegistrations?.();
    if (regs) for (const r of regs) await r.unregister();
  } catch { }
}

/* ---------- Helpers ---------- */

function cacheKeyForRequest(req) {
  // Cache GETs by URL including query params
  return `${CACHE_KEY_PREFIX}${req.url}`;
}

async function readRequestBodyOnce(req) {
  // Clone to avoid consuming the original stream
  try { return await req.clone().text(); } catch { return ''; }
}

function headersToObject(headers) {
  const out = {};
  try {
    for (const [k, v] of headers.entries()) out[k] = v;
  } catch { }
  return out;
}

// Every API error handler below threw the raw response body as the Error
// message, so a Flask `jsonify({"error": "..."})` 4xx landed in a toast as
// the literal JSON text — readable to nobody. Every endpoint in this app
// uses that same {"error": "..."} shape, so unwrapping it once here fixes
// every catch-block toast that does `err.message || 'X failed'`, not just
// the caller that happened to notice.
function apiErrorMessage(rawText, fallback) {
  if (rawText) {
    try {
      const parsed = JSON.parse(rawText);
      if (parsed && typeof parsed.error === 'string' && parsed.error) return parsed.error;
    } catch { /* not JSON (e.g. an HTML error page) — fall through to raw text */ }
  }
  return rawText || fallback;
}

async function loadQueue() {
  return (await storage.get(QUEUE_KEY)) || [];
}

async function saveQueue(queue) {
  await storage.set(QUEUE_KEY, queue);
}

/* ---------- Public API ---------- */

/**
 * Initialize network listeners. Call once on app boot.
 */
async function initNetworkListener() {
  // Window events for web
  try {
    window.addEventListener('online', () => { isOnline = true; flushQueue(); });
    window.addEventListener('offline', () => { isOnline = false; });
  } catch { }

  isOnline = typeof navigator !== 'undefined' ? !!navigator.onLine : true;

  if (isOnline) flushQueue(); // try once at startup
}

/**
 * GET with cache. Returns { data, fromCache }
 * - Online and 2xx: stores JSON in cache and returns it.
 * - Online non-2xx: throws an error with server message if possible.
 * - Offline: returns cached data if present, else throws.
 */
async function fetchWithCache(request) {
  const key = cacheKeyForRequest(request);
  if (!isOnline) {
    const cached = offlineAllowed ? await storage.get(key) : null;
    if (cached != null) return { data: cached, fromCache: true };
    throw new Error('Offline and no cached data available');
  }

  let res;
  try {
    res = await fetch(request);
  } catch (e) {
    // If network failed but we have cache, return it
    const cached = offlineAllowed ? await storage.get(key) : null;
    if (cached != null) return { data: cached, fromCache: true };
    throw e;
  }

  if (!res.ok) {
    // Read the body as text to get the actual server error message (which might be HTML)
    const status = res.status;
    const msg = await res.clone().text().catch(() => '');

    if (status === 401) {
      // Throw a specific error that checkLoginStatus can handle.
      throw new Error(`UNAUTHORIZED: ${apiErrorMessage(msg, 'Authentication required')}`);
    }

    // For other non-2xx statuses, throw the server's error message or a generic status error
    const err = new Error(apiErrorMessage(msg, `Request failed with status ${status}`));
    err.status = status;
    throw err;
  }

  // --- CRITICAL FIX START: Check Content-Type for 2xx responses ---
  const contentType = res.headers.get('Content-Type');
  if (contentType && !contentType.includes('application/json')) {
    const htmlBody = await res.clone().text().catch(() => '');
    console.error(`Status 200/2xx, but unexpected Content-Type: ${contentType}. Body starts with: ${htmlBody.substring(0, 50)}`);
    throw new Error(`Server returned HTML for API call (status ${res.status}). Expected JSON.`);
  }
  // --- CRITICAL FIX END ---

  // Only proceed to JSON parsing if res.ok is true (status 200-299)
  try {
    const data = await res.json();
    if (offlineAllowed) await storage.set(key, data);
    return { data, fromCache: false };
  } catch (e) {
    // This catches issues like 'empty body on successful response' OR if the HTML failed to parse as JSON
    console.error(`Failed to parse successful response from ${request.url} as JSON:`, e);
    throw new Error(`Invalid server response format for status ${res.status}.`);
  }
}
/**
 * POST/PUT/DELETE with offline queue.
 * Accepts plain arguments to avoid Request stream issues.
 * Supports legacy Request object as first arg for backward compatibility (cache issues).
 * @param {string|Request} urlOrRequest
 * @param {string|FormData} [body]
 * @param {string} [method]
 * @param {Headers|Object} [headers]
 * @returns JSON response or 'QUEUED'
 */
async function postWithQueue(urlOrRequest, body, method = 'POST', headers = {}, options = {}) {
  let requestUrl, requestBody, requestMethod, requestHeaders;

  // POLYMORPHIC HANDLING: Detect if called with legacy Request object (Browser cache mismatch)
  if (typeof urlOrRequest === 'object' && typeof urlOrRequest.url === 'string') {
    console.warn("Mobile/Offline: Cache mismatch detected. Handling legacy Request object.");
    const req = urlOrRequest;
    requestUrl = req.url;
    requestMethod = req.method;
    requestHeaders = headersToObject(req.headers);
    try {
      // Attempt to read body. If it was already consumed by a failed clone, this might fail,
      // but usually 'new Request()' from api.js is fresh.
      requestBody = await req.text();
    } catch (e) {
      console.warn("Legacy Request body read failed:", e);
      requestBody = '';
    }
  } else {
    // Standard New Signature
    requestUrl = urlOrRequest;
    requestBody = body;
    requestMethod = method;
    requestHeaders = headers instanceof Headers ? headersToObject(headers) : headers;
  }

  // Prepare fetch options
  const fetchOptions = {
    method: requestMethod,
    headers: requestHeaders,
    body: requestBody,
    credentials: 'include',
    signal: options.signal // Pass the AbortSignal
  };

  if (isOnline) {
    try {
      const res = await fetch(requestUrl, fetchOptions);

      if (!res.ok) {
        if (res.status >= 400 && res.status < 500) {
          const msg = await res.text();
          const err = new Error(apiErrorMessage(msg, res.statusText));
          err.status = res.status; // Attach status code!
          throw err;
        }

        // Queue on 5xx errors or network failures (unless offline is forbidden)
        if (!offlineAllowed) {
          const msg = await res.text().catch(() => '');
          const err = new Error(apiErrorMessage(msg, res.statusText));
          err.status = res.status;
          throw err;
        }
        await queueRequest({ url: requestUrl, method: requestMethod, headers: requestHeaders, body: requestBody });
        return 'QUEUED';
      }
      return await res.json();
    } catch (e) {
      // AbortError should NOT be queued?
      if (e.name === 'AbortError') {
        throw e; // Propagate abort up
      }
      // CRITICAL FIX: Do not queue client errors (4xx)
      if (e.status && e.status >= 400 && e.status < 500) {
        throw e;
      }
      if (!offlineAllowed) throw e; // no local persistence of request bodies
      console.warn("Fetch failed, queuing:", e);
      await queueRequest({ url: requestUrl, method: requestMethod, headers: requestHeaders, body: requestBody });
      return 'QUEUED';
    }
  } else {
    if (!offlineAllowed) {
      throw new Error('You are offline. Offline mode is disabled by your organization.');
    }
    // Offline, queue immediately
    await queueRequest({ url: requestUrl, method: requestMethod, headers: requestHeaders, body: requestBody });
    return 'QUEUED';
  }
}

async function queueRequest(parts) {
  const queue = await loadQueue();
  queue.push({
    url: parts.url,
    method: parts.method,
    headers: parts.headers,
    body: parts.body,
    timestamp: Date.now()
  });
  await saveQueue(queue);
}

/**
 * Attempts to send all queued writes. Called on reconnect.
 */
async function flushQueue() {
  if (!isOnline || !offlineAllowed) return;

  let queue = await loadQueue();
  if (!queue.length) return;

  const remaining = [];
  for (const item of queue) {
    try {
      const res = await fetch(item.url, {
        method: item.method,
        headers: item.headers,
        body: item.body
      });
      if (!res.ok) {
        // CRITICAL FIX: Discard 4xx errors (Client Error). Do not retry them.
        if (res.status >= 400 && res.status < 500) {
          console.warn(`[OfflineManager] Discarding failed queue item (Status ${res.status}): ${item.url}`);
          // Do NOT push to remaining
        } else {
          // Keep it for later if server error (5xx)
          remaining.push(item);
        }
      }
      // We do not need to return anything here
    } catch {
      // Still offline or network glitch. Keep it.
      remaining.push(item);
    }
  }
  await saveQueue(remaining);
}

/* ---------- Exports ---------- */

export default {
  initNetworkListener,
  fetchWithCache,
  postWithQueue,
  setOfflineAllowed
};