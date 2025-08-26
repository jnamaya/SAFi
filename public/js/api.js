export const urls = {
    LOGIN: '/api/login',
    LOGOUT: '/api/logout',
    ME: '/api/me',
    PROFILES: '/api/profiles',
    CONVERSATIONS: '/api/conversations',
    PROCESS: '/api/process_prompt',
    AUDIT: '/api/audit_result',
    DELETE_ACCOUNT: '/api/me/delete'
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
export const fetchHistory = (id) => fetchWithHandling(`${urls.CONVERSATIONS}/${id}/history`);
export const processUserMessage = (message, conversation_id) => fetchWithHandling(urls.PROCESS, { method: 'POST', body: JSON.stringify({ message, conversation_id }) });
export const fetchAuditResult = (messageId) => fetchWithHandling(`${urls.AUDIT}/${messageId}`);
export const checkConnection = () => fetch('/api/health').then(res => res.ok).catch(() => false);
export const deleteAccount = () => fetchWithHandling(urls.DELETE_ACCOUNT, { method: 'POST' });

export const fetchAvailableProfiles = () => fetchWithHandling(urls.PROFILES);

export const updateUserProfile = (profileName) => {
    return fetchWithHandling('/api/me/profile', {
        method: 'PUT',
        body: JSON.stringify({ profile: profileName })
    });
};
