/**
 * Inbox (backlog 57): everything waiting on this user, as a Control Panel
 * tab under Account, with a count pill on its nav row.
 *
 * The pill is a TO-DO count, not an unread count: pending work stays on it
 * until someone acts, so there is no read-state to store anywhere. The data
 * comes from /api/attention, which is role-aware server-side; this module
 * renders whatever it is given and never decides visibility itself.
 *
 * Originally a bell in the chat sidebar header; moved here 2026-08-17 at
 * Nelson's request, next to the other personal surfaces (Profile, Scheduled
 * Updates) instead of crowding the sidebar chrome.
 */
import * as api from '../core/api.js';

let _timer = null;

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

async function _fetch() {
    try {
        return await api.fetchAttention();
    } catch (e) {
        return null; // a failed poll keeps the last badge rather than flashing it away
    }
}

function _updateBadge(payload) {
    const badge = document.getElementById('nav-inbox-badge');
    if (!badge || !payload) return;
    const total = payload.total || 0;
    badge.textContent = total > 99 ? '99+' : String(total);
    badge.classList.toggle('hidden', total === 0);
}

async function refreshBadge() {
    _updateBadge(await _fetch());
}

/** Start the badge poller. Called once the user is signed in (the sidebar
 * render); safe to call again, it just restarts the timer. */
export function initAttentionBadge() {
    refreshBadge();
    if (_timer) clearInterval(_timer);
    _timer = setInterval(refreshBadge, 5 * 60 * 1000);
}

/** The Inbox tab. Fetches fresh on every entry: the list must reflect the
 * work as it stands now, not as it stood when the badge last polled. */
export async function renderSettingsInboxTab() {
    const container = document.getElementById('tab-inbox');
    if (!container) return;
    container.innerHTML = `
        <div class="max-w-3xl">
            <div class="settings-page-header">
                <h1>Inbox</h1>
                <p>Everything currently waiting on you. Items leave on their own once the work is done.</p>
            </div>
            <div id="inbox-list">
                <div class="text-center text-gray-500 py-10"><div class="thinking-spinner w-6 h-6 mx-auto"></div></div>
            </div>
        </div>`;

    const payload = await _fetch();
    _updateBadge(payload);
    const list = container.querySelector('#inbox-list');
    if (!list) return;
    if (!payload) {
        list.innerHTML = `<p class="text-sm text-red-500">Could not load the inbox. Try again in a moment.</p>`;
        return;
    }
    const items = payload.items || [];
    if (!items.length) {
        list.innerHTML = `
            <div class="border border-gray-200 dark:border-neutral-700 rounded-xl p-10 text-center">
                <p class="text-sm font-medium text-gray-700 dark:text-gray-300">Nothing is waiting on you.</p>
                <p class="text-xs text-gray-400 mt-1">Pending reviews, invitations, incidents, and failing schedules will show up here.</p>
            </div>`;
        return;
    }
    list.innerHTML = `<div class="space-y-2">` + items.map(it => `
        <div class="attention-row w-full px-4 py-3.5 rounded-xl border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 hover:border-green-300 dark:hover:border-green-700 hover:shadow-sm transition-all flex items-start gap-3 cursor-pointer" data-target="${esc(it.target)}">
            <span class="min-w-[26px] h-6 px-1.5 rounded-full bg-green-600 text-white text-xs font-bold flex items-center justify-center mt-0.5">${it.count > 99 ? '99+' : it.count}</span>
            <span class="min-w-0 flex-1">
                <span class="block text-sm font-medium text-gray-900 dark:text-white">${esc(it.title)}</span>
                ${it.examples && it.examples.length ? `<span class="block text-xs text-gray-500 truncate mt-0.5">${esc(it.examples.join(', '))}</span>` : ''}
                ${age(it.oldest) ? `<span class="block text-[11px] text-gray-400 mt-0.5">${esc(age(it.oldest))}</span>` : ''}
            </span>
            ${it.dismissible
                ? `<button type="button" class="attention-dismiss text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:underline shrink-0 mt-1">Dismiss</button>`
                : `<svg class="w-4 h-4 text-gray-300 dark:text-gray-600 shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>`}
        </div>`).join('') + `</div>`;

    // Deep link: we are already inside the Control Panel, so switching tab
    // is one click on the target's own nav button. Dismiss acknowledges the
    // caller's decided tool requests without navigating.
    list.querySelectorAll('.attention-row').forEach(row =>
        row.addEventListener('click', () =>
            document.getElementById(`nav-${row.dataset.target}`)?.click()));
    list.querySelectorAll('.attention-dismiss').forEach(btn =>
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await api.acknowledgeToolOutcomes();
                renderSettingsInboxTab();
            } catch (err) {
                // leave the row; the next open retries
            }
        }));
}
