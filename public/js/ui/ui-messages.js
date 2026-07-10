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
    default: [
        "Reading your message carefully...",
        "Thinking through the best response...",
        "Reviewing for accuracy and care...",
        "Almost ready..."
    ],
    "The Philosopher": [
        "Consulting Aristotle's Ethics...",
        "Weighing both sides of the question...",
        "Seeking the virtuous path forward...",
        "Crafting a thoughtful, balanced reply..."
    ],
    "The Bible Scholar": [
        "Consulting the Berean Standard Bible...",
        "Analyzing the historical context...",
        "Checking cross-references...",
        "Drawing from scholarly consensus..."
    ],
    "The Fiduciary": [
        "Checking the latest market data...",
        "Reviewing with objectivity and care...",
        "Making sure no advice slips through...",
        "Preparing a clear, balanced response..."
    ],
    "The Jurist": [
        "Reviewing Constitutional precedents...",
        "Analyzing relevant case law...",
        "Checking for legal balance...",
        "Preparing a neutral, informed response..."
    ],
    "The Health Navigator": [
        "Looking into your health question...",
        "Finding relevant care options...",
        "Making sure guidance is safe and clear...",
        "Preparing your response..."
    ],
    "The SAFi Guide": [
        "Searching the SAFi documentation...",
        "Verifying the framework details...",
        "Pulling together the right explanation...",
        "Almost ready..."
    ],
    "The Socratic Tutor": [
        "Thinking of the right question to ask you...",
        "Finding a hint that guides without giving away...",
        "Planning the next step in your learning...",
        "Making sure not to spoil the answer..."
    ],
    "The Vault": [
        "Running security protocols...",
        "Access verification in progress...",
        "Protecting classified information...",
        "Preparing a secure response..."
    ],
    "The Negotiator": [
        "Reviewing your offer...",
        "Considering the negotiation so far...",
        "Thinking through a counter-position...",
        "Preparing a response..."
    ],
    "The Contoso Governance Officer": [
        "Reviewing Contoso IT policies...",
        "Checking compliance requirements...",
        "Consulting the SOPs...",
        "Preparing a governance-aligned response..."
    ],
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
marked.setOptions({
    renderer: renderer,
    breaks: true,
    gfm: true,
    mangle: false,
    headerIds: false,
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    }
});

function _markdownToPlainText(markdown) {
    try {
        const html = marked.parse(markdown);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        return tempDiv.textContent || tempDiv.innerText || '';
    } catch (e) { return markdown; }
}

// --- HELPER: Score segment for the unified action bar ---
const iconChevronRight = `<svg class="score-chevron" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/></svg>`;

function _makeDivider() {
    const d = document.createElement('span');
    d.className = 'actionbar-divider';
    return d;
}

function _createScoreSegment(score, onClick) {
    const numScore = (score === null || score === undefined) ? 10.0 : parseFloat(score);

    let tier = 'seg-green';
    let label = 'Aligned';
    if (numScore < 5.0) {
        tier = 'seg-red';
        label = 'Concern';
    } else if (numScore < 8.0) {
        tier = 'seg-yellow';
        label = 'Caution';
    }

    const button = document.createElement('button');
    button.className = `score-seg ${tier}`;
    button.setAttribute('aria-label', `Alignment score ${numScore.toFixed(1)} out of 10, ${label}. Click to view reasoning.`);
    button.setAttribute('title', 'View alignment reasoning');
    button.innerHTML = `
        <span class="score-dot"></span>
        <span class="score-val">${numScore.toFixed(1)}</span>
        <span class="score-label">${label}</span>
        ${iconChevronRight}
    `;
    button.addEventListener('click', (e) => {
        e.stopPropagation();
        onClick();
    });
    return button;
}

// Score segment + trailing divider, grouped so it can be injected/replaced
// atomically when the audit score arrives after the bar is first rendered.
function _createScoreWrap(score, onClick) {
    const wrap = document.createElement('div');
    wrap.className = 'score-wrap';
    wrap.appendChild(_createScoreSegment(score, onClick));
    wrap.appendChild(_makeDivider());
    return wrap;
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

// --- FILE TYPE CONFIG (mirrors chat.js — used for in-chat attachment cards) ---
function _getFileTypeConfig(filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const configs = {
        pdf:  { label: 'PDF' },
        docx: { label: 'DOC' },
        doc:  { label: 'DOC' },
        xlsx: { label: 'XLS' },
        xls:  { label: 'XLS' },
        csv:  { label: 'CSV' },
        txt:  { label: 'TXT' },
        md:   { label: 'MD'  },
        pptx: { label: 'PPT' },
        ppt:  { label: 'PPT' },
    };
    return configs[ext] || { label: ext.toUpperCase() || 'FILE' };
}

function _formatFileSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
    const list = suggestedPrompts.map(p => `<button class="ai-prompt-suggestion-btn">${p}</button>`).join('');
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
        ttsBtn.className = 'tts-btn shrink-0';
        ttsBtn.innerHTML = iconPlay;
        ttsBtn.onclick = () => playSpeech(final_text_raw, ttsBtn);

        copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn shrink-0';
        copyBtn.innerHTML = iconCopy;
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(_markdownToPlainText(final_text_raw)).then(() => {
                ui.showToast('Copied', 'success');
                copyBtn.innerHTML = iconCheck;
                setTimeout(() => copyBtn.innerHTML = iconCopy, 2000);
            });
        };

        messageDiv.innerHTML = `
      <div class="ai-avatar"><img src="${avatarUrl}" class="w-full h-full"></div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble cursor-pointer"><div class="meta"></div></div>
      </div>
    `;
    } else {
        // User Message - Render text immediately
        if (options.onRetry) {
            retryBtn = document.createElement('button');
            retryBtn.className = 'retry-btn flex items-center justify-center p-1 rounded-full hover:bg-white/20 transition-colors shrink-0 text-white ml-2 opacity-80 hover:opacity-100';
            retryBtn.innerHTML = iconRetry;
            retryBtn.setAttribute('title', 'Retry this prompt');
            retryBtn.onclick = () => options.onRetry(typeof text === 'string' ? text : final_text_raw);
        }

        // Build file attachment cards — supports multiple files
        let fileChipHtml = '';
        // Normalise: new `attachedFiles` (array) or legacy `attachedFile` (string / object)
        const attachedFilesArr = options.attachedFiles
            ? options.attachedFiles
            : (options.attachedFile ? [options.attachedFile] : []);

        if (attachedFilesArr.length > 0) {
            const cards = attachedFilesArr.map(af => {
                const fname    = typeof af === 'string' ? af : (af.name || '');
                const fsize    = (typeof af === 'object' && af !== null) ? af.size : null;
                const cfg      = _getFileTypeConfig(fname);
                const sizeStr  = _formatFileSize(fsize);
                return `
                <div class="inline-flex items-center gap-2.5 px-3 py-2 bg-white/15 rounded-xl border border-white/25 max-w-[280px]">
                    <div class="flex flex-col items-center justify-center w-9 h-11 rounded-lg shrink-0 border bg-white/10 border-white/30">
                        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                        </svg>
                        <span class="text-[9px] font-bold leading-none mt-0.5 text-white/90">${cfg.label}</span>
                    </div>
                    <div class="flex flex-col min-w-0 flex-1">
                        <span class="text-sm font-medium text-white truncate leading-snug">${fname}</span>
                        ${sizeStr ? `<span class="text-xs text-white/65 mt-0.5">${sizeStr}</span>` : ''}
                    </div>
                </div>`;
            });
            fileChipHtml = `<div class="flex flex-wrap gap-2 mb-2">${cards.join('')}</div>`;
        }

        const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
        messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">${fileChipHtml}${final_html}<div class="meta"></div></div>
        </div>
        <div class="user-avatar"><img src="${avatarUrl}" class="w-full h-full"></div>
    `;
    }

    // 2. POPULATE META FOOTER (Before Animation Logic)
    const metaDiv = messageDiv.querySelector('.meta');

    if (sender === 'ai') {
        // Unified action bar: [score segment | copy · audio · time]
        const bar = document.createElement('div');
        bar.className = 'msg-actionbar';

        const hasScore = payload?.spirit_score !== null && payload?.spirit_score !== undefined;
        if (hasScore && whyHandler) {
            bar.appendChild(_createScoreWrap(payload.spirit_score, () => whyHandler(payload)));
        }
        if (copyBtn) bar.appendChild(copyBtn);
        if (ttsBtn) bar.appendChild(ttsBtn);

        const stamp = document.createElement('div');
        stamp.className = 'stamp actionbar-time';
        stamp.textContent = formatTime(date);
        bar.appendChild(stamp);

        metaDiv.appendChild(bar);
    } else {
        // User message: optional retry button + timestamp, right-aligned.
        const rightMeta = document.createElement('div');
        rightMeta.className = 'flex items-center gap-2 ml-auto';

        const stamp = document.createElement('div');
        stamp.className = 'stamp text-xs';
        stamp.textContent = formatTime(date);

        if (retryBtn) rightMeta.prepend(retryBtn);
        rightMeta.appendChild(stamp);
        metaDiv.appendChild(rightMeta);
    }


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
        const bar = metaDiv?.querySelector('.msg-actionbar');
        if (bar) {
            // Replace any existing score (idempotent) and inject at the front.
            bar.querySelector('.score-wrap')?.remove();
            bar.prepend(_createScoreWrap(payload.spirit_score, () => whyHandler(payload)));
        }
    }

    const wrapper = container.querySelector('.ai-content-wrapper');
    if (wrapper && payload.suggested_prompts?.length > 0 && !container.querySelector('.prompt-suggestions-container')) {
        wrapper.insertAdjacentHTML('beforeend', _renderSuggestionsHtml(payload.suggested_prompts, false));
        _attachSuggestionHandlers(wrapper);
    }
}

// State to track current loading profile name
let currentLoadingProfile = null;

export function showLoadingIndicator(profileName) {
    currentLoadingProfile = profileName;
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
        <div class="ai-avatar"><img src="${avatarUrl}" class="w-full h-full"></div>
        <div class="ai-content-wrapper">
            <div class="thinking-container">
                <div class="thinking-pulse-wave">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <span id="thinking-status" class="transition-opacity duration-200">Thinking...</span>
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
    if (!statusSpan || !text) return;
    ui.clearLoadingInterval();
    if (statusSpan.textContent !== text) {
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

// Escape agent-authored text (descriptions, value names, prompts come from the
// DB and are org-user-authored) before it goes through innerHTML.
function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const LOCK_ICON = `<svg class="inline-block w-3 h-3 -mt-0.5 mr-1" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-label="Non-negotiable"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"/></svg>`;

const SHIELD_ICON = `<svg class="inline-block w-3.5 h-3.5 -mt-0.5 mr-1" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/></svg>`;

export function displayEmptyState(activeProfile, promptClickHandler, firstName = '') {
    ui._ensureElements();
    document.querySelector('.empty-state-container')?.remove();
    if (!activeProfile) return;

    // "Scope Compliance" is a synthetic hard gate injected by the compiler; the
    // scope line below already communicates it, so skip its chip.
    const valuesHtml = (activeProfile.values || [])
        .filter(v => (v.value || v.name || '') !== 'Scope Compliance')
        .map(v => {
            const name = escapeHtml(v.value || v.name || '');
            const isGate = !!v.hard_gate;
            const definition = v.definition || v.rubric?.description || '';
            let tip = isGate
                ? `Non-negotiable — responses that violate this value are blocked.${definition ? ' ' + definition : ''}`
                : definition;
            if (tip.length > 200) tip = tip.slice(0, 197) + '…';
            const tipAttr = tip ? ` title="${escapeHtml(tip)}"` : '';
            return `<span class="value-chip${isGate ? ' value-chip-gate' : ''}"${tipAttr}>${isGate ? LOCK_ICON : ''}${name}</span>`;
        })
        .join('');
    const promptsHtml = (activeProfile.example_prompts || [])
        .map(p => `<button class="example-prompt-btn">"${escapeHtml(p)}"</button>`)
        .join('');
    const avatarUrl = getAvatarForProfile(activeProfile.name);

    const container = document.createElement('div');
    container.className = 'empty-state-container';
    container.style.cssText = 'width: 100%; max-width: 56rem; margin: 0 auto; padding: 0 1rem;';

    const greetingHtml = firstName
        ? `<h1 class="text-4xl font-bold text-neutral-800 dark:text-neutral-200 mb-6">Hi ${escapeHtml(firstName)}</h1>`
        : '';

    const descriptionHtml = activeProfile.description
        ? `<p class="text-sm text-neutral-500 dark:text-neutral-400 max-w-lg mx-auto mb-4">${escapeHtml(activeProfile.description)}</p>`
        : '';

    // Governance provenance: who constrains this agent (Charter → Policy).
    const provParts = [];
    if (activeProfile.has_charter) {
        provParts.push(escapeHtml(activeProfile.org_name ? `${activeProfile.org_name} Charter` : 'Org Charter'));
    }
    if (activeProfile.policy_name) provParts.push(escapeHtml(activeProfile.policy_name));
    const governanceHtml = provParts.length
        ? `<p class="text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-2">${SHIELD_ICON}Governed by ${provParts.join(' → ')}</p>`
        : '';

    const scopeHtml = activeProfile.scope_statement
        ? `<p class="text-xs text-neutral-400 dark:text-neutral-500 max-w-lg mx-auto mb-2">Scope: ${escapeHtml(activeProfile.scope_statement)} Questions outside this scope will be redirected.</p>`
        : '';

    const kbName = activeProfile.rag_knowledge_base;
    const kbHtml = kbName
        ? `<p class="text-xs text-neutral-400 dark:text-neutral-500 mb-2">Has access to the &ldquo;${escapeHtml(String(kbName).replace(/[_-]+/g, ' '))}&rdquo; knowledge base.</p>`
        : '';

    const promptsSectionHtml = promptsHtml
        ? `<p class="text-sm text-neutral-500 dark:text-neutral-400 mb-3">Try asking:</p>
           <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mx-auto w-full">${promptsHtml}</div>`
        : '';

    container.innerHTML = `
      <div class="text-center pt-8 pb-4">
        ${greetingHtml}
        <div class="inline-flex items-center gap-3 bg-neutral-100 dark:bg-neutral-800 rounded-2xl px-4 py-3 mb-4">
          <img src="${avatarUrl}" alt="${escapeHtml(activeProfile.name)}" class="w-10 h-10 rounded-lg object-cover shrink-0">
          <div class="text-left">
            <p class="text-xs font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Active Agent</p>
            <p class="text-sm font-semibold text-neutral-800 dark:text-neutral-100">${escapeHtml(activeProfile.name || 'Default')}</p>
          </div>
        </div>
        ${descriptionHtml}
        ${governanceHtml}
        ${scopeHtml}
        ${kbHtml}
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        <p class="text-xs text-neutral-400 dark:text-neutral-500 mt-2 mb-8">
          Switch agents anytime from the <span class="font-semibold">+</span> menu in the message bar.
        </p>
        ${promptsSectionHtml}
      </div>`;

    ui.elements.chatWindow.appendChild(container);

    // Re-select and attach listeners to ensure they work even if DOM slightly shifted
    const promptButtons = container.querySelectorAll('.example-prompt-btn');
    promptButtons.forEach(btn => {
        btn.onclick = (e) => { // Use onclick property for explicit binding
            e.preventDefault();
            e.stopPropagation();
            const text = btn.innerText.replace(/^"|"$/g, ''); // Remove surrounding quotes only
            if (promptClickHandler && typeof promptClickHandler === 'function') {
                promptClickHandler(text);
            }
        };
    });
}