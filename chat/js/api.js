// js/api.js

export const urls = {
    LOGIN: '/api/login',
    LOGOUT: '/api/logout',
    ME: '/api/me',
    PROFILES: '/api/profiles',
    MODELS: '/api/models',
    UPDATE_MODELS: '/api/me/models',
    UPDATE_PROFILE: '/api/me/profile',
    CONVERSATIONS: '/api/conversations',
    PROCESS: '/api/process_prompt',
    AUDIT: '/api/audit_result',
    DELETE_ACCOUNT: '/api/me/delete',
    TTS: '/api/tts_audio',
    PIN_CONVERSATION: (id) => `/api/conversations/${id}/pin`, // New pin URL
};

// --- CORE FETCH HANDLER ---
async function fetchWithHandling(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            // CRITICAL: Ensure session cookies are sent with every request
            credentials: 'include', 
            headers: { 
                'Content-Type': 'application/json', 
                ...options.headers 
            },
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'An unknown error occurred or server response was non-JSON.' }));
            // Log the raw status for debugging
            console.error(`API Call failed (${response.status} ${response.statusText}):`, errorData);
            throw new Error(errorData.error || errorData.message || `Request failed with status ${response.status}`);
        }
        return response.json();
    } catch (error) {
        console.error(`API call to ${url} failed:`, error);
        throw error;
    }
}

// --- EXPORTED API FUNCTIONS ---

// Special handling for getMe to return null on initial fetch failure, 
// but use the robust handler logic.
export const getMe = async () => {
    try {
        // Use direct fetch with credentials: 'include' for the initial session check
        const response = await fetch(urls.ME, { credentials: 'include' });
        if (!response.ok) {
            // If session is missing (401), we expect this on initial load.
            return null;
        }
        return response.json();
    } catch (error) {
        console.error('getMe failed:', error);
        return null;
    }
};

export const fetchConversations = () => fetchWithHandling(urls.CONVERSATIONS);
export const createNewConversation = () => fetchWithHandling(urls.CONVERSATIONS, { method: 'POST' });
export const renameConversation = (id, title) => fetchWithHandling(`${urls.CONVERSATIONS}/${id}`, { method: 'PUT', body: JSON.stringify({ title }) });
export const deleteConversation = (id) => fetchWithHandling(`${urls.CONVERSATIONS}/${id}`, { method: 'DELETE' });

// --- NEW: Pin/Unpin Toggle ---
export const togglePinConversation = (id, isPinned) => {
    return fetchWithHandling(urls.PIN_CONVERSATION(id), { 
        method: 'PATCH', 
        body: JSON.stringify({ is_pinned: isPinned }) 
    });
};
// --- END NEW ---

export const fetchHistory = (id, limit = 50, offset = 0) => {
    const url = `${urls.CONVERSATIONS}/${id}/history?limit=${limit}&offset=${offset}`;
    return fetchWithHandling(url);
};

export const processUserMessage = (message, conversation_id, userName) => {
    return fetchWithHandling(urls.PROCESS, { 
        method: 'POST', 
        body: JSON.stringify({ 
            message, 
            conversation_id,
            user_name: userName 
        }) 
    });
};

export const fetchAuditResult = (messageId) => fetchWithHandling(`${urls.AUDIT}/${messageId}`);
export const checkConnection = () => fetch('/api/health').then(res => res.ok).catch(() => false);
export const deleteAccount = () => fetchWithHandling(urls.DELETE_ACCOUNT, { method: 'DELETE' }); // Changed to DELETE based on standard REST

export const fetchAvailableProfiles = () => fetchWithHandling(urls.PROFILES);

export const updateUserProfile = (profileName) => {
    return fetchWithHandling(urls.UPDATE_PROFILE, {
        method: 'PUT',
        body: JSON.stringify({ profile: profileName })
    });
};

export const fetchAvailableModels = () => fetchWithHandling(urls.MODELS);

export const updateUserModels = (models) => {
    return fetchWithHandling(urls.UPDATE_MODELS, {
        method: 'PUT',
        body: JSON.stringify(models)
    });
};

export const fetchTTSAudio = (text) => {
    return fetch(urls.TTS, {
        method: 'POST',
        credentials: 'include', // Ensure cookies are sent
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
    }).then(response => {
        if (!response.ok) {
            throw new Error('TTS audio generation failed.');
        }
        return response.blob(); 
    });
};