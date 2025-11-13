import * as api from './api.js';
import * as ui from './ui.js';
import * as uiRender from './ui-render.js';

// --- CONVERSATION STATE ---
export let currentConversationId = null;
let convoToRename = { id: null, oldTitle: null };
let convoToDelete = null;

// --- CORE CONVERSATION MANAGEMENT ---

export async function loadConversations(activeProfileData, user, promptClickHandler, showModal) {
    try {
        const conversations = await api.fetchConversations();
        const convoList = document.getElementById('convo-list');
        if (!convoList) return;
        
        convoList.innerHTML = `<h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>`;

        if (conversations?.length > 0) {
            const handlers = {
                // Pass user and activeProfileData down
                switchHandler: (id) => switchConversation(id, activeProfileData, user, showModal),
                renameHandler: handleRename,
                deleteHandler: handleDelete
            };
            
            conversations.sort((a, b) => {
                const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
                const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
                return dateB - dateA;
            });

            conversations.forEach(convo => {
                const link = uiRender.renderConversationLink(convo, handlers);
                convoList.appendChild(link);
            });

            const targetConvoId = (currentConversationId && conversations.some(c => c.id === currentConversationId))
                    ? currentConversationId
                    : conversations[0].id;
            
            await switchConversation(targetConvoId, activeProfileData, user, showModal);
        } else {
            // FIX: If no conversations exist on initial load, do NOT create one yet.
            // Just display the empty state, allowing the first message to trigger creation.
            await startNewConversation(false, activeProfileData, user, promptClickHandler); 
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        ui.showToast('Failed to load conversations.', 'error');
    }
}

// Added 'user' parameter
export async function startNewConversation(isInitialLoad = false, activeProfileData, user, promptClickHandler) { 
    // MODIFICATION: Hide Control Panel when starting new chat
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    if (isInitialLoad) {
        // --- REMOVED INITIAL CONVERSATION CREATION LOGIC ---
        // This path is now only used if loadConversations specifically passes true,
        // which currently only happens in the fallback error case.
        try {
            const newConvo = await api.createNewConversation();
            const convoList = document.getElementById('convo-list');
            const handlers = { 
                // Pass user and activeProfileData down
                switchHandler: (id) => switchConversation(id, activeProfileData, user, ui.showModal), 
                renameHandler: handleRename, 
                deleteHandler: handleDelete 
            };
            
            const link = uiRender.renderConversationLink(newConvo, handlers);
            const listHeading = convoList.querySelector('h3');
            if (listHeading) {
                listHeading.after(link); 
            } else {
                convoList.appendChild(link);
            }
            await switchConversation(newConvo.id, activeProfileData, user, ui.showModal);
        } catch (error) {
            console.error('Failed to create initial conversation:', error);
            ui.showToast('Could not start a new chat.', 'error');
        }
    } else {
        // This is the core logic for starting a *truly* new chat.
        currentConversationId = null;
        uiRender.setActiveConvoLink(null);
        uiRender.resetChatView();
        uiRender.updateChatTitle('New Chat');

        // --- MODIFICATION: Ensure profile chip is updated for new chats ---
        uiRender.updateActiveProfileChip(activeProfileData.name || 'Default');
        // --- END MODIFICATION ---

        // FIX: Use the passed 'user' object
        const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
        uiRender.displaySimpleGreeting(firstName);
        uiRender.displayEmptyState(activeProfileData, promptClickHandler);
    }
}


// Added 'user' parameter
export async function switchConversation(id, activeProfileData, user, showModal) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');
    
    currentConversationId = id;
    uiRender.setActiveConvoLink(id);
    uiRender.resetChatView();
    uiRender.updateActiveProfileChip(activeProfileData.name || 'Default');

    try {
        const activeLink = document.querySelector(`#convo-list a[data-id="${id}"]`);
        const title = activeLink ? activeLink.querySelector('.convo-title').textContent : 'SAFi';
        uiRender.updateChatTitle(title);
    } catch (e) {
        console.warn('Could not set chat title', e);
        uiRender.updateChatTitle('SAFi');
    }

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
                // FIX: Use the passed 'user' object
                if (turn.role === 'user' && user) {
                    options.avatarUrl = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
                }
                
                // --- NEW: Handle suggestedPrompts if available in history/storage ---
                // NOTE: suggestedPrompts are not stored in the current schema, but we initialize here
                options.suggestedPrompts = [];
                // --- END NEW ---

                uiRender.displayMessage(
                    turn.role, 
                    turn.content, 
                    date, 
                    turn.message_id,
                    payload,
                    (p) => showModal('conscience', p),
                    options
                );
            });
        } else {
            // FIX: Use the passed 'user' object
            const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
            uiRender.displaySimpleGreeting(firstName);
            // If we switch to a conversation that has no history (e.g., just created), display the empty state
            uiRender.displayEmptyState(activeProfileData, (text) => { 
                // This handler routes back to sendMessage logic for consistency.
                ui.elements.messageInput.value = text;
                ui.elements.sendButton.disabled = false;
                autoSize();
                sendMessage(activeProfileData, user);
            });
        }
        
        ui.scrollToBottom();
    } catch (error) {
        console.error('Failed to switch conversation/load history:', error);
        ui.showToast(`Could not load chat history. Error: ${error.message}`, 'error'); // <-- IMPROVED TOAST MESSAGE
    }
}

// --- MESSAGE FLOW ---

export async function sendMessage(activeProfileData, user) {
    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage) return;

    if (!currentConversationId) {
        try {
            const newConvo = await api.createNewConversation();
            currentConversationId = newConvo.id;

            const handlers = { 
                switchHandler: (id) => switchConversation(id, activeProfileData, user, ui.showModal), 
                renameHandler: handleRename, 
                deleteHandler: handleDelete 
            };
            uiRender.prependConversationLink(newConvo, handlers);
            uiRender.setActiveConvoLink(currentConversationId);

        } catch (error) {
            console.error('Failed to create new conversation on send:', error);
            ui.showToast('Could not start a new chat.', 'error');
            return;
        }
    }

    const buttonIcon = document.getElementById('button-icon');
    const buttonLoader = document.getElementById('button-loader');
    
    buttonIcon.classList.add('hidden');
    buttonLoader.classList.remove('hidden');
    ui.elements.sendButton.disabled = true;
    
    const now = new Date();
    // FIX: Use the passed 'user' object
    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    uiRender.displayMessage('user', userMessage, now, null, null, null, { avatarUrl: pic });
    
    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    
    // START SIMULATION
    const loadingIndicator = uiRender.showLoadingIndicator(activeProfileData.name);

    try {
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId);
        
        const ledger = typeof initialResponse.ledger === 'string' ? JSON.parse(initialResponse.ledger) : initialResponse.ledger;
        const values = typeof initialResponse.values === 'string' ? JSON.parse(initialResponse.values) : initialResponse.values;

        const initialPayload = {
            ledger: ledger || [],
            profile: initialResponse.profile || activeProfileData.name || null,
            values: values || [],
            spirit_score: initialResponse.spirit_score,
            spirit_scores_history: [initialResponse.spirit_score] 
        };
        
        // --- THIS IS THE CRITICAL FIX ---
        // Get suggested prompts, will be [] for approved messages
        const suggestedPrompts = initialResponse.suggestedPrompts || [];

        const options = {
            suggestedPrompts: suggestedPrompts
        };
        // --- END FIX ---

        const hasInitialPayload = initialPayload.ledger && initialPayload.ledger.length > 0;
        
        uiRender.displayMessage(
          'ai',
          initialResponse.finalOutput,
          new Date(),
          initialResponse.messageId,
          initialPayload,
          (payload) => ui.showModal('conscience', payload),
          options // <-- Pass options (including suggestedPrompts) here
        );

        if (initialResponse.newTitle) {
            try {
                // --- THIS IS THE FIX ---
                // We just need to update the title in the sidebar, not reload everything.
                // Reloading wipes the chat window and its suggestions.
                const link = document.querySelector(`#convo-list a[data-id="${currentConversationId}"]`);
                if (link) {
                    const titleEl = link.querySelector('.convo-title');
                    if (titleEl) titleEl.textContent = initialResponse.newTitle;
                }
                // And update the main chat header title
                uiRender.updateChatTitle(initialResponse.newTitle);
                // --- END FIX ---
            } catch (titleError) {
                console.error("Failed to update conversation title:", titleError);
            }
        }

        if (initialResponse.messageId && !hasInitialPayload) {
            pollForAuditResults(initialResponse.messageId);
        }
        
    } catch (error) {
        uiRender.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
        // STOP SIMULATION
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
            
            uiRender.updateMessageWithAudit(messageId, payload, (p) => ui.showModal('conscience', p));
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


export function autoSize() {
    const input = ui.elements.messageInput;
    if (!input) return;

    const sendButton = ui.elements.sendButton;

    const hasText = input.value.trim().length > 0;
    sendButton.disabled = !hasText;

    input.style.height = 'auto';
    const newHeight = input.scrollHeight;
    input.style.height = `${newHeight}px`;
}

// --- CONVERSATION RENAMING/DELETING ---

export function handleRename(id, oldTitle) {
    convoToRename = { id, oldTitle };
    ui.showModal('rename', { oldTitle });
}

export async function handleConfirmRename(activeProfileData, user) {
    const { id, oldTitle } = convoToRename;
    const newTitle = ui.elements.renameInput.value.trim();
    
    if (newTitle && newTitle !== oldTitle) {
        try {
            await api.renameConversation(id, newTitle);
            ui.showToast('Conversation renamed.', 'success');
            // Reload conversations to update sidebar titles
            await loadConversations(activeProfileData, user, () => {}, ui.showModal);
            if (id === currentConversationId) {
                uiRender.updateChatTitle(newTitle);
            }
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
        }
    }
    ui.closeModal();
    convoToRename = { id: null, oldTitle: null };
}

export function handleDelete(id) {
    convoToDelete = id;
    ui.showModal('delete-convo');
}

export async function handleConfirmDelete(activeProfileData, user) {
    const id = convoToDelete;
    if (!id) return;
    
    try {
        await api.deleteConversation(id);
        ui.showToast('Conversation deleted.', 'success');
        if (id === currentConversationId) {
            currentConversationId = null;
        }
        // Reload conversations which automatically switches to the next one or a new chat
        await loadConversations(activeProfileData, user, () => {}, ui.showModal);
    } catch (error) {
        ui.showToast('Could not delete conversation.', 'error');
    }
    
    ui.closeModal();
    convoToDelete = null;
}