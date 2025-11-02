import * as api from './api.js';
import * as ui from './ui.js';
import * as utils from './utils.js';

let currentConversationId = null;
let user = null; // Store user object
let activeProfileData = {}; // Stores the full profile details
let availableProfiles = []; // Stores the list of *full profile objects*
let availableModels = []; 

let convoToRename = { id: null, oldTitle: null };
let convoToDelete = null;

async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        user = (me && me.ok) ? me.user : null;
        
        ui.updateUIForAuthState(user, handleLogout, null, handleOpenSettingsModal);
        
        if (user) {
            const [profilesResponse, modelsResponse] = await Promise.all([
                api.fetchAvailableProfiles(),
                api.fetchAvailableModels()
            ]);
            
            availableProfiles = profilesResponse.available || [];
            availableModels = modelsResponse.models || [];
            
            const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
            
            activeProfileData = availableProfiles.find(p => p.key === currentProfileKey) || availableProfiles[0] || {};
            
            await loadConversations();
        }
        attachEventListeners();
    } catch (error) {
        console.error("Failed to check login status:", error);
        ui.updateUIForAuthState(null);
        attachEventListeners();
    }
}

async function handleProfileChange(newProfileName) {
    try {
        await api.updateUserProfile(newProfileName);
        const selectedProfile = availableProfiles.find(p => p.key === newProfileName);
        ui.showToast(`Profile switched to ${selectedProfile.name}. Reloading...`, 'success');
        
        setTimeout(() => window.location.reload(), 1000);

    } catch (error) {
        console.error('Failed to switch profile:', error);
        ui.showToast('Could not switch profile.', 'error');
    }
}

function handleOpenSettingsModal() {
    ui.showModal('settings', {
        user: user,
        profiles: {
            available: availableProfiles,
            active_profile_key: activeProfileData.key
        },
        models: availableModels,
        handlers: {
            profile: handleProfileChange,
            models: handleModelsSave,
            theme: handleThemeToggle,
            logout: handleLogout,
            delete: () => ui.showModal('delete')
        }
    });
}

async function handleModelsSave(newModels) {
    try {
        await api.updateUserModels(newModels);
        ui.showToast('Model preferences saved. Reloading...', 'success');
        
        setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
         console.error('Failed to save models:', error);
        ui.showToast('Could not save model preferences.', 'error');
    }
}

function handleThemeToggle() {
    document.documentElement.classList.toggle('dark');
    localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    
    const updateThemeUI = (scope) => {
        const isDark = document.documentElement.classList.contains('dark');
        const lightIcon = scope.querySelector('#theme-icon-light, #modal-theme-icon-light');
        const darkIcon = scope.querySelector('#theme-icon-dark, #modal-theme-icon-dark');
        const label = scope.querySelector('#modal-theme-label');

        if(lightIcon && darkIcon) {
            lightIcon.style.display = isDark ? 'block' : 'none';
            darkIcon.style.display = isDark ? 'none' : 'block';
        }
        if (label) {
            label.textContent = isDark ? 'Dark Mode' : 'Light Mode';
        }
    };
    
    const dropdown = document.getElementById('settings-dropdown');
    if (dropdown) updateThemeUI(dropdown);
}

async function loadConversations(switchToId = null) {
    try {
        const conversations = await api.fetchConversations();
        const convoList = document.getElementById('convo-list');
        if (!convoList) return;
        
        convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>`;

        if (conversations?.length > 0) {
            const handlers = {
                switchHandler: switchConversation,
                renameHandler: handleRename,
                deleteHandler: handleDelete
            };
            
            conversations.sort((a, b) => {
                const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
                const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
                return dateB - dateA;
            });

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
            await startNewConversation(true); // Pass true for initial load
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
    }
}

async function startNewConversation(isInitialLoad = false) { 
    if (isInitialLoad) {
        // This is the first-ever load and there are no convos.
        // We MUST create one to start with.
        try {
            const newConvo = await api.createNewConversation();
            const convoList = document.getElementById('convo-list');
            const handlers = { switchHandler: switchConversation, renameHandler: handleRename, deleteHandler: handleDelete };
            
            const link = ui.renderConversationLink(newConvo, handlers);
            const listHeading = convoList.querySelector('h3');
            if (listHeading) {
                listHeading.after(link); // Insert after the "Conversations" heading
            } else {
                convoList.appendChild(link); // Fallback
            }
            await switchConversation(newConvo.id);
        } catch (error) {
            console.error('Failed to create initial conversation:', error);
            ui.showToast('Could not start a new chat.', 'error');
        }
    } else {
        // This is a user clicking "New Chat"
        currentConversationId = null;
        ui.setActiveConvoLink(null); // Deselect all conversations
        ui.resetChatView();

        // Show the empty state greeting
        const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
        ui.displaySimpleGreeting(firstName);
        ui.displayEmptyState(activeProfileData, handleExamplePromptClick);
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
            const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
            ui.displaySimpleGreeting(firstName);
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
    if (!userMessage) return; // Don't send empty messages

    let isNewConversation = false;

    if (!currentConversationId) {
        // This is the first message of a new chat. Create it now.
        isNewConversation = true;
        try {
            const newConvo = await api.createNewConversation();
            currentConversationId = newConvo.id; // Set the ID for the rest of the function

            // Manually add this new chat to the sidebar
            const handlers = { switchHandler: switchConversation, renameHandler: handleRename, deleteHandler: handleDelete };
            ui.prependConversationLink(newConvo, handlers);
            ui.setActiveConvoLink(currentConversationId);

        } catch (error) {
            console.error('Failed to create new conversation on send:', error);
            ui.showToast('Could not start a new chat.', 'error');
            return; // Stop if creation fails
        }
    }

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

    const thinkingTimeout = setTimeout(() => {
        if (thinkingStatus) {
            thinkingStatus.textContent = 'Still thinking...';
        }
    }, 4000);

    try {
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId);
        
        const ledger = typeof initialResponse.ledger === 'string' 
            ? JSON.parse(initialResponse.ledger) 
            : initialResponse.ledger;
            
        const values = typeof initialResponse.values === 'string' 
            ? JSON.parse(initialResponse.values) 
            : initialResponse.values;

        const initialPayload = {
            ledger: ledger || [],
            profile: initialResponse.profile || null,
            values: values || [],
            spirit_score: initialResponse.spirit_score,
            spirit_scores_history: [initialResponse.spirit_score] 
        };

        const hasInitialPayload = initialPayload.ledger && initialPayload.ledger.length > 0;
        
        ui.displayMessage(
          'ai',
          initialResponse.finalOutput,
          new Date(),
          initialResponse.messageId,
          hasInitialPayload ? initialPayload : null, 
          (payload) => ui.showModal('conscience', payload)
        );

        if (initialResponse.newTitle) {
            // A new title was generated (either on message 1 or later).
            // We must refresh the list to show the new title.
            // This is now safe because the message is already on-screen.
            try {
                const conversations = await api.fetchConversations();
                const convoList = document.getElementById('convo-list');
                if (convoList) {
                    const handlers = {
                        switchHandler: switchConversation,
                        renameHandler: handleRename,
                        deleteHandler: handleDelete
                    };
                    
                    convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>`;
        
                    conversations.sort((a, b) => {
                        const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
                        const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
                        return dateB - dateA;
                    });
        
                    conversations.forEach(convo => {
                        const link = ui.renderConversationLink(convo, handlers);
                        convoList.appendChild(link);
                    });
                    
                    ui.setActiveConvoLink(currentConversationId);
                }
            } catch (listError) {
                console.error("Failed to refresh conversation list:", listError);
            }
        }

        if (initialResponse.messageId && !hasInitialPayload) {
            pollForAuditResults(initialResponse.messageId);
        }
        
    } catch (error) {
        ui.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
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
        if (!currentConversationId) {
            reject(new Error('Polling stopped, conversation changed.'));
            return;
        }
        
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
            console.warn(`Polling timed out for message ${messageId}.`);
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

function handleRename(id, oldTitle) {
    convoToRename = { id, oldTitle };
    ui.showModal('rename', { oldTitle });
}

async function handleConfirmRename() {
    const { id, oldTitle } = convoToRename;
    const newTitle = ui.elements.renameInput.value.trim();
    
    if (newTitle && newTitle !== oldTitle) {
        try {
            await api.renameConversation(id, newTitle);
            ui.showToast('Conversation renamed.', 'success');
            await loadConversations(id); 
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
        }
    }
    ui.closeModal();
    convoToRename = { id: null, oldTitle: null };
}

function handleDelete(id) {
    convoToDelete = id;
    ui.showModal('delete-convo');
}

async function handleConfirmDelete() {
    const id = convoToDelete;
    if (!id) return;
    
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
    
    ui.closeModal();
    convoToDelete = null;
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
        newChatButton.addEventListener('click', () => { startNewConversation(false); if (window.innerWidth < 768) ui.closeSidebar(); });
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
    
    ui.elements.closeSettingsModal?.addEventListener('click', ui.closeModal);
    ui.setupSettingsTabs();
    
    document.getElementById('close-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('got-it-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('cancel-delete-btn')?.addEventListener('click', ui.closeModal);
    document.getElementById('modal-backdrop')?.addEventListener('click', ui.closeModal);
    document.getElementById('confirm-delete-btn')?.addEventListener('click', handleDeleteAccount);

    ui.elements.cancelRenameBtn?.addEventListener('click', ui.closeModal);
    ui.elements.confirmRenameBtn?.addEventListener('click', handleConfirmRename);
    ui.elements.renameInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleConfirmRename();
        }
    });

    ui.elements.cancelDeleteConvoBtn?.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteConvoBtn?.addEventListener('click', handleConfirmDelete);
    
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
        if (settingsMenu && !settingsMenu.contains(event.target)) {
            document.getElementById('settings-dropdown')?.classList.add('hidden');
        }
        
        const convoMenuButton = event.target.closest('.convo-menu-button');
        if (!convoMenuButton) {
            ui.closeAllConvoMenus();
        }
    });
}

document.addEventListener('DOMContentLoaded', checkLoginStatus);

