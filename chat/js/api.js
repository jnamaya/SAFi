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

console.log("SAFI API Loaded v2.3 (Fixes 405 & Verbose AI)");

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
    PROFILES: j('/api/agents/all'), // DB-backed list
    MODELS: j('/api/models'),
    UPDATE_MODELS: j('/api/me/models'),
    UPDATE_PROFILE: j('/api/me/profile'),
    CONVERSATIONS: j('/api/conversations'),
    PROCESS: j('/api/process_prompt'),
    AUDIT: j('/api/audit_result'),
    DELETE_ACCOUNT: j('/api/me/delete'),
    TTS: j('/api/tts_audio'),
    MY_PROFILE: j('/api/me/profile'),
    AGENTS: j('/api/agents'),
    RUBRIC_GEN: j('/api/generate/rubric'), // Fixed: No trailing slash
    POLICIES: j('/api/policies'),
    CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}`,
    HISTORY: (id, limit = 50, offset = 0) => `${urls.CONVERSATIONS}/${id}/history?limit=${limit}&offset=${offset}`,
    PIN_CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}/pin`,

    // Org & Domain
    ORG_ME: j('/api/organizations/me'),
    ORG_CREATE: j('/api/organizations'),
    ORG_VERIFY_START: j('/api/organizations/domain/start'),
    ORG_VERIFY_CHECK: j('/api/organizations/domain/verify'),
    ORG_VERIFY_CANCEL: j('/api/organizations/domain/cancel'),
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
    // We construct the body string and headers here
    const headers = await createHeaders();
    const bodyStr = JSON.stringify(body);

    // Pass plain arguments to offlineManager to avoid Request stream issues
    return await offlineManager.postWithQueue(url, bodyStr, method, headers);
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
    } catch (e) {
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

// TTS audio
export const fetchTTSAudio = async (text) => {
    const headers = await createHeaders();
    const body = JSON.stringify({ text });

    const response = await fetch(urls.TTS, {
        method: 'POST',
        headers: headers,
        body: body,
        credentials: 'include'
    });

    if (!response.ok) {
        throw new Error('TTS audio generation failed.');
    }
    return response.blob();
};

// --- NEW: API functions for "My Profile" tab ---
export async function fetchUserProfileMemory() {
    return httpGet(urls.MY_PROFILE);
}

export async function updateUserProfileMemory(profileData) {
    return httpJSON(urls.MY_PROFILE, 'POST', profileData);
}

// --- NEW: API functions for Custom Agents ---
export async function saveAgent(agentData) {
    if (agentData.is_update_mode) {
        return httpJSON(urls.AGENTS, 'PUT', agentData);
    } else {
        return httpJSON(urls.AGENTS, 'POST', agentData);
    }
}

export async function getAgent(key) {
    return httpGet(`${urls.AGENTS}/${key}`);
}

export async function deleteAgent(key) {
    return httpJSON(`${urls.AGENTS}/${key}`, 'DELETE', {});
}

export async function generateRubric(valueName, context) {
    return httpJSON(urls.RUBRIC_GEN, 'POST', { value_name: valueName, context });
}

// --- GOVERNANCE API Functions ---

export async function fetchPolicies() {
    return httpGet(`${urls.POLICIES}?_t=${Date.now()}`);
}

export async function savePolicy(policyData) {
    if (policyData.policy_id) {
        return httpJSON(`${urls.POLICIES}/${policyData.policy_id}`, 'PUT', policyData);
    } else {
        return httpJSON(urls.POLICIES, 'POST', policyData);
    }
}

export async function getPolicy(policyId) {
    return httpGet(`${urls.POLICIES}/${policyId}`);
}

export async function deletePolicy(policyId) {
    return httpJSON(`${urls.POLICIES}/${policyId}`, 'DELETE', {});
}

export async function generateKey(policyId, label = "Default") {
    return httpJSON(`${urls.POLICIES}/${policyId}/keys`, 'POST', { label });
}

export async function generatePolicyContent(type, context, extraData = {}) {
    return httpJSON(`${urls.POLICIES}/ai/generate`, 'POST', { type, context, ...extraData });
}

// --- ORGANIZATION API Functions ---

export async function getMyOrganization() {
    return httpGet(urls.ORG_ME);
}

export async function saveOrganization(orgData) {
    // If we were editing, we'd use PUT, but currently we only confirm creation via Wizard
    // which uses this. If we implement "Update Settings", we will need a PUT route.
    return httpJSON(urls.ORG_CREATE, 'POST', orgData);
}

export async function startDomainVerification(orgId, domain) {
    return httpJSON(urls.ORG_VERIFY_START, 'POST', { org_id: orgId, domain });
}

export async function cancelDomainVerification(orgId) {
    return httpJSON(urls.ORG_VERIFY_CANCEL, 'POST', { org_id: orgId });
}

export async function checkDomainVerification(orgId) {
    return httpJSON(urls.ORG_VERIFY_CHECK, 'POST', { org_id: orgId });
}

export async function updateOrganization(orgId, data) {
    return httpJSON(`/api/organizations/${orgId}`, 'PUT', data);
}

export async function getOrganizationMembers(orgId) {
    return httpGet(`/api/organizations/${orgId}/members`);
}

export async function updateMemberRole(orgId, userId, role) {
    return httpJSON(`/api/organizations/${orgId}/members/${userId}/role`, 'PUT', { role });
}

export async function removeMember(orgId, userId) {
    return httpJSON(`/api/organizations/${orgId}/members/${userId}`, 'DELETE', {});
}
