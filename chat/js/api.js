export const urls = {
    LOGIN: '/api/login',
    LOGOUT: '/api/logout',
    ME: '/api/me',
    PROFILES: '/api/profiles',
    MODELS: '/api/models', // --- MODIFICATION: Added new models endpoint
    UPDATE_MODELS: '/api/me/models', // --- MODIFICATION: Added new update models endpoint
    UPDATE_PROFILE: '/api/me/profile', // --- MODIFICATION: Added new update profile endpoint
    CONVERSATIONS: '/api/conversations',
    PROCESS: '/api/process_prompt',
    AUDIT: '/api/audit_result',
    DELETE_ACCOUNT: '/api/me/delete',
    // --- NEW TTS Endpoint ---
    TTS: '/api/tts_audio' 
    // --- END NEW ---
};

async function fetchWithHandling(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: { 'Content-Type': 'application/json', ...options.headers },
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'An unknown error occurred.' }));
            throw new Error(errorData.error || errorData.message);
        }
        return response.json();
    } catch (error) {
        console.error(`API call to ${url} failed:`, error);
        throw error;
    }
}

export const getMe = () => fetch(urls.ME).then(res => res.json()).catch(() => null);
export const fetchConversations = () => fetchWithHandling(urls.CONVERSATIONS);
export const createNewConversation = () => fetchWithHandling(urls.CONVERSATIONS, { method: 'POST' });
export const renameConversation = (id, title) => fetchWithHandling(`${urls.CONVERSATIONS}/${id}`, { method: 'PUT', body: JSON.stringify({ title }) });
export const deleteConversation = (id) => fetchWithHandling(`${urls.CONVERSATIONS}/${id}`, { method: 'DELETE' });

// --- CHANGE: Updated fetchHistory to support pagination ---
// This function now takes limit and offset parameters and appends them
// to the URL as query strings for the backend to use.
export const fetchHistory = (id, limit = 50, offset = 0) => {
    const url = `${urls.CONVERSATIONS}/${id}/history?limit=${limit}&offset=${offset}`;
    return fetchWithHandling(url);
};

// --- MODIFICATION: Added userName parameter ---
export const processUserMessage = (message, conversation_id, userName) => {
    return fetchWithHandling(urls.PROCESS, { 
        method: 'POST', 
        body: JSON.stringify({ 
            message, 
            conversation_id,
            user_name: userName // Pass the user's name to the backend
        }) 
    });
};
// --- END MODIFICATION ---

export const fetchAuditResult = (messageId) => fetchWithHandling(`${urls.AUDIT}/${messageId}`);
export const checkConnection = () => fetch('/api/health').then(res => res.ok).catch(() => false);
export const deleteAccount = () => fetchWithHandling(urls.DELETE_ACCOUNT, { method: 'POST' });

export const fetchAvailableProfiles = () => fetchWithHandling(urls.PROFILES);

export const updateUserProfile = (profileName) => {
    return fetchWithHandling(urls.UPDATE_PROFILE, {
        method: 'PUT',
        body: JSON.stringify({ profile: profileName })
    });
};

// --- MODIFICATION: Added new functions for model management ---
export const fetchAvailableModels = () => fetchWithHandling(urls.MODELS);

export const updateUserModels = (models) => {
    return fetchWithHandling(urls.UPDATE_MODELS, {
        method: 'PUT',
        body: JSON.stringify(models)
    });
};
// --- END MODIFICATION ---

// --- NEW API Function for TTS ---
export const fetchTTSAudio = (text) => {
    return fetch(urls.TTS, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
    }).then(response => {
        if (!response.ok) {
            throw new Error('TTS audio generation failed.');
        }
        // Return the raw Blob response, not JSON
        return response.blob(); 
    });
};
// --- END NEW API Function ---