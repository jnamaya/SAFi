// ui-messages.js

import { formatTime } from '../core/utils.js';
import * as ui from './ui.js';
import { getAvatarForProfile } from './ui-auth-sidebar.js';
import { playSpeech } from '../services/tts-audio.js';
import { iconPlay } from './ui-render-constants.js';

// --- ICONS ---
const iconCopy = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
const iconCheck = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
const iconShield = `<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>`;
const iconRetry = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>`;

// --- CONFIG: Persona-Specific Loading Messages ---
const LOADING_MESSAGES = {
    default: ["Consulting with the Intellect...", "Structuring the response...", "Checking against safety guidelines...", "Finalizing output..."],
    "The Philosopher": ["Consulting Aristotle's Ethics...", "Applying the Golden Mean...", "Analyzing for Eudaimonia...", "Ensuring practical wisdom (Phronesis)..."],
    "The Bible Scholar": ["Consulting the Berean Standard Bible...", "Analyzing historical context...", "Checking cross-references...", "Synthesizing theological consensus..."],
    "The Fiduciary": ["Analyzing financial context...", "Checking for fiduciary alignment...", "Ensuring objective, non-advisory tone...", "Verifying disclaimers..."],
    "The Jurist": ["Reviewing Constitutional precedents...", "Analyzing via the Bill of Rights...", "Checking separation of powers...", "Ensuring legal neutrality..."],
    "The Health Navigator": ["Reviewing medical terminology...", "Checking patient privacy guidelines...", "Ensuring non-diagnostic tone...", "Structuring clear guidance..."],
    "The SAFi Guide": ["Searching SAFi documentation...", "Verifying architecture details...", "Checking framework concepts...", "Formatting technical explanation..."],
    // NEW PERSONAS
    "The Socratic Tutor": ["Evaluating student's understanding...", "Formulating a guiding question...", "Checking pedagogical constraints...", "Ensuring the answer isn't revealed..."],
    "The Vault": ["Verifying security clearance...", "Checking for prompt injection...", "Protecting the secret code...", "Formulating a secure refusal..."],
    "The Negotiator": ["Assessing leverage...", "Checking negotiation history...", "Evaluating trust score...", "Formulating a counter-offer..."]
};

// --- MARKDOWN SETUP ---
const renderer = new marked.Renderer();
renderer.table = function (token) {
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

// --- TYPEWRITER STATE ---
let typingTimeout = null;
let currentTypingSession = null;

function stopTyping() {
    if (typingTimeout) {
        clearTimeout(typingTimeout);
        typingTimeout = null;
    }
    currentTypingSession = null;
}

/**
 * Simulates typing by traversing the DOM Tree.
 * Preserves HTML structure (Bold, Tables, Lists) while animating text.
 * NOW WITH ADAPTIVE SPEED.
 */
function typeWriterEffect(targetElement, htmlContent, onComplete) {
    stopTyping();

    // 1. Parse HTML into a virtual DOM fragment
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlContent;

    // 2. Flatten the DOM into a queue of operations
    const steps = [];

    function traverse(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            if (node.textContent.length > 0) {
                steps.push({ type: 'text', content: node.textContent });
            }
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            // Capture attributes (class, href, etc.)
            const attributes = {};
            if (node.attributes) {
                for (const attr of node.attributes) {
                    attributes[attr.name] = attr.value;
                }
            }

            steps.push({ type: 'open', tagName: node.tagName, attributes });

            // Recursively traverse children
            node.childNodes.forEach(traverse);

            // Mark end of element
            steps.push({ type: 'close' });
        }
    }

    // Fill the steps queue
    tempDiv.childNodes.forEach(traverse);

    // 3. Adaptive Speed Calculation
    const fullText = tempDiv.textContent || "";
    const textLength = fullText.length;

    let charsPerTick = 2;
    if (textLength > 50) charsPerTick = 3;
    if (textLength > 100) charsPerTick = 5;
    if (textLength > 500) charsPerTick = 15;
    if (textLength > 1000) charsPerTick = 30;
    if (textLength > 2500) charsPerTick = 80;

    const delay = 5; // 5ms per tick

    // 4. Execution
    let stepIndex = 0;
    let charIndex = 0;
    let currentParent = targetElement;

    // Store session to allow force-finish
    currentTypingSession = {
        element: targetElement,
        fullHtml: htmlContent,
        onComplete
    };

    function type() {
        if (!currentTypingSession) return; // Stopped/Cancelled

        if (stepIndex >= steps.length) {
            if (onComplete) onComplete();
            stopTyping();
            return;
        }

        const step = steps[stepIndex];

        if (step.type === 'open') {
            // Create the element immediately
            const newEl = document.createElement(step.tagName);
            for (const [key, val] of Object.entries(step.attributes)) {
                newEl.setAttribute(key, val);
            }
            currentParent.appendChild(newEl);
            currentParent = newEl; // Step down into this element
            stepIndex++;

            ui.scrollToBottom(); // Scroll on structure change
            type(); // Recursively call immediately (don't wait for tags)
        }
        else if (step.type === 'close') {
            // Step up to parent
            if (currentParent !== targetElement) {
                currentParent = currentParent.parentNode;
            }
            stepIndex++;
            type(); // Recursively call immediately
        }
        else if (step.type === 'text') {
            const content = step.content;

            // Type chunk of text
            const remaining = content.length - charIndex;
            const chunkLength = Math.min(charsPerTick, remaining);
            const chunk = content.substr(charIndex, chunkLength);

            // Efficiently append text
            if (currentParent.lastChild && currentParent.lastChild.nodeType === Node.TEXT_NODE) {
                currentParent.lastChild.textContent += chunk;
            } else {
                currentParent.appendChild(document.createTextNode(chunk));
            }

            charIndex += chunkLength;

            if (charIndex >= content.length) {
                stepIndex++;
                charIndex = 0;
            }

            typingTimeout = setTimeout(type, delay);
        }
    }

    type();
}

function forceFinishTyping() {
    if (currentTypingSession && typingTimeout) {
        clearTimeout(typingTimeout);
        const { element, fullHtml, onComplete } = currentTypingSession;

        element.innerHTML = fullHtml;
        ui.scrollToBottom();

        if (onComplete) onComplete();

        stopTyping();
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
    const existing = ui.elements.chatWindow.querySelector('.simple-greeting');
    if (existing) existing.remove();
    const div = document.createElement('div');
    div.className = 'simple-greeting text-4xl font-bold text-center pt-10 pb-1 text-neutral-800 dark:text-neutral-200';
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

    let final_text_raw;
    if (typeof text === 'object' && text !== null) {
        final_text_raw = "```json\n" + JSON.stringify(text, null, 2) + "\n```";
    } else {
        final_text_raw = String(text ?? '[Sorry, the model returned an empty response.]');
    }

    const final_html = DOMPurify.sanitize(marked.parse(final_text_raw));

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;

    // Define buttons variable here
    let ttsBtn, copyBtn, retryBtn;

    // 1. BUILD BASIC STRUCTURE (No text yet for AI)
    if (sender === 'ai') {
        const profileName = payload?.profile || null;
        const avatarUrl = getAvatarForProfile(profileName);

        ttsBtn = document.createElement('button');
        ttsBtn.className = 'tts-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
        ttsBtn.innerHTML = iconPlay;
        ttsBtn.onclick = () => playSpeech(final_text_raw, ttsBtn);

        copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
        copyBtn.innerHTML = iconCopy;
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(_markdownToPlainText(final_text_raw)).then(() => {
                ui.showToast('Copied', 'success');
                copyBtn.innerHTML = iconCheck;
                setTimeout(() => copyBtn.innerHTML = iconCopy, 2000);
            });
        };

        messageDiv.innerHTML = `
      <div class="ai-avatar"><img src="${avatarUrl}" class="w-full h-full rounded-lg"></div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble cursor-pointer"><div class="meta"></div></div>
      </div>
    `;
    } else {
        // User Message - Render text immediately
        if (options.onRetry) {
            retryBtn = document.createElement('button');
            retryBtn.className = 'retry-btn flex items-center justify-center p-1 rounded-full hover:bg-white/20 transition-colors shrink-0 text-[#f8f8f8] ml-2';
            retryBtn.innerHTML = iconRetry;
            retryBtn.setAttribute('title', 'Retry this prompt');
            retryBtn.onclick = () => options.onRetry(typeof text === 'string' ? text : final_text_raw);
        }

        const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
        messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">${final_html}<div class="meta"></div></div>
        </div>
        <div class="user-avatar"><img src="${avatarUrl}" class="w-full h-full rounded-full"></div>
    `;
    }

    // 2. POPULATE META FOOTER (Before Animation Logic)
    const metaDiv = messageDiv.querySelector('.meta');
    const leftMeta = document.createElement('div');
    const rightMeta = document.createElement('div');
    rightMeta.className = 'flex items-center gap-2 ml-auto';

    const hasScore = payload?.spirit_score !== null && payload?.spirit_score !== undefined;
    if (hasScore && whyHandler) {
        const pill = _createTrustPill(payload.spirit_score, () => whyHandler(payload));
        leftMeta.appendChild(pill);
    }

    const stamp = document.createElement('div');
    stamp.className = 'stamp text-xs';
    stamp.textContent = formatTime(date);

    if (sender === 'ai') {
        if (copyBtn) rightMeta.prepend(copyBtn);
        if (ttsBtn) rightMeta.prepend(ttsBtn);
    } else if (sender === 'user' && retryBtn) {
        rightMeta.prepend(retryBtn);
    }
    rightMeta.appendChild(stamp);
    metaDiv.appendChild(leftMeta);
    metaDiv.appendChild(rightMeta);


    // 3. HANDLE CONTENT & ANIMATION (AI Only)
    if (sender === 'ai') {
        const chatBubble = messageDiv.querySelector('.chat-bubble');
        const contentWrapper = messageDiv.querySelector('.ai-content-wrapper');

        let promptsHtml = '';
        if (options.suggestedPrompts?.length > 0) {
            promptsHtml = _renderSuggestionsHtml(options.suggestedPrompts, final_text_raw.includes("🛑 **The answer was blocked**"));
        }

        if (options.animate) {
            // Safe to remove now because it is fully populated
            metaDiv.remove();

            const clickHandler = () => {
                forceFinishTyping();
                chatBubble.removeEventListener('click', clickHandler);
                chatBubble.classList.remove('cursor-pointer');
            };
            chatBubble.addEventListener('click', clickHandler);

            typeWriterEffect(chatBubble, final_html, () => {
                if (!chatBubble.contains(metaDiv)) chatBubble.appendChild(metaDiv);

                if (promptsHtml && !contentWrapper.querySelector('.prompt-suggestions-container')) {
                    contentWrapper.insertAdjacentHTML('beforeend', promptsHtml);
                    _attachSuggestionHandlers(contentWrapper);
                }
                ui.scrollToBottom();
                chatBubble.removeEventListener('click', clickHandler);
                chatBubble.classList.remove('cursor-pointer');
            });
        } else {
            // Standard instant render
            chatBubble.insertAdjacentHTML('afterbegin', final_html);
            chatBubble.classList.remove('cursor-pointer');
            if (promptsHtml) {
                contentWrapper.insertAdjacentHTML('beforeend', promptsHtml);
                _attachSuggestionHandlers(contentWrapper);
            }
        }
    }

    // 4. APPEND TO DOM
    messageContainer.appendChild(messageDiv);
    ui.elements.chatWindow.appendChild(messageContainer);

    if (!options.animate) {
        ui.scrollToBottom();
    }

    _attachSuggestionHandlers(messageContainer);
    return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const container = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!container) return;

    const hasScore = payload?.spirit_score !== null && payload?.spirit_score !== undefined;
    if (hasScore) {
        const metaDiv = container.querySelector('.meta');
        if (metaDiv) {
            metaDiv.querySelectorAll('.why-btn').forEach(el => el.remove());
            metaDiv.querySelectorAll('.trust-score-pill').forEach(el => el.remove());

            const pill = _createTrustPill(payload.spirit_score, () => whyHandler(payload));

            let leftMeta = metaDiv.querySelector('div:first-child');
            if (!leftMeta || leftMeta.classList.contains('flex')) {
                leftMeta = document.createElement('div');
                metaDiv.prepend(leftMeta);
            }
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

    if (statusSpan) statusSpan.textContent = messages[0];

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

export function updateThinkingStatus(text) {
    const statusSpan = document.getElementById('thinking-status');
    if (statusSpan && statusSpan.textContent !== text) {
        // Stop the generic "Thinking..." rotator to prioritize real reasoning
        ui.clearLoadingInterval();

        statusSpan.style.opacity = '0';
        setTimeout(() => {
            statusSpan.textContent = text;
            statusSpan.style.opacity = '1';
        }, 200);
    }
}

export function resetChatView() {
    ui._ensureElements();
    stopTyping(); // stop any active animation when switching
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
    container.style.cssText = 'width: 100%; max-width: 56rem; margin: 0 auto; padding: 0 1rem;';

    // --- UPDATED INSTRUCTION TEXT AND ICON ---
    container.innerHTML = `
      <div class="text-center pt-2">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <img src="${avatarUrl}" class="w-20 h-20 rounded-lg mx-auto mt-4">
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-4">agent, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        <p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-2xl mx-auto">${activeProfile.description || ''}</p>
        
        <!-- CHANGED: Updated text and replaced gear icon with ellipsis -->
        <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different agent, click your profile <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z"></path></svg> in the sidebar.
        </div>
        
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mx-auto w-full">${promptsHtml}</div>
      </div>`;

    ui.elements.chatWindow.appendChild(container);
    container.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
}