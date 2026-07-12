// js/ui/ui-saved.js
// Saved content: the save-to-folder picker (anchored to the bookmark button in
// the message action bar) and the "Saved" browser modal opened from the sidebar.

import * as api from '../core/api.js';
import * as ui from './ui.js';

const iconFolder = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"></path></svg>`;
const iconBookmark = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"></path></svg>`;
const iconTrash = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
const iconCopy = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
const iconOpen = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>`;
const iconClose = `<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`;

// --- Save-to-folder picker -------------------------------------------------

function closeSavePicker() {
    document.querySelector('.save-picker-menu')?.remove();
    document.removeEventListener('click', _outsideClose, true);
}

function _outsideClose(e) {
    if (!e.target.closest('.save-picker-menu')) closeSavePicker();
}

/**
 * Small anchored dropdown asking which folder the answer goes to.
 * onPick(projectId|null) is called once; null = saved loose.
 */
export function showSavePicker(anchor, projects, onPick) {
    closeSavePicker();

    const menu = document.createElement('div');
    menu.className = 'save-picker-menu convo-menu-dropdown fixed z-50 w-56 bg-white dark:bg-neutral-800 rounded-xl shadow-2xl ring-1 ring-black/[0.06] dark:ring-white/10 p-1.5';
    menu.addEventListener('click', (e) => e.stopPropagation());

    const header = document.createElement('div');
    header.className = 'px-2.5 py-1.5 text-xs font-semibold text-neutral-400 dark:text-neutral-500 uppercase tracking-wider';
    header.textContent = 'Save to';
    menu.appendChild(header);

    const addItem = (label, icon, projectId) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'flex items-center gap-3 w-full text-left px-2.5 py-2 text-sm font-medium rounded-lg transition-colors text-neutral-700 dark:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-neutral-700/60';
        const iconSpan = document.createElement('span');
        iconSpan.className = 'shrink-0 text-neutral-400 dark:text-neutral-500';
        iconSpan.innerHTML = icon;
        const labelSpan = document.createElement('span');
        labelSpan.className = 'truncate';
        labelSpan.textContent = label;
        btn.append(iconSpan, labelSpan);
        btn.addEventListener('click', () => { closeSavePicker(); onPick(projectId); });
        menu.appendChild(btn);
    };

    addItem('Saved (no folder)', iconBookmark, null);
    (projects || []).forEach(p => addItem(p.name || 'Untitled', iconFolder, p.id));

    document.body.appendChild(menu);

    // Position near the anchor, clamped to the viewport.
    const r = anchor.getBoundingClientRect();
    const mw = menu.offsetWidth, mh = menu.offsetHeight;
    let left = Math.min(r.left, window.innerWidth - mw - 8);
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    menu.style.left = `${Math.max(8, left)}px`;
    menu.style.top = `${top}px`;

    // Defer so the click that opened the picker doesn't immediately close it.
    setTimeout(() => document.addEventListener('click', _outsideClose, true), 0);
}

// --- Saved content browser modal -------------------------------------------

let _modalState = null; // { items, projects, filter, onJump }

function closeSavedModal() {
    document.getElementById('saved-content-modal')?.remove();
    document.getElementById('saved-content-backdrop')?.remove();
    document.removeEventListener('keydown', _escClose);
    _modalState = null;
}

function _escClose(e) {
    if (e.key === 'Escape') closeSavedModal();
}

function _renderMarkdown(text) {
    try {
        return DOMPurify.sanitize(marked.parse(String(text ?? '')));
    } catch {
        const div = document.createElement('div');
        div.textContent = String(text ?? '');
        return div.innerHTML;
    }
}

function _scoreBadge(score) {
    if (score === null || score === undefined) return '';
    const color = score >= 8 ? 'text-green-600 dark:text-green-400'
        : score >= 5 ? 'text-amber-600 dark:text-amber-400'
        : 'text-red-500 dark:text-red-400';
    return `<span class="inline-flex items-center gap-1 text-xs font-semibold ${color}" title="Spirit alignment score">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>${score}/10
    </span>`;
}

function _renderList() {
    const { items, projects, filter } = _modalState;
    const listEl = document.getElementById('saved-content-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    const projectNames = Object.fromEntries((projects || []).map(p => [p.id, p.name]));
    const visible = items.filter(it =>
        filter === 'all' ? true : filter === 'none' ? !it.project_id : it.project_id === filter
    );

    if (!visible.length) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-sm text-neutral-500 dark:text-neutral-400 py-12';
        empty.textContent = items.length
            ? 'Nothing saved in this folder yet.'
            : 'Nothing saved yet. Use the bookmark icon under any response to keep it here.';
        listEl.appendChild(empty);
        return;
    }

    visible.forEach(item => {
        const card = document.createElement('div');
        card.className = 'border border-neutral-200 dark:border-neutral-800 rounded-xl overflow-hidden';

        // Header row (click to expand/collapse)
        const head = document.createElement('button');
        head.type = 'button';
        head.className = 'w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-neutral-50 dark:hover:bg-neutral-800/60 transition-colors';
        const created = item.created_at ? new Date(item.created_at) : null;
        const metaBits = [
            item.profile_name ? `<span class="truncate">${item.profile_name}</span>` : '',
            created ? `<span>${created.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</span>` : '',
            item.project_id && projectNames[item.project_id]
                ? `<span class="inline-flex items-center gap-1 truncate">${iconFolder.replace('w-[18px] h-[18px]', 'w-3.5 h-3.5')}${projectNames[item.project_id]}</span>`
                : '',
            _scoreBadge(item.spirit_score),
        ].filter(Boolean).join('<span class="text-neutral-300 dark:text-neutral-600">·</span>');

        head.innerHTML = `
            <div class="min-w-0 flex-1">
                <p class="text-sm font-medium text-neutral-900 dark:text-white truncate saved-title"></p>
                <div class="flex items-center flex-wrap gap-x-2 gap-y-1 mt-1 text-xs text-neutral-500 dark:text-neutral-400">${metaBits}</div>
            </div>
            <svg class="w-4 h-4 mt-1 shrink-0 text-neutral-400 transition-transform saved-chevron" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"></path></svg>`;
        head.querySelector('.saved-title').textContent = item.title || 'Saved item';

        // Body (rendered markdown + actions), hidden until expanded
        const body = document.createElement('div');
        body.className = 'hidden border-t border-neutral-200 dark:border-neutral-800';
        body.innerHTML = `
            <div class="chat-bubble px-4 py-3 text-sm max-w-none overflow-x-auto">${_renderMarkdown(item.content)}</div>
            <div class="flex items-center flex-wrap gap-2 px-4 py-2.5 bg-neutral-50 dark:bg-neutral-900/50 border-t border-neutral-200 dark:border-neutral-800"></div>`;

        const actions = body.querySelector('.flex.items-center');

        const mkAction = (icon, label, onClick, danger = false) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = `inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${danger
                ? 'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10'
                : 'text-neutral-600 dark:text-neutral-300 hover:bg-neutral-200/70 dark:hover:bg-neutral-800'}`;
            b.innerHTML = `${icon}<span>${label}</span>`;
            b.addEventListener('click', onClick);
            actions.appendChild(b);
            return b;
        };

        mkAction(iconCopy, 'Copy', () => {
            navigator.clipboard.writeText(item.content || '').then(() => ui.showToast('Copied', 'success'));
        });

        if (item.origin_exists && item.conversation_id) {
            mkAction(iconOpen, 'Open conversation', () => {
                closeSavedModal();
                _modalStateSafeJump(item.conversation_id);
            });
        }

        // Move-to-folder select
        const moveWrap = document.createElement('label');
        moveWrap.className = 'inline-flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400 ml-auto';
        const select = document.createElement('select');
        select.className = 'text-xs bg-transparent border border-neutral-200 dark:border-neutral-700 rounded-lg px-2 py-1.5 text-neutral-700 dark:text-neutral-200 dark:bg-neutral-900 focus:outline-none';
        const optNone = document.createElement('option');
        optNone.value = ''; optNone.textContent = 'No folder';
        select.appendChild(optNone);
        (projects || []).forEach(p => {
            const o = document.createElement('option');
            o.value = p.id; o.textContent = p.name || 'Untitled';
            select.appendChild(o);
        });
        select.value = item.project_id || '';
        select.addEventListener('change', async () => {
            const target = select.value || null;
            try {
                await api.moveSavedContent(item.id, target);
                item.project_id = target;
                ui.showToast('Moved', 'success');
                _renderList();
            } catch {
                ui.showToast('Could not move.', 'error');
                select.value = item.project_id || '';
            }
        });
        moveWrap.appendChild(select);
        actions.appendChild(moveWrap);

        // Two-step delete (no browser confirm dialogs elsewhere in the app)
        let armed = false, disarmTimer = null;
        const delBtn = mkAction(iconTrash, 'Delete', async () => {
            if (!armed) {
                armed = true;
                delBtn.querySelector('span').textContent = 'Confirm?';
                disarmTimer = setTimeout(() => {
                    armed = false;
                    delBtn.querySelector('span').textContent = 'Delete';
                }, 3000);
                return;
            }
            clearTimeout(disarmTimer);
            try {
                await api.deleteSavedContent(item.id);
                _modalState.items = _modalState.items.filter(i => i.id !== item.id);
                ui.showToast('Deleted', 'success');
                _renderList();
            } catch {
                ui.showToast('Could not delete.', 'error');
            }
        }, true);

        head.addEventListener('click', () => {
            body.classList.toggle('hidden');
            head.querySelector('.saved-chevron').classList.toggle('rotate-180');
        });

        card.append(head, body);
        listEl.appendChild(card);
    });
}

function _modalStateSafeJump(conversationId) {
    const jump = _jumpHandler;
    if (jump) jump(conversationId);
}

let _jumpHandler = null;

/**
 * Opens the Saved content browser.
 * opts.projects — current folder list (for names, filter, move targets)
 * opts.onJumpToConversation(id) — navigate to the origin conversation
 */
export async function openSavedModal(opts = {}) {
    closeSavedModal();
    _jumpHandler = opts.onJumpToConversation || null;

    const backdrop = document.createElement('div');
    backdrop.id = 'saved-content-backdrop';
    backdrop.className = 'fixed inset-0 bg-black/60 z-40';
    backdrop.addEventListener('click', closeSavedModal);

    const modal = document.createElement('div');
    modal.id = 'saved-content-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.className = 'fixed inset-0 sm:inset-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 w-full sm:w-auto sm:min-w-[560px] sm:max-w-2xl bg-white dark:bg-neutral-900 sm:rounded-xl sm:shadow-2xl z-50 flex flex-col h-full sm:h-auto sm:max-h-[85vh]';
    modal.innerHTML = `
        <div class="flex items-center justify-between p-5 border-b border-neutral-200 dark:border-neutral-800 shrink-0">
            <div class="flex items-center gap-3">
                <span class="p-2 bg-green-100 dark:bg-green-900/40 rounded-full text-green-600 dark:text-green-400">${iconBookmark}</span>
                <h3 class="text-lg font-semibold">Saved Content</h3>
            </div>
            <div class="flex items-center gap-3">
                <select id="saved-content-filter" class="text-sm bg-transparent border border-neutral-200 dark:border-neutral-700 rounded-lg px-2.5 py-1.5 text-neutral-700 dark:text-neutral-200 dark:bg-neutral-900 focus:outline-none">
                    <option value="all">All folders</option>
                    <option value="none">No folder</option>
                </select>
                <button id="close-saved-content" type="button" aria-label="Close modal" class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700">${iconClose}</button>
            </div>
        </div>
        <div id="saved-content-list" class="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3 min-h-[160px]">
            <div class="text-center text-sm text-neutral-500 dark:text-neutral-400 py-12">Loading…</div>
        </div>`;

    document.body.append(backdrop, modal);
    document.addEventListener('keydown', _escClose);
    modal.querySelector('#close-saved-content').addEventListener('click', closeSavedModal);

    const filterEl = modal.querySelector('#saved-content-filter');
    (opts.projects || []).forEach(p => {
        const o = document.createElement('option');
        o.value = p.id; o.textContent = p.name || 'Untitled';
        filterEl.appendChild(o);
    });

    let items = [];
    try {
        const res = await api.fetchSavedContent();
        items = Array.isArray(res) ? res : [];
    } catch {
        document.getElementById('saved-content-list').innerHTML =
            '<div class="text-center text-sm text-red-500 py-12">Could not load saved content.</div>';
        return;
    }

    _modalState = { items, projects: opts.projects || [], filter: 'all' };
    filterEl.addEventListener('change', () => {
        if (_modalState) { _modalState.filter = filterEl.value; _renderList(); }
    });
    _renderList();
}
