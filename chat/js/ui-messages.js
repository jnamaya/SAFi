// ui-messages.js

import { formatTime } from './utils.js';
import * as ui from './ui.js'; 
import { getAvatarForProfile } from './ui-auth-sidebar.js'; 
import { playSpeech } from './tts-audio.js'; 
import { iconPlay } from './ui-render-constants.js'; 

// --- ICONS ---
const iconCopy = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
const iconCheck = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;

// --- CONFIG: Persona-Specific Loading Messages ---
const LOADING_MESSAGES = {
    default: [
        "Consulting with the Intellect...",
        "Structuring the response...",
        "Checking against safety guidelines...",
        "Finalizing output..."
    ],
    "The Philosopher": [
        "Consulting Aristotle's Ethics...",
        "Applying the Golden Mean...",
        "Analyzing for Eudaimonia...",
        "Ensuring practical wisdom (Phronesis)..."
    ],
    "The Bible Scholar": [
        "Consulting the Berean Standard Bible...",
        "Analyzing historical context...",
        "Checking cross-references...",
        "Synthesizing theological consensus..."
    ],
    "The Fiduciary": [
        "Analyzing financial context...",
        "Checking for fiduciary alignment...",
        "Ensuring objective, non-advisory tone...",
        "Verifying disclaimers..."
    ],
    "The Jurist": [
        "Reviewing Constitutional precedents...",
        "Analyzing via the Bill of Rights...",
        "Checking separation of powers...",
        "Ensuring legal neutrality..."
    ],
    "The Health Navigator": [
        "Reviewing medical terminology...",
        "Checking patient privacy guidelines...",
        "Ensuring non-diagnostic tone...",
        "Structuring clear guidance..."
    ],
    "The SAFi Guide": [
        "Searching SAFi documentation...",
        "Verifying architecture details...",
        "Checking framework concepts...",
        "Formatting technical explanation..."
    ]
};

// --- MARKDOWN & HIGHLIGHTING SETUP ---

// 1. Create a custom renderer to override specific HTML generation
const renderer = new marked.Renderer();

// 2. Override the 'table' renderer to wrap it in a scrollable div
// FIXED for Marked v15+: Accepts a single 'token' object instead of header/body strings
renderer.table = function(token) {
    let header = '';
    let body = '';
    
    // Reconstruct the header HTML using the renderer's own cell method
    // Marked v15 stores header cells in token.header
    let headerRow = '';
    if (token.header) {
        for (const cell of token.header) {
            headerRow += this.tablecell(cell); 
        }
    }
    header += this.tablerow({ text: headerRow });

    // Reconstruct the body HTML
    // Marked v15 stores rows in token.rows
    if (token.rows) {
        for (const row of token.rows) {
            let bodyRow = '';
            for (const cell of row) {
                 bodyRow += this.tablecell(cell);
            }
            body += this.tablerow({ text: bodyRow });
        }
    }
    
    if (body) body = `<tbody>${body}</tbody>`;

    // Wrap in the scrollable container
    return `<div class="table-wrapper">
              <table>
                <thead>${header}</thead>
                ${body}
              </table>
            </div>`;
};

// 3. Apply options including the custom renderer
marked.setOptions({
  renderer: renderer, 
  breaks: false, 
  gfm: true,
  mangle: false,
  headerIds: false,
  highlight: function(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  }
});

/**
 * Converts a markdown string to plain text by stripping all tags.
 */
function _markdownToPlainText(markdown) {
    try {
        const html = marked.parse(markdown);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        return tempDiv.textContent || tempDiv.innerText || '';
    } catch (e) {
        console.error("Error converting markdown to plain text", e);
        return markdown;
    }
}

// --- MESSAGE RENDERING ---

let lastRenderedDay = '';

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

export function displaySimpleGreeting(firstName) {
  ui._ensureElements();
  const existingGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (existingGreeting) existingGreeting.remove();

  const greetingDiv = document.createElement('div');
  greetingDiv.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  greetingDiv.textContent = `Hi ${firstName}`;
  ui.elements.chatWindow.appendChild(greetingDiv);
}

function _attachSuggestionHandlers(container) {
    if (!container) return;
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
      btn.replaceWith(btn.cloneNode(true));
    });
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const promptText = btn.textContent.replace(/"/g, '').trim();
            ui.elements.messageInput.value = promptText;
            ui.elements.sendButton.disabled = false;
            ui.elements.messageInput.style.height = 'auto'; 
            ui.elements.messageInput.style.height = `${ui.elements.messageInput.scrollHeight}px`; 
            ui.elements.messageInput.focus();
            if (ui.elements.sendButton) {
                ui.elements.sendButton.click();
            }
            const suggestionBox = btn.closest('.prompt-suggestions-container');
            if (suggestionBox) {
                suggestionBox.remove();
            }
        });
    });
}

function _renderSuggestionsHtml(suggestedPrompts, isBlocked) {
    if (!suggestedPrompts || suggestedPrompts.length === 0) return '';

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
  let copyButtonElement = null;

  // --- BUG FIX: SAFEGUARD AGAINST RAW OBJECTS ---
  // If the AI returns a raw object (like stock data) instead of a string,
  // we convert it to a JSON code block so the user can see it instead of "[object Object]".
  let final_text;
  if (typeof text === 'object' && text !== null) {
      // Pretty print the object as JSON
      final_text = "```json\n" + JSON.stringify(text, null, 2) + "\n```";
  } else {
      final_text = String(text ?? '[Sorry, the model returned an empty response.]');
  }
  // --- END FIX ---

  if (sender === 'ai') {
    const profileName = (payload && payload.profile) ? payload.profile : null;
    const avatarUrl = getAvatarForProfile(profileName);
    
    let promptsHtml = '';
    if (suggestedPrompts.length > 0) {
        const isBlocked = final_text.includes("🛑 **The answer was blocked**");
        promptsHtml = _renderSuggestionsHtml(suggestedPrompts, isBlocked);
    }

    // --- TTS Button ---
    ttsButtonElement = document.createElement('button'); 
    ttsButtonElement.className = 'tts-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    ttsButtonElement.setAttribute('aria-label', 'Play message audio');
    ttsButtonElement.innerHTML = iconPlay; 
    ttsButtonElement.addEventListener('click', () => {
        playSpeech(final_text, ttsButtonElement); 
    });

    // --- Copy Button ---
    copyButtonElement = document.createElement('button');
    copyButtonElement.className = 'copy-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    copyButtonElement.setAttribute('aria-label', 'Copy message text');
    copyButtonElement.innerHTML = iconCopy;

    copyButtonElement.addEventListener('click', () => {
        const plainText = _markdownToPlainText(final_text);
        navigator.clipboard.writeText(plainText).then(() => {
            ui.showToast('Copied to clipboard', 'success');
            copyButtonElement.innerHTML = iconCheck;
            setTimeout(() => {
                copyButtonElement.innerHTML = iconCopy;
            }, 2000);
        }, (err) => {
            console.error('Failed to copy text: ', err);
            ui.showToast('Failed to copy text', 'error');
        });
    });

    messageDiv.innerHTML = `
      <div class="ai-avatar">
        <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-full h-full rounded-lg">
      </div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble">
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
      whyButton.addEventListener('click', () => whyHandler(payload));
      leftMeta.appendChild(whyButton);
  }
  
  metaDiv.appendChild(leftMeta);

  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp text-xs'; 
  stampDiv.textContent = formatTime(date);
  
  if (sender === 'ai') {
      if (copyButtonElement) rightMeta.prepend(copyButtonElement);
      if (ttsButtonElement) rightMeta.prepend(ttsButtonElement);
  }

  rightMeta.appendChild(stampDiv);
  metaDiv.appendChild(rightMeta);
  
  messageContainer.appendChild(messageDiv);
  ui.elements.chatWindow.appendChild(messageContainer);
  ui.scrollToBottom();
  
  _attachSuggestionHandlers(messageContainer);
  return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const messageContainer = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageContainer) return;

    const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
    
    if (hasLedger) {
        const metaDiv = messageContainer.querySelector('.meta');
        if (!metaDiv) return;

        const oldWhyButton = metaDiv.querySelector('.why-btn');
        if (oldWhyButton) oldWhyButton.remove();

        const whyButton = document.createElement('button');
        whyButton.className = 'why-btn';
        whyButton.textContent = 'View Ethical Reasoning';
        whyButton.addEventListener('click', () => whyHandler(payload)); 

        let leftMeta = metaDiv.querySelector('div:first-child');
        if (!leftMeta || leftMeta.classList.contains('flex')) { 
            leftMeta = document.createElement('div');
            metaDiv.prepend(leftMeta);
        }
        leftMeta.prepend(whyButton);
    }

    const existingSuggestions = messageContainer.querySelector('.prompt-suggestions-container');
    const suggestedPrompts = payload.suggested_prompts || [];

    if (!existingSuggestions && suggestedPrompts.length > 0) {
        const aiContentWrapper = messageContainer.querySelector('.ai-content-wrapper');
        if (aiContentWrapper) {
            const promptsHtml = _renderSuggestionsHtml(suggestedPrompts, false); 
            aiContentWrapper.insertAdjacentHTML('beforeend', promptsHtml);
            _attachSuggestionHandlers(aiContentWrapper);
        }
    }
}

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
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic transition-opacity duration-200">Thinking...</span>
            </div>
        </div>
    </div>`;
  ui.elements.chatWindow.appendChild(loadingContainer);
  ui.scrollToBottom();

  const statusSpan = loadingContainer.querySelector('#thinking-status');

  // --- PERSONA-SPECIFIC LOGIC ---
  const messages = LOADING_MESSAGES[profileName] || LOADING_MESSAGES.default;
  let stage = 0;

  if (statusSpan) statusSpan.textContent = messages[0];

  const updateStatus = () => {
    stage++;
    const message = messages[stage % messages.length];
    if (statusSpan) {
        statusSpan.style.opacity = '0';
        setTimeout(() => {
            statusSpan.textContent = message;
            statusSpan.style.opacity = '1';
        }, 200);
    }
  };

  const interval = setInterval(updateStatus, 2500);
  ui.setLoadingInterval(interval); 

  return loadingContainer;
}

export function resetChatView() {
  ui._ensureElements();
  lastRenderedDay = '';
  while (ui.elements.chatWindow.firstChild) {
    ui.elements.chatWindow.removeChild(ui.elements.chatWindow.firstChild);
  }
}

export function displayEmptyState(activeProfile, promptClickHandler) {
  ui._ensureElements();
  const existingEmptyState = document.querySelector('.empty-state-container');
  if (existingEmptyState) existingEmptyState.remove();

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
    
    emptyStateContainer.style.width = '98%';
    emptyStateContainer.style.margin = '0 auto';

    emptyStateContainer.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <img src="${avatarUrl}" alt="${activeProfile.name || 'SAFi'} Avatar" class="w-20 h-20 rounded-lg mx-auto mt-4">
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-4">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        ${descriptionHtml}
         <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, open the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> 'Control Panel'.
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