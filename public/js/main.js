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
        // Add back the "History" heading after clearing
        ui.elements.convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>`;

        if (conversations?.length > 0) {
            const currentConvoExists = conversations.some(c => c.id === currentConversationId);
            const targetConvoId = (currentConversationId && currentConvoExists) ? currentConversationId : conversations[0].id;
            
            const handlers = {
                switchHandler: switchConversation,
                renameHandler: handleRename,
                deleteHandler: handleDelete
            };
            conversations.forEach(convo => ui.renderConversationLink(convo, handlers));
            await switchConversation(targetConvoId);
        } else {
            await startNewConversation();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
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
            const link = document.querySelector(`#convo-list a[data-id="${currentConversationId}"] span`);
            if (link) link.textContent = initialResponse.newTitle;
        }
        
        if (initialResponse.messageId) {
            pollForAuditResults(initialResponse.messageId);
        }
        
    } catch (error) {
        loadingIndicator.remove();
        ui.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
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

async function handleRename(id, oldTitle) {
    const newTitle = prompt('Enter new name for the conversation:', oldTitle);
    if (newTitle && newTitle.trim() !== oldTitle) {
        try {
            await api.renameConversation(id, newTitle);
            ui.showToast('Conversation renamed.', 'success');
            await loadConversations();
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
        }
    }
}

async function handleDelete(id) {
    if (confirm('Are you sure you want to delete this conversation?')) {
        try {
            await api.deleteConversation(id);
            ui.showToast('Conversation deleted.', 'success');
            if (id === currentConversationId) {
                currentConversationId = null;
            }
            await loadConversations();
        } catch (error) {
            ui.showToast('Could not delete conversation.', 'error');
        }
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
    checkLoginStatus();

    ui.elements.sendButton.disabled = true;
    ui.elements.messageInput.addEventListener('input', autoSize);

    ui.elements.loginButton.addEventListener('click', () => { window.location.href = api.urls.LOGIN; });
    ui.elements.sendButton.addEventListener('click', sendMessage);
    ui.elements.messageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    ui.elements.newChatButton.addEventListener('click', () => { startNewConversation(); if (window.innerWidth < 768) ui.closeSidebar(); });
    
    ui.elements.menuToggle.addEventListener('click', ui.openSidebar);
    ui.elements.closeSidebarButton.addEventListener('click', ui.closeSidebar);
    ui.elements.sidebarOverlay.addEventListener('click', ui.closeSidebar);
    ui.elements.closeConscienceModalBtn.addEventListener('click', ui.closeModal);
    ui.elements.cancelDeleteBtn.addEventListener('click', ui.closeModal);
    ui.elements.modalBackdrop.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteBtn.addEventListener('click', handleDeleteAccount);
    
    document.addEventListener('click', (event) => {
        const settingsMenu = document.getElementById('settings-menu');
        const settingsDropdown = document.getElementById('settings-dropdown');
        if (settingsMenu && !settingsMenu.contains(event.target)) {
            settingsDropdown?.classList.add('hidden');
        }
    });

    ui.elements.userProfileContainer.addEventListener('click', (event) => {
        const settingsButton = event.target.closest('#settings-button');
        if (settingsButton) {
            const settingsDropdown = document.getElementById('settings-dropdown');
            settingsDropdown?.classList.toggle('hidden');
        }
    });
    
    new ResizeObserver(() => { ui.scrollToBottom(); }).observe(ui.elements.composerFooter);
    window.addEventListener('resize', () => { ui.scrollToBottom(); });
}

document.addEventListener('DOMContentLoaded', initializeApp);
