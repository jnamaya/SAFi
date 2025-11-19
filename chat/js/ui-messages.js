// ui-messages.js

import { formatTime } from './utils.js';
import * as ui from './ui.js'; 
import { getAvatarForProfile } from './ui-auth-sidebar.js'; 
import { playSpeech } from './tts-audio.js'; 
import { iconPlay } from './ui-render-constants.js'; 

// --- ICONS ---
const iconCopy = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
const iconCheck = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
const iconShield = `<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>`;

// --- CONFIG: Persona-Specific Loading Messages ---
const LOADING_MESSAGES = {
    default: ["Consulting with the Intellect...", "Structuring the response...", "Checking against safety guidelines...", "Finalizing output..."],
    "The Philosopher": ["Consulting Aristotle's Ethics...", "Applying the Golden Mean...", "Analyzing for Eudaimonia...", "Ensuring practical wisdom (Phronesis)..."],
    "The Bible Scholar": ["Consulting the Berean Standard Bible...", "Analyzing historical context...", "Checking cross-references...", "Synthesizing theological consensus..."],
    "The Fiduciary": ["Analyzing financial context...", "Checking for fiduciary alignment...", "Ensuring objective, non-advisory tone...", "Verifying disclaimers..."],
    "The Jurist": ["Reviewing Constitutional precedents...", "Analyzing via the Bill of Rights...", "Checking separation of powers...", "Ensuring legal neutrality..."],
    "The Health Navigator": ["Reviewing medical terminology...", "Checking patient privacy guidelines...", "Ensuring non-diagnostic tone...", "Structuring clear guidance..."],
    "The SAFi Guide": ["Searching SAFi documentation...", "Verifying architecture details...", "Checking framework concepts...", "Formatting technical explanation..."]
};

// --- MARKDOWN SETUP ---
const renderer = new marked.Renderer();
renderer.table = function(token) {
    let header = '';
    let body = '';
    let headerRow = '';
    for (const cell of token.header) { headerRow += this.tablecell(cell); }
    header += this.tablerow({ text: headerRow });
    for (const row of token.rows) {
        let bodyRow = '';
        for (const cell of row) { bodyRow += this.tablecell(cell); }
        body += this.tablerow({ text: bodyRow });
    }
    if (body) body = `<tbody>${body}</tbody>`;
    return `<div class="table-wrapper"><table><thead>${header}</thead>${body}</table></div>`;
};
marked.setOptions({ renderer: renderer, breaks: false, gfm: true, mangle: false, headerIds: false });

function _markdownToPlainText(markdown) {
    try {
        const html = marked.parse(markdown);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        return tempDiv.textContent || tempDiv.innerText || '';
    } catch (e) { return markdown; }
}

// --- HELPER: Create Trust Score Pill ---
function _createTrustPill(score, onClick) {
    const button = document.createElement('button');
    button.className = 'trust-score-pill';
    
    // Default to Green/High if score is missing but audit exists, or parse score
    const numScore = (score === null || score === undefined) ? 10.0 : parseFloat(score);
    
    let colorClass = 'trust-green';
    let label = 'Aligned';

    if (numScore < 5.0) {
        colorClass = 'trust-red';
        label = 'Concern';
    } else if (numScore < 8.0) {
        colorClass = 'trust-yellow';
        label = 'Caution';
    }

    button.classList.add(colorClass);
    
    // Accessible label
    button.setAttribute('aria-label', `Trust Score: ${numScore.toFixed(1)} out of 10. Click to view reasoning.`);
    button.setAttribute('title', 'View Ethical Reasoning');

    button.innerHTML = `
        ${iconShield}
        <span>${numScore.toFixed(1)}/10 ${label}</span>
    `;
    
    button.addEventListener('click', (e) => {
        e.stopPropagation();
        onClick();
    });
    
    return button;
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
  const existing = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (existing) existing.remove();
  const div = document.createElement('div');
  div.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  div.textContent = `Hi ${firstName}`;
  ui.elements.chatWindow.appendChild(div);
}

function _attachSuggestionHandlers(container) {
    if (!container) return;
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => btn.replaceWith(btn.cloneNode(true)));
    container.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            ui.elements.messageInput.value = btn.textContent.replace(/"/g, '').trim();
            ui.elements.sendButton.disabled = false;
            ui.elements.messageInput.style.height = 'auto';
            ui.elements.messageInput.style.height = `${ui.elements.messageInput.scrollHeight}px`;
            ui.elements.messageInput.focus();
            if (ui.elements.sendButton) ui.elements.sendButton.click();
            btn.closest('.prompt-suggestions-container')?.remove();
        });
    });
}

function _renderSuggestionsHtml(suggestedPrompts, isBlocked) {
    if (!suggestedPrompts?.length) return '';
    const list = suggestedPrompts.map(p => `<button class="ai-prompt-suggestion-btn text-left w-full p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors border border-neutral-200 dark:border-neutral-700 text-sm italic">"${p}"</button>`).join('');
    return `<div class="mt-3 pt-3 border-t border-neutral-200 dark:border-neutral-700 space-y-2 prompt-suggestions-container"><p class="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider mb-1">${isBlocked ? "Try a different prompt:" : "Suggested follow-ups:"}</p>${list}</div>`;
}

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null, options = {}) {
  ui._ensureElements();
  document.querySelector('.empty-state-container')?.remove();
  document.querySelector('.simple-greeting')?.remove();
  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) messageContainer.dataset.messageId = messageId;

  let final_text;
  if (typeof text === 'object' && text !== null) {
      final_text = "```json\n" + JSON.stringify(text, null, 2) + "\n```";
  } else {
      final_text = String(text ?? '[Sorry, the model returned an empty response.]');
  }

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;
  
  let ttsBtn, copyBtn;

  if (sender === 'ai') {
    const profileName = payload?.profile || null;
    const avatarUrl = getAvatarForProfile(profileName);
    let promptsHtml = '';
    if (options.suggestedPrompts?.length > 0) {
        promptsHtml = _renderSuggestionsHtml(options.suggestedPrompts, final_text.includes("🛑 **The answer was blocked**"));
    }

    ttsBtn = document.createElement('button');
    ttsBtn.className = 'tts-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    ttsBtn.innerHTML = iconPlay;
    ttsBtn.onclick = () => playSpeech(final_text, ttsBtn);

    copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    copyBtn.innerHTML = iconCopy;
    copyBtn.onclick = () => {
        navigator.clipboard.writeText(_markdownToPlainText(final_text)).then(() => {
            ui.showToast('Copied', 'success');
            copyBtn.innerHTML = iconCheck;
            setTimeout(() => copyBtn.innerHTML = iconCopy, 2000);
        });
    };

    messageDiv.innerHTML = `
      <div class="ai-avatar"><img src="${avatarUrl}" class="w-full h-full rounded-lg"></div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble"><div class="meta"></div></div>
        ${promptsHtml}
      </div>
    `;
    messageDiv.querySelector('.chat-bubble').insertAdjacentHTML('afterbegin', DOMPurify.sanitize(marked.parse(final_text)));
  } else {
    const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
    messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">${DOMPurify.sanitize(marked.parse(final_text))}<div class="meta"></div></div>
        </div>
        <div class="user-avatar"><img src="${avatarUrl}" class="w-full h-full rounded-full"></div>
    `;
  }

  const metaDiv = messageDiv.querySelector('.meta');
  const leftMeta = document.createElement('div');
  const rightMeta = document.createElement('div');
  rightMeta.className = 'flex items-center gap-2 ml-auto';

  // --- NEW: Add Trust Pill (Link Removed) ---
  const hasLedger = payload?.ledger?.length > 0;
  if (hasLedger && whyHandler) {
      // 1. Create and append the pill
      const pill = _createTrustPill(payload.spirit_score, () => whyHandler(payload));
      leftMeta.appendChild(pill);
  }

  const stamp = document.createElement('div');
  stamp.className = 'stamp text-xs';
  stamp.textContent = formatTime(date);

  if (sender === 'ai') {
      if (copyBtn) rightMeta.prepend(copyBtn);
      if (ttsBtn) rightMeta.prepend(ttsBtn);
  }
  rightMeta.appendChild(stamp);
  metaDiv.appendChild(leftMeta);
  metaDiv.appendChild(rightMeta);

  messageContainer.appendChild(messageDiv);
  ui.elements.chatWindow.appendChild(messageContainer);
  ui.scrollToBottom();
  _attachSuggestionHandlers(messageContainer);
  return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const container = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!container) return;

    const hasLedger = payload?.ledger?.length > 0;
    if (hasLedger) {
        const metaDiv = container.querySelector('.meta');
        if (metaDiv) {
            // Clean up old buttons (text link OR old pill)
            metaDiv.querySelectorAll('.why-btn').forEach(el => el.remove());
            metaDiv.querySelectorAll('.trust-score-pill').forEach(el => el.remove());

            // Create new pill with updated score
            const pill = _createTrustPill(payload.spirit_score, () => whyHandler(payload));

            let leftMeta = metaDiv.querySelector('div:first-child');
            if (!leftMeta || leftMeta.classList.contains('flex')) { // basic check if it's the left container
                leftMeta = document.createElement('div');
                metaDiv.prepend(leftMeta);
            }
            
            // Prepend only the pill
            leftMeta.prepend(pill);
        }
    }

    const wrapper = container.querySelector('.ai-content-wrapper');
    if (wrapper && payload.suggested_prompts?.length > 0 && !container.querySelector('.prompt-suggestions-container')) {
        wrapper.insertAdjacentHTML('beforeend', _renderSuggestionsHtml(payload.suggested_prompts, false));
        _attachSuggestionHandlers(wrapper);
    }
}

export function showLoadingIndicator(profileName) {
  ui._ensureElements();
  ui.clearLoadingInterval(); 
  document.querySelector('.empty-state-container')?.remove();
  document.querySelector('.simple-greeting')?.remove();
  maybeInsertDayDivider(new Date());

  const container = document.createElement('div');
  container.className = 'message-container';
  const avatarUrl = getAvatarForProfile(profileName || null);
  
  container.innerHTML = `
    <div class="message ai">
        <div class="ai-avatar"><img src="${avatarUrl}" class="w-full h-full rounded-lg"></div>
        <div class="ai-content-wrapper">
            <div class="flex items-center gap-3">
              <div class="thinking-spinner"></div>
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic transition-opacity duration-200">Thinking...</span>
            </div>
        </div>
    </div>`;
  ui.elements.chatWindow.appendChild(container);
  ui.scrollToBottom();

  const statusSpan = container.querySelector('#thinking-status');
  const messages = LOADING_MESSAGES[profileName] || LOADING_MESSAGES.default;
  let stage = 0;
  
  if(statusSpan) statusSpan.textContent = messages[0];

  const interval = setInterval(() => {
      stage++;
      const msg = messages[stage % messages.length];
      if (statusSpan) {
          statusSpan.style.opacity = '0';
          setTimeout(() => {
              statusSpan.textContent = msg;
              statusSpan.style.opacity = '1';
          }, 200);
      }
  }, 2500);
  ui.setLoadingInterval(interval);

  return container;
}

export function resetChatView() {
  ui._ensureElements();
  lastRenderedDay = '';
  ui.elements.chatWindow.innerHTML = '';
}

export function displayEmptyState(activeProfile, promptClickHandler) {
  ui._ensureElements();
  document.querySelector('.empty-state-container')?.remove();
  if (!activeProfile) return;

  const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
  const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
  const avatarUrl = getAvatarForProfile(activeProfile.name);
  
  const container = document.createElement('div');
  container.className = 'empty-state-container';
  container.style.cssText = 'width: 98%; margin: 0 auto;';
  container.innerHTML = `
      <div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <img src="${avatarUrl}" class="w-20 h-20 rounded-lg mx-auto mt-4">
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-4">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        <p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-2xl mx-auto">${activeProfile.description || ''}</p>
        <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, open the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> 'Control Panel'.
        </div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mx-auto w-full">${promptsHtml}</div>
      </div>`;
  
  ui.elements.chatWindow.appendChild(container);
  container.querySelectorAll('.example-prompt-btn').forEach(btn => {
      btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
  });
}