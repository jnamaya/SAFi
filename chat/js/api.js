// js/api.js

import { 
    setAuthToken, 
    getAuthToken, 
    awaitAuthInit, 
    clearAuthToken // Function specifically for clearing the token
} from './cache.js'; 

import offlineManager from './offline-manager.js';

const Cap = typeof window !== "undefined" ? window.Capacitor : null;
const isNative = !!(Cap && Cap.isNativePlatform && Cap.isNativePlatform());

// Use the fixed host for Capacitor builds
const HOST = "https://safi.selfalignmentframework.com";
const j = (p) => (isNative ? `${HOST}${p}` : p);

// Export Auth utilities used by app.js
export { awaitAuthInit, setAuthToken, getAuthToken, clearAuthToken }; 

export const urls = {
    LOGIN: j('/api/login'),
    MOBILE_LOGIN: j("/api/auth/google/mobile"),
    LOGOUT: j('/api/logout'),
    ME: j('/api/me'),
    PROFILES: j('/api/profiles'),
    MODELS: j('/api/models'), 
    UPDATE_MODELS: j('/api/me/models'), 
    UPDATE_PROFILE: j('/api/me/profile'), 
    CONVERSATIONS: j('/api/conversations'),
    PROCESS: j('/api/process_prompt'),
    AUDIT: j('/api/audit_result'),
    DELETE_ACCOUNT: j('/api/me/delete'),
    TTS: j('/api/tts_audio'),
    // --- NEW: API endpoint for the user's learned profile ---
    MY_PROFILE: j('/api/me/profile'),
    // --- END NEW ---
    CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}`, 
    HISTORY: (id, limit = 50, offset = 0) => `${urls.CONVERSATIONS}/${id}/history?limit=${limit}&offset=${offset}`,
    // NEW URL for Pin Toggle
    PIN_CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}/pin`,
};


// --- CORE HYBRID FETCHING FUNCTIONS ---

async function createHeaders() {
    const auth = await getAuthToken();
    const headers = new Headers();
    headers.append("Content-Type", "application/json");
    if (auth) headers.append("Authorization", `Bearer ${auth}`);
    return headers;
}

// GET requests use offlineManager.fetchWithCache
async function httpGet(url) {
    const request = new Request(url, {
        method: 'GET',
        headers: await createHeaders(),
        credentials: 'include'
    });
    const result = await offlineManager.fetchWithCache(request);
    // The data is nested in the 'data' property by fetchWithCache
    if (result && result.data) {
        return result.data;
    }
    // Fallback if the structure is flat (e.g., from a direct fetch)
    return result; 
}

// POST/PUT/DELETE/PATCH requests use offlineManager.postWithQueue
async function httpJSON(url, method, body) {
    const request = new Request(url, {
        method,
        headers: await createHeaders(),
        body: JSON.stringify(body),
        credentials: 'include'
    });
    return await offlineManager.postWithQueue(request);
}

function ensureOkOrQueued(res, tag) {
    if (res === 'QUEUED') return 'QUEUED';
    if (res && res.ok === false) {
        const msg = res.error || JSON.stringify(res);
        throw new Error(`${tag}: ${msg}`);
    }
    return res;
}


// --- EXPORTED API FUNCTIONS (Hybrid) ---

export async function login(payload) {
    const res = await httpJSON(urls.LOGIN, "POST", payload);
    if (res && res.token) await setAuthToken(res.token);
    return ensureOkOrQueued(res, "login");
}

export async function mobileLogin(code) {
    const res = await httpJSON(urls.MOBILE_LOGIN, "POST", { code });
    if (res?.token) {
      await setAuthToken(res.token);
      return { ok: true, token: res.token };
    }
    return ensureOkOrQueued(res, "mobile_login");
}

export async function logout() {
    try { 
        await httpJSON(urls.LOGOUT, "POST", {}); 
    } catch(e) {
        console.warn("Logout API call failed, clearing token anyway.", e);
    } finally {
      await clearAuthToken(); // Use clearAuthToken from cache.js
    }
    return { ok: true };
}

export const getMe = () => httpGet(urls.ME);

// User/Profile/Model management
export const fetchAvailableProfiles = () => httpGet(urls.PROFILES);
export const fetchAvailableModels = () => httpGet(urls.MODELS);
export const updateUserProfile = (profileName) => 
    httpJSON(urls.UPDATE_PROFILE, 'PUT', { profile: profileName });
export const updateUserModels = (models) => 
    httpJSON(urls.UPDATE_MODELS, 'PUT', models);

// Conversation management
export const fetchConversations = () => httpGet(urls.CONVERSATIONS);
export const createNewConversation = () => httpJSON(urls.CONVERSATIONS, 'POST', {});
export const renameConversation = (id, title) => 
    httpJSON(urls.CONVERSATION(id), 'PUT', { title });
export const deleteConversation = (id) => 
    httpJSON(urls.CONVERSATION(id), 'DELETE', {});
    
// NEW API function for Pin Toggle
export const togglePinConversation = (id, isPinned) => 
    httpJSON(urls.PIN_CONVERSATION(id), 'PATCH', { is_pinned: isPinned });

// Chat flow
export const fetchHistory = (id, limit = 50, offset = 0) => 
    httpGet(urls.HISTORY(id, limit, offset)); 
export const processUserMessage = (message, conversation_id) => 
    httpJSON(urls.PROCESS, 'POST', { message, conversation_id });
export const fetchAuditResult = (messageId) => 
    httpGet(`${urls.AUDIT}/${messageId}`);
export const deleteAccount = () => 
    httpJSON(urls.DELETE_ACCOUNT, 'DELETE', {});

// TTS audio does not need offline queue/cache, but it DOES need auth.
export const fetchTTSAudio = async (text) => {
    // Create auth headers
    const headers = await createHeaders(); 
    // Set body
    const body = JSON.stringify({ text });

    const response = await fetch(urls.TTS, {
        method: 'POST',
        headers: headers, // Use the auth headers
        body: body,
        credentials: 'include' // Match other requests
    });

    if (!response.ok) {
        throw new Error('TTS audio generation failed.');
    }
    return response.blob(); 
};

// --- NEW: API functions for "My Profile" tab ---

/**
 * Fetches the user's learned profile from the backend.
 * @returns {Promise<Object>} A promise that resolves to the user's profile object.
 */
export async function fetchUserProfileMemory() {
    return httpGet(urls.MY_PROFILE);
}

/**
 * Saves the user's (potentially edited) profile to the backend.
 * @param {Object} profileData - The complete profile object to save.
 * @returns {Promise<Object>} A promise that resolves to the saved profile.
 */
export async function updateUserProfileMemory(profileData) {
    return httpJSON(urls.MY_PROFILE, 'POST', profileData);
}
// --- END NEW ---