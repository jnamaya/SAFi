// ui-share-dialog.js
//
// Sharing dialog for conversations and folders (backlog 56), reusing org
// groups exactly like the agent-share dialog (ui-settings-agents.js) does.
// Two differences from that dialog: a role selector (viewer/contributor,
// not a single can_use level), and two resource kinds sharing one body
// renderer since the schema and endpoints are identical in shape.

import * as api from '../core/api.js';
import * as ui from './ui.js';

function esc(s) {
    const div = document.createElement('div');
    div.textContent = String(s ?? '');
    return div.innerHTML;
}

function openDialog(kind, id, name) {
    document.getElementById('share-dialog-modal')?.remove();
    const modal = document.createElement('div');
    modal.id = 'share-dialog-modal';
    modal.className = 'fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/50';
    const noun = kind === 'project' ? 'folder' : 'conversation';
    modal.innerHTML = `
        <div class="bg-white dark:bg-neutral-900 rounded-2xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col overflow-hidden">
            <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-neutral-800">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-white">Share ${noun} &ldquo;${esc(name)}&rdquo;</h3>
                <button id="share-dialog-close" class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <div id="share-dialog-body" class="p-6 overflow-y-auto custom-scrollbar">
                <div class="text-center text-gray-500 py-8"><div class="thinking-spinner w-6 h-6 mx-auto mb-3"></div>Loading sharing...</div>
            </div>
        </div>`;
    document.body.appendChild(modal);
    const close = () => modal.remove();
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    modal.querySelector('#share-dialog-close').addEventListener('click', close);
    renderBody(modal, kind, id);
}

async function renderBody(modal, kind, id) {
    const body = modal.querySelector('#share-dialog-body');
    if (!body) return;
    const calls = kind === 'project'
        ? { get: api.getProjectShares, grant: api.grantProjectShare, revoke: api.revokeProjectShare }
        : { get: api.getConversationShares, grant: api.grantConversationShare, revoke: api.revokeConversationShare };

    let res;
    try {
        res = await calls.get(id);
    } catch (err) {
        body.innerHTML = `<p class="text-sm text-red-500">${esc(err.message || 'Could not load sharing.')}</p>`;
        return;
    }
    const grants = res.grants || [];
    const grantedIds = new Set(grants.map(g => `${g.grantee_type}:${g.grantee_id}`));
    const groups = (res.groups || []).filter(g => !grantedIds.has(`group:${g.id}`));
    const members = (res.members || []).filter(m => !grantedIds.has(`user:${m.id}`));

    const roleLabel = (r) => r === 'contributor' ? 'can continue it' : 'can view it';
    const grantRows = grants.length ? grants.map(g => `
        <div class="flex items-center justify-between py-2 border-b border-gray-100 dark:border-neutral-800 last:border-0">
            <div class="min-w-0">
                <p class="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">${esc(g.grantee_name || g.grantee_id)}</p>
                <p class="text-xs text-gray-500 truncate">${g.grantee_type === 'group' ? 'Group' : esc(g.grantee_email || '')} &middot; ${roleLabel(g.role)}</p>
            </div>
            <button type="button" data-type="${g.grantee_type}" data-id="${esc(g.grantee_id)}"
                class="share-revoke-btn text-xs text-red-500 hover:underline flex-shrink-0 ml-3">Remove</button>
        </div>`).join('')
        : `<p class="text-sm text-gray-500 py-2">Not shared with anyone yet. Only you can see it.</p>`;

    const groupOpts = groups.map(g =>
        `<option value="group:${esc(g.id)}">${esc(g.name)} (${g.member_count} member${g.member_count === 1 ? '' : 's'})</option>`).join('');
    const memberOpts = members.map(m =>
        `<option value="user:${esc(m.id)}">${esc(m.name || m.email || m.id)}</option>`).join('');

    body.innerHTML = `
        <p class="text-xs text-gray-500 dark:text-gray-400 mb-4">People and groups you share with can see this ${kind === 'project' ? 'folder' : 'conversation'}${kind === 'project' ? ' and everything inside it' : ''}. A contributor can continue it in their own name; a viewer can only read it.</p>
        <div class="flex flex-col sm:flex-row gap-2 mb-5">
            <select id="share-grantee-select" class="settings-modal-select flex-1">
                <option value="">Select a person or group...</option>
                ${groupOpts ? `<optgroup label="Groups">${groupOpts}</optgroup>` : ''}
                ${memberOpts ? `<optgroup label="People">${memberOpts}</optgroup>` : ''}
            </select>
            <select id="share-role-select" class="settings-modal-select sm:w-40">
                <option value="viewer">Viewer</option>
                <option value="contributor">Contributor</option>
            </select>
            <button id="share-grant-btn" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold whitespace-nowrap">Share</button>
        </div>
        <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">Who has access</h4>
        <div>${grantRows}</div>`;

    body.querySelector('#share-grant-btn').addEventListener('click', async () => {
        const sel = body.querySelector('#share-grantee-select');
        const roleSel = body.querySelector('#share-role-select');
        if (!sel.value) return;
        const sep = sel.value.indexOf(':');
        const granteeType = sel.value.slice(0, sep);
        const granteeId = sel.value.slice(sep + 1);
        try {
            await calls.grant(id, granteeType, granteeId, roleSel.value);
            ui.showToast('Shared.', 'success');
            await renderBody(modal, kind, id);
        } catch (err) {
            ui.showToast(err.message || 'Share failed', 'error');
        }
    });

    body.querySelectorAll('.share-revoke-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                await calls.revoke(id, btn.dataset.type, btn.dataset.id);
                ui.showToast('Access removed.', 'success');
                await renderBody(modal, kind, id);
            } catch (err) {
                ui.showToast(err.message || 'Remove failed', 'error');
            }
        });
    });
}

export function openConversationShareDialog(conversationId, title) {
    openDialog('conversation', conversationId, title || 'Untitled');
}

export function openProjectShareDialog(projectId, name) {
    openDialog('project', projectId, name || 'Untitled');
}
