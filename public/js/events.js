// js/events.js
// Handles application logic triggered by user events.

import * as api from './api.js';
import { ui, updateUIForAuthState } from './ui/index.js';
import * as state from './state.js';

async function loadConversations(switchToId = null) {
    try {
        const conversations = await api.fetchConversations();
        const convoList = ui.elements.convoList();
        if (!convoList) return;
        
        convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>`;
        
        if (conversations?.length > 0) {
            conversations.forEach(convo => {
                const link = ui.renderConversationLink(convo, {
                    switchHandler: switchConversation,
                    renameHandler: handleRename,
                    deleteHandler: handleDelete
                });
                convoList.appendChild(link);
            });
            const { currentConversationId } = state.getState();
            const targetId = switchToId ?? (conversations.some(c => c.id === currentConversationId) ? currentConversationId : conversations[0].id);
            await switchConversation(targetId);
        } else {
            await startNewConversation(true);
        }
    } catch (error) {
        ui.showToast('Failed to load conversations.', 'error');
    }
}

async function startNewConversation(isInitialLoad = false) {
    try {
        const newConvo = await api.createNewConversation();
        if (isInitialLoad) {
            const link = ui.renderConversationLink(newConvo, { switchHandler: switchConversation, renameHandler: handleRename, deleteHandler: handleDelete });
            ui.elements.convoList()?.appendChild(link);
            await switchConversation(newConvo.id);
        } else {
            await loadConversations(newConvo.id);
        }
    } catch (error) {
        ui.showToast('Could not start a new chat.', 'error');
    }
}

async function switchConversation(id) {
    state.setCurrentConversationId(id);
    ui.setActiveConvoLink(id);
    ui.resetChatView();

    try {
        const history = await api.fetchHistory(id);
        if (history?.length > 0) {
            history.forEach(turn => {
                const payload = {
                    ledger: JSON.parse(turn.conscience_ledger || '[]'),
                    profile: turn.profile_name,
                    values: JSON.parse(turn.profile_values || '[]'),
                    spirit_score: turn.spirit_score
                };
                ui.displayMessage(turn.role, turn.content, new Date(turn.timestamp), turn.message_id, payload, (p) => ui.showModal('conscience', p));
            });
        } else {
            ui.displayEmptyState(state.getState().activeProfileData, handleExamplePromptClick);
        }
        ui.scrollToBottom();
    } catch (error) {
        ui.showToast('Could not load chat history.', 'error');
    }
}

function pollForAuditResults(messageId, maxAttempts = 10, interval = 2000) {
    let attempts = 0;
    const executePoll = async (resolve, reject) => {
        try {
            const result = await api.fetchAuditResult(messageId);
            attempts++;
            if (result && result.status === 'complete') {
                const payload = {
                    ledger: JSON.parse(result.ledger || '[]'),
                    profile: result.profile,
                    values: JSON.parse(result.values || '[]'),
                    spirit_score: result.spirit_score
                };
                ui.updateMessageWithAudit(messageId, payload, (p) => ui.showModal('conscience', p));
                resolve(result);
            } else if (attempts >= maxAttempts) {
                reject(new Error('Polling timed out.'));
            } else {
                setTimeout(() => executePoll(resolve, reject), interval);
            }
        } catch (error) {
            reject(error);
        }
    };
    return new Promise(executePoll);
}

async function sendMessage() {
    const input = ui.elements.messageInput();
    const { currentConversationId } = state.getState();
    if (!input || !currentConversationId) return;

    const userMessage = input.value.trim();
    if (!userMessage) return;

    const sendButton = document.getElementById('send-button');
    const buttonIcon = document.getElementById('button-icon');
    const buttonLoader = document.getElementById('button-loader');
    
    buttonIcon.classList.add('hidden');
    buttonLoader.classList.remove('hidden');
    sendButton.disabled = true;

    ui.displayMessage('user', userMessage);
    const originalMessage = input.value;
    input.value = '';
    
    const loadingIndicator = ui.showLoadingIndicator();

    try {
        const response = await api.processUserMessage(userMessage, currentConversationId);
        ui.displayMessage('ai', response.finalOutput, new Date(), response.messageId, null, (p) => ui.showModal('conscience', p));
        if (response.newTitle) {
            const link = document.querySelector(`#convo-list a[data-id="${currentConversationId}"] span`);
            if (link) link.textContent = response.newTitle;
        }
        if (response.messageId) pollForAuditResults(response.messageId).catch(console.error);
    } catch (error) {
        ui.displayMessage('ai', 'Sorry, an error occurred.');
        input.value = originalMessage;
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
        if(loadingIndicator) loadingIndicator.remove();
        buttonIcon.classList.remove('hidden');
        buttonLoader.classList.add('hidden');
        sendButton.disabled = false;
        input.focus();
    }
}

async function handleRename(id, oldTitle) {
    const newTitle = prompt('Enter new name:', oldTitle);
    if (newTitle && newTitle.trim() !== oldTitle) {
        try {
            await api.renameConversation(id, newTitle);
            ui.showToast('Renamed successfully.', 'success');
            await loadConversations();
        } catch (error) {
            ui.showToast('Could not rename.', 'error');
        }
    }
}

async function handleDelete(id) {
    if (confirm('Delete this conversation forever?')) {
        try {
            await api.deleteConversation(id);
            ui.showToast('Conversation deleted.', 'success');
            if (id === state.getState().currentConversationId) {
                state.setCurrentConversationId(null);
            }
            await loadConversations();
        } catch (error) {
            ui.showToast('Could not delete.', 'error');
        }
    }
}

async function handleLogout() {
    await fetch(api.urls.LOGOUT, { method: 'POST' });
    window.location.reload();
}

async function handleDeleteAccount() {
    try {
        await api.deleteAccount();
        ui.showToast('Account deleted.', 'success');
        setTimeout(() => window.location.reload(), 1500);
    } catch (error) {
        ui.showToast(error.message, 'error');
    } finally {
        ui.closeModal();
    }
}

async function handleProfileChange(event) {
    const newProfileKey = event.target.value;
    try {
        await api.updateUserProfile(newProfileKey);
        const { availableProfiles } = state.getState();
        const selected = availableProfiles.find(p => p.key === newProfileKey);
        ui.showToast(`Profile switched to ${selected.name}.`, 'success');
        await checkLoginStatus(); // Re-initialize to get new profile details
    } catch (error) {
        ui.showToast('Could not switch profile.', 'error');
    }
}

function handleExamplePromptClick(promptText) {
    const input = ui.elements.messageInput();
    if(input) input.value = promptText;
    sendMessage();
}

export async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        const user = (me && me.ok) ? me.user : null;
        state.setUser(user);

        let profiles = [], activeKey = null;
        if (user) {
            const profileResponse = await api.fetchAvailableProfiles();
            profiles = profileResponse.available || [];
            activeKey = user.active_profile || (profiles[0] ? profiles[0].key : null);
            state.setAvailableProfiles(profiles);
            state.setActiveProfileData(profileResponse.active_details || {});
        }
        
        updateUIForAuthState(user, profiles, activeKey);

        if (user) {
            await loadConversations();
        }
    } catch (error) {
        updateUIForAuthState(null);
    }
}

export function attachEventListeners() {
    // This function uses event delegation on the document body to reduce
    // the number of listeners attached directly to elements, especially
    // for dynamically created content.
    document.body.addEventListener('click', (e) => {
        const target = e.target;
        const button = target.closest('button');
        if (!button) return;

        const id = button.id;
        if (id === 'login-button') window.location.href = api.urls.LOGIN;
        if (id === 'send-button') sendMessage();
        if (id === 'new-chat-button') {
            startNewConversation();
            if (window.innerWidth < 768) ui.closeSidebar();
        }
        if (id === 'menu-toggle') ui.openSidebar();
        if (id === 'close-sidebar-button') ui.closeSidebar();
        if (id === 'logout-button') handleLogout();
        if (id === 'delete-account-btn') ui.showModal('delete');
        if (id === 'confirm-delete-btn') handleDeleteAccount();
        if (id === 'cancel-delete-btn' || id === 'close-conscience-modal') ui.closeModal();
        
        if (id === 'settings-button') ui.elements.settingsDropdown()?.classList.toggle('hidden');
        if (id === 'theme-toggle') {
            document.documentElement.classList.toggle('dark');
            localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        }
    });

    // Specific listeners for elements that need them
    ui.elements.messageInput()?.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }});
    document.getElementById('sidebar-overlay')?.addEventListener('click', ui.closeSidebar);
    ui.elements.modalBackdrop()?.addEventListener('click', ui.closeModal);
    
    // Use delegation for profile selector change
    document.body.addEventListener('change', (e) => {
        if (e.target.id === 'profile-selector') {
            handleProfileChange(e);
        }
    });

    // Hide settings dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const menu = ui.elements.settingsMenu();
        if (menu && !menu.contains(e.target)) {
            ui.elements.settingsDropdown()?.classList.add('hidden');
        }
    });
}
