/**
 * js/cache.js
 * Handles LOCAL UI STATE CACHING and Auth Token Persistence.
 */

// Get native plugin from the global Capacitor object
const Cap = typeof window !== "undefined" ? window.Capacitor : null;
const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());
const Preferences = Cap?.Plugins?.Preferences;

/**
 * A wrapper for native key-value storage.
 */
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
        await Preferences.set({ key, data });
      } else {
        localStorage.setItem(key, data);
      }
    } catch (e) {
      if (e.name === 'QuotaExceededError' || e.code === 22) {
        console.warn(`Storage quota exceeded while saving ${key}. Attempting eviction...`);
        const evicted = await evictOldCache(10); // Remove 10 items
        if (evicted) {
          // Retry save
          try {
            const data = JSON.stringify(value);
            localStorage.setItem(key, data);
            console.log(`Retry save of ${key} successful after eviction.`);
          } catch (retryErr) {
            console.warn(`Failed to save ${key} after 10-item eviction. Trying scorched earth...`);
            await evictOldCache(25); // Remove 25 items
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

/**
 * Utility to calculate current localStorage usage.
 */
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

/**
 * Evicts cached items to free up space.
 * targetCount: How many items to attempt to remove.
 */
async function evictOldCache(targetCount = 5) {
  try {
    const convos = await loadConvoList();
    let spacesCleared = 0;

    // 1. Sort convos by last_updated (oldest first)
    const sortedConvos = [...convos].sort((a, b) => (a.last_updated || '').localeCompare(b.last_updated || ''));

    // 2. Remove oldest conversation histories (the bulk of our custom cache)
    for (const c of sortedConvos) {
      if (spacesCleared >= targetCount) break;
      const historyKey = CACHE_KEYS.CONVO_PREFIX + c.id;
      if (localStorage.getItem(historyKey)) {
        localStorage.removeItem(historyKey);
        spacesCleared++;
      }
    }

    // 3. Remove offline-manager cached GET requests (safi_cache_v1)
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

    // 4. Orphaned key cleanup (fallback)
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


// --- AUTH TOKEN MANAGEMENT (Moved from old api_mobile.js) ---

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

// Function used by logout/delete account
export async function clearAuthToken() {
  await setAuthToken("");
}


// --- CONVERSATION CACHE MANAGEMENT (From original cache.js) ---

const CACHE_KEYS = {
  CONVO_LIST: 'safi_convo_list',
  CONVO_PREFIX: 'safi_convo_' // Followed by convoId
};

export async function saveConvoList(conversations) {
  try {
    // Ensure all objects have is_pinned property, defaulting to false if missing
    const sanitizedConversations = conversations.map(c => ({
      ...c,
      is_pinned: c.is_pinned === true // Ensure it's explicitly boolean true, otherwise false
    }));
    await NativeStorage.set(CACHE_KEYS.CONVO_LIST, sanitizedConversations);
  } catch (e) {
    console.error('Failed to save convo list to cache:', e);
  }
}

export async function loadConvoList() {
  try {
    const convos = (await NativeStorage.get(CACHE_KEYS.CONVO_LIST)) || [];
    // Sanitize on load to ensure old entries work
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
      // New conversation created offline, add it.
      convos.unshift({ id: convoId, ...safeUpdates });
    }

    // Sorting will be handled by chat.js on render, but we ensure the cache is clean
    await saveConvoList(convos);
  } catch (e) {
    console.error('Failed to update convo in list cache:', e);
  }
}

export async function deleteConvo(convoId) {
  try {
    const convos = (await loadConvoList()).filter(c => c.id !== convoId);
    await saveConvoList(convos);
    await NativeStorage.remove(CACHE_KEYS.CONVO_PREFIX + convoId);
  } catch (e) {
    console.error('Failed to delete convo from cache:', e);
  }
}

export async function saveConvoHistory(convoId, history) {
  try {
    await NativeStorage.set(CACHE_KEYS.CONVO_PREFIX + convoId, history);
  } catch (e) {
    console.error(`Failed to save history for ${convoId}:`, e);
  }
}

export async function loadConvoHistory(convoId) {
  try {
    return (await NativeStorage.get(CACHE_KEYS.CONVO_PREFIX + convoId)) || [];
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
  try {
    const convos = await loadConvoList();

    await NativeStorage.remove(CACHE_KEYS.CONVO_LIST);

    if (convos && convos.length > 0) {
      for (const convo of convos) {
        await NativeStorage.remove(CACHE_KEYS.CONVO_PREFIX + convo.id);
      }
    }
  } catch (e) {
    console.error('Failed to clear all cache:', e);
  }
}