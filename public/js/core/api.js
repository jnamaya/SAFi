// js/api.js

import {
    setAuthToken,
    getAuthToken,
    awaitAuthInit,
    clearAuthToken // Function specifically for clearing the token
} from './cache.js';

import offlineManager from '../services/offline-manager.js';

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
    TOOLS: j('/api/agents/tools'),
    RUBRIC_GEN: j('/api/generate/rubric'), // Fixed: No trailing slash
    VALUES_GEN: j('/api/generate/values'),
    SCOPE_GEN: j('/api/generate/scope'),
    POLICIES: j('/api/policies'),
    CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}`,
    HISTORY: (id, limit = 50, offset = 0) => `${urls.CONVERSATIONS}/${id}/history?limit=${limit}&offset=${offset}`,
    PIN_CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}/pin`,
    PROJECTS: j('/api/projects'),
    PROJECT: (id) => `${j('/api/projects')}/${id}`,
    MOVE_CONVERSATION: (id) => `${urls.CONVERSATIONS}/${id}/project`,
    SAVED_CONTENT: j('/api/saved-content'),
    SAVED_ITEM: (id) => `${j('/api/saved-content')}/${id}`,
    MOVE_SAVED_ITEM: (id) => `${j('/api/saved-content')}/${id}/project`,

    // Org & Domain
    ORG_ME: j('/api/organizations/me'),
    ORG_CREATE: j('/api/organizations'),
    ORG_VERIFY_START: j('/api/organizations/domain/start'),
    ORG_VERIFY_CHECK: j('/api/organizations/domain/verify'),
    ORG_VERIFY_CANCEL: j('/api/organizations/domain/cancel'),

    // Document Upload
    DOCUMENTS_EXTRACT: j('/api/documents/extract'),
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
async function httpJSON(url, method, body, options = {}) {
    // We construct the body string and headers here
    const headers = await createHeaders();
    const bodyStr = JSON.stringify(body);

    // Pass plain arguments to offlineManager to avoid Request stream issues
    return await offlineManager.postWithQueue(url, bodyStr, method, headers, options);
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

export const getMe = async () => {
    try {
        return await httpGet(urls.ME);
    } catch (e) {
        // Suppress 401/Unauthorized errors for the 'me' check to avoid console noise
        if (e.message && e.message.includes('UNAUTHORIZED')) {
            return { ok: false, user: null };
        }
        throw e;
    }
};

// User/Profile/Model management
export const fetchAvailableProfiles = () => httpGet(urls.PROFILES);
export const fetchAvailableModels = () => httpGet(urls.MODELS);
export const updateUserProfile = (profileName) =>
    httpJSON(urls.UPDATE_PROFILE, 'PUT', { profile: profileName });
export const updateUserModels = (models) =>
    httpJSON(urls.UPDATE_MODELS, 'PUT', models);

// Conversation management
export const fetchConversations = () => httpGet(urls.CONVERSATIONS);
export const createNewConversation = (projectId = null) =>
    httpJSON(urls.CONVERSATIONS, 'POST', projectId ? { project_id: projectId } : {});
export const renameConversation = (id, title) =>
    httpJSON(urls.CONVERSATION(id), 'PUT', { title });
export const deleteConversation = (id) =>
    httpJSON(urls.CONVERSATION(id), 'DELETE', {});
export const clearAllConversations = () =>
    httpJSON(urls.CONVERSATIONS, 'DELETE', {});

export const togglePinConversation = (id, isPinned) =>
    httpJSON(urls.PIN_CONVERSATION(id), 'PATCH', { is_pinned: isPinned });

// Projects (workspaces)
export const fetchProjects = () => httpGet(urls.PROJECTS);
export const createProject = (name) => httpJSON(urls.PROJECTS, 'POST', { name });
export const renameProject = (id, name) => httpJSON(urls.PROJECT(id), 'PUT', { name });
export const deleteProject = (id) => httpJSON(urls.PROJECT(id), 'DELETE', {});
export const moveConversationToProject = (id, projectId) =>
    httpJSON(urls.MOVE_CONVERSATION(id), 'PATCH', { project_id: projectId });

// Saved content (snapshots of individual AI responses)
export const fetchSavedContent = () => httpGet(urls.SAVED_CONTENT);
export const saveContent = (messageId, projectId = null) =>
    httpJSON(urls.SAVED_CONTENT, 'POST', { message_id: messageId, project_id: projectId });
export const moveSavedContent = (id, projectId) =>
    httpJSON(urls.MOVE_SAVED_ITEM(id), 'PATCH', { project_id: projectId });
export const deleteSavedContent = (id) => httpJSON(urls.SAVED_ITEM(id), 'DELETE', {});

// Chat flow
export const fetchHistory = (id, limit = 50, offset = 0) =>
    httpGet(urls.HISTORY(id, limit, offset));
export const processUserMessage = (message, conversation_id, signal = null, message_id = null) =>
    httpJSON(urls.PROCESS, 'POST', { message, conversation_id, message_id }, { signal });
export const fetchAuditResult = (messageId) =>
    httpGet(`${urls.AUDIT}/${messageId}`);
export const cancelMessage = (messageId) =>
    httpJSON(`/api/cancel/${messageId}`, 'POST', {});
export const deleteAccount = () =>
    httpJSON(urls.DELETE_ACCOUNT, 'DELETE', {});

// Auth & Third-party Tools
export const fetchAuthStatus = () => httpGet(j('/api/auth/status'));

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

// Returns the raw Response so the caller can stream the body
export const fetchTTSStream = async (text) => {
    const headers = await createHeaders();
    const response = await fetch(urls.TTS, {
        method: 'POST',
        headers,
        body: JSON.stringify({ text }),
        credentials: 'include'
    });
    if (!response.ok) throw new Error('TTS stream failed.');
    return response;
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

export async function fetchAvailableTools() {
    return httpGet(urls.TOOLS);
}

export async function generateRubric(valueName, context) {
    return httpJSON(urls.RUBRIC_GEN, 'POST', { value_name: valueName, context });
}

export async function suggestValues(context) {
    return httpJSON(urls.VALUES_GEN, 'POST', { context });
}

export async function generateScope(personality) {
    return httpJSON(urls.SCOPE_GEN, 'POST', { personality });
}

export async function getAuthStatus() {
    return httpGet(j(`/api/auth/status?_t=${Date.now()}`));
}

export async function disconnectProvider(provider) {
    return httpJSON(j(`/api/auth/${provider}/disconnect`), 'POST', {});
}

export async function getDashboardToken() {
    return httpJSON(j('/api/auth/dashboard-token'), 'POST', {});
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

export const createPolicy = savePolicy;
export const updatePolicy = savePolicy;

export async function getPolicy(policyId) {
    return httpGet(`${urls.POLICIES}/${policyId}`);
}

export async function getPolicyVersions(policyId) {
    return httpGet(`${urls.POLICIES}/${policyId}/versions`);
}

export async function getPolicyVersion(policyId, version) {
    return httpGet(`${urls.POLICIES}/${policyId}/versions/${version}`);
}

export async function restorePolicyVersion(policyId, version) {
    return httpJSON(`${urls.POLICIES}/${policyId}/versions/${version}/restore`, 'POST', {});
}

export async function deletePolicy(policyId) {
    return httpJSON(`${urls.POLICIES}/${policyId}`, 'DELETE', {});
}

export async function generateKey(policyId, label = "Default") {
    return httpJSON(`${urls.POLICIES}/${policyId}/keys`, 'POST', { label });
}

export async function rotateKey(policyId) {
    return httpJSON(`${urls.POLICIES}/${policyId}/rotate_key`, 'POST', {});
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

// --- Enterprise identity: org identity config, invitations, sessions ---

export async function getOrgIdentity(orgId) {
    return httpGet(`/api/organizations/${orgId}/identity`);
}
export async function updateOrgIdentity(orgId, changes) {
    return httpJSON(`/api/organizations/${orgId}/identity`, 'PUT', changes);
}
export async function listInvitations(orgId) {
    return httpGet(`/api/organizations/${orgId}/invitations`);
}
export async function createInvitation(orgId, email, role) {
    return httpJSON(`/api/organizations/${orgId}/invitations`, 'POST', { email, role });
}
export async function revokeInvitation(orgId, inviteId) {
    return httpJSON(`/api/organizations/${orgId}/invitations/${inviteId}`, 'DELETE', {});
}
export async function revokeMemberSessions(orgId, userId) {
    return httpJSON(`/api/organizations/${orgId}/members/${userId}/sessions`, 'DELETE', {});
}

export async function removeMember(orgId, userId) {
    return httpJSON(`/api/organizations/${orgId}/members/${userId}`, 'DELETE', {});
}

export async function getCharter(orgId) {
    return httpGet(`/api/organizations/${orgId}/charter`);
}

export async function saveCharter(orgId, data) {
    return httpJSON(`/api/organizations/${orgId}/charter`, 'PUT', data);
}

export async function deleteCharter(orgId) {
    return httpJSON(`/api/organizations/${orgId}/charter`, 'DELETE', {});
}

// --- Document Upload ---

/**
 * Uploads a file and returns the extracted text content.
 * Uses a direct fetch (not offline manager) since file uploads can't be queued.
 *
 * @param {File} file - The File object from an input element.
 * @returns {Promise<{text: string, filename: string, total_chars: number, was_truncated: boolean}>}
 */
export async function extractDocumentText(file) {
    const formData = new FormData();
    formData.append('file', file);

    const auth = await getAuthToken();
    const headers = new Headers();
    // NOTE: Do NOT set Content-Type for FormData — the browser sets it
    // automatically with the correct multipart boundary.
    if (auth) headers.append('Authorization', `Bearer ${auth}`);

    const response = await fetch(urls.DOCUMENTS_EXTRACT, {
        method: 'POST',
        headers: headers,
        body: formData,
        credentials: 'include'
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || 'Document extraction failed.');
    }

    return data;
}

// --- SECURITY INCIDENTS API Functions (Reg S-P registry, admin-only) ---

export async function listIncidents(orgId) {
    return httpGet(j(`/api/organizations/${orgId}/incidents`));
}

export async function createIncident(orgId, data) {
    return httpJSON(j(`/api/organizations/${orgId}/incidents`), 'POST', data);
}

export async function getIncident(orgId, incidentId) {
    return httpGet(j(`/api/organizations/${orgId}/incidents/${incidentId}`));
}

export async function updateIncident(orgId, incidentId, data) {
    return httpJSON(j(`/api/organizations/${orgId}/incidents/${incidentId}`), 'PUT', data);
}

export async function logIncidentEvent(orgId, incidentId, data) {
    return httpJSON(j(`/api/organizations/${orgId}/incidents/${incidentId}/events`), 'POST', data);
}

// Export is a file download — used as a plain href/window.open target,
// not through the JSON pipeline.
export function incidentExportUrl(orgId, incidentId, format) {
    return j(`/api/organizations/${orgId}/incidents/${incidentId}/export?format=${format}`);
}

// --- RECORDS GOVERNANCE API Functions (retention, legal hold, examiner export) ---

export async function getRetention(orgId) {
    return httpGet(j(`/api/organizations/${orgId}/retention`));
}

export async function updateRetention(orgId, data) {
    return httpJSON(j(`/api/organizations/${orgId}/retention`), 'PUT', data);
}

export async function getComplianceLog(orgId, limit = 20) {
    return httpGet(j(`/api/organizations/${orgId}/compliance-log?limit=${limit}`));
}

// --- LLM provider allow-list (HIPAA BAA chains / EU data residency) ---

export async function getOrgProviders(orgId) {
    return httpGet(j(`/api/organizations/${orgId}/providers`));
}

// allowlist: array of provider keys, or null for unrestricted
export async function updateOrgProviders(orgId, allowlist) {
    return httpJSON(j(`/api/organizations/${orgId}/providers`), 'PUT', { allowlist });
}

// File download — plain URL for window.open/href, not the JSON pipeline.
export function recordsExportUrl(orgId, from, to, userId) {
    const u = userId ? `&user_id=${encodeURIComponent(userId)}` : '';
    return j(`/api/organizations/${orgId}/records/export?from=${from}&to=${to}${u}`);
}
