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
import * as ui from './ui.js';

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

async function _fetchActions() {
    try {
        return await api.fetchAttentionActions();
    } catch (e) {
        return null; // non-reviewers get a 403/empty; not an error worth surfacing
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

function _approvalBlock(kind, items) {
    if (!items || !items.length) return '';
    const rows = items.map(it => {
        const label = kind === 'policy_changes'
            ? esc(it.policy_name || it.id)
            : (it.request_type === 'policy'
                ? `${esc(it.policy_name || it.id)} (policy tool grant)`
                : esc(it.agent_name || it.id));
        const detail = kind === 'policy_changes'
            ? `changes ${(it.changed || []).map(f => `<code class="bg-gray-100 dark:bg-neutral-800 px-1 py-0.5 rounded">${esc(f)}</code>`).join(' ')}`
            : `adds ${(it.added || []).map(t => `<code class="bg-gray-100 dark:bg-neutral-800 px-1 py-0.5 rounded">${esc(t)}</code>`).join(' ')}`;
        return `
            <div class="px-4 py-3 flex flex-wrap items-center gap-3 border-t border-gray-100 dark:border-neutral-800">
                <div class="min-w-0 flex-1">
                    <p class="text-sm font-medium text-gray-900 dark:text-white truncate">${label}</p>
                    <p class="text-xs text-gray-500 truncate">submitted by ${esc(it.requester_name || '?')} &middot; ${detail}</p>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    <button data-att-kind="${kind}" data-req="${esc(it.id)}" class="att-approve px-3 py-1.5 text-xs font-semibold text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors">Approve</button>
                    <button data-att-kind="${kind}" data-req="${esc(it.id)}" class="att-reject px-3 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors">Reject</button>
                </div>
            </div>`;
    }).join('');
    const title = kind === 'policy_changes'
        ? 'Policy changes awaiting approval'
        : 'Tool grants awaiting approval';
    return `
        <div class="border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 rounded-xl overflow-hidden">
            <div class="px-4 py-3 border-b border-amber-200 dark:border-amber-800">
                <h3 class="text-sm font-semibold text-amber-800 dark:text-amber-300">${title}</h3>
                <p class="text-xs text-amber-700 dark:text-amber-400 mt-0.5">Approve or reject right here; the change takes effect on approval.</p>
            </div>
            ${rows}
        </div>`;
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

    // The approval categories render expandable action blocks with their IDs.
    // The generic /api/attention rollup gives only counts, so the actionable
    // list is fetched from /api/attention/actions, which carries the IDs.
    let actions = null;
    const hasApproval = items.some(it => it.key === 'policy_changes' || it.key === 'tool_requests');
    if (hasApproval) actions = await _fetchActions();

    // Rows that are NOT approvals render the usual count chips.
    const simpleItems = items.filter(it => it.key !== 'policy_changes' && it.key !== 'tool_requests');
    let simpleHtml = '';
    if (simpleItems.length) {
        simpleHtml = `<div class="space-y-2">` + simpleItems.map(it => `
            <div class="attention-row w-full px-4 py-3.5 rounded-xl border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 transition-all flex items-start gap-3 ${it.actionable ? 'hover:border-green-300 dark:hover:border-green-700 hover:shadow-sm cursor-pointer' : ''}" data-target="${esc(it.target)}" data-dismissible="${it.dismissible ? '1' : ''}" data-actionable="${it.actionable ? '1' : ''}">
                <span class="min-w-[26px] h-6 px-1.5 rounded-full ${it.actionable ? 'bg-green-600' : 'bg-gray-400 dark:bg-neutral-600'} text-white text-xs font-bold flex items-center justify-center mt-0.5">${it.count > 99 ? '99+' : it.count}</span>
                <span class="min-w-0 flex-1">
                    <span class="block text-sm font-medium text-gray-900 dark:text-white">${esc(it.title)}</span>
                    ${it.examples && it.examples.length ? `<span class="block text-xs text-gray-500 truncate mt-0.5">${esc(it.examples.join(', '))}</span>` : ''}
                    ${age(it.oldest) ? `<span class="block text-[11px] text-gray-400 mt-0.5">${esc(age(it.oldest))}</span>` : ''}
                </span>
                ${it.dismissible
                    ? `<button type="button" class="attention-dismiss text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:underline shrink-0 mt-1">Dismiss</button>`
                    : (it.actionable
                        ? `<svg class="w-4 h-4 text-gray-300 dark:text-gray-600 shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>`
                        : `<span class="text-[11px] text-gray-400 shrink-0 mt-1">Waiting</span>`)}
            </div>`).join('') + `</div>`;
    }

    const policyBlock = (hasApproval && actions) ? _approvalBlock('policy_changes', actions.policy_changes) : '';
    const toolBlock = (hasApproval && actions) ? _approvalBlock('tool_requests', actions.tool_requests) : '';
    list.innerHTML = `<div class="space-y-3">${policyBlock}${toolBlock}${simpleHtml}</div>`;

    // Simple actionable rows deep-link; informational rows do not navigate.
    list.querySelectorAll('.attention-row').forEach(row =>
        row.addEventListener('click', () => {
            if (row.dataset.actionable !== '1') return;
            document.getElementById(`nav-${row.dataset.target}`)?.click();
        }));
    list.querySelectorAll('.attention-dismiss').forEach(btn =>
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await api.acknowledgeToolOutcomes();
                refreshBadge();
                renderSettingsInboxTab();
            } catch (err) {
                // leave the row; the next open retries
            }
        }));

    // Approve/Reject straight from the inbox.
    const onDone = async () => {
        refreshBadge();
        renderSettingsInboxTab();
    };
    list.querySelectorAll('.att-approve').forEach(btn =>
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const kind = btn.dataset.attKind;
            const id = btn.dataset.req;
            try {
                const res = kind === 'policy_changes'
                    ? await api.approvePolicyChange(id)
                    : await api.approveToolRequest(id);
                ui.showToast(res && res.self_approved
                    ? 'Approved (recorded as non-independent: you are the only eligible approver).'
                    : 'Approved.', 'success');
                onDone();
            } catch (e) {
                ui.showToast(e.message || 'Approval failed', 'error');
                btn.disabled = false;
            }
        }));
    list.querySelectorAll('.att-reject').forEach(btn =>
        btn.addEventListener('click', async () => {
            const reason = prompt('Reason for rejecting (optional):') ?? null;
            if (reason === null) return;
            btn.disabled = true;
            const kind = btn.dataset.attKind;
            const id = btn.dataset.req;
            try {
                if (kind === 'policy_changes') {
                    await api.rejectPolicyChange(id, reason);
                } else {
                    await api.rejectToolRequest(id, reason);
                }
                ui.showToast('Rejected.', 'success');
                onDone();
            } catch (e) {
                ui.showToast(e.message || 'Rejection failed', 'error');
                btn.disabled = false;
            }
        }));
}
