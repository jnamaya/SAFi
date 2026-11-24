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
const CACHE_KEY_PREFIX = 'safi_cache_v1:';
let isOnline = true;
let offlineAllowed = true;

async function setOfflineAllowed(allowed) {
  offlineAllowed = allowed !== false;
  if (offlineAllowed) return;
  try {
    const doomed = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && (k.startsWith(CACHE_KEY_PREFIX) || k.startsWith('safi_cache:') || k === QUEUE_KEY)) doomed.push(k);
    }
    doomed.forEach(k => localStorage.removeItem(k));
  } catch { }
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


function cacheKeyForRequest(req) {
  return `${CACHE_KEY_PREFIX}${req.url}`;
}

async function readRequestBodyOnce(req) {
  try { return await req.clone().text(); } catch { return ''; }
}

function headersToObject(headers) {
  const out = {};
  try {
    for (const [k, v] of headers.entries()) out[k] = v;
  } catch { }
  return out;
}

function apiErrorMessage(rawText, fallback) {
  if (rawText) {
    try {
      const parsed = JSON.parse(rawText);
      if (parsed && typeof parsed.error === 'string' && parsed.error) return parsed.error;
    } catch {   }
  }
  return rawText || fallback;
}

async function loadQueue() {
  return (await storage.get(QUEUE_KEY)) || [];
}

async function saveQueue(queue) {
  await storage.set(QUEUE_KEY, queue);
}


async function initNetworkListener() {
  try {
    window.addEventListener('online', () => { isOnline = true; flushQueue(); });
    window.addEventListener('offline', () => { isOnline = false; });
  } catch { }

  isOnline = typeof navigator !== 'undefined' ? !!navigator.onLine : true;

  if (isOnline) flushQueue();
}

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
    const cached = offlineAllowed ? await storage.get(key) : null;
    if (cached != null) return { data: cached, fromCache: true };
    throw e;
  }

  if (!res.ok) {
    const status = res.status;
    const msg = await res.clone().text().catch(() => '');

    if (status === 401) {
      throw new Error(`UNAUTHORIZED: ${apiErrorMessage(msg, 'Authentication required')}`);
    }

    const err = new Error(apiErrorMessage(msg, `Request failed with status ${status}`));
    err.status = status;
    throw err;
  }

  const contentType = res.headers.get('Content-Type');
  if (contentType && !contentType.includes('application/json')) {
    const htmlBody = await res.clone().text().catch(() => '');
    console.error(`Status 200/2xx, but unexpected Content-Type: ${contentType}. Body starts with: ${htmlBody.substring(0, 50)}`);
    throw new Error(`Server returned HTML for API call (status ${res.status}). Expected JSON.`);
  }

  try {
    const data = await res.json();
    if (offlineAllowed) await storage.set(key, data);
    return { data, fromCache: false };
  } catch (e) {
    console.error(`Failed to parse successful response from ${request.url} as JSON:`, e);
    throw new Error(`Invalid server response format for status ${res.status}.`);
  }
}
async function postWithQueue(urlOrRequest, body, method = 'POST', headers = {}, options = {}) {
  let requestUrl, requestBody, requestMethod, requestHeaders;

  if (typeof urlOrRequest === 'object' && typeof urlOrRequest.url === 'string') {
    console.warn("Mobile/Offline: Cache mismatch detected. Handling legacy Request object.");
    const req = urlOrRequest;
    requestUrl = req.url;
    requestMethod = req.method;
    requestHeaders = headersToObject(req.headers);
    try {
      requestBody = await req.text();
    } catch (e) {
      console.warn("Legacy Request body read failed:", e);
      requestBody = '';
    }
  } else {
    requestUrl = urlOrRequest;
    requestBody = body;
    requestMethod = method;
    requestHeaders = headers instanceof Headers ? headersToObject(headers) : headers;
  }

  const fetchOptions = {
    method: requestMethod,
    headers: requestHeaders,
    body: requestBody,
    credentials: 'include',
    signal: options.signal
  };

  if (isOnline) {
    try {
      const res = await fetch(requestUrl, fetchOptions);

      if (!res.ok) {
        if (res.status >= 400 && res.status < 500) {
          const msg = await res.text();
          const err = new Error(apiErrorMessage(msg, res.statusText));
          err.status = res.status;
          throw err;
        }

        if (!offlineAllowed || options.noQueue) {
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
      if (e.name === 'AbortError') {
        throw e;
      }
      if (e.status && e.status >= 400 && e.status < 500) {
        throw e;
      }
      if (!offlineAllowed || options.noQueue) throw e;
      console.warn("Fetch failed, queuing:", e);
      await queueRequest({ url: requestUrl, method: requestMethod, headers: requestHeaders, body: requestBody });
      return 'QUEUED';
    }
  } else {
    if (!offlineAllowed) {
      throw new Error('You are offline. Offline mode is disabled by your organization.');
    }
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
        if (res.status >= 400 && res.status < 500) {
          console.warn(`[OfflineManager] Discarding failed queue item (Status ${res.status}): ${item.url}`);
        } else {
          remaining.push(item);
        }
      }
    } catch {
      remaining.push(item);
    }
  }
  await saveQueue(remaining);
}


export default {
  initNetworkListener,
  fetchWithCache,
  postWithQueue,
  setOfflineAllowed
};