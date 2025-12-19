// Conversation Management Logic:chat.js

import * as api from './api.js';
import * as ui from '../ui/ui.js';
import * as uiAuthSidebar from '../ui/ui-auth-sidebar.js';
import * as uiMessages from '../ui/ui-messages.js';
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
    // --- ADDED --- (Feature 1)
    // Check for the flag set during profile change
    const forceNewChat = sessionStorage.getItem('forceNewChat') === 'true';
    if (forceNewChat) {
        // Clear the flag so it doesn't persist on future reloads
        sessionStorage.removeItem('forceNewChat');
    }
    // --- END ADDED ---

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
            // --- MODIFIED BLOCK --- (Feature 1)
            if (forceNewChat) {
                // If the flag is set, always start a new conversation
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            } else if (conversations?.length > 0) {
                // Original logic: load the last active or most recent convo
                const targetConvoId = (currentConversationId && conversations.some(c => c.id === currentConversationId))
                    ? currentConversationId
                    : conversations[0].id;

                await switchConversation(targetConvoId, activeProfileData, user, showModal, true); // Scroll to bottom on full load
            } else {
                // Original logic: no convos exist, so start a new one
                await startNewConversation(false, activeProfileData, user, promptClickHandler);
            }
            // --- END MODIFIED BLOCK ---
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
    return loadConversations(activeProfileData, user, () => { }, showModal, false);
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
        pinHandler: (id, isPinned) => handleTogglePin(id, isPinned, activeProfileData, user) // Pass all args
    };

    // Separate pinned and unpinned lists
    const pinnedConversations = conversations.filter(c => c.is_pinned);
    const unpinnedConversations = conversations.filter(c => !c.is_pinned);

    if (pinnedConversations.length > 0) {
        const pinnedHeader = document.createElement('h3');
        pinnedHeader.className = 'px-3 mt-2 mb-2 text-xs font-medium text-gray-500 uppercase tracking-wider';
        pinnedHeader.textContent = 'Pinned Conversations';
        convoList.appendChild(pinnedHeader);

        pinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    }

    if (unpinnedConversations.length > 0) {
        // Container for Header + New Chat
        const headerContainer = document.createElement('div');
        headerContainer.className = 'flex items-center justify-between px-3 mt-6 mb-2 group';

        const allHeader = document.createElement('h3');
        allHeader.className = 'text-xs font-medium text-gray-500 uppercase tracking-wider';
        allHeader.textContent = 'All Conversations';

        // Inline New Chat Button
        const newChatBtn = document.createElement('button');
        newChatBtn.type = 'button';
        newChatBtn.className = 'flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-green-600 dark:text-gray-400 dark:hover:text-green-500 transition-colors';
        newChatBtn.innerHTML = `
            <span>New Chat</span>
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
        `;
        newChatBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            startNewConversation(false, activeProfileData, user, () => { });
            if (window.innerWidth < 768) ui.closeSidebar();
        });

        headerContainer.appendChild(allHeader);
        headerContainer.appendChild(newChatBtn);
        convoList.appendChild(headerContainer);

        unpinnedConversations.forEach(convo => {
            const link = uiAuthSidebar.renderConversationLink(convo, handlers);
            convoList.appendChild(link);
        });
    } else {
        // Fallback: List is empty (or all pinned). Show Header + Button anyway.
        const headerContainer = document.createElement('div');
        // Add margin top if there are pinned items
        const mt = pinnedConversations.length > 0 ? 'mt-6 border-t border-gray-100 dark:border-gray-800 pt-4' : 'mt-2';
        headerContainer.className = `flex items-center justify-between px-3 mb-2 group ${mt}`;

        const allHeader = document.createElement('h3');
        allHeader.className = 'text-xs font-medium text-gray-500 uppercase tracking-wider';
        allHeader.textContent = 'All Conversations';

        const newChatBtn = document.createElement('button');
        newChatBtn.type = 'button';
        newChatBtn.className = 'flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-green-600 dark:text-gray-400 dark:hover:text-green-500 transition-colors';
        newChatBtn.innerHTML = `
             <span>New Chat</span>
             <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
         `;
        newChatBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            startNewConversation(false, activeProfileData, user, () => { });
            if (window.innerWidth < 768) ui.closeSidebar();
        });

        headerContainer.appendChild(allHeader);
        headerContainer.appendChild(newChatBtn);
        convoList.appendChild(headerContainer);
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
        // Updated to pass activeProfileData for retry logic
        renderHistory(cachedHistory, user, showModal, activeProfileData);
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
            // Updated to pass activeProfileData for retry logic
            renderHistory(history, user, showModal, activeProfileData);
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

// Updated signature to accept activeProfileData
function renderHistory(history, user, showModal, activeProfileData) {
    if (!history || history.length === 0) return;

    history.forEach((turn, i) => {
        const date = turn.timestamp ? new Date(turn.timestamp) : new Date();
        const ledger = typeof turn.conscience_ledger === 'string' ? JSON.parse(turn.conscience_ledger) : turn.conscience_ledger;
        const values = typeof turn.profile_values === 'string' ? JSON.parse(turn.profile_values) : turn.profile_values;

        // --- THIS IS THE FIX ---
        // Parse `suggested_prompts` from a string to an array, just like we do for the ledger.
        let parsedSuggestions = [];
        if (turn.suggested_prompts) {
            if (typeof turn.suggested_prompts === 'string') {
                try { parsedSuggestions = JSON.parse(turn.suggested_prompts); } catch (e) { parsedSuggestions = []; }
            } else if (Array.isArray(turn.suggested_prompts)) {
                parsedSuggestions = turn.suggested_prompts;
            }
        }
        // --- END FIX ---

        // --- THIS IS THE FIX ---
        // Filter out null/undefined scores *before* passing to the trend line.
        const scoresHistory = history.slice(0, i + 1)
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);
        // --- END FIX ---

        const payload = {
            ledger: ledger || [],
            profile: turn.profile_name,
            values: values || [],
            spirit_score: turn.spirit_score,
            spirit_scores_history: scoresHistory,
            // --- MODIFIED: Use the parsed array ---
            suggested_prompts: parsedSuggestions,
            message_id: turn.message_id // Ensure message_id is in payload
        };

        const options = {};
        if (turn.role === 'user' && user) {
            options.avatarUrl = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;

            // --- NEW: Retry Handler ---
            // If activeProfileData is available, allow retry
            if (activeProfileData) {
                options.onRetry = (text) => {
                    ui.elements.messageInput.value = text;
                    autoSize();
                    ui.elements.sendButton.disabled = false;
                    ui.elements.messageInput.focus();
                    sendMessage(activeProfileData, user);
                };
            }
        }
        // --- MODIFIED: Use the parsed array ---
        options.suggestedPrompts = parsedSuggestions;

        uiMessages.displayMessage(
            turn.role,
            turn.content,
            date,
            turn.message_id,
            payload,
            async (p) => {
                // --- FIX: Fetch fresh history on click ---
                const freshHistory = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                let freshScores = [];
                if (msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
            },
            options
        );

        // If audit data is missing, poll for it
        // --- MODIFIED: Use the parsed array for the check ---
        const suggestions = parsedSuggestions;
        const isBlocked = turn.content && turn.content.includes("🛑 **The answer was blocked**");

        // We poll if:
        // 1. The audit is pending
        // 2. AND (it's a blocked message OR it's an approved message missing suggestions)
        if (turn.role === 'ai' && turn.message_id && turn.audit_status === 'pending') {
            // This logic is now handled inside pollForAuditResults, we just need to call it.
            pollForAuditResults(turn.message_id);
        }
        // --- END MODIFIED ---
    });
}


// --- MESSAGE FLOW ---

// --- ABORT CONTROLLER STATE ---
let currentAbortController = null;

function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0, v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

export async function sendMessage(activeProfileData, user) {
    // 1. Check if we are currently sending (and thus can cancel)
    if (currentAbortController) {
        console.log('Cancelling request...');
        currentAbortController.abort();
        currentAbortController = null;

        // UI Reset is handled in the catch block or manually here if needed immediately
        ui.showToast('Request cancelled.', 'info');

        // Reset button immediately
        const buttonIcon = document.getElementById('button-icon');
        const buttonLoader = document.getElementById('button-loader');
        buttonIcon.classList.remove('hidden');
        buttonIcon.innerHTML = `
           <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd"
                d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                clip-rule="evenodd" />
            </svg>`;
        buttonLoader.classList.add('hidden');

        // Re-evaluate disabled state based on input text (likely empty if just sent)
        // But the input was cleared! So we should keep it focused.
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;

        ui.clearLoadingInterval();
        const loadingIndicator = document.querySelector('.loading-indicator'); // Or robust find
        if (loadingIndicator) loadingIndicator.remove();
        return;
    }

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
                pinHandler: (id, isPinned) => handleTogglePin(id, isPinned, activeProfileData, user)
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

    // UI: Show Stop Button instead of Spinner/Arrow
    // Ideally we want a nice transition. For now, swap icon to "Stop"
    buttonIcon.classList.remove('hidden'); // Keep icon visible
    buttonIcon.innerHTML = `
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <rect x="5" y="5" width="10" height="10" rx="1"></rect>
        </svg>`;

    // We do NOT use the spinner anymore, or we use it as a border? 
    // The user asked for "cancel option to the spinning button". 
    // Let's keep the spinner but put the stop icon INSIDE it?
    // Current CSS structure: button-icon OR button-loader. Loader replaces icon.
    // Let's show loader AND stop icon.
    buttonLoader.classList.remove('hidden'); // Spinner rotating
    // Remove the icon? No, we want the stop icon visible. 
    // The loader is likely a div that spins. If we put text inside it spins.
    // Let's look at index.html: loader is empty div.
    // Solution: Keep loader spinning (if it's absolute/overlay) or just show Stop icon.
    // "cancel option to the spinning button" -> implied Stop Button.
    // Standard UI: Spinner ring around a square stop button.
    // Simpler UI: Just a stop button. 

    // Let's do: Stop Icon only. No spinner, or spinner around it? 
    // Given the request, "spinning button" usually means "button is loading". 
    // I will replace the spinner with an actionable Stop Icon.
    buttonLoader.classList.add('hidden'); // Hide simple spinner
    // Stop icon is already set above.
    ui.elements.sendButton.disabled = false; // ENABLED so we can click to cancel!

    // FORCE STYLE to ensure it turns red, overriding any CSS specificity issues
    ui.elements.sendButton.classList.remove('bg-green-600', 'hover:bg-green-700');
    ui.elements.sendButton.classList.add('bg-red-600', 'hover:bg-red-700');
    ui.elements.sendButton.style.backgroundColor = '#dc2626'; // tailwind red-600
    ui.elements.sendButton.style.color = '#ffffff';

    // Init AbortController
    currentAbortController = new AbortController();

    const now = new Date();
    // ADDED NULL CHECK: Safely get user info
    const pic = user && (user.picture || user.avatar) || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user && user.name ? user.name.charAt(0) : 'U'}`;
    const userMessageId = crypto.randomUUID();

    // --- NEW: Retry Handler for optimistic message ---
    const retryHandler = (text) => {
        ui.elements.messageInput.value = text;
        autoSize();
        ui.elements.sendButton.disabled = false;
        ui.elements.messageInput.focus();
        sendMessage(activeProfileData, user);
    };

    uiMessages.displayMessage('user', userMessage, now, userMessageId, null, null, {
        avatarUrl: pic,
        onRetry: retryHandler
    });

    const userMessageObject = {
        role: 'user',
        content: userMessage,
        timestamp: now.toISOString(),
        message_id: userMessageId,
        audit_status: 'n/a' // User messages don't need audit
    };
    await cache.addMessageToHistory(currentConversationId, userMessageObject);

    const originalMessage = ui.elements.messageInput.value;
    ui.elements.messageInput.value = '';
    autoSize();

    const loadingIndicator = uiMessages.showLoadingIndicator(activeProfileData.name);

    const aiMessageId = generateUUID();
    pollForAuditResults(aiMessageId); // Start polling for reasoning immediately

    try {
        // PASS SIGNAL AND MESSAGE_ID HERE
        const initialResponse = await api.processUserMessage(userMessage, currentConversationId, currentAbortController.signal, aiMessageId);

        ui.clearLoadingInterval();
        if (loadingIndicator && loadingIndicator.parentNode) loadingIndicator.remove();

        if (initialResponse === 'QUEUED') {
            ui.showToast('Message queued, will send when online.', 'info');
            // Remove user message from display/cache as it will be resent on flush.
            const userMsgElement = document.querySelector(`[data-message-id="${userMessageId}"]`);
            if (userMsgElement) userMsgElement.remove();
            return;
        }

        // --- START BUG FIX: Handle empty/missing data from API ---
        const mainAnswer = initialResponse.finalOutput ?? '[Sorry, the model returned an empty response.]';
        const ledger = typeof initialResponse.conscienceLedger === 'string' ? JSON.parse(initialResponse.conscienceLedger) : (initialResponse.conscienceLedger || []);
        const values = typeof initialResponse.profileValues === 'string' ? JSON.parse(initialResponse.profileValues) : (initialResponse.profileValues || []);
        const suggestions = initialResponse.suggestedPrompts || [];
        const messageId = initialResponse.messageId || aiMessageId;
        const profileName = initialResponse.activeProfile || activeProfileData.name || null;
        const spiritScore = initialResponse.spirit_score;
        const isBlocked = mainAnswer.includes("🛑 **The answer was blocked**");
        // --- END BUG FIX ---

        // Fetch full history *including* the user message we just added
        const historyForPayload = await cache.loadConvoHistory(currentConversationId);

        // Filter out null/undefined scores *before* passing to the trend line.
        const scoresHistoryForPayload = historyForPayload
            .map(t => t.spirit_score)
            .filter(s => s !== null && s !== undefined);
        // Add the new score (if it exists) to the history for the trend line
        if (spiritScore !== null && spiritScore !== undefined) {
            scoresHistoryForPayload.push(spiritScore);
        }

        const aiMessageObject = {
            role: 'ai',
            content: mainAnswer,
            timestamp: new Date().toISOString(),
            message_id: messageId,
            conscience_ledger: ledger,
            profile_name: profileName,
            profile_values: values,
            spirit_score: spiritScore,
            suggested_prompts: suggestions,
            audit_status: isBlocked ? 'complete' : 'pending'
        };

        await cache.addMessageToHistory(currentConversationId, aiMessageObject);

        const initialPayload = {
            ledger: ledger,
            profile: profileName,
            values: values,
            spirit_score: spiritScore,
            spirit_scores_history: scoresHistoryForPayload,
            message_id: messageId
        };

        uiMessages.displayMessage(
            'ai',
            mainAnswer,
            new Date(),
            messageId,
            initialPayload,
            async (p) => {
                const freshHistory = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                let freshScores = [];
                if (msgIndex > -1) {
                    freshScores = freshHistory.slice(0, msgIndex + 1)
                        .map(t => t.spirit_score)
                        .filter(s => s !== null && s !== undefined);
                }

                ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
            },
            { suggestedPrompts: suggestions, animate: true }
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

        if (messageId && !isBlocked) {
            // Already polling, but ensure we keep polling if needed
            // pollForAuditResults(messageId); 
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            // Handled by the abort logic at top of function? No, confusing.
            // If we aborted, we probably already handled UI cleanup.
            // BUT, fetch throws AbortError. So we land here.
            console.log('Fetch aborted in catch block.');
            return; // Exit cleanly
        }

        uiMessages.displayMessage('ai', 'Sorry, an error occurred.', new Date(), null, null, null);
        ui.elements.messageInput.value = originalMessage;
        autoSize();
        ui.showToast(error.message || 'An unknown error occurred.', 'error');
    } finally {
        // Reset Button Style
        buttonIcon.classList.remove('hidden');
        buttonIcon.innerHTML = `
           <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
               <path fill-rule="evenodd"
                 d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z"
                 clip-rule="evenodd" />
             </svg>`;

        buttonLoader.classList.add('hidden');

        ui.elements.sendButton.classList.remove('bg-red-600', 'hover:bg-red-700'); // Revert Color
        ui.elements.sendButton.classList.add('bg-green-600', 'hover:bg-green-700');
        ui.elements.sendButton.style.backgroundColor = ''; // Remove inline style

        ui.elements.sendButton.disabled = false;

        currentAbortController = null;

        // Re-focus and check input state
        ui.elements.messageInput.focus();
        // Since input is empty after send, disable it again if needed
        ui.elements.sendButton.disabled = ui.elements.messageInput.value.trim().length === 0;
    }
}

function pollForAuditResults(messageId, maxAttempts = 100, interval = 2000) {
    let attempts = 0;

    const executePoll = async (resolve, reject) => {
        if (!currentConversationId) {
            // Polling stopped, conversation switched/deleted
            return;
        }

        attempts++;

        try {
            const auditResult = await api.fetchAuditResult(messageId);

            // --- START FIX: Check for ledger OR suggestions ---

            // --- NEW: Live Reasoning Update ---
            // --- NEW: Live Reasoning Update ---
            if (auditResult.reasoning_log) {
                let log = auditResult.reasoning_log;
                if (typeof log === 'string') log = JSON.parse(log);

                if (log.length > 0) {
                    const lastStep = log[log.length - 1].step;
                    uiMessages.updateThinkingStatus(lastStep);
                }
            }

            // Check if the auditResult is valid and has *something* new
            const rawLedger = auditResult?.ledger;
            const rawSuggestions = auditResult?.suggested_prompts;

            const hasLedger = rawLedger && (Array.isArray(rawLedger) || typeof rawLedger === 'string');
            const hasSuggestions = rawSuggestions && (Array.isArray(rawSuggestions) || typeof rawSuggestions === 'string');

            // We update the UI if the audit is complete and has *either* a ledger *or* suggestions *or* a spirit score
            const hasScore = auditResult.spirit_score !== null && auditResult.spirit_score !== undefined;

            if (auditResult && auditResult.status === 'complete' && (hasLedger || hasSuggestions || hasScore)) {

                // Process Ledger (if it exists)
                let parsedLedger = []; // Default to empty
                if (rawLedger) {
                    if (typeof rawLedger === 'string') {
                        try { parsedLedger = JSON.parse(rawLedger); } catch (e) { parsedLedger = []; }
                    } else if (Array.isArray(rawLedger)) {
                        parsedLedger = rawLedger;
                    }
                }

                // --- THIS IS THE FIX ---
                // Process Suggestions (if they exist)
                let parsedSuggestions = []; // Default to empty
                if (rawSuggestions) {
                    if (typeof rawSuggestions === 'string') {
                        try { parsedSuggestions = JSON.parse(rawSuggestions); } catch (e) { parsedSuggestions = []; }
                    } else if (Array.isArray(rawSuggestions)) {
                        parsedSuggestions = rawSuggestions;
                    }
                }
                // --- END FIX ---


                // 1. Update local cache with *all* audit data
                const history = await cache.loadConvoHistory(currentConversationId);
                const msgIndex = history.findIndex(m => m.message_id === messageId);
                if (msgIndex > -1) {

                    history[msgIndex] = {
                        ...history[msgIndex], // Keeps old `content`
                        ...auditResult,       // Adds new audit data (ledger, score, etc.)
                        content: history[msgIndex].content, // EXPLICITLY preserve content
                        conscience_ledger: parsedLedger, // Save parsed array
                        suggested_prompts: parsedSuggestions, // Save parsed array
                        audit_status: 'complete' // Mark as complete
                    };

                    await cache.saveConvoHistory(currentConversationId, history);
                }

                // 2. Load updated history for accurate trend line
                const updatedHistory = await cache.loadConvoHistory(currentConversationId);

                // --- THIS IS THE FIX ---
                // Filter out null/undefined scores *before* passing to the trend line.
                const spiritScoresHistory = updatedHistory
                    .map(t => t.spirit_score)
                    .filter(s => s !== null && s !== undefined);
                // --- END FIX ---

                // 3. Build the payload for the UI
                const payload = {
                    ...auditResult, // This will include spirit_score, note
                    ledger: parsedLedger, // Pass parsed array
                    suggested_prompts: parsedSuggestions, // Pass parsed array
                    spirit_scores_history: spiritScoresHistory,
                    message_id: messageId // Ensure message_id is in payload
                };

                // 4. Update the UI
                uiMessages.updateMessageWithAudit(messageId, payload, async (p) => {
                    // --- FIX: Fetch fresh history on click ---
                    const freshHistory = await cache.loadConvoHistory(currentConversationId);
                    const msgIndex = freshHistory.findIndex(m => m.message_id === p.message_id);

                    let freshScores = [];
                    if (msgIndex > -1) {
                        freshScores = freshHistory.slice(0, msgIndex + 1)
                            .map(t => t.spirit_score)
                            .filter(s => s !== null && s !== undefined);
                    }

                    ui.showModal('conscience', { ...p, spirit_scores_history: freshScores });
                });
                resolve(auditResult);
            } else if (attempts >= maxAttempts) {
                console.warn(`Polling timed out for message ${messageId}.`);
                reject(new Error('Polling timed out.'));
            } else {
                setTimeout(() => executePoll(resolve, reject), interval);
            }
        } catch (error) {
            const msg = error.message || '';
            const status = error.status;
            if (status === 404 || status === 401 || msg.includes('not_found') || msg.includes('404')) {
                // Not ready yet or transient error, retry
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

    if (!hasText) {
        input.style.height = '44px'; // Force reset to min-height
        return;
    }

    // Reset height to auto to shrink properly
    input.style.height = 'auto';

    // Calculate new height, capped by max-height in CSS (if set, or we can enforce here)
    // The CSS class max-h-32 (approx 128px) handles the scrolling limit.
    // We just need to set scrollHeight.
    input.style.height = `${input.scrollHeight}px`;
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

            // --- THIS IS THE FIX ---
            // Define the click handler locally, since we can't access the one from app.js
            // This handler does what app.js's handleExamplePromptClick does.
            const newChatPromptHandler = (promptText) => {
                ui.elements.messageInput.value = promptText;
                autoSize();
                ui.elements.sendButton.disabled = false;
                sendMessage(activeProfileData, user);
            };
            // Pass the *real* handler, not the empty dummy function
            await startNewConversation(false, activeProfileData, user, newChatPromptHandler);
            // --- END FIX ---
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