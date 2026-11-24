const isNative = false;
const Preferences = null;

const NativeStorage = {
  async get(key) {
    try {
      if (Preferences && isNative) {
        const { value } = await Preferences.get({ key });
        return value ? JSON.parse(value) : null;
      } else {
        const value = localStorage.getItem(key);
        return value ? JSON.parse(value) : null;
      }
    } catch (e) {
      console.error(`Failed to get item ${key} from storage:`, e);
      return null;
    }
  },
  async set(key, value) {
    try {
      const data = JSON.stringify(value);
      if (Preferences && isNative) {
        await Preferences.set({ key, value: data });
      } else {
        localStorage.setItem(key, data);
      }
    } catch (e) {
      if (e.name === 'QuotaExceededError' || e.code === 22) {
        console.warn(`Storage quota exceeded while saving ${key}. Attempting eviction...`);
        const evicted = await evictOldCache(10);
        if (evicted) {
          try {
            const data = JSON.stringify(value);
            localStorage.setItem(key, data);
            console.log(`Retry save of ${key} successful after eviction.`);
          } catch (retryErr) {
            console.warn(`Failed to save ${key} after 10-item eviction. Trying scorched earth...`);
            await evictOldCache(25);
            try {
              localStorage.setItem(key, JSON.stringify(value));
              console.log(`Retry save of ${key} successful after aggressive eviction.`);
            } catch (finalErr) {
              console.error(`Could not evict enough space for ${key}. Storage might be fundamentally full.`, getStorageUsage());
            }
          }
        } else {
          console.error(`Could not evict enough space for ${key}.`);
        }
      } else {
        console.error(`Failed to set item ${key} in storage:`, e);
      }
    }
  },
  async remove(key) {
    try {
      if (Preferences && isNative) {
        await Preferences.remove({ key });
      } else {
        localStorage.removeItem(key);
      }
    } catch (e) {
      console.error(`Failed to remove item ${key} from storage:`, e);
    }
  }
};

function getStorageUsage() {
  let total = 0;
  for (const x in localStorage) {
    if (!localStorage.hasOwnProperty(x)) continue;
    total += ((localStorage[x].length + x.length) * 2);
  }
  return {
    totalBytes: total,
    totalKB: (total / 1024).toFixed(2),
    totalMB: (total / (1024 * 1024)).toFixed(2),
    count: localStorage.length
  };
}

async function evictOldCache(targetCount = 5) {
  try {
    const convos = await loadConvoList();
    let spacesCleared = 0;

    const sortedConvos = [...convos].sort((a, b) => (a.last_updated || '').localeCompare(b.last_updated || ''));

    for (const c of sortedConvos) {
      if (spacesCleared >= targetCount) break;
      const historyKey = CACHE_KEYS.CONVO_PREFIX + c.id;
      if (localStorage.getItem(historyKey)) {
        localStorage.removeItem(historyKey);
        spacesCleared++;
      }
    }

    if (spacesCleared < targetCount && !isNative && typeof localStorage !== 'undefined') {
      const cacheKeys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && (key.startsWith('safi_cache_v1:') || key.startsWith('safi_cache:'))) {
          cacheKeys.push(key);
        }
      }

      for (const k of cacheKeys) {
        if (spacesCleared >= targetCount) break;
        localStorage.removeItem(k);
        spacesCleared++;
      }
    }

    if (spacesCleared === 0 && !isNative && typeof localStorage !== 'undefined') {
      const keysToDelete = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(CACHE_KEYS.CONVO_PREFIX)) {
          const id = key.replace(CACHE_KEYS.CONVO_PREFIX, '');
          if (!convos.some(cv => cv.id === id)) {
            keysToDelete.push(key);
          }
        }
      }
      for (const k of keysToDelete) {
        if (spacesCleared >= targetCount) break;
        localStorage.removeItem(k);
        spacesCleared++;
      }
    }

    return spacesCleared > 0;
  } catch (err) {
    console.error("Error during cache eviction:", err);
    return false;
  }
}


const TOKEN_KEY = "safi_auth_token";
let _cachedToken = "";
const _authInitPromise = initializeAuthToken();

async function initializeAuthToken() {
  try {
    if (Preferences && isNative) {
      const { value } = await Preferences.get({ key: TOKEN_KEY });
      _cachedToken = value || "";
    } else {
      _cachedToken = localStorage.getItem(TOKEN_KEY) || "";
    }
    console.log(`[AUTH] Initial token load complete. Token present: ${_cachedToken.length > 0}`);
  } catch (e) {
    console.error("[AUTH] Error initializing token from storage:", e);
    _cachedToken = "";
  }
}

export async function awaitAuthInit() {
  return _authInitPromise;
}

export async function setAuthToken(token) {
  const value = token || "";
  _cachedToken = value;
  try {
    if (Preferences && isNative) {
      await Preferences.set({ key: TOKEN_KEY, value });
    } else {
      localStorage.setItem(TOKEN_KEY, value);
    }
  } catch (e) {
    console.error("[AUTH] Error setting token:", e);
  }
}

export async function getAuthToken() {
  await _authInitPromise;
  return _cachedToken;
}

export async function clearAuthToken() {
  await setAuthToken("");
}


const CACHE_KEYS = {
  CONVO_LIST: 'safi_convo_list',
  CONVO_PREFIX: 'safi_convo_'
};

let persistenceAllowed = true;

const _mem = new Map();
const MEM_MAX_ENTRIES = 12;

function _memSet(key, value) {
  _mem.delete(key);
  _mem.set(key, value);
  while (_mem.size > MEM_MAX_ENTRIES) {
    _mem.delete(_mem.keys().next().value);
  }
}

function _memGet(key) {
  if (!_mem.has(key)) return null;
  const value = _mem.get(key);
  _memSet(key, value);
  return value;
}

export function _memoryStats() {
  return { entries: _mem.size, keys: [..._mem.keys()], persistenceAllowed };
}

export async function setPersistenceAllowed(allowed) {
  const next = allowed !== false;
  const changed = next !== persistenceAllowed;
  persistenceAllowed = next;
  if (!persistenceAllowed) {
    console.info('[cache] Local persistence is disabled by org policy — '
      + 'this session is memory-only; nothing is written to device storage.');
    _mem.clear();
    await clearAllCache();
  } else if (changed) {
    _mem.clear();
  }
}

export async function saveConvoList(conversations) {
  _memSet(CACHE_KEYS.CONVO_LIST, conversations.map(c => ({
    ...c, is_pinned: c.is_pinned === true
  })));
  if (!persistenceAllowed) return 'memory-only';
  try {
    const sanitizedConversations = conversations.map(c => ({
      ...c,
      is_pinned: c.is_pinned === true
    }));
    await NativeStorage.set(CACHE_KEYS.CONVO_LIST, sanitizedConversations);
  } catch (e) {
    console.error('Failed to save convo list to cache:', e);
  }
}

export async function loadConvoList() {
  try {
    const cached = _memGet(CACHE_KEYS.CONVO_LIST);
    const convos = cached || (persistenceAllowed
      ? ((await NativeStorage.get(CACHE_KEYS.CONVO_LIST)) || [])
      : []);
    return convos.map(c => ({
      ...c,
      is_pinned: c.is_pinned === true
    }));
  } catch (e) {
    console.error('Failed to load convo list from cache:', e);
    return [];
  }
}

export async function updateConvoInList(convoId, updates) {
  try {
    const convos = await loadConvoList();
    const convoIndex = convos.findIndex(c => c.id === convoId);

    const safeUpdates = {
      ...updates,
      is_pinned: updates.is_pinned === true ? true : (updates.is_pinned === false ? false : undefined)
    };

    if (convoIndex > -1) {
      convos[convoIndex] = { ...convos[convoIndex], ...safeUpdates };
    } else {
      convos.unshift({ id: convoId, ...safeUpdates });
    }

    await saveConvoList(convos);
  } catch (e) {
    console.error('Failed to update convo in list cache:', e);
  }
}

export async function deleteConvo(convoId) {
  try {
    const convos = (await loadConvoList()).filter(c => c.id !== convoId);
    await saveConvoList(convos);
    _mem.delete(CACHE_KEYS.CONVO_PREFIX + convoId);
    await NativeStorage.remove(CACHE_KEYS.CONVO_PREFIX + convoId);
  } catch (e) {
    console.error('Failed to delete convo from cache:', e);
  }
}

export async function saveConvoHistory(convoId, history) {
  const key = CACHE_KEYS.CONVO_PREFIX + convoId;
  _memSet(key, history);
  if (!persistenceAllowed) return 'memory-only';
  try {
    await NativeStorage.set(key, history);
    return 'persisted';
  } catch (e) {
    console.error(`Failed to save history for ${convoId}:`, e);
    return 'failed';
  }
}

export async function loadConvoHistory(convoId) {
  const key = CACHE_KEYS.CONVO_PREFIX + convoId;
  const inMemory = _memGet(key);
  if (inMemory) return inMemory;
  if (!persistenceAllowed) return [];
  try {
    const stored = (await NativeStorage.get(key)) || [];
    if (stored.length) _memSet(key, stored);
    return stored;
  } catch (e) {
    console.error(`Failed to load history for ${convoId}:`, e);
    return [];
  }
}

export async function addMessageToHistory(convoId, message) {
  try {
    const history = await loadConvoHistory(convoId);
    if (!history.some(m => m.message_id === message.message_id)) {
      history.push(message);
      await saveConvoHistory(convoId, history);
    }
  } catch (e) {
    console.error(`Failed to add message to history for ${convoId}:`, e);
  }
}

export async function clearAllCache() {
  _mem.clear();
  try {
    const convos = await loadConvoList();

    await NativeStorage.remove(CACHE_KEYS.CONVO_LIST);

    if (convos && convos.length > 0) {
      for (const convo of convos) {
        await NativeStorage.remove(CACHE_KEYS.CONVO_PREFIX + convo.id);
      }
    }
    try {
      const doomed = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(CACHE_KEYS.CONVO_PREFIX)) doomed.push(k);
      }
      doomed.forEach(k => localStorage.removeItem(k));
    } catch { }
  } catch (e) {
    console.error('Failed to clear all cache:', e);
  }
}