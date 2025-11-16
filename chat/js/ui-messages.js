// ui-messages.js

import { formatTime } from './utils.js';
import * as ui from './ui.js'; 
import { getAvatarForProfile } from './ui-auth-sidebar.js'; 
import { playSpeech } from './tts-audio.js'; 
import { iconPlay } from './ui-render-constants.js'; 

// NOTE: marked, hljs, DOMPurify are assumed to be available globally from the original file's context.

// --- MARKDOWN & HIGHLIGHTING SETUP ---
marked.setOptions({
  breaks: false, 
  gfm: true,
  mangle: false,
  headerIds: false,
  highlight: function(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  }
});

// --- MESSAGE RENDERING ---

let lastRenderedDay = '';

/**
 * Inserts a day divider if the date is different from the last rendered message.
 * @param {Date} date - The date of the current message.
 */
export function maybeInsertDayDivider(date) {
  ui._ensureElements();
  const key = date.toLocaleDateString();
  if (key !== lastRenderedDay) {
    lastRenderedDay = key;
    const div = document.createElement('div');
    div.className = 'flex items-center justify-center my-2';
    div.innerHTML = `<div class="text-xs text-neutral-500 dark:text-neutral-400 px-3 py-1 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">${date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>`;
    ui.elements.chatWindow.appendChild(div);
  }
}

/**
 * Displays a simple "Hi [Name]" greeting when a new chat starts.
 * @param {string} firstName 
 */
export function displaySimpleGreeting(firstName) {
  ui._ensureElements();
  const existingGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (existingGreeting) existingGreeting.remove();

  const greetingDiv = document.createElement('div');
  greetingDiv.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  greetingDiv.textContent = `Hi ${firstName}`;
  ui.elements.chatWindow.appendChild(greetingDiv);
}

/**
 * Attaches click handlers to suggestion buttons.
 * @param {HTMLElement} container - The element containing the buttons (either .ai-content-wrapper or .message-container)
 */
function _attachSuggestionHandlers(container) {
    if (!container) return;
    
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
      // Remove old listener to prevent duplicates, just in case
      btn.replaceWith(btn.cloneNode(true));
    });

    // Add new listeners to the new nodes
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const promptText = btn.textContent.replace(/"/g, '').trim();
            ui.elements.messageInput.value = promptText;
            ui.elements.sendButton.disabled = false;
            ui.elements.messageInput.style.height = 'auto'; 
            ui.elements.messageInput.style.height = `${ui.elements.messageInput.scrollHeight}px`; 
            ui.elements.messageInput.focus();
            // --- FIX: Click the send button to send the message ---
            if (ui.elements.sendButton) {
                ui.elements.sendButton.click();
            }
            // --- END FIX ---
            const suggestionBox = btn.closest('.prompt-suggestions-container');
            if (suggestionBox) {
                suggestionBox.remove();
            }
        });
    });
}

/**
 * Renders the HTML for suggestion buttons.
 * @param {string[]} suggestedPrompts - A list of prompt strings.
 * @param {boolean} isBlocked - Whether the message was blocked.
 * @returns {string} - The HTML string for the suggestions block.
 */
function _renderSuggestionsHtml(suggestedPrompts, isBlocked) {
    if (!suggestedPrompts || suggestedPrompts.length === 0) {
        return '';
    }

    const promptsList = suggestedPrompts.map(p => 
        `<button class="ai-prompt-suggestion-btn text-left w-full p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors border border-neutral-200 dark:border-neutral-700 text-sm italic">
            "${p}"
        </button>`
    ).join('');
    
    const suggestionTitle = isBlocked ? "Try a different prompt:" : "Suggested follow-ups:";
    
    return `
        <div class="mt-3 pt-3 border-t border-neutral-200 dark:border-neutral-700 space-y-2 prompt-suggestions-container">
            <p class="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider mb-1">${suggestionTitle}</p>
            ${promptsList}
        </div>
    `;
}

/**
 * Displays a single chat message (user or AI).
 */
export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null, options = {}) {
  ui._ensureElements();
  const emptyState = ui.elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();

  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) {
    messageContainer.dataset.messageId = messageId;
  }
  
  const suggestedPrompts = options.suggestedPrompts || [];

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;

  let ttsButtonElement = null; 

  // --- MODIFIED --- (Blank Message Fix)
  // This is the final safeguard. If 'text' arrives as null or undefined,
  // it will be replaced with the fallback string, preventing a blank message.
  const final_text = String(text ?? '[Sorry, the model returned an empty response.]');
  // --- END MODIFIED ---

  if (sender === 'ai') {
    const profileName = (payload && payload.profile) ? payload.profile : null;
    const avatarUrl = getAvatarForProfile(profileName);
    
    let promptsHtml = '';
    // --- MODIFIED --- (Feature 2)
    // This block now only renders suggestions for *blocked* answers
    // Approved-answer suggestions are loaded async by updateMessageWithAudit
    if (suggestedPrompts.length > 0) {
        const isBlocked = final_text.includes("🛑 **The answer was blocked**");
        
        if (isBlocked) {
            promptsHtml = _renderSuggestionsHtml(suggestedPrompts, true);
        }
        // --- ADDED: Render suggestions if they came with an approved answer ---
        // (This happens when loading history)
        else {
            promptsHtml = _renderSuggestionsHtml(suggestedPrompts, false);
        }
        // --- END ADDED ---
    }
    // --- END MODIFIED ---

    // --- TTS Button Creation ---
    ttsButtonElement = document.createElement('button'); 
    ttsButtonElement.className = 'tts-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    ttsButtonElement.setAttribute('aria-label', 'Play message audio');
    ttsButtonElement.innerHTML = iconPlay; 
    
    ttsButtonElement.addEventListener('click', () => {
        playSpeech(final_text, ttsButtonElement); 
    });
    // --- END TTS ---

    messageDiv.innerHTML = `
      <div class="ai-avatar">
        <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-full h-full rounded-lg">
      </div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble">
          <!-- Content will be injected here -->
          <div class="meta"></div>
        </div>
        ${promptsHtml}
      </div>
    `;
    const bubble = messageDiv.querySelector('.chat-bubble');
    bubble.insertAdjacentHTML('afterbegin', DOMPurify.sanitize(marked.parse(final_text)));
    
  } else {
    const bubbleHtml = DOMPurify.sanitize(marked.parse(final_text));
    const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
    messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">
             ${bubbleHtml}
             <div class="meta"></div>
           </div>
        </div>
        <div class="user-avatar">
            <img src="${avatarUrl}" alt="User Avatar" class="w-full h-full rounded-full">
        </div>
    `;
  }
  
  const metaDiv = messageDiv.querySelector('.meta');
  const leftMeta = document.createElement('div');
  const rightMeta = document.createElement('div');
  
  rightMeta.className = 'flex items-center gap-2 ml-auto';

  const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
  if (hasLedger && whyHandler) {
      const whyButton = document.createElement('button');
      whyButton.className = 'why-btn';
      whyButton.textContent = 'View Ethical Reasoning';
      // This click handler has the "payload" as it exists when displayMessage is called
      // It might be stale, which is why updateMessageWithAudit MUST fix it.
      whyButton.addEventListener('click', () => whyHandler(payload));
      leftMeta.appendChild(whyButton);
  }
  
  metaDiv.appendChild(leftMeta);

  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp text-xs'; 
  stampDiv.textContent = formatTime(date);
  
  // Prepend TTS button to rightMeta (before stampDiv) for AI messages
  if (sender === 'ai' && ttsButtonElement) {
      rightMeta.prepend(ttsButtonElement);
  }

  rightMeta.appendChild(stampDiv);
  metaDiv.appendChild(rightMeta);
  
  messageContainer.appendChild(messageDiv);
  
  // This was missing, adding it back to ensure window scrolls
  ui.elements.chatWindow.appendChild(messageContainer);
  ui.scrollToBottom();
  
  // Attach handlers for any suggestions that were rendered (i.e., blocked or from history)
  _attachSuggestionHandlers(messageContainer);
  
  return messageContainer;
}

/**
 * Adds the "View Ethical Reasoning" button and async suggestions to an existing message.
 */
export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const messageContainer = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageContainer) return;

    const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
    
    // --- 1. Add/Update "Why" button ---
    if (hasLedger) {
        const metaDiv = messageContainer.querySelector('.meta');
        if (!metaDiv) return; // Should not happen

        // --- THIS IS THE FIX ---
        // Find and remove any *existing* "Why" button.
        // This old button has a "stale closure" with the old, incomplete payload.
        const oldWhyButton = metaDiv.querySelector('.why-btn');
        if (oldWhyButton) {
            oldWhyButton.remove();
        }
        // --- END FIX ---

        // Create the new button with the new, correct payload
        const whyButton = document.createElement('button');
        whyButton.className = 'why-btn';
        whyButton.textContent = 'View Ethical Reasoning';
        // This click handler now uses the "payload" passed into updateMessageWithAudit,
        // which contains the fully updated spirit_scores_history.
        whyButton.addEventListener('click', () => whyHandler(payload)); 

        // Find the left-side container (or create it)
        let leftMeta = metaDiv.querySelector('div:first-child');
        
        // Ensure leftMeta is the correct container (not the rightMeta)
        if (!leftMeta || leftMeta.classList.contains('flex')) { 
            leftMeta = document.createElement('div');
            metaDiv.prepend(leftMeta);
        }
        
        // Prepend the new button to appear first
        leftMeta.prepend(whyButton);
    }

    // --- 2. Add suggestions if they arrived with the audit ---
    const existingSuggestions = messageContainer.querySelector('.prompt-suggestions-container');
    const suggestedPrompts = payload.suggested_prompts || [];

    // Only add if they don't exist and we have new ones
    if (!existingSuggestions && suggestedPrompts.length > 0) {
        const aiContentWrapper = messageContainer.querySelector('.ai-content-wrapper');
        if (aiContentWrapper) {
            // Render with isBlocked=false (for "Suggested follow-ups:")
            const promptsHtml = _renderSuggestionsHtml(suggestedPrompts, false); 
            aiContentWrapper.insertAdjacentHTML('beforeend', promptsHtml);
            
            // Re-attach handlers for these *new* buttons
            _attachSuggestionHandlers(aiContentWrapper);
        }
    }
}


/**
 * Displays the AI thinking indicator with cycling status messages.
 */
export function showLoadingIndicator(profileName) {
  ui._ensureElements();
  ui.clearLoadingInterval(); 

  const emptyState = ui.elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();
  
  maybeInsertDayDivider(new Date());

  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'message-container';
  
  const avatarUrl = getAvatarForProfile(profileName || null); 
  const altText = (profileName || 'SAFi') + ' Avatar';

  loadingContainer.innerHTML = `
    <div class="message ai">
        <div class="ai-avatar">
            <img src="${avatarUrl}" alt="${altText}" class="w-full h-full rounded-lg">
        </div>
        <div class="ai-content-wrapper">
            <div class="flex items-center gap-3">
              <div class="thinking-spinner"></div>
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic">Thinking...</span>
            </div>
        </div>
    </div>`;
  ui.elements.chatWindow.appendChild(loadingContainer);
  ui.scrollToBottom();

  const statusSpan = loadingContainer.querySelector('#thinking-status');

  const stage1IntellectMessages = [
    "Consulting with the Intellect...",
    "Packaging the prompt for the AI model...",
    "Drafting response..."
  ];
  
  const stage2WillMessages = [
    "Intellect draft received. Consulting Will faculty...",
    "Analyzing draft against non-negotiable rules...",
    "Running gatekeeper check..."
  ];

  const stage3DelayedMessages = [
    "This is a complex prompt, so generation is taking longer than usual...",
    "If you are using claude,Gemini or GTP for the Intellect, those models take longer, sorry..",
    "Ensuring a high-quality draft, please wait...",
    "Almost done hang on...",
    "Just a few more moments..."
  ];

  let stage = 0;

  const updateStatus = () => {
    stage++;
    let messagePool;

    if (stage === 1) {
      messagePool = stage1IntellectMessages;
    } else if (stage === 2) {
      messagePool = stage2WillMessages;
    } else {
      messagePool = stage3DelayedMessages;
    }
    
    const message = messagePool[Math.floor(Math.random() * messagePool.length)];
    if (statusSpan) {
      statusSpan.textContent = message;
    }
  };

  updateStatus();

  const randomDelay = 3000 + (Math.random() * 1500);
  const interval = setInterval(updateStatus, randomDelay);
  ui.setLoadingInterval(interval); 

  return loadingContainer;
}

/**
 * Clears all messages from the chat window and resets the day divider state.
 */
export function resetChatView() {
  ui._ensureElements();
  lastRenderedDay = '';
  while (ui.elements.chatWindow.firstChild) {
    ui.elements.chatWindow.removeChild(ui.elements.chatWindow.firstChild);
  }
}

/**
 * Displays the initial empty state with profile information and example prompts.
 */
export function displayEmptyState(activeProfile, promptClickHandler) {
  ui._ensureElements();
  const existingEmptyState = document.querySelector('.empty-state-container');
  if (existingEmptyState) {
    existingEmptyState.remove();
  }

  if (activeProfile && ui.elements.chatWindow) {
    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    
    const description = activeProfile.description_short || activeProfile.description || '';
    const descriptionHtml = description
      ? `<p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-2xl mx-auto">${description}</p>`
      : '';
    
    const avatarUrl = getAvatarForProfile(activeProfile.name);

    const emptyStateContainer = document.createElement('div');
    emptyStateContainer.className = 'empty-state-container';
    
    // --- THIS IS THE FIX ---
    // Add margin and set width to 98%
    emptyStateContainer.style.width = '98%';
    emptyStateContainer.style.margin = '0 auto';
    // --- END FIX ---

    emptyStateContainer.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <img src="${avatarUrl}" alt="${activeProfile.name || 'SAFi'} Avatar" class="w-20 h-20 rounded-lg mx-auto mt-4">
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-4">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        ${descriptionHtml}
         <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, open the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> 'Control Panel'.
        </div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-6xl mx-auto">${promptsHtml}</div>
      </div>`;
    
    ui.elements.chatWindow.appendChild(emptyStateContainer);

    emptyStateContainer.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
  }
}