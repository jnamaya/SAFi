// ui-messages.js

import { formatTime } from '../core/utils.js';
import * as ui from './ui.js';
import * as api from '../core/api.js';
import { getAvatarForProfile } from './ui-auth-sidebar.js';
import { playSpeech } from '../services/tts-audio.js';
import { iconPlay } from './ui-render-constants.js';
import { getActiveModelLabel, isPublicDemoUi } from './ui-model-selector.js';

// --- ICONS ---
const iconCopy = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
const iconCheck = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
const iconShield = `<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>`;
const iconRetry = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>`;
const iconDots = `<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.75"/><circle cx="12" cy="12" r="1.75"/><circle cx="19" cy="12" r="1.75"/></svg>`;

// Action-menu outside-click close: bind once for the whole module, not per
// message (a listener per rendered message would leak).
let _actionMenuOutsideBound = false;
function _bindActionMenuOutsideClose() {
    if (_actionMenuOutsideBound) return;
    _actionMenuOutsideBound = true;
    document.addEventListener('click', () => {
        document.querySelectorAll('.msg-action-menu:not(.hidden)')
            .forEach(m => m.classList.add('hidden'));
    });
}

// A document needs a title. Prefer the answer's first markdown heading, else
// its first non-empty line trimmed to a sensible length, else a default.
function _deriveDocTitle(raw) {
    const lines = String(raw || '').split('\n');
    for (const ln of lines) {
        const h = ln.match(/^#{1,6}\s+(.*)$/);
        if (h && h[1].trim()) return h[1].trim().slice(0, 80);
    }
    for (const ln of lines) {
        const t = ln.trim().replace(/[*_`#>-]/g, '').trim();
        if (t) return t.slice(0, 60);
    }
    return 'SAFi Document';
}

// The overflow (⋯) control: keeps the action bar to copy + audio and tucks
// the rest (retry, save, exports) behind one button. Retry lives here rather
// than as an icon so it can't be misclicked for Listen — an accidental retry
// re-runs a governed turn, which the deliberate menu click prevents. Renders
// the already-governed answer to a downloadable file via the export endpoint.
function _createOverflowControl({ getText, getAgent, messageId, onRedo }) {
    _bindActionMenuOutsideClose();
    const wrap = document.createElement('div');
    wrap.className = 'overflow-control relative shrink-0';

    const btn = document.createElement('button');
    btn.className = 'overflow-btn shrink-0';
    btn.innerHTML = iconDots;
    btn.title = 'More actions';
    btn.setAttribute('aria-label', 'More actions');

    const menu = document.createElement('div');
    // right-0: the button sits near the right of the bar, so the menu opens
    // toward the left edge rather than off-screen.
    menu.className = 'msg-action-menu hidden absolute z-50 bottom-full mb-1 right-0 min-w-[180px] rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 shadow-lg py-1';

    const item = (label, onClick) => {
        const b = document.createElement('button');
        b.className = 'block w-full text-left px-3 py-1.5 text-sm text-neutral-700 dark:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-neutral-700';
        b.textContent = label;
        b.onclick = (e) => {
            e.stopPropagation();
            menu.classList.add('hidden');
            onClick();
        };
        return b;
    };

    // Retry first: re-ask the prompt that produced this answer. In the menu
    // (not an icon) so it is a deliberate click — a stray retry re-runs a
    // governed turn.
    if (onRedo) {
        menu.appendChild(item('Retry — ask again', () => onRedo()));
    }

    // Save only when the message has a server-side id (snapshot needs it).
    if (messageId) {
        menu.appendChild(item('Save response', () => {
            document.dispatchEvent(new CustomEvent('safi:save-content', {
                detail: { messageId, anchor: btn },
            }));
        }));
    }

    const exportAs = (label, fmt) => item(label, async () => {
        try {
            ui.showToast(`Preparing ${label}…`, 'info');
            await api.exportDocument({
                text: getText(),
                format: fmt,
                title: _deriveDocTitle(getText()),
                agent: getAgent(),
            });
        } catch (err) {
            ui.showToast(err.message || 'Export failed', 'error');
        }
    });
    menu.appendChild(exportAs('Export as PDF', 'pdf'));
    menu.appendChild(exportAs('Export as Word (.docx)', 'docx'));
    menu.appendChild(exportAs('Export as Markdown', 'md'));

    btn.onclick = (e) => {
        e.stopPropagation();
        const open = !menu.classList.contains('hidden');
        document.querySelectorAll('.msg-action-menu').forEach(m => m.classList.add('hidden'));
        if (!open) menu.classList.remove('hidden');
    };

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    return wrap;
}

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
// Fenced code: header bar with language label + per-block copy button.
// Highlighting happens here because marked v5+ dropped the setOptions
// `highlight` hook the old code relied on.
renderer.code = function (token) {
    const lang = (token.lang || '').trim().split(/\s+/)[0];
    let highlighted;
    let langClass = '';
    try {
        if (lang && hljs.getLanguage(lang)) {
            highlighted = hljs.highlight(token.text, { language: lang }).value;
            langClass = ` language-${lang}`;
        } else {
            highlighted = hljs.highlightAuto(token.text).value;
        }
    } catch (e) {
        highlighted = escapeHtml(token.text);
    }
    return `<div class="code-block">`
        + `<div class="code-block-header">`
        + `<span class="code-block-lang">${escapeHtml(lang || 'code')}</span>`
        + `<button type="button" class="code-copy-btn" aria-label="Copy code">${iconCopy}<span>Copy</span></button>`
        + `</div>`
        + `<pre><code class="hljs${langClass}">${highlighted}</code></pre>`
        + `</div>`;
};
// External links open in a new tab instead of navigating away mid-conversation.
renderer.link = function (token) {
    const html = marked.Renderer.prototype.link.call(this, token);
    return html.replace(/^<a /, '<a target="_blank" rel="noopener noreferrer" ');
};
marked.setOptions({
    renderer: renderer,
    breaks: true,
    gfm: true,
    mangle: false,
    headerIds: false
});

// Delegated handler for the per-block copy buttons (message HTML is injected
// via innerHTML, so listeners can't be attached at render time).
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.code-copy-btn');
    if (!btn) return;
    const codeEl = btn.closest('.code-block')?.querySelector('pre code');
    if (!codeEl) return;
    navigator.clipboard.writeText(codeEl.textContent || '').then(() => {
        btn.classList.add('copied');
        btn.innerHTML = `${iconCheck}<span>Copied</span>`;
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = `${iconCopy}<span>Copy</span>`;
        }, 1500);
    });
});

function _markdownToPlainText(markdown) {
    try {
        const html = marked.parse(markdown);
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        // Code-block header chrome (lang label, Copy button) is UI, not content.
        tempDiv.querySelectorAll('.code-block-header').forEach(el => el.remove());
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

// Conflicts below this confidence stay in the modal rather than on the chip —
// the inline treatment is only worth its space when the finding is firm.
const CONFLICT_CONF_MIN = 0.7;

const iconWarn = `<svg class="conflict-warn" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m0 3.5h.01M10.36 3.59L2.7 16.5A1.9 1.9 0 004.34 19.4h15.32a1.9 1.9 0 001.64-2.9L13.64 3.59a1.9 1.9 0 00-3.28 0z"/></svg>`;

// Conflicts worth surfacing without opening anything, strongest first. A
// missing `confidence` counts as qualifying: dropping a conflict because its
// metadata is absent is the wrong direction to be wrong in.
function _significantConflicts(payload) {
    const ledger = Array.isArray(payload?.ledger) ? payload.ledger : [];
    return ledger
        .filter(r => (r?.score || 0) < 0 && (r?.confidence ?? 1) >= CONFLICT_CONF_MIN)
        .sort((a, b) => (b?.confidence ?? 1) - (a?.confidence ?? 1));
}

/**
 * The single definition of a turn's alignment tier.
 *
 * Consumed by BOTH the score chip and the avatar's status ring. Kept in one
 * place deliberately: two copies of these thresholds would eventually disagree,
 * and a ring showing green beside a chip reading "Caution" on the same turn is
 * worse than either signal alone in a product whose whole claim is that the
 * displayed judgement is the recorded one.
 *
 * No score means the audit has not completed. Never fabricate one — the
 * conscience modal shows "N/A · audit pending" for the same state, and a chip
 * reading "10.0 Aligned" for a turn nothing has judged is the single most
 * misleading thing this bar could say. The ring is larger and more prominent
 * than the chip, so `pending` there must read as neutral, never as aligned.
 */
export function _scoreTier(payload) {
    const raw = payload?.spirit_score;
    const hasScore = raw !== null && raw !== undefined && !Number.isNaN(parseFloat(raw));
    const numScore = hasScore ? parseFloat(raw) : null;

    let tier = 'seg-green';
    let label = 'Aligned';
    if (!hasScore) {
        tier = 'seg-pending';
        label = 'Audit pending';
    } else if (numScore < 5.0) {
        tier = 'seg-red';
        label = 'Concern';
    } else if (numScore < 8.0) {
        tier = 'seg-yellow';
        label = 'Caution';
    }
    return { tier, label, hasScore, numScore };
}

/** Ring classes are derived mechanically from the chip's tier, so the two
 *  vocabularies cannot drift into meaning different things. */
const RING_CLASSES = ['ring-pending', 'ring-green', 'ring-yellow', 'ring-red'];

/**
 * Paint the avatar's status ring with the turn's outcome.
 *
 * Called at first render (usually `pending` on a live turn, the real tier when
 * replaying history) and again from updateMessageWithAudit() when the async
 * audit lands. Safe to call repeatedly.
 */
function _applyRingState(container, payload) {
    const avatar = container?.querySelector('.ai-avatar');
    if (!avatar) return;
    const { tier } = _scoreTier(payload);
    avatar.classList.remove(...RING_CLASSES);
    avatar.classList.add(tier.replace('seg-', 'ring-'));
}

function _createScoreSegment(payload, onClick) {
    const { tier, label, hasScore, numScore } = _scoreTier(payload);

    const conflicts = _significantConflicts(payload);
    const n = conflicts.length;
    const countWord = n === 1 ? 'conflict' : 'conflicts';
    const countText = `${n} ${countWord}`;

    const button = document.createElement('button');
    button.className = `score-seg ${tier}${n > 0 ? ' has-conflicts' : ''}`;
    button.setAttribute('aria-label', hasScore
        ? `Alignment score ${numScore.toFixed(1)} out of 10, ${label}${n > 0 ? `, ${countText}` : ''}. Click to view reasoning.`
        : 'Alignment audit pending. Click to view reasoning.');
    button.setAttribute('title', n > 0 ? 'View the conflicts' : 'View alignment reasoning');
    button.innerHTML = `
        <span class="score-dot"></span>
        <span class="score-val">${hasScore ? numScore.toFixed(1) : '—'}</span>
        <span class="score-label">${label}</span>
        ${n > 0 ? `<span class="score-conflicts">${iconWarn}<span class="conflict-n">${n}</span> <span class="conflict-word">${countWord}</span></span>` : ''}
        ${iconChevronRight}
    `;
    button.addEventListener('click', (e) => {
        e.stopPropagation();
        onClick();
    });
    return button;
}

// Names the strongest conflicting value under the bubble. Deliberately not
// gated on score tier: a turn can score 8.5 "Aligned" and still carry a firm
// conflict, and that is exactly the turn a reviewer must not skim past.
function _createConflictNote(payload, onClick) {
    const conflicts = _significantConflicts(payload);
    if (conflicts.length === 0) return null;

    const top = conflicts[0];
    const name = String(top.value || top.name || top.Value || 'an unnamed value');
    const others = conflicts.length - 1;

    const note = document.createElement('button');
    note.className = 'conflict-note';
    note.setAttribute('title', 'View the conflicts');
    note.innerHTML = `${iconWarn}<span>Conflicts with <strong>${escapeHtml(name)}</strong>${others > 0 ? ` and ${others} other${others === 1 ? '' : 's'}` : ''}</span>`;
    note.addEventListener('click', (e) => {
        e.stopPropagation();
        onClick();
    });
    return note;
}

// Score segment + trailing divider, grouped so it can be injected/replaced
// atomically when the audit score arrives after the bar is first rendered.
function _createScoreWrap(payload, onClick) {
    const wrap = document.createElement('div');
    wrap.className = 'score-wrap';
    wrap.appendChild(_createScoreSegment(payload, onClick));
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
            // Insert as one unit: SVG can't be rebuilt with createElement
            // (needs createElementNS), and UI chrome like the code-block
            // header should appear whole, not letter-by-letter.
            if (node.tagName.toLowerCase() === 'svg' ||
                (node.classList && node.classList.contains('code-block-header'))) {
                steps.push({ type: 'atomic', html: node.outerHTML });
                return;
            }

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
        else if (step.type === 'atomic') {
            currentParent.insertAdjacentHTML('beforeend', step.html);
            stepIndex++;
            type(); // No delay — chrome appears whole
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
    let ttsBtn, copyBtn, retryBtn, overflowCtrl;

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

        // Retry now lives in the overflow menu (see _createOverflowControl):
        // re-asking re-runs a governed turn, so it is a deliberate menu click
        // rather than an icon adjacent to Listen. chat.js hands in onRedo
        // because regenerating means re-entering sendMessage with the preceding
        // prompt, which this renderer doesn't know. It asks AGAIN rather than
        // replacing: the new governed turn is its own audit record and the old
        // one stays on the trail.

        // Overflow (⋯): Save + the export options, so the bar stays copy /
        // retry / audio. Save-to-folder needs a server-side message id (the
        // snapshot is taken from chat_history), so it only appears with one.
        overflowCtrl = _createOverflowControl({
            getText: () => final_text_raw,
            getAgent: () => payload?.profile || '',
            messageId,
            onRedo: options.onRedo,
        });

        messageDiv.innerHTML = `
      <div class="ai-avatar"><img src="${avatarUrl}" alt="${escapeHtml(profileName || 'AI agent')}" class="w-full h-full"></div>
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

        const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/16a34a/FFFFFF?text=U`;
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
            bar.appendChild(_createScoreWrap(payload, () => whyHandler(payload)));
        }
        // Kept visible: copy, audio. Retry, save, and exports live behind the
        // overflow (⋯), which sits last. Retry is out of the bar so it can't
        // be misclicked for Listen.
        if (copyBtn) bar.appendChild(copyBtn);
        if (ttsBtn) bar.appendChild(ttsBtn);

        const stamp = document.createElement('div');
        stamp.className = 'stamp actionbar-time';
        stamp.textContent = formatTime(date);
        bar.appendChild(stamp);

        if (overflowCtrl) bar.appendChild(overflowCtrl);

        // Conflict note claims its own line above the bar (see .conflict-note).
        const conflictNote = whyHandler ? _createConflictNote(payload, () => whyHandler(payload)) : null;
        if (conflictNote) metaDiv.appendChild(conflictNote);
        metaDiv.appendChild(bar);

        // Paint the avatar ring with the same tier as the chip. On a live turn
        // the score has not arrived yet, so this sets `pending` (neutral grey)
        // and updateMessageWithAudit() repaints it; when replaying history the
        // score is already present and the real outcome shows immediately.
        _applyRingState(messageDiv, payload);
    } else {
        // User message: copy + optional retry + timestamp, right-aligned.
        const rightMeta = document.createElement('div');
        rightMeta.className = 'flex items-center gap-2 ml-auto';

        // Copy the prompt. Unconditional — unlike retry it needs no send
        // machinery, and unlike the AI copy it needs no server id. Copies the
        // RAW prompt text, not the rendered HTML, so what lands on the
        // clipboard is what was typed. Styled like the retry button: the user
        // bubble is white-on-green, so the AI bar's grey icons would vanish.
        const copyPromptBtn = document.createElement('button');
        copyPromptBtn.className = 'copy-prompt-btn flex items-center justify-center p-1 rounded-full hover:bg-white/20 transition-colors shrink-0 text-white opacity-80 hover:opacity-100';
        copyPromptBtn.innerHTML = iconCopy;
        copyPromptBtn.title = 'Copy prompt';
        copyPromptBtn.setAttribute('aria-label', 'Copy this prompt');
        copyPromptBtn.onclick = () => {
            const raw = typeof text === 'string' ? text : final_text_raw;
            navigator.clipboard.writeText(raw).then(() => {
                ui.showToast('Prompt copied', 'success');
                copyPromptBtn.innerHTML = iconCheck;
                setTimeout(() => copyPromptBtn.innerHTML = iconCopy, 2000);
            });
        };

        const stamp = document.createElement('div');
        stamp.className = 'stamp text-xs';
        stamp.textContent = formatTime(date);

        rightMeta.appendChild(copyPromptBtn);
        if (retryBtn) rightMeta.appendChild(retryBtn);
        rightMeta.appendChild(stamp);
        metaDiv.appendChild(rightMeta);
    }


    // 3. HANDLE CONTENT & ANIMATION (AI Only)
    if (sender === 'ai') {
        const chatBubble = messageDiv.querySelector('.chat-bubble');

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
                ui.scrollToBottom();
                chatBubble.removeEventListener('click', clickHandler);
                chatBubble.classList.remove('cursor-pointer');
            });
        } else {
            // Standard instant render
            chatBubble.insertAdjacentHTML('afterbegin', final_html);
            chatBubble.classList.remove('cursor-pointer');
        }
    }

    // 4. APPEND TO DOM
    messageContainer.appendChild(messageDiv);
    ui.elements.chatWindow.appendChild(messageContainer);

    if (!options.animate) {
        ui.scrollToBottom();
    }

    return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const container = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!container) return;

    // Repaint the ring only when this payload is actually ABOUT the audit.
    //
    // Repainting unconditionally used to reset the ring to grey: a partial
    // payload with no spirit_score scored as `pending` moments after the audit
    // had coloured it. The second caller that sent those partial payloads (the
    // suggestions poller) is gone, but the guard stays — any future partial
    // update would reintroduce the same symptom.
    //
    // Gate on KEY PRESENCE rather than truthiness: an audit that legitimately
    // completes with spirit_score null still carries the key, so it repaints and
    // correctly stays neutral. A suggestions-only update carries neither key and
    // must leave the ring alone.
    const carriesAuditInfo = !!payload
        && ('spirit_score' in payload || 'ledger' in payload);
    if (carriesAuditInfo) _applyRingState(container, payload);

    const hasScore = payload?.spirit_score !== null && payload?.spirit_score !== undefined;
    if (hasScore) {
        const metaDiv = container.querySelector('.meta');
        const bar = metaDiv?.querySelector('.msg-actionbar');
        if (bar) {
            // Replace any existing score (idempotent) and inject at the front.
            bar.querySelector('.score-wrap')?.remove();
            bar.prepend(_createScoreWrap(payload, () => whyHandler(payload)));
        }
        // Same for the conflict note: the ledger only arrives with the audit,
        // so this is where it appears on a live turn. Replace, never duplicate.
        if (metaDiv) {
            metaDiv.querySelector('.conflict-note')?.remove();
            const note = _createConflictNote(payload, () => whyHandler(payload));
            if (note) metaDiv.prepend(note);
        }
    }

}

// --- PIPELINE TRACE ---
// Maps the backend's reasoning-log strings onto the governance pipeline's
// stages so the loader can show real progress, never a fake animation.
// 'Gather' is the agentic tool-call loop: it only exists on turns where the
// agent actually calls tools (log entries tagged phase:"gather") and stays
// hidden otherwise, so plain chat turns keep the 4-stage trace.
const PIPELINE_STAGES = ['Analyze', 'Draft', 'Gather', 'Audit', 'Score'];
const GATHER_STAGE = 2;

function _stageForStep(entry) {
    if (entry?.phase === 'gather') return GATHER_STAGE;
    const t = (entry?.step || '').toLowerCase();
    if (t.startsWith('analyzing')) return 0;
    if (t.startsWith('drafting')) return 1;
    if (t.startsWith('checking response structure')) return 3;
    if (t.includes('audit')) return 3;                  // Auditing / Re-auditing / governance response
    if (t.startsWith('refining')) return 3;             // reflexion loop stays visibly in Audit
    if (t.startsWith('applying governance')) return 3;  // redirect path
    if (t.startsWith('computing alignment')) return 4;
    if (t.startsWith('preparing your answer')) return 4;
    return -1;
}

// "Searching the web (step 2)..." -> "Searching the web"
function _gatherLabel(text) {
    return (text || '').replace(/\s*\(step \d+\)/i, '').replace(/\.{3,}$/, '').trim();
}

const STEP_CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>`;

// Stages start hidden ('unrevealed') and slide in one by one as the backend
// actually reaches them — only the first stage is visible up front.
function _renderPipelineTraceHtml() {
    return `<div class="pipeline-trace" id="pipeline-trace">` + PIPELINE_STAGES.map((label, i) =>
        (i > 0 ? `<span class="step-connector unrevealed"></span>` : '')
        + `<span class="pipeline-step${i === 0 ? ' active' : ' unrevealed'}${i === GATHER_STAGE ? ' gather' : ''}" data-stage="${i}">`
        + `<span class="step-dot">${STEP_CHECK_ICON}</span>`
        + `<span class="step-label">${label}</span>`
        + `</span>`
    ).join('') + `</div>`;
}

function _setTraceStage(stage, gatherSeen, gatherLabel) {
    if (stage < 0) return;
    const trace = document.getElementById('pipeline-trace');
    if (!trace) return;
    trace.querySelectorAll('.pipeline-step').forEach(el => {
        const i = Number(el.dataset.stage);
        // On non-agentic turns the Gather stage never happened — keep it
        // collapsed even after later stages pass it.
        const skip = i === GATHER_STAGE && !gatherSeen;
        el.classList.toggle('unrevealed', skip || i > stage);
        el.classList.toggle('done', !skip && i < stage);
        el.classList.toggle('active', !skip && i === stage);
        if (i === GATHER_STAGE) {
            // While gathering, the label is the live tool status
            // ("Searching the web"); it settles back to "Gather" once done.
            const labelEl = el.querySelector('.step-label');
            const text = (i === stage && gatherLabel) ? gatherLabel : PIPELINE_STAGES[GATHER_STAGE];
            if (labelEl && labelEl.textContent !== text) labelEl.textContent = text;
        }
    });
    trace.querySelectorAll('.step-connector').forEach((el, idx) => {
        // Connector idx sits between step idx and idx+1; it appears together
        // with step idx+1 and fills green at the same moment. The connector
        // leading into a skipped Gather stage stays collapsed with it.
        const skip = idx === GATHER_STAGE - 1 && !gatherSeen;
        el.classList.toggle('unrevealed', skip || idx >= stage);
        el.classList.toggle('done', !skip && idx < stage);
    });
}

/**
 * Feed the full reasoning log (array of {step, phase?}) into the trace. Uses
 * the whole log, not just the last entry, so fast stages the poll skipped
 * over still get their checkmarks.
 */
export function updatePipelineTrace(log) {
    if (!Array.isArray(log) || log.length === 0) return;
    let maxStage = -1;
    let gatherSeen = false;
    let gatherLabel = '';
    for (const entry of log) {
        const s = _stageForStep(entry);
        if (s > maxStage) maxStage = s;
        if (s === GATHER_STAGE) {
            gatherSeen = true;
            gatherLabel = _gatherLabel(entry?.step) || gatherLabel;
        }
    }
    _setTraceStage(maxStage, gatherSeen, gatherLabel);
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
        <div class="ai-avatar is-thinking"><img src="${avatarUrl}" alt="${escapeHtml(profileName || 'AI agent')}" class="w-full h-full"></div>
        <div class="ai-content-wrapper">
            <div class="thinking-container">
                <div class="thinking-pulse-wave">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                ${_renderPipelineTraceHtml()}
            </div>
        </div>
    </div>`;
    ui.elements.chatWindow.appendChild(container);
    ui.scrollToBottom();

    return container;
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

    // Resolved server-side (synderesis._resolve_kb_display_name): user-created
    // knowledge bases are identified by UUID, so the raw field would render as
    // a GUID here. Null when the agent points at a knowledge base that no
    // longer exists — say nothing rather than name a dead one.
    const kbName = activeProfile.rag_knowledge_base_name;
    const kbHtml = kbName
        ? `<p class="text-xs text-neutral-400 dark:text-neutral-500 mb-2">Has access to the &ldquo;${escapeHtml(String(kbName))}&rdquo; knowledge base.</p>`
        : '';

    const promptsSectionHtml = promptsHtml
        ? `<p class="text-sm text-neutral-500 dark:text-neutral-400 mb-3">Try asking:</p>
           <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mx-auto w-full">${promptsHtml}</div>`
        : '';

    // Public demo only. A visitor there reads a small model's prose as SAFi's
    // quality, so the last surface before the first message has to say that
    // SAFi is the governance layer, not the intelligence. In a customer's
    // deployment the same line is wrong: staff are not evaluating SAFi, the
    // model is an internal detail, and disclaiming the intelligence only
    // undermines confidence in a tool they are required to use.
    const modelLabel = isPublicDemoUi() ? getActiveModelLabel() : null;
    const modelHtml = modelLabel
        ? `<p class="text-xs text-neutral-400 dark:text-neutral-500 mb-2">
             Running <span class="font-medium">${escapeHtml(modelLabel)}</span> — SAFi is the
             governance layer, not the intelligence. The policy is enforced identically
             whichever model sits underneath.
           </p>`
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
        ${modelHtml}
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