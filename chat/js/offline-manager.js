/**
 * offline-manager.js
 * Handles GET caching, POST/PUT/DELETE queuing, and reconnect flush.
 * Safe for both web and Capacitor native.
 */

const Cap = typeof window !== 'undefined' ? window.Capacitor : null;
const Plugins = Cap?.Plugins || {};
const Network = Plugins?.Network; // optional
// Simple storage abstraction. Uses localStorage everywhere for simplicity.
const storage = {
  async get(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
  },
  async set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
  async remove(key) {
    try { localStorage.removeItem(key); } catch {}
  }
};

const QUEUE_KEY = 'safi_offline_queue_v1';
const CACHE_KEY_PREFIX = 'safi_cache_v1:'; // cache per URL
let isOnline = true;

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
  } catch {}
  return out;
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
  } catch {}

  // Capacitor Network plugin if present
  if (Network && typeof Network.addListener === 'function') {
    try {
      const status = await Network.getStatus();
      isOnline = !!status.connected;
      Network.addListener('networkStatusChange', (st) => {
        isOnline = !!st.connected;
        if (isOnline) flushQueue();
      });
    } catch {
      // fallback to navigator.onLine
      isOnline = typeof navigator !== 'undefined' ? !!navigator.onLine : true;
    }
  } else {
    isOnline = typeof navigator !== 'undefined' ? !!navigator.onLine : true;
  }

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
    const cached = await storage.get(key);
    if (cached != null) return { data: cached, fromCache: true };
    throw new Error('Offline and no cached data available');
  }

  let res;
  try {
    res = await fetch(request);
  } catch (e) {
    // If network failed but we have cache, return it
    const cached = await storage.get(key);
    if (cached != null) return { data: cached, fromCache: true };
    throw e;
  }

  if (!res.ok) {
    // Read the body as text to get the actual server error message (which might be HTML)
    const status = res.status;
    const msg = await res.clone().text().catch(() => '');

    if (status === 401) {
        // Throw a specific error that checkLoginStatus can handle.
        throw new Error(`UNAUTHORIZED: ${msg || 'Authentication required'}`);
    }
    
    // For other non-2xx statuses, throw the raw server message or generic status error
    throw new Error(msg || `Request failed with status ${status}`);
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
    await storage.set(key, data);
    return { data, fromCache: false };
  } catch (e) {
    // This catches issues like 'empty body on successful response' OR if the HTML failed to parse as JSON
    console.error(`Failed to parse successful response from ${request.url} as JSON:`, e);
    throw new Error(`Invalid server response format for status ${res.status}.`);
  }
}

/**
 * POST/PUT/DELETE with offline queue.
 * Returns JSON if sent now, or 'QUEUED' if stored for later.
 */
async function postWithQueue(request) {
  // Safely capture parts before we touch the network
  const bodyText = await readRequestBodyOnce(request);
  const method = request.method || 'POST';
  const headers = headersToObject(request.headers);
  const url = request.url;

  if (isOnline) {
    try {
      const res = await fetch(request);
      if (!res.ok) {
        // Queue on server error too, to avoid losing intent
        await queueRequest({ url, method, headers, bodyText });
        return 'QUEUED';
      }
      // Return JSON exactly once
      return await res.json();
    } catch {
      // Network failed, queue it
      await queueRequest({ url, method, headers, bodyText });
      return 'QUEUED';
    }
  } else {
    // Offline, queue immediately
    await queueRequest({ url, method, headers, bodyText });
    return 'QUEUED';
  }
}

/* ---------- Queue handling ---------- */

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
  if (!isOnline) return;

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
        // Keep it for later if server still unhappy
        remaining.push(item);
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
  postWithQueue
};