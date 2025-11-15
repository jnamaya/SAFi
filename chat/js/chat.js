// Conversation Management Logic:chat.js

import * as api from './api.js';
import * as ui from './ui.js';
import * as uiAuthSidebar from './ui-auth-sidebar.js';
import * as uiMessages from './ui-messages.js';
import * as cache from './cache.js'; // Use cache for optimistic updates
// CHANGE: Import the utility function
import { formatRelativeTime } from './utils.js';


// --- CONVERSATION STATE ---
export let currentConversationId = null;
let convoToRename = { id: null, oldTitle: null };
let convoToDelete = null;

// --- CORE EXPORTED HANDLERS (Fixing ReferenceError) ---
// Moved declarations of handlers here to ensure they are defined before renderConvoList uses them.
export function handleRename(id, oldTitle) {
    convoToRename = { id, oldTitle };
    ui.showModal('rename', { oldTitle });
}

export function handleDelete(id) {
    convoToDelete = id;
    ui.showModal('delete-convo');
}

export async function handleTogglePin(id, isPinned, activeProfileData, user) {
    ui.closeAllConvoMenus();
    const newPinState = !isPinned;
    const oldPinState = isPinned; // Store old state for rollback
    
    try {
        // 1. Optimistic UI Update (Update local cache instantly)
        // This is done BEFORE the network call to make the change feel instant
        await cache.updateConvoInList(id, { is_pinned: newPinState }); 
        
        // 2. Refresh list only to update sidebar order/title without scrolling chat
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
        
        // 3. API Call (Sync to server)
        const response = await api.togglePinConversation(id, newPinState);
        
        if (response === 'QUEUED') {
            ui.showToast(newPinState ? 'Pin queued.' : 'Unpin queued.', 'info');
        } else {
            ui.showToast(newPinState ? 'Conversation pinned.' : 'Conversation unpinned.', 'success');
        }
        
        // 4. Reload list again to ensure server-side update is reflected
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        console.error('Failed to toggle pin status:', error);
        ui.showToast('Could not save pin status.', 'error');
        
        // 5. Rollback on failure 
        await cache.updateConvoInList(id, { is_pinned: oldPinState }); 
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
    }
}


// --- CORE CONVERSATION MANAGEMENT ---

/**
 * Loads conversation list from server/cache, re-renders sidebar, 
 * and optionally switches to the active chat and scrolls to the bottom.
 * @param {object} activeProfileData 
 * @param {object} user 
 * @param {function} promptClickHandler 
 * @param {function} showModal 
 * @param {boolean} [shouldSwitchChat=true] - NEW: If false, only the list is refreshed, preserving current chat view.
 */
export async function loadConversations(activeProfileData, user, promptClickHandler, showModal, shouldSwitchChat = true) {
    // 1. Load from local cache for immediate display
    const cachedConvos = await cache.loadConvoList();
    if (cachedConvos.length > 0) {
        renderConvoList(cachedConvos, activeProfileData, user, showModal);
    }

    try {
        // 2. Fetch fresh data (uses offlineManager/cache)
        const response = await api.fetchConversations();
        
        const conversations = Array.isArray(response) ? response 
          : (response && Array.isArray(response.conversations)) ? response.conversations
          : [];

        // 3. Save new list and render if different
        await cache.saveConvoList(conversations);
        renderConvoList(conversations, activeProfileData, user, showModal);

        if (shouldSwitchChat) {
            if (conversations?.length > 0) {
                const targetConvoId = (currentConversationId && conversations.some(c => c.id === currentConversationId))
                        ? currentConversationId
                        : conversations[0].id;
                
                await switchConversation(targetConvoId, activeProfileData, user, showModal, true); // Scroll to bottom on full load
            } else {
                await startNewConversation(false, activeProfileData, user, promptClickHandler); 
            }
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
        if (cachedConvos.length === 0) {
             ui.showToast('Failed to load conversations. Check connectivity.', 'error');
        }
    }
}

/**
 * NEW: Loads conversation list from server/cache and re-renders sidebar ONLY.
 * This is used for actions like Pin/Delete/Rename where we don't want to force
 * the main chat window to reload or scroll.
 */
export async function refreshConvoListOnly(activeProfileData, user, showModal) {
    // This calls loadConversations but explicitly sets shouldSwitchChat to false.
    return loadConversations(activeProfileData, user, () => {}, showModal, false);
}


function renderConvoList(conversations, activeProfileData, user, showModal) {
    const convoList = document.getElementById('convo-list');
    if (!convoList) return;

    // ADDED SAFETY CHECK: Ensure user object exists before proceeding
    if (!user) {
        console.warn('Cannot render conversation list: User data is missing.');
        return;
    }

    convoList.innerHTML = '';
    
    // --- NEW: Sorting Logic (Pinned first, then by date) ---
    conversations.sort((a, b) => {
        // Pinned conversations always come first
        if (a.is_pinned !== b.is_pinned) {
            return a.is_pinned ? -1 : 1;
        }
        // Then sort by last_updated (most recent first)
        const dateA = a.last_updated ? new Date(a.last_updated) : new Date(0);
        const dateB = b.last_updated ? new Date(b.last_updated) : new Date(0);
        return dateB - dateA;
    });

    const handlers = {
        switchHandler: (id) => switchConversation(id, activeProfileData, user, showModal, true), // Click always switches/scrolls
        // NOTE: handleRename, handleDelete, handleTogglePin are now defined at the module top level.
        renameHandler: handleRename, 
        deleteHandler: handleDelete,
        pinHandler: handleTogglePin
    };
    
    // Separate pinned and unpinned lists
    const pinnedConversations = conversations.filter(c => c.is_pinned);
    const unpinnedConversations = conversations.filter(c => !c.is_pinned);

    if (pinnedConversations.length > 0) {
        const pinnedHeader = document.createElement('h3');
        pinnedHeader.className = 'px-2 pt-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2';
        pinnedHeader.textContent = 'Pinned Conversations';
        convoList.appendChild(pinnedHeader);
        
        pinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    }

    if (unpinnedConversations.length > 0) {
        const allHeader = document.createElement('h3');
        allHeader.className = 'px-2 pt-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2';
        allHeader.textContent = 'All Conversations';
        convoList.appendChild(allHeader);

        unpinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    }
    // --- END NEW: Sorting Logic ---

    // Ensure the currently active link is highlighted after rendering
    if (currentConversationId) {
        uiAuthSidebar.setActiveConvoLink(currentConversationId);
    }
}


export async function startNewConversation(isInitialLoad = false, activeProfileData, user, promptClickHandler) { 
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');

    if (!isInitialLoad) {
        currentConversationId = null;
        uiAuthSidebar.setActiveConvoLink(null);
        uiMessages.resetChatView();
        uiAuthSidebar.updateChatTitle('New Chat');

        uiAuthSidebar.updateActiveProfileChip(activeProfileData.name || 'Default');

        // ADDED NULL CHECK: Safely get first name
        const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
        uiMessages.displaySimpleGreeting(firstName);
        uiMessages.displayEmptyState(activeProfileData, promptClickHandler);
    } 
    // We rely on sendMessage to create the conversation when the user types the first message.
}

/**
 * Switches the main chat view to the specified conversation ID.
 * @param {string} id - The conversation ID.
 * @param {object} activeProfileData 
 * @param {object} user 
 * @param {function} showModal 
 * @param {boolean} [shouldScroll=false] - NEW: If true, scrolls to the bottom after rendering history.
 */
export async function switchConversation(id, activeProfileData, user, showModal, shouldScroll = false) {
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
    if (ui.elements.chatView) ui.elements.chatView.classList.remove('hidden');
    
    currentConversationId = id;
    uiAuthSidebar.setActiveConvoLink(id);
    uiMessages.resetChatView();
    uiAuthSidebar.updateActiveProfileChip(activeProfileData.name || 'Default');

    // Set title optimistically
    try {
        const activeLink = document.querySelector(`a[data-id="${id}"]`);
        const title = activeLink ? activeLink.querySelector('.convo-title').textContent : 'SAFi';
        uiAuthSidebar.updateChatTitle(title);
    } catch (e) {
        uiAuthSidebar.updateChatTitle('SAFi');
    }

    // 1. Load from local UI state cache first
    const cachedHistory = await cache.loadConvoHistory(id);
    if (cachedHistory.length > 0) {
        renderHistory(cachedHistory, user, showModal);
        if (shouldScroll) ui.scrollToBottom(); // Scroll only if requested
    } else {
        // ADDED NULL CHECK: Safely get first name
        const firstName = user && user.name ? user.name.split(' ')[0] : 'There';
        uiMessages.displaySimpleGreeting(firstName);
        uiMessages.displayEmptyState(activeProfileData, (text) => { 
            ui.elements.messageInput.value = text;
            ui.elements.sendButton.disabled = false;
            autoSize();
            sendMessage(activeProfileData, user);
        });
    }

    try {
        // 2. Then fetch from network (or network's API cache via offlineManager)
        const historyResponse = await api.fetchHistory(id);
        const history = Array.isArray(historyResponse) ? historyResponse 
          : (historyResponse && Array.isArray(historyResponse.history)) ? historyResponse.history
          : [];

        // 3. Save to local UI state cache, re-render, and scroll
        await cache.saveConvoHistory(id, history);
        
        // Only re-render if the newly fetched history is different from the cache we rendered,
        // or if we initially rendered the empty state (cachedHistory.length === 0).
        if (cachedHistory.length === 0 || JSON.stringify(cachedHistory) !== JSON.stringify(history)) {
            uiMessages.resetChatView();
            renderHistory(history, user, showModal);
            if (shouldScroll) ui.scrollToBottom(); // Scroll only if requested
        }
    } catch (error) {
        console.error('Failed to fetch conversation history:', error);
        // If fetch failed but we rendered cache, just warn.
        if (cachedHistory.length === 0) {
            ui.showToast('Could not load chat history.', 'error');
        }
    }
}

function renderHistory(history, user, showModal) {
    if (!history || history.length === 0) return;

    history.forEach((turn, i) => {
        const date = turn.timestamp ? new Date(turn.timestamp) : new Date();
        const ledger = typeof turn.conscience_ledger === 'string' ? JSON.parse(turn.conscience_ledger) : turn.conscience_ledger;
        const values = typeof turn.profile_values === 'string' ? JSON.parse(turn.profile_values) : turn.profile_values;
        
        // Pass the scores of the previous turns for the trend line calculation
        const scoresHistory = history.slice(0, i + 1).map(t => t.spirit_score);

        const payload = {
            ledger: ledger || [],
            profile: turn.profile_name,
            values: values || [],
            spirit_score: turn.spirit_score,
            spirit_scores_history: scoresHistory
        };

        const options = {};
        if (turn.role === 'user' && user) {
            options.avatarUrl = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
        }
        options.suggestedPrompts = turn.suggested_prompts || [];

        uiMessages.displayMessage(
            turn.role,
            turn.content,
            date,
            turn.message_id,
            payload,
            (p) => showModal('conscience', p),
            options
        );
        
        // If audit data is missing, poll for it
        if (turn.role === 'ai' && !ledger && turn.message_id) {
            pollForAuditResults(turn.message_id);
        }
    });
}


// --- MESSAGE FLOW ---

export async function sendMessage(activeProfileData, user) {
    const userMessage = ui.elements.messageInput.value.trim();
    if (!userMessage) return;

    let isNewConversation = false;
    
    if (!currentConversationId) {
        isNewConversation = true;
        try {
            const newConvo = await api.createNewConversation();
            
            if (newConvo === 'QUEUED') {
                ui.showToast('Offline: Cannot start new chat now.', 'error');
                return;
            }

            currentConversationId = newConvo.id;
            // The API response now includes is_pinned: false
            const newConvoMeta = { 
                id: newConvo.id, 
                title: 'Untitled', 
                last_updated: new Date().toISOString(),
                is_pinned: newConvo.is_pinned === true
            };
            await cache.updateConvoInList(newConvo.id, newConvoMeta);
            
            const handlers = { 
                switchHandler: (id) => switchConversation(id, activeProfileData, user, ui.showModal, true), 
                renameHandler: handleRename, 
                deleteHandler: handleDelete,
                pinHandler: handleTogglePin
            };
            uiAuthSidebar.prependConversationLink(newConvoMeta, handlers);
            uiAuthSidebar.setActiveConvoLink(currentConversationId);

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
    // ADDED NULL CHECK: Safely get user info
    const pic = user && (user.picture || user.avatar) || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user && user.name ? user.name.charAt(0) : 'U'}`;
    const userMessageId = crypto.randomUUID();

    uiMessages.displayMessage('user', userMessage, now, userMessageId, null, null, { avatarUrl: pic });
    
    const userMessageObject = {
        role: 'user',
        content: userMessage,
        timestamp: now.toISOString(),
        message_id: userMessageId
    };
    await cache.addMessageToHistory(currentConversationId, userMessageObject);
    
    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();
    
    const loadingIndicator = uiMessages.showLoadingIndicator(activeProfileData.name);

    try {
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId);
        
        ui.clearLoadingInterval();
        if(loadingIndicator) loadingIndicator.remove();
        
        if (initialResponse === 'QUEUED') {
            ui.showToast('Message queued, will send when online.', 'info');
            // Remove user message from display/cache as it will be resent on flush.
            const userMsgElement = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (userMsgElement) userMsgElement.remove();
            // Since we don't have handleExamplePromptClick here, we'll just rely on the app resume listener
            return;
        }

        const ledger = typeof initialResponse.ledger === 'string' ? JSON.parse(initialResponse.ledger) : initialResponse.ledger;
        const values = typeof initialResponse.values === 'string' ? JSON.parse(initialResponse.values) : initialResponse.values;

        // Fetch full history to get correct trend line
        const historyForPayload = await cache.loadConvoHistory(currentConversationId);
        
        const aiMessageObject = {
            role: 'ai',
            content: initialResponse.finalOutput,
            timestamp: new Date().toISOString(),
            message_id: initialResponse.messageId,
            conscience_ledger: initialResponse.ledger,
            profile_name: initialResponse.profile,
            profile_values: initialResponse.values,
            spirit_score: initialResponse.spirit_score,
            suggested_prompts: initialResponse.suggestedPrompts || []
        };
        
        await cache.addMessageToHistory(currentConversationId, aiMessageObject);

        const initialPayload = {
            ledger: ledger || [],
            profile: initialResponse.profile || activeProfileData.name || null,
            values: values || [],
            spirit_score: initialResponse.spirit_score,
            spirit_scores_history: historyForPayload.map(t => t.spirit_score)
        };

        uiMessages.displayMessage(
          'ai',
          initialResponse.finalOutput,
          new Date(),
          initialResponse.messageId,
          initialPayload,
          (payload) => ui.showModal('conscience', payload),
          { suggestedPrompts: initialResponse.suggestedPrompts || [] } 
        );
        
        const updateMeta = { last_updated: new Date().toISOString() };
        
        if (initialResponse.newTitle && isNewConversation) {
            updateMeta.title = initialResponse.newTitle;
        }

        if (updateMeta.title || isNewConversation) {
            const link = document.querySelector(`a[data-id="${currentConversationId}"]`);
            if (link) {
                const titleEl = link.querySelector('.convo-title');
                const timeEl = link.querySelector('.convo-timestamp');
                if (updateMeta.title) titleEl.textContent = updateMeta.title;
                if (timeEl) timeEl.textContent = formatRelativeTime(new Date());
                uiAuthSidebar.updateChatTitle(updateMeta.title || 'Untitled');
            }
        }
        await cache.updateConvoInList(currentConversationId, updateMeta);


        const hasInitialLedger = initialPayload.ledger && initialPayload.ledger.length > 0;
        if (initialResponse.messageId && !hasInitialLedger) {
            pollForAuditResults(initialResponse.messageId);
        }
        
    } catch (error) {
        uiMessages.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
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
            // Polling stopped, conversation switched/deleted
            return;
        }
        
        attempts++;

        try {
            const auditResult = await api.fetchAuditResult(messageId);
            
            const rawLedger = auditResult ? auditResult.ledger : null;
            let parsedLedger = null;
    
            if (rawLedger) {
                if (typeof rawLedger === 'string') {
                    try { parsedLedger = JSON.parse(rawLedger); } catch (e) { parsedLedger = []; }
                } else if (Array.isArray(rawLedger)) {
                    parsedLedger = rawLedger;
                }
            }

            if (parsedLedger && parsedLedger.length > 0) {
                // 1. Update local cache with audit data
                const history = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = history.findIndex(m => m.message_id === messageId);
                if (msgIndex > -1) {
                    history[msgIndex] = { ...history[msgIndex], ...auditResult, conscience_ledger: parsedLedger };
                    await cache.saveConvoHistory(currentConversationId, history);
                }
                
                // 2. Load updated history for accurate trend line
                const updatedHistory = await cache.loadConvoHistory(currentConversationId);
                
                const spiritScoresHistory = updatedHistory
                     .filter(t => t.spirit_score !== null && t.spirit_score !== undefined)
                     .map(t => t.spirit_score);
    
                const payload = { 
                    ...auditResult, 
                    ledger: parsedLedger, 
                    spirit_scores_history: spiritScoresHistory 
                };
                
                uiMessages.updateMessageWithAudit(messageId, payload, (p) => ui.showModal('conscience', p));
                resolve(auditResult);
            } else if (attempts >= maxAttempts) {
                console.warn(`Polling timed out for message ${messageId}.`);
                reject(new Error('Polling timed out.'));
            } else {
                setTimeout(() => executePoll(resolve, reject), interval);
            }
        } catch (error) {
             const msg = error.message || '';
             if (msg.includes('404') || msg.includes('UNAUTHORIZED')) {
                // Not ready yet, retry
                setTimeout(() => executePoll(resolve, reject), interval);
             } else {
                 console.error(`Error polling for audit on ${messageId}:`, error);
             }
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

// --- CONVERSATION RENAMING/DELETING/PINNING ---

export async function handleConfirmRename(activeProfileData, user) {
    const { id, oldTitle } = convoToRename;
    const newTitle = ui.elements.renameInput.value.trim();
    
    if (newTitle && newTitle !== oldTitle) {
        try {
            await cache.updateConvoInList(id, { title: newTitle }); // Optimistic UI update
            
            // NEW: Only refresh the list, do not switch chat or scroll
            await refreshConvoListOnly(activeProfileData, user, ui.showModal);
            
            const response = await api.renameConversation(id, newTitle);
            
            if (response === 'QUEUED') {
                ui.showToast('Rename queued.', 'info');
            } else {
                ui.showToast('Conversation renamed.', 'success');
            }

            // Reload conversations again after server response
            await refreshConvoListOnly(activeProfileData, user, ui.showModal);
            
            if (id === currentConversationId) {
                uiAuthSidebar.updateChatTitle(newTitle);
            }
        } catch (error) {
            ui.showToast('Could not rename conversation.', 'error');
            await cache.updateConvoInList(id, { title: oldTitle }); // Rollback
        }
    }
    ui.closeModal();
    convoToRename = { id: null, oldTitle: null };
}

export async function handleConfirmDelete(activeProfileData, user) {
    const id = convoToDelete;
    if (!id) return;
    
    try {
        await cache.deleteConvo(id); // Optimistic UI update

        if (id === currentConversationId) {
            currentConversationId = null;
        }

        // NEW: Only refresh the list, then if the current chat was deleted, start a new one
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);
        
        if (currentConversationId === null) {
             // If deleted chat was the active one, start a fresh view
             await startNewConversation(false, activeProfileData, user, () => {}); 
        }

        const response = await api.deleteConversation(id);
        
        if (response === 'QUEUED') {
            ui.showToast('Delete queued.', 'info');
        } else {
            ui.showToast('Conversation deleted.', 'success');
        }

        // Reload to clean up the queue/ensure final state
        await refreshConvoListOnly(activeProfileData, user, ui.showModal);

    } catch (error) {
        ui.showToast('Could not delete conversation.', 'error');
        // Note: Delete rollback is complex, rely on next sync to fix list if API failed but queue is cleared.
    }
    
    ui.closeModal();
    convoToDelete = null;
}