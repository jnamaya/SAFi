/**
 * Attention bell (backlog 57): a badge with the count of items waiting on
 * this user, and a panel that deep-links each category to the tab where the
 * action happens.
 *
 * The badge is a TO-DO count, not an unread count: pending work stays on it
 * until someone acts, so there is no read-state to store anywhere. The data
 * is fetched from /api/attention, which is role-aware server-side; this
 * module renders whatever it is given and never decides visibility itself.
 */
import * as api from '../core/api.js';

let _timer = null;
let _last = { items: [], total: 0 };

function esc(s) {
    const div = document.createElement('div');
    div.textContent = String(s ?? '');
    return div.innerHTML;
}

function age(iso) {
    if (!iso) return '';
    const ms = Date.now() - new Date(iso).getTime();
    if (!(ms > 0)) return '';
    const days = Math.floor(ms / 86400000);
    if (days >= 1) return `oldest ${days} day${days === 1 ? '' : 's'}`;
    const hours = Math.floor(ms / 3600000);
    if (hours >= 1) return `oldest ${hours} hour${hours === 1 ? '' : 's'}`;
    return 'new';
}

async function refresh() {
    const badge = document.getElementById('attention-badge');
    if (!badge) return;
    try {
        _last = await api.fetchAttention();
    } catch (e) {
        return; // keep the last known badge rather than flashing it away
    }
    const total = _last.total || 0;
    badge.textContent = total > 99 ? '99+' : String(total);
    badge.classList.toggle('hidden', total === 0);
}

function goTo(target) {
    document.getElementById('attention-panel')?.remove();
    document.getElementById('control-panel-btn')?.click();
    document.getElementById(`nav-${target}`)?.click();
}

async function openPanel() {
    document.getElementById('attention-panel')?.remove();
    const modal = document.createElement('div');
    modal.id = 'attention-panel';
    modal.className = 'fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/50';
    modal.innerHTML = `
        <div class="bg-white dark:bg-neutral-900 rounded-2xl shadow-xl w-full max-w-md max-h-[80vh] flex flex-col overflow-hidden">
            <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-neutral-800">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-white">Needs attention</h3>
                <button id="attention-close" class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <div id="attention-body" class="p-4 overflow-y-auto custom-scrollbar">
                <div class="text-center text-gray-500 py-6"><div class="thinking-spinner w-5 h-5 mx-auto"></div></div>
            </div>
        </div>`;
    document.body.appendChild(modal);
    const close = () => modal.remove();
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    modal.querySelector('#attention-close').addEventListener('click', close);

    await refresh();
    const body = modal.querySelector('#attention-body');
    if (!body) return;
    const items = _last.items || [];
    if (!items.length) {
        body.innerHTML = `<p class="text-sm text-gray-500 text-center py-6">Nothing is waiting on you.</p>`;
        return;
    }
    body.innerHTML = items.map(it => `
        <button type="button" data-target="${esc(it.target)}"
            class="attention-row w-full text-left px-3 py-3 rounded-xl hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors flex items-start gap-3">
            <span class="min-w-[24px] h-6 px-1.5 rounded-full bg-green-600 text-white text-xs font-bold flex items-center justify-center mt-0.5">${it.count > 99 ? '99+' : it.count}</span>
            <span class="min-w-0 flex-1">
                <span class="block text-sm font-medium text-gray-900 dark:text-white">${esc(it.title)}</span>
                ${it.examples && it.examples.length ? `<span class="block text-xs text-gray-500 truncate mt-0.5">${esc(it.examples.join(', '))}</span>` : ''}
                ${age(it.oldest) ? `<span class="block text-[11px] text-gray-400 mt-0.5">${esc(age(it.oldest))}</span>` : ''}
            </span>
            <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
        </button>`).join('');
    body.querySelectorAll('.attention-row').forEach(btn =>
        btn.addEventListener('click', () => goTo(btn.dataset.target)));
}

export function initAttentionBell() {
    const bell = document.getElementById('attention-bell');
    if (!bell) return;
    bell.addEventListener('click', openPanel);
    refresh();
    if (_timer) clearInterval(_timer);
    _timer = setInterval(refresh, 5 * 60 * 1000);
}
