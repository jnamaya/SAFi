// js/events.js
// Handles user interactions, API calls, and application logic.

import * as api from './api.js';
import * as ui from './ui/index.js';
import * as state from './state.js';

/**
 * This is the main initialization function for the entire application.
 */
async function initializeApp() {
    // First, check the login status and render the initial UI.
    await checkLoginStatus();
    
    // Now that the UI is built, attach listeners to the core, static elements.
    attachStaticEventListeners();
}

/**
 * Attaches event listeners to static elements that are always present in the HTML.
 */
function attachStaticEventListeners() {
    ui.elements.sendButton()?.addEventListener('click', sendMessage);
    ui.elements.messageInput()?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    ui.elements.messageInput()?.addEventListener('input', handleInput);
    ui.elements.menuToggle()?.addEventListener('click', ui.openSidebar);
    
    // Modals
    ui.elements.closeConscienceModalBtn()?.addEventListener('click', ui.closeModal);
    ui.elements.cancelDeleteBtn()?.addEventListener('click', ui.closeModal);
    ui.elements.modalBackdrop()?.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteBtn()?.addEventListener('click', eventHandlers.deleteAccountHandler);

    // Add a document-level listener to close the settings dropdown when clicking outside
    document.addEventListener('click', (event) => {
        const settingsMenu = document.getElementById('settings-menu');
        if (settingsMenu && !settingsMenu.contains(event.target)) {
            document.getElementById('settings-dropdown')?.classList.add('hidden');
        }
    });
}

/**
 * Checks the user's login status and renders the appropriate UI.
 */
async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        const user = (me && me.ok) ? me.user : null;
        
        const profilesResponse = await api.fetchAvailableProfiles();
        state.setState({
            user,
            availableProfiles: profilesResponse.available || [],
            activeProfile: profilesResponse.active_details || {},
        });

        const currentAppState = state.getState();
        // The UI rendering function no longer needs handlers passed to it.
        ui.updateUIForAuthState(
            currentAppState.user, 
            currentAppState.availableProfiles, 
            currentAppState.activeProfile?.key
        );

        if (user) {
            await loadConversations();
        } else {
            ui.displayGuestWelcome();
        }
    } catch (error) {
        console.error("Failed to initialize app:", error);
        ui.updateUIForAuthState(null, [], null);
        ui.displayGuestWelcome();
    }
}

/**
 * Handles the logic for sending a user's message.
 */
async function sendMessage() {
    const { user, currentConversationId } = state.getState();

    if (!user) {
        eventHandlers.loginHandler();
        return;
    }

    const messageInput = ui.elements.messageInput();
    const sendButton = ui.elements.sendButton();
    const userMessage = messageInput.value.trim();

    if (!userMessage || !currentConversationId || !sendButton) return;

    sendButton.disabled = true;
    ui.displayMessage('user', userMessage);
    messageInput.value = '';
    
    const loadingIndicator = ui.showLoadingIndicator();

    try {
        const response = await api.processUserMessage(userMessage, currentConversationId);
        if (response.newTitle) {
            const link = document.querySelector(`#convo-list a[data-id="${currentConversationId}"] span`);
            if (link) link.textContent = response.newTitle;
        }
        ui.displayMessage('ai', response.finalOutput, new Date(), response.messageId, null, (p) => ui.showModal('conscience', p));
    } catch (error) {
        ui.displayMessage('ai', 'Sorry, an error occurred.');
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
        loadingIndicator?.remove();
        sendButton.disabled = false;
        messageInput.focus();
    }
}

/**
 * Loads the list of conversations for a logged-in user.
 */
async function loadConversations(switchToId = null) {
    try {
        const conversations = await api.fetchConversations();
        const convoList = document.getElementById('convo-list');
        if (!convoList) return;

        convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>`;
        if (conversations?.length > 0) {
            conversations.forEach(convo => {
                const link = ui.renderConversationLink(convo, eventHandlers);
                convoList.appendChild(link);
            });
            const targetId = switchToId || state.getState().currentConversationId || conversations[0].id;
            await switchConversation(targetId);
        } else {
            await startNewChat();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
    }
}

/**
 * Switches the active conversation view.
 */
async function switchConversation(id) {
    state.setState({ currentConversationId: id });
    ui.setActiveConvoLink(id);
    ui.resetChatView();

    try {
        const history = await api.fetchHistory(id);
        if (history?.length > 0) {
            history.forEach(turn => ui.displayMessage(turn.role, turn.content, new Date(turn.timestamp)));
        } else {
            const { activeProfile } = state.getState();
            ui.displayEmptyStateForUser(activeProfile, handleExamplePromptClick);
        }
    } catch (error) {
        console.error('Failed to switch conversation:', error);
    }
}

/**
 * Creates a new chat and switches to it.
 */
async function startNewChat() {
    try {
        const newConvo = await api.createNewConversation();
        await loadConversations(newConvo.id);
    } catch (error) {
        console.error('Failed to create new conversation:', error);
    }
}

// Export the event handlers so the UI modules can import them directly.
export const eventHandlers = {
    loginHandler: () => { window.location.href = api.urls.LOGIN; },
    logoutHandler: async () => {
        await fetch(api.urls.LOGOUT, { method: 'POST' });
        window.location.reload();
    },
    deleteAccountHandler: async () => {
        try {
            await api.deleteAccount();
            window.location.reload();
        } catch(e) {
            ui.showToast('Could not delete account.', 'error');
        } finally {
            ui.closeModal();
        }
    },
    profileChangeHandler: async (event) => {
        await api.updateUserProfile(event.target.value);
        initializeApp(); 
    },
    newChatHandler: () => {
        const { user } = state.getState();
        if (user) {
            startNewChat();
        } else {
            ui.elements.messageInput()?.focus();
        }
        if (window.innerWidth < 768) ui.closeSidebar();
    },
    switchHandler: switchConversation,
    renameHandler: async (id, oldTitle) => {
        const newTitle = prompt('Enter new name:', oldTitle);
        if (newTitle && newTitle.trim() !== oldTitle) {
            await api.renameConversation(id, newTitle);
            loadConversations();
        }
    },
    deleteHandler: async (id) => {
        if (confirm('Are you sure?')) {
            await api.deleteConversation(id);
            if (id === state.getState().currentConversationId) {
                state.setState({ currentConversationId: null });
            }
            loadConversations();
        }
    },
};

function handleExamplePromptClick(promptText) {
    const messageInput = ui.elements.messageInput();
    if(messageInput) {
        messageInput.value = promptText;
        sendMessage();
    }
}

function handleInput() {
    const messageInput = ui.elements.messageInput();
    const sendButton = ui.elements.sendButton();
    if (!messageInput || !sendButton) return;

    const hasText = messageInput.value.trim().length > 0;
    sendButton.disabled = !hasText;
}

export { initializeApp };

