import * as api from './api.js';
import * as ui from './ui.js';
import * as utils from './utils.js';

let currentConversationId = null;
const msgCountByConvo = {};
let activeProfileData = {}; // Stores the full profile details
let availableProfiles = []; // Stores the list of profile names

function getMsgCount(id) { return msgCountByConvo[id] ?? 0; }
function bumpMsgCount(id) { msgCountByConvo[id] = getMsgCount(id) + 1; }

async function checkLoginStatus() {
    const me = await api.getMe();
    const user = (me && me.ok) ? me.user : null;
    
    ui.updateUIForAuthState(user, handleLogout, handleProfileChange);
    
    if (user) {
        activeProfileData = user.active_profile_details || {};
        
        const profilesResponse = await api.fetchAvailableProfiles();
        availableProfiles = profilesResponse.available || [];
        const currentProfileKey = user.active_profile || availableProfiles[0];
        
        ui.populateProfileSelector(availableProfiles, currentProfileKey);
        
        await loadConversations();
    }
    
    const isOnline = await api.checkConnection();
    ui.updateConnectionStatus(isOnline);
}

async function handleProfileChange(event) {
    const newProfileName = event.target.value;
    try {
        await api.updateUserProfile(newProfileName);
        ui.showToast(`Profile switched to ${newProfileName}`, 'success');
        
        await checkLoginStatus();

    } catch (error) {
        console.error('Failed to switch profile:', error);
        ui.showToast('Could not switch profile.', 'error');
        event.target.value = activeProfileData.name ? activeProfileData.name.toLowerCase() : '';
    }
}


async function loadConversations() {
    try {
        const conversations = await api.fetchConversations();
        ui.elements.convoList.innerHTML = '';
        if (conversations?.length > 0) {
            const currentConvoExists = conversations.some(c => c.id === currentConversationId);
            const targetConvoId = (currentConversationId && currentConvoExists) ? currentConversationId : conversations[0].id;
            
            conversations.forEach(convo => ui.renderConversationLink(convo, switchConversation, showOptionsMenu));
            await switchConversation(targetConvoId);
        } else {
            await startNewConversation();
        }
        ui.updateConnectionStatus(true);
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
        ui.updateConnectionStatus(false);
    }
}

async function startNewConversation() {
    try {
        const newConvo = await api.createNewConversation();
        await loadConversations();
        if (newConvo && newConvo.id) {
            await switchConversation(newConvo.id);
        }
    } catch (error) {
        console.error('Failed to create new conversation:', error);
        ui.showToast('Could not start a new chat.', 'error');
    }
}

async function switchConversation(id) {
    currentConversationId = id;
    ui.setActiveConvoLink(id);
    ui.resetChatView();

    try {
        const history = await api.fetchHistory(id);
        
        if (history?.length > 0) {
            history.forEach((turn, i) => {
                const dateString = turn.timestamp;
                const date = dateString 
                    ? new Date(dateString.replace(' ', 'T') + 'Z') 
                    : utils.getOrInitTimestamp(id, i, turn.role, turn.content);
                
                // --- CHANGE: The payload for the modal now uses historical data from the 'turn' object ---
                const payload = {
                    ledger: turn.conscience_ledger || [],
                    profile: turn.profile_name,
                    values: turn.profile_values,
                    spirit_score: turn.spirit_score 
                };

                ui.displayMessage(
                    turn.role, 
                    turn.content, 
                    date, 
                    turn.message_id,
                    payload,
                    (p) => ui.showModal('conscience', p)
                );
            });
        } else {
            ui.displayEmptyState(activeProfileData, handleExamplePromptClick);
        }
        
        msgCountByConvo[id] = history?.length || 0;
        ui.scrollToBottom();
    } catch (error) {
        console.error('Failed to switch conversation:', error);
        ui.showToast('Could not load chat history.', 'error');
        ui.displayEmptyState(activeProfileData, handleExamplePromptClick);
    }
}

function handleExamplePromptClick(promptText) {
    ui.elements.messageInput.value = promptText;
    sendMessage();
    autoSize();
}

async function sendMessage() {
    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage || !currentConversationId) return;
    
    const now = new Date();
    ui.displayMessage('user', userMessage, now, null, null, null);
    utils.setTimestamp(currentConversationId, getMsgCount(currentConversationId), 'user', userMessage, now);
    bumpMsgCount(currentConversationId);

    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    
    const loadingIndicator = ui.showLoadingIndicator();

    try {
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId);
        loadingIndicator.remove();
        
        const aiNow = new Date();
        
        ui.displayMessage(
          'ai',
          initialResponse.finalOutput,
          aiNow,
          initialResponse.messageId,
          null, 
          (payload) => ui.showModal('conscience', payload)
        );

        utils.setTimestamp(currentConversationId, getMsgCount(currentConversationId), 'ai', initialResponse.finalOutput, aiNow);
        bumpMsgCount(currentConversationId);

        if (initialResponse.newTitle) {
            const link = document.querySelector(`#convo-list div[data-id="${currentConversationId}"] button`);
            if (link) link.textContent = initialResponse.newTitle;
        }
        
        if (initialResponse.messageId) {
            pollForAuditResults(initialResponse.messageId);
        }
        
        ui.updateConnectionStatus(true);
    } catch (error) {
        loadingIndicator.remove();
        ui.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
        ui.updateConnectionStatus(false);
    } finally {
        ui.elements.messageInput.focus();
    }
}

function pollForAuditResults(messageId, maxAttempts = 10, interval = 2000) {
    let attempts = 0;

    const executePoll = async (resolve, reject) => {
        const result = await api.fetchAuditResult(messageId);
        attempts++;

        if (result && result.status === 'complete') {
            // --- CHANGE: The result from the API now contains the correct historical data ---
            const payload = {
                ledger: result.ledger || [],
                profile: result.profile || null,
                values: result.values || [],
                spirit_score: result.spirit_score
            };
            ui.updateMessageWithAudit(messageId, payload, (p) => ui.showModal('conscience', p));
            resolve(result);
        } else if (attempts >= maxAttempts) {
            console.warn(`Stopped polling for message ${messageId} after ${maxAttempts} attempts.`);
            reject(new Error('Polling timed out.'));
        } else {
            setTimeout(() => executePoll(resolve, reject), interval);
        }
    };

    return new Promise(executePoll);
}


function autoSize() {
    const input = ui.elements.messageInput;
    const sendButton = ui.elements.sendButton;

    const hasText = input.value.trim().length > 0;
    sendButton.disabled = !hasText;

    input.style.height = 'auto';
    const scrollHeight = input.scrollHeight;
    const maxHeight = 120; 
    
    input.style.height = `${Math.min(scrollHeight, maxHeight)}px`;

    if (scrollHeight > maxHeight) {
        input.classList.add('overflow-y-auto', 'custom-scrollbar');
    } else {
        input.classList.remove('overflow-y-auto', 'custom-scrollbar');
    }

    ui.scrollToBottom();
}

function showOptionsMenu(event, id, title) {
    event.stopPropagation();
    document.querySelector('.options-menu')?.remove();
    const menu = document.createElement('div');
    menu.className = 'options-menu absolute z-50 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 text-sm py-1';
    menu.style.left = `${event.clientX}px`;
    menu.style.top = `${event.clientY}px`;
    menu.innerHTML = `
        <button class="w-full text-left px-4 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="rename">Rename</button>
        <button class="w-full text-left px-4 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="export">Export</button>
        <button class="w-full text-left px-4 py-2 text-red-600 dark:text-red-500 hover:bg-neutral-100 dark:hover:bg-neutral-600" data-action="delete">Delete</button>`;
    document.body.appendChild(menu);
    menu.addEventListener('click', (e) => {
        const action = e.target.dataset.action;
        if (action === 'rename') handleRename(id, title);
        if (action === 'export') window.open(`${api.urls.CONVERSATIONS}/${id}/export`, '_blank');
        if (action === 'delete') handleDelete(id);
        menu.remove();
    });
    setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
}

async function handleRename(id, oldTitle) {
    const newTitle = prompt('Enter new name for the conversation:', oldTitle);
    if (newTitle && newTitle.trim() !== oldTitle) {
        ui.showToast('Conversation renamed.', 'success');
        await api.renameConversation(id, newTitle);
        await loadConversations();
    }
}

async function handleDelete(id) {
    if (confirm('Are you sure you want to delete this conversation?')) {
        ui.showToast('Conversation deleted.', 'success');
        await api.deleteConversation(id);
        await loadConversations();
    }
}

async function handleLogout() {
    await fetch(api.urls.LOGOUT, { method: 'POST', credentials: 'include' });
    window.location.reload();
}

async function handleDeleteAccount() {
    try {
        await api.deleteAccount();
        ui.showToast('Account deleted successfully.', 'success');
        setTimeout(() => window.location.reload(), 1500);
    } catch (error) {
        ui.showToast(error.message, 'error');
    } finally {
        ui.closeModal();
    }
}

function initializeApp() {
    ui.updateThemeUI();
    checkLoginStatus();
    setInterval(() => api.checkConnection().then(ui.updateConnectionStatus), 60000);

    ui.elements.sendButton.disabled = true;
    ui.elements.messageInput.addEventListener('input', autoSize);

    ui.elements.loginButton.addEventListener('click', () => { window.location.href = api.urls.LOGIN; });
    ui.elements.sendButton.addEventListener('click', sendMessage);
    ui.elements.messageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    ui.elements.newChatButton.addEventListener('click', () => { startNewConversation(); if (window.innerWidth < 768) ui.closeSidebar(); });
    
    ui.elements.themeToggle.addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        ui.updateThemeUI();
    });
    
    ui.elements.menuToggle.addEventListener('click', ui.openSidebar);
    ui.elements.closeSidebarButton.addEventListener('click', ui.closeSidebar);
    ui.elements.sidebarOverlay.addEventListener('click', ui.closeSidebar);
    ui.elements.closeConscienceModalBtn.addEventListener('click', ui.closeModal);
    ui.elements.mobileCloseConscienceModalBtn.addEventListener('click', ui.closeModal);
    ui.elements.cancelDeleteBtn.addEventListener('click', ui.closeModal);
    ui.elements.modalBackdrop.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteBtn.addEventListener('click', handleDeleteAccount);
    
    new ResizeObserver(() => { ui.scrollToBottom(); }).observe(ui.elements.composerFooter);
    window.addEventListener('resize', () => { ui.scrollToBottom(); });
}

document.addEventListener('DOMContentLoaded', initializeApp);
