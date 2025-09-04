import * as api from './api.js';
import * as ui from './ui.js';
import * as utils from './utils.js';

let currentConversationId = null;
let user = null; // Store user object
let activeProfileData = {}; // Stores the full profile details
let availableProfiles = []; // Stores the list of profile objects {key, name}

async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        user = (me && me.ok) ? me.user : null;
        
        ui.updateUIForAuthState(user, handleLogout, handleProfileChange);
        
        if (user) {
            const profilesResponse = await api.fetchAvailableProfiles();
            availableProfiles = profilesResponse.available || [];
            
            const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
            
            activeProfileData = profilesResponse.active_details || {};
            
            ui.populateProfileSelector(availableProfiles, currentProfileKey);
            
            await loadConversations();
        }
        attachEventListeners();
    } catch (error) {
        console.error("Failed to check login status:", error);
        ui.updateUIForAuthState(null);
        attachEventListeners();
    }
}

async function handleProfileChange(event) {
    const newProfileName = event.target.value;
    try {
        await api.updateUserProfile(newProfileName);
        const selectedProfile = availableProfiles.find(p => p.key === newProfileName);
        ui.showToast(`Profile switched to ${selectedProfile.name}`, 'success');
        
        await checkLoginStatus();

    } catch (error) {
        console.error('Failed to switch profile:', error);
        ui.showToast('Could not switch profile.', 'error');
        event.target.value = activeProfileData.name ? activeProfileData.name.toLowerCase() : '';
    }
}


async function loadConversations(switchToId = null) {
    try {
        const conversations = await api.fetchConversations();
        const convoList = document.getElementById('convo-list');
        if (!convoList) return;
        
        convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>`;

        if (conversations?.length > 0) {
            const handlers = {
                switchHandler: switchConversation,
                renameHandler: handleRename,
                deleteHandler: handleDelete
            };
            conversations.forEach(convo => {
                const link = ui.renderConversationLink(convo, handlers);
                convoList.appendChild(link);
            });

            const targetConvoId = switchToId 
                ? switchToId
                : (currentConversationId && conversations.some(c => c.id === currentConversationId))
                    ? currentConversationId
                    : conversations[0].id;
            
            await switchConversation(targetConvoId);
        } else {
            await startNewConversation(true);
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
    }
}

async function startNewConversation(isInitialLoad = false) {
    try {
        const newConvo = await api.createNewConversation();
        
        if (isInitialLoad) {
            const convoList = document.getElementById('convo-list');
            const handlers = { switchHandler: switchConversation, renameHandler: handleRename, deleteHandler: handleDelete };
            const link = ui.renderConversationLink(newConvo, handlers);
            convoList.appendChild(link);
            await switchConversation(newConvo.id);
        } else {
            await loadConversations(newConvo.id);
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
                const date = turn.timestamp ? new Date(turn.timestamp) : new Date();
                
                const ledger = typeof turn.conscience_ledger === 'string' ? JSON.parse(turn.conscience_ledger) : turn.conscience_ledger;
                const values = typeof turn.profile_values === 'string' ? JSON.parse(turn.profile_values) : turn.profile_values;

                const payload = {
                    ledger: ledger || [],
                    profile: turn.profile_name,
                    values: values || [],
                    spirit_score: turn.spirit_score,
                    spirit_scores_history: history.slice(0, i + 1).map(t => t.spirit_score)
                };

                const options = {};
                if (turn.role === 'user' && user) {
                    options.avatarUrl = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
                }

                ui.displayMessage(
                    turn.role, 
                    turn.content, 
                    date, 
                    turn.message_id,
                    payload,
                    (p) => ui.showModal('conscience', p),
                    options
                );
            });
        } else {
            ui.displayEmptyState(activeProfileData, handleExamplePromptClick);
        }
        
        ui.scrollToBottom();
    } catch (error) {
        console.error('Failed to switch conversation:', error);
        ui.showToast('Could not load chat history.', 'error');
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

    const buttonIcon = document.getElementById('button-icon');
    const buttonLoader = document.getElementById('button-loader');
    
    buttonIcon.classList.add('hidden');
    buttonLoader.classList.remove('hidden');
    ui.elements.sendButton.disabled = true;
    
    const now = new Date();
    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    ui.displayMessage('user', userMessage, now, null, null, null, { avatarUrl: pic });
    
    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    
    const loadingIndicator = ui.showLoadingIndicator();
    const thinkingStatus = loadingIndicator.querySelector('#thinking-status');

    // --- CHANGE: Removed the long safiLoop array and setInterval ---

    // --- CHANGE: Added a simple timeout to change text if response is slow ---
    const thinkingTimeout = setTimeout(() => {
        if (thinkingStatus) {
            thinkingStatus.textContent = 'Still thinking...';
        }
    }, 4000); // 4 seconds

    try {
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId);
        
        ui.displayMessage(
          'ai',
          initialResponse.finalOutput,
          new Date(),
          initialResponse.messageId,
          null, 
          (payload) => ui.showModal('conscience', payload)
        );

        if (initialResponse.newTitle) {
            const link = document.querySelector(`#convo-list a[data-id="${currentConversationId}"] span`);
            if (link) link.textContent = initialResponse.newTitle;
        }
        
        if (initialResponse.messageId) {
            pollForAuditResults(initialResponse.messageId);
        }
        
    } catch (error) {
        ui.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
        // --- CHANGE: Clear the new timeout instead of the old interval ---
        clearTimeout(thinkingTimeout);
        if(loadingIndicator) loadingIndicator.remove();
        buttonIcon.classList.remove('hidden');
        buttonLoader.classList.add('hidden');
        ui.elements.sendButton.disabled = false;
        ui.elements.messageInput.focus();
    }
}

function pollForAuditResults(messageId, maxAttempts = 10, interval = 2000) {
    let attempts = 0;

    const executePoll = async (resolve, reject) => {
        const result = await api.fetchAuditResult(messageId);
        attempts++;

        if (result && result.status === 'complete') {
            const ledger = typeof result.ledger === 'string' ? JSON.parse(result.ledger) : result.ledger;
            const values = typeof result.values === 'string' ? JSON.parse(result.values) : result.values;

            const history = await api.fetchHistory(currentConversationId);
            const currentTurnIndex = history.findIndex(t => t.message_id === messageId);

            const payload = {
                ledger: ledger || [],
                profile: result.profile || null,
                values: values || [],
                spirit_score: result.spirit_score,
                spirit_scores_history: history.slice(0, currentTurnIndex + 1).map(t => t.spirit_score)
            };
            
            ui.updateMessageWithAudit(messageId, payload, (p) => ui.showModal('conscience', p));
            resolve(result);
        } else if (attempts >= maxAttempts) {
            reject(new Error('Polling timed out.'));
        } else {
            setTimeout(() => executePoll(resolve, reject), interval);
        }
    };

    return new Promise(executePoll);
}

function autoSize() {
    const input = ui.elements.messageInput;
    if (!input) return;

    const sendButton = ui.elements.sendButton;

    const hasText = input.value.trim().length > 0;
    sendButton.disabled = !hasText;

    input.style.height = 'auto';
    const newHeight = input.scrollHeight;
    input.style.height = `${newHeight}px`;
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

function attachEventListeners() {
    if (ui.elements.loginButton) {
        ui.elements.loginButton.addEventListener('click', () => { window.location.href = api.urls.LOGIN; });
    }

    if (ui.elements.sendButton) {
        ui.elements.sendButton.addEventListener('click', sendMessage);
        ui.elements.messageInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
        ui.elements.messageInput.addEventListener('input', autoSize);
    }
    
    const newChatButton = document.getElementById('new-chat-button');
    if (newChatButton) {
        newChatButton.addEventListener('click', () => { startNewConversation(); if (window.innerWidth < 768) ui.closeSidebar(); });
    }

    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) {
        menuToggle.addEventListener('click', ui.openSidebar);
    }
    
    const closeSidebarButton = document.getElementById('close-sidebar-button');
    if(closeSidebarButton) {
        closeSidebarButton.addEventListener('click', ui.closeSidebar);
    }

    const sidebarOverlay = document.getElementById('sidebar-overlay');
    if(sidebarOverlay) {
        sidebarOverlay.addEventListener('click', ui.closeSidebar);
    }
    
    document.getElementById('close-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('got-it-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('cancel-delete-btn')?.addEventListener('click', ui.closeModal);
    document.getElementById('modal-backdrop')?.addEventListener('click', ui.closeModal);
    document.getElementById('confirm-delete-btn')?.addEventListener('click', handleDeleteAccount);
    
    const settingsMenu = document.getElementById('settings-menu');
    if (settingsMenu) {
        settingsMenu.addEventListener('click', (event) => {
            const settingsButton = event.target.closest('#settings-button');
            if (settingsButton) {
                const settingsDropdown = document.getElementById('settings-dropdown');
                settingsDropdown?.classList.toggle('hidden');
            }
        });
    }

    document.addEventListener('click', (event) => {
        const settingsMenu = document.getElementById('settings-menu');
        const settingsDropdown = document.getElementById('settings-dropdown');
        if (settingsMenu && !settingsMenu.contains(event.target)) {
            settingsDropdown?.classList.add('hidden');
        }
    });
}

document.addEventListener('DOMContentLoaded', checkLoginStatus);
