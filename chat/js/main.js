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

// MODIFICATION: Removed old thinkingTimeouts array
// let thinkingTimeouts = [];

async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        user = (me && me.ok) ? me.user : null;
        
        // MODIFICATION: 3.1. Updated auth UI call with theme handler
        ui.updateUIForAuthState(
            user, 
            handleLogout, 
            () => ui.showModal('delete'),
            applyTheme // Pass the new theme handler
        );
        
        if (user) {
            const [profilesResponse, modelsResponse] = await Promise.all([
                api.fetchAvailableProfiles(),
                api.fetchAvailableModels()
            ]);
            
            availableProfiles = profilesResponse.available || [];
            availableModels = modelsResponse.models || [];
            
            const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
            
            activeProfileData = availableProfiles.find(p => p.key === currentProfileKey) || availableProfiles[0] || {};
            
            // MODIFICATION: 1.1. Render control panel content on load
            renderControlPanel();
            
            await loadConversations();
        }
        attachEventListeners();
    } catch (error) {
        console.error("Failed to check login status:", error);
        ui.updateUIForAuthState(null, handleLogout, () => ui.showModal('delete'), applyTheme);
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

// MODIFICATION: 1.1. New function to render CP content
function renderControlPanel() {
    if (!user) return;
    
    ui.renderSettingsProfileTab(
        availableProfiles, 
        activeProfileData.key, 
        handleProfileChange
    );
    
    ui.renderSettingsModelsTab(
        availableModels, 
        user, 
        handleModelsSave
    );

    // MODIFICATION: 3.1. Render new App Settings tab
    ui.renderSettingsAppTab(
        localStorage.theme || 'system',
        applyTheme,
        handleLogout,
        () => ui.showModal('delete') // Open delete account modal
    );
    
    // Dashboard tab is lazy-loaded on click
}

// MODIFICATION: 1.2. New handler for App Settings modal
// MODIFICATION: 3.1. This is now removed
// function handleOpenAppSettingsModal() { ... }

// MODIFICATION: 1.1. handleOpenSettingsModal is GONE

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

// MODIFICATION: 3.1. Replaced handleThemeToggle with applyTheme
/**
 * Applies the selected theme and saves it to localStorage.
 * @param {'light' | 'dark' | 'system'} theme 
 */
function applyTheme(theme) {
    if (theme === 'system') {
        localStorage.removeItem('theme');
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
    } else if (theme === 'dark') {
        localStorage.theme = 'dark';
        document.documentElement.classList.add('dark');
    } else {
        localStorage.theme = 'light';
        document.documentElement.classList.remove('dark');
    }

    // Re-render the settings tab if it's open to update the radio buttons
    if (ui.elements.controlPanelView && !ui.elements.controlPanelView.classList.contains('hidden')) {
        const currentActiveTab = document.querySelector('.modal-tab-button.active');
        if (currentActiveTab && currentActiveTab.id === 'cp-nav-app-settings') {
            ui.renderSettingsAppTab(
                theme,
                applyTheme,
                handleLogout,
                () => ui.showModal('delete')
            );
        }
    }
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
    // MODIFICATION: 1.1. Hide Control Panel when starting new chat
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');
    // END MODIFICATION

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
        ui.updateChatTitle('New Chat'); // <-- MODIFICATION: Update title

        // Show the empty state greeting
        const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
        ui.displaySimpleGreeting(firstName);
        ui.displayEmptyState(activeProfileData, handleExamplePromptClick);
    }
}


async function switchConversation(id) {
    // MODIFICATION: 2.7. Hide Control Panel on conversation switch
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');
    
    currentConversationId = id;
    ui.setActiveConvoLink(id);
    ui.resetChatView();
    // MODIFICATION: 1.3. Update profile chip on switch
    ui.updateActiveProfileChip(activeProfileData.name || 'Default');

    // MODIFICATION: Update chat title
    try {
        const activeLink = document.querySelector(`#convo-list a[data-id="${id}"]`);
        const title = activeLink ? activeLink.querySelector('.convo-title').textContent : 'SAFi';
        ui.updateChatTitle(title);
    } catch (e) {
        console.warn('Could not set chat title', e);
        ui.updateChatTitle('SAFi'); // Fallback
    }
    // END MODIFICATION

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

// MODIFICATION: 2.1. Helper to clear timeouts - REMOVED
// function clearThinkingTimeouts() { ... }

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
    
    // *** 1. START SIMULATION ***
    // MODIFICATION: Pass active profile name to loading indicator
    const loadingIndicator = ui.showLoadingIndicator(activeProfileData.name);
    
    // MODIFICATION: Removed all old static setTimeout logic

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
            // *** 3. PROVIDE FALLBACK ***
            profile: initialResponse.profile || activeProfileData.name || null,
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
          initialPayload, // Pass the payload
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
                    // MODIFICATION: Update title after list refresh
                    ui.updateChatTitle(initialResponse.newTitle);
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
        // *** 2. STOP SIMULATION ***
        ui.clearLoadingInterval();
        
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
            if (id === currentConversationId) {
                ui.updateChatTitle(newTitle); // MODIFICATION: Update title if active
            }
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

    // MODIFICATION: 1.1. Added Control Panel button listener
    const controlPanelButton = document.getElementById('control-panel-btn');
    if (controlPanelButton) {
        controlPanelButton.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            if (window.innerWidth < 768) ui.closeSidebar();
        });
    }
    if (ui.elements.controlPanelBackButton) {
        ui.elements.controlPanelBackButton.addEventListener('click', () => {
            ui.elements.controlPanelView.classList.add('hidden');
            ui.elements.chatView.classList.remove('hidden');
        });
    }
    // MODIFICATION: 1.3. Added Active Profile Chip listeners
    if (ui.elements.activeProfileChip) {
        ui.elements.activeProfileChip.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            // Programmatically click profile tab
            if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
        });
    }
    if (ui.elements.activeProfileChipMobile) {
        ui.elements.activeProfileChipMobile.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            // Programmatically click profile tab
            if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
        });
    }
    // END MODIFICATION

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
    
    // MODIFICATION: 1.1. Removed settings modal listener
    // MODIFICATION: 3.1. Removed appSettingsModal listener
    ui.setupControlPanelTabs(); // Replaced setupSettingsTabs
    
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
    
    // MODIFICATION: 3.1. Removed settingsMenu listener
    
    document.addEventListener('click', (event) => {
        // MODIFICATION: 3.1. Removed settingsMenu click-away
        
        const convoMenuButton = event.target.closest('.convo-menu-button');
        if (!convoMenuButton) {
            ui.closeAllConvoMenus();
        }
    });
}

document.addEventListener('DOMContentLoaded', checkLoginStatus);