import { responseToJsonSafe } from './utils.js';

const API_BASE_URL = window.__API_BASE_URL__ || '';

export const urls = {
    LOGIN: `${API_BASE_URL}/api/login`,
    LOGOUT: `${API_BASE_URL}/api/logout`,
    ME: `${API_BASE_URL}/api/me`,
    CONVERSATIONS: `${API_BASE_URL}/api/conversations`,
    // CHANGE: Added the new profiles endpoint
    PROFILES: `${API_BASE_URL}/api/profiles`,
    PROCESS_PROMPT: `${API_BASE_URL}/api/process_prompt`,
    HEALTH: `${API_BASE_URL}/api/health`,
};

export async function getMe() {
    try {
        const res = await fetch(urls.ME, { credentials: 'include', cache: 'no-store' });
        if (!res.ok) return null;
        return await responseToJsonSafe(res);
    } catch {
        return null;
    }
}

export async function checkConnection() {
    try {
        const response = await fetch(urls.HEALTH);
        return response.ok;
    } catch (error) {
        return false;
    }
}

// CHANGE: This new function calls your backend to get the active value profile.
export async function fetchActiveProfile() {
    const response = await fetch(urls.PROFILES, { credentials: 'include', cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
}

export async function fetchConversations() {
    const response = await fetch(urls.CONVERSATIONS, { credentials: 'include', cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
}

export async function createNewConversation() {
    const res = await fetch(urls.CONVERSATIONS, { method: 'POST', credentials: 'include' });
    if (!res.ok) throw new Error('Failed to create conversation');
    return await res.json();
}

export async function renameConversation(id, newTitle) {
    return await fetch(`${urls.CONVERSATIONS}/${id}`, { 
        method: 'PUT', 
        headers: { 'Content-Type': 'application/json' }, 
        credentials: 'include', 
        body: JSON.stringify({ title: newTitle.trim() }) 
    });
}

export async function deleteConversation(id) {
    return await fetch(`${urls.CONVERSATIONS}/${id}`, { method: 'DELETE', credentials: 'include' });
}

export async function fetchHistory(id) {
    const response = await fetch(`${urls.CONVERSATIONS}/${id}/history`, { credentials: 'include', cache: 'no-store' });
    return await response.json();
}

export async function processUserMessage(message, conversationId) {
    const response = await fetch(urls.PROCESS_PROMPT, { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        credentials: 'include', 
        body: JSON.stringify({ message, conversation_id: conversationId }) 
    });
    if (!response.ok) {
        const errorData = await responseToJsonSafe(response);
        throw new Error(errorData?.error || `Request failed with status ${response.status}`);
    }
    return await responseToJsonSafe(response) || {};
}

export async function deleteAccount() {
    const response = await fetch(urls.ME, { method: 'DELETE', credentials: 'include' });
    if (!response.ok) throw new Error('Failed to delete account.');
}
