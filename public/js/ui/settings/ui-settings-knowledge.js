/**
 * js/ui/settings/ui-settings-knowledge.js
 *
 * The Knowledge tab: user-created document repositories an agent can be
 * grounded in.
 *
 * Why this is a Control Panel tab and not part of the composer's data-source
 * dropdown: a knowledge base is a durable, owned, governed asset with a
 * lifecycle — the same kind of thing as an Agent or a Policy. `ui-data-sources.js`
 * is a per-chat affordance for OAuth connectors and owns nothing.
 *
 * TWO THINGS THE UI MUST KEEP SAYING OUT LOUD, because both are cases where
 * the honest state looks like a bug if unexplained:
 *
 *   1. **Indexing is asynchronous.** Uploading a document does not make it
 *      retrievable; the indexer container has to rebuild first. A card that
 *      jumped straight to "ready" would be lying, so status is polled.
 *   2. **A shared KB answers only from its APPROVED subset.** If three
 *      documents await review, the agent is grounded in less than the list
 *      appears to show, and the operator has to be told that in words.
 */
import * as api from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';

let currentUser = null;
let openKbId = null;      // non-null when the detail view is showing
let pollTimer = null;

const SHARED_VISIBILITIES = ['member', 'auditor', 'editor', 'admin'];

// Statuses that mean the indexer still has work to do, so the view should
// keep refreshing. Anything else is a resting state.
const BUSY_STATUSES = ['pending', 'indexing'];

export function setKnowledgeCurrentUser(user) {
    currentUser = user;
}

function canManage() {
    return !!currentUser && ['admin', 'editor'].includes(currentUser.role);
}

function isReviewer() {
    return !!currentUser && ['admin', 'auditor'].includes(currentUser.role);
}

function container() {
    return document.getElementById('tab-knowledge');
}

export async function renderSettingsKnowledgeTab() {
    const el = container();
    if (!el) return;
    stopPolling();
    openKbId = null;

    el.innerHTML = `
        <div class="settings-page-header">
            <h1>Knowledge</h1>
            <p>Document repositories your agents can be grounded in. An agent
               attached to a knowledge base retrieves from it on every turn and
               cites what it used.</p>
        </div>
        <div id="kb-root"><div class="text-sm text-gray-500 flex items-center gap-2">
            <span class="thinking-spinner w-4 h-4"></span> Loading…
        </div></div>
    `;
    await renderList();
}

// --- List view ------------------------------------------------------------

async function renderList() {
    const root = document.getElementById('kb-root');
    if (!root) return;

    let bases = [];
    try {
        const res = await api.listKnowledgeBases();
        bases = (res && res.knowledge_bases) || [];
    } catch (e) {
        root.innerHTML = errorBox('Could not load knowledge bases.');
        return;
    }

    root.innerHTML = `
        ${canManage() ? `
        <div class="mb-6">
            <button id="kb-create-btn" data-manage="1" class="w-full flex items-center justify-center gap-2 p-4 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl hover:border-green-500 hover:bg-green-50 dark:hover:bg-green-900/20 transition-all group">
                <div class="p-2 bg-gray-100 dark:bg-neutral-800 rounded-full group-hover:bg-green-100 dark:group-hover:bg-green-800 transition-colors">
                    <svg class="w-6 h-6 text-gray-500 dark:text-gray-400 group-hover:text-green-600 dark:group-hover:text-green-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                    </svg>
                </div>
                <div class="text-left">
                    <h4 class="font-semibold text-gray-700 dark:text-gray-200 group-hover:text-green-700 dark:group-hover:text-green-300">Create a knowledge base</h4>
                    <p class="text-xs text-gray-500 dark:text-gray-400 group-hover:text-green-600/70">Upload documents your agents can retrieve from</p>
                </div>
            </button>
        </div>` : `
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
            These are the document repositories shared with you. Agents attached
            to one retrieve from it on every turn and cite the documents they used.
        </p>`}

        ${bases.length === 0 ? `
        <p class="text-sm text-gray-500 dark:text-gray-400">No knowledge bases yet.</p>` : `
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            ${bases.map(kbCard).join('')}
        </div>`}
    `;

    document.getElementById('kb-create-btn')?.addEventListener('click', openCreateForm);
    root.querySelectorAll('[data-kb-open]').forEach(btn => {
        btn.addEventListener('click', () => openDetail(btn.getAttribute('data-kb-open')));
    });

    if (bases.some(kb => BUSY_STATUSES.includes(kb.status))) startPolling(renderList);
    else stopPolling();
}

function kbCard(kb) {
    const mine = currentUser && String(kb.created_by) === String(currentUser.id);
    return `
        <button data-kb-open="${escapeHtml(kb.id)}"
            class="group relative flex flex-col text-left rounded-2xl border border-gray-200 dark:border-neutral-800 bg-white dark:bg-neutral-800 hover:border-green-300 dark:hover:border-green-700 hover:shadow-md transition-all duration-200 p-5">
            <div class="flex items-start justify-between gap-2 mb-2">
                <h4 class="font-semibold text-gray-900 dark:text-white">${escapeHtml(kb.name)}</h4>
                ${statusPill(kb)}
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 flex-1 mb-3">
                ${escapeHtml(kb.description || 'No description')}
            </p>
            <div class="flex items-center gap-2 flex-wrap text-[11px] text-gray-400">
                <span>${kb.chunk_count} chunk${kb.chunk_count === 1 ? '' : 's'}</span>
                <span>&middot;</span>
                <span>${kb.is_shared ? 'Shared with the org' : 'Private'}</span>
                ${mine ? '' : '<span>&middot;</span><span>Shared with you</span>'}
            </div>
        </button>`;
}

function statusPill(kb) {
    const map = {
        ready:    ['Ready', 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300'],
        indexing: ['Indexing…', 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'],
        pending:  ['Queued', 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'],
        empty:    ['Empty', 'bg-gray-100 text-gray-600 dark:bg-neutral-700 dark:text-gray-300'],
        failed:   ['Failed', 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300'],
    };

    // A shared KB whose documents are all awaiting review is legitimately at
    // zero chunks — but "Empty" reads as a malfunction to whoever just watched
    // their working corpus drop to nothing on sharing it. Name the actual
    // reason instead; it is also the only state with an action attached.
    const awaiting = (kb.pending_count || 0) > 0;
    if (awaiting && kb.status !== 'indexing' && kb.status !== 'pending') {
        return `<span class="shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">${
            kb.chunk_count > 0 ? `${kb.pending_count} awaiting review` : 'Awaiting approval'}</span>`;
    }

    const [label, classes] = map[kb.status] || map.empty;
    return `<span class="shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium ${classes}">${label}</span>`;
}

// --- Create ---------------------------------------------------------------

function openCreateForm() {
    const root = document.getElementById('kb-root');
    if (!root) return;
    stopPolling();
    root.innerHTML = `
        <div class="border border-gray-200 dark:border-neutral-700 rounded-xl p-6 max-w-xl">
            <h3 class="font-semibold text-gray-900 dark:text-white mb-4">New knowledge base</h3>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
            <input id="kb-new-name" type="text" maxlength="255" placeholder="e.g. Underwriting Manuals"
                class="w-full mb-4 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-green-500 outline-none">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description <span class="text-gray-400 font-normal">(optional)</span></label>
            <textarea id="kb-new-desc" rows="3" placeholder="What is in here, and what should an agent use it for?"
                class="w-full mb-2 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-green-500 outline-none resize-y"></textarea>
            <div id="kb-new-error" class="hidden text-sm text-red-600 dark:text-red-400 mb-3"></div>
            <div class="flex gap-2 mt-4">
                <button id="kb-new-save" class="px-4 py-2 text-sm font-medium rounded-lg bg-green-600 hover:bg-green-700 text-white">Create</button>
                <button id="kb-new-cancel" class="px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 dark:border-neutral-600 text-gray-700 dark:text-gray-300">Cancel</button>
            </div>
        </div>`;

    document.getElementById('kb-new-cancel').addEventListener('click', renderList);
    document.getElementById('kb-new-save').addEventListener('click', async (e) => {
        const name = document.getElementById('kb-new-name').value.trim();
        const errorEl = document.getElementById('kb-new-error');
        if (!name) {
            errorEl.textContent = 'A name is required.';
            errorEl.classList.remove('hidden');
            return;
        }
        e.currentTarget.disabled = true;
        try {
            const kb = await api.createKnowledgeBase({
                name,
                description: document.getElementById('kb-new-desc').value.trim()
            });
            await openDetail(kb.id);
        } catch (err) {
            errorEl.textContent = err.message || 'Could not create the knowledge base.';
            errorEl.classList.remove('hidden');
            e.currentTarget.disabled = false;
        }
    });
}

// --- Detail view ----------------------------------------------------------

async function openDetail(kbId) {
    openKbId = kbId;
    stopPolling();
    const root = document.getElementById('kb-root');
    if (!root) return;
    root.innerHTML = `<div class="text-sm text-gray-500 flex items-center gap-2">
        <span class="thinking-spinner w-4 h-4"></span> Loading…</div>`;
    await renderDetail();
}

async function renderDetail() {
    const root = document.getElementById('kb-root');
    if (!root || !openKbId) return;

    let kb;
    try {
        kb = await api.getKnowledgeBase(openKbId);
    } catch (e) {
        root.innerHTML = errorBox('Could not load that knowledge base.');
        return;
    }

    // From the server, not re-derived here. `_can_write` already owns this rule
    // (ownership, not rank — mirroring delete_agent), and a second copy in the
    // browser would drift the moment that rule changes.
    const mine = !!kb.can_manage;
    const docs = kb.documents || [];
    const pending = kb.pending_count || 0;

    root.innerHTML = `
        <button id="kb-back" class="mb-4 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-white flex items-center gap-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
            All knowledge bases
        </button>

        <div class="flex items-start justify-between gap-4 mb-1">
            <h2 class="text-xl font-bold text-gray-900 dark:text-white">${escapeHtml(kb.name)}</h2>
            ${statusPill(kb)}
        </div>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">${escapeHtml(kb.description || '')}</p>

        ${kb.status === 'failed' ? `
        <div class="mb-4 p-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 text-sm text-red-800 dark:text-red-300">
            <strong>Indexing failed.</strong> ${escapeHtml(kb.status_detail || '')}
            The previous index, if any, is still in use.
        </div>` : ''}

        ${BUSY_STATUSES.includes(kb.status) ? `
        <div class="mb-4 p-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 text-sm text-blue-800 dark:text-blue-300 flex items-center gap-2">
            <span class="thinking-spinner w-4 h-4"></span>
            Indexing. Documents become retrievable when this finishes.
        </div>` : ''}

        ${kb.is_shared && pending > 0 ? `
        <div class="mb-4 p-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10 text-sm text-amber-900 dark:text-amber-200">
            <strong>${pending} document${pending === 1 ? '' : 's'} awaiting approval.</strong>
            ${kb.chunk_count > 0
                ? `Agents using this knowledge base are answering from the approved
                   documents only — not from the full list below.`
                : `Nothing here is approved yet, so agents using this knowledge
                   base are currently answering <strong>without any grounding
                   from it</strong>.`}
            ${allPendingAreMine(kb, docs) && !kb.sole_reviewer ? `
            <p class="mt-2">
                You uploaded all of these, and no one can approve their own
                documents. Either ask another Admin or Auditor in your
                organization to review them, or switch this knowledge base back
                to <strong>private</strong> above — private knowledge needs no
                review and will be re-indexed immediately.
            </p>` : ''}
        </div>` : ''}

        ${kb.is_shared && pending > 0 && kb.sole_reviewer ? `
        <div class="mb-4 p-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 text-sm text-blue-900 dark:text-blue-200">
            <strong>Sole administrator.</strong> You are the only Admin or
            Auditor in this organization, so you may approve your own uploads.
            Each such sign-off is recorded as <strong>not independent</strong>
            on the document and in the evidence log. This stops applying
            automatically as soon as another Admin or Auditor joins.
        </div>` : ''}

        ${mine ? sharingCard(kb) : ''}
        ${mine ? uploadCard() : ''}

        <h3 class="font-semibold text-gray-900 dark:text-white mt-6 mb-2">Documents</h3>
        ${docs.length === 0
            ? `<p class="text-sm text-gray-500 dark:text-gray-400">No documents yet.</p>`
            : `<div class="border border-gray-200 dark:border-neutral-700 rounded-lg divide-y divide-gray-200 dark:divide-neutral-700">
                 ${docs.map(d => docRow(d, kb, mine)).join('')}
               </div>`}

        ${mine ? `
        <div class="mt-8 pt-6 border-t border-gray-200 dark:border-neutral-700 flex items-center gap-3">
            <button id="kb-reindex" class="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-neutral-600 text-gray-700 dark:text-gray-300">Rebuild index</button>
            <button id="kb-delete" class="px-3 py-2 text-sm rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20">Delete knowledge base</button>
        </div>` : ''}
    `;

    document.getElementById('kb-back').addEventListener('click', () => {
        openKbId = null;
        renderList();
    });
    if (mine) {
        wireSharing(kb);
        wireUpload(kb);
        document.getElementById('kb-reindex')?.addEventListener('click', async (e) => {
            e.currentTarget.disabled = true;
            await api.reindexKnowledgeBase(kb.id);
            renderDetail();
        });
        document.getElementById('kb-delete')?.addEventListener('click', async () => {
            if (!confirm(`Delete "${kb.name}" and all its documents? Agents using it will lose their grounding.`)) return;
            await api.deleteKnowledgeBase(kb.id);
            openKbId = null;
            renderList();
        });
    }
    wireDocActions(kb);

    if (BUSY_STATUSES.includes(kb.status)) startPolling(renderDetail);
    else stopPolling();
}

/**
 * True when every pending document was uploaded by the current user.
 *
 * That is the dead end: separation of duties means you cannot clear your own
 * queue, so a sole Admin who shares a corpus they built watches it drop to
 * zero grounding with no in-product way forward. The rule is right; leaving
 * someone to discover it by staring at an empty index is not.
 */
function allPendingAreMine(kb, docs) {
    if (!currentUser) return false;
    const pendingDocs = (docs || []).filter(d => d.status === 'pending');
    return pendingDocs.length > 0 &&
        pendingDocs.every(d => String(d.uploaded_by) === String(currentUser.id));
}

function sharingCard(kb) {
    return `
        <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4 mb-4">
            <div class="flex items-start justify-between gap-4">
                <div>
                    <h4 class="font-semibold text-gray-800 dark:text-white text-sm">Share with my organization</h4>
                    <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-2xl">
                        Private knowledge is yours alone and needs no review.
                        Sharing sends every document for approval by an Admin or
                        Auditor — someone other than whoever uploaded it — and
                        the index is rebuilt so nothing unreviewed stays
                        retrievable in the meantime.
                    </p>
                </div>
                <label class="relative inline-flex items-center cursor-pointer shrink-0">
                    <input type="checkbox" id="kb-share-toggle" class="sr-only peer" ${kb.is_shared ? 'checked' : ''}>
                    <div class="w-11 h-6 bg-gray-200 dark:bg-neutral-700 peer-focus:ring-2 peer-focus:ring-green-500 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></div>
                </label>
            </div>
        </div>`;
}

function wireSharing(kb) {
    const toggle = document.getElementById('kb-share-toggle');
    if (!toggle) return;
    toggle.addEventListener('change', async (e) => {
        const share = e.currentTarget.checked;
        if (share && !confirm(
            'Share this knowledge base with your organization?\n\n' +
            'Every document will be set back to "awaiting approval" and removed ' +
            'from the index until an Admin or Auditor approves it. You cannot ' +
            'approve documents you uploaded yourself.')) {
            e.currentTarget.checked = false;
            return;
        }
        e.currentTarget.disabled = true;
        try {
            await api.updateKnowledgeBase(kb.id, { visibility: share ? 'member' : 'private' });
        } catch (err) {
            alert(err.message || 'Could not change sharing.');
        }
        renderDetail();
    });
}

function uploadCard() {
    return `
        <div id="kb-drop" class="border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl p-6 text-center hover:border-green-500 transition-colors">
            <input type="file" id="kb-file" class="hidden" multiple
                   accept=".txt,.md,.pdf,.docx,.xlsx,.csv">
            <p class="text-sm text-gray-600 dark:text-gray-300">
                <button id="kb-browse" class="font-medium text-green-600 hover:text-green-700">Choose files</button>
                or drag them here
            </p>
            <p class="text-xs text-gray-400 mt-1">PDF, DOCX, XLSX, CSV, TXT, MD</p>
            <div id="kb-upload-status" class="hidden mt-3 text-sm text-gray-500"></div>
        </div>`;
}

function wireUpload(kb) {
    const drop = document.getElementById('kb-drop');
    const input = document.getElementById('kb-file');
    if (!drop || !input) return;

    document.getElementById('kb-browse').addEventListener('click', () => input.click());
    input.addEventListener('change', () => uploadFiles(kb, Array.from(input.files || [])));

    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.add('border-green-500', 'bg-green-50', 'dark:bg-green-900/20');
    }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.remove('border-green-500', 'bg-green-50', 'dark:bg-green-900/20');
    }));
    drop.addEventListener('drop', (e) => {
        uploadFiles(kb, Array.from(e.dataTransfer?.files || []));
    });
}

async function uploadFiles(kb, files) {
    if (!files.length) return;
    const status = document.getElementById('kb-upload-status');
    status.classList.remove('hidden');

    const failures = [];
    for (let i = 0; i < files.length; i++) {
        status.textContent = `Uploading ${i + 1} of ${files.length}: ${files[i].name}…`;
        try {
            await api.uploadKnowledgeBaseDocument(kb.id, files[i]);
        } catch (err) {
            // Report per-file rather than aborting the batch: one unreadable
            // PDF in a drop of twenty should not discard the other nineteen.
            failures.push(`${files[i].name}: ${err.message}`);
        }
    }
    if (failures.length) {
        status.innerHTML = `<span class="text-red-600 dark:text-red-400">${
            escapeHtml(failures.join(' · '))}</span>`;
        setTimeout(renderDetail, 4000);
    } else {
        renderDetail();
    }
}

function docRow(doc, kb, mine) {
    const kb_shared = kb.is_shared;
    const badges = {
        private:  ['Indexed', 'text-gray-500'],
        approved: ['Approved', 'text-green-600 dark:text-green-400'],
        pending:  ['Awaiting approval', 'text-amber-600 dark:text-amber-400'],
        rejected: ['Rejected', 'text-red-600 dark:text-red-400'],
    };
    // A read-only viewer sees whether a document is grounding answers, not the
    // workflow state that decided it. "Awaiting review" is kept because a
    // partially-grounded agent is something an operator must be able to see;
    // "rejected" becomes "not in use" because the fact of a rejection is
    // governance deliberation and its reason is not sent to them at all.
    const readOnlyBadges = {
        private:  ['In use', 'text-green-600 dark:text-green-400'],
        approved: ['In use', 'text-green-600 dark:text-green-400'],
        pending:  ['Awaiting review', 'text-amber-600 dark:text-amber-400'],
        rejected: ['Not in use', 'text-gray-500'],
    };
    const [label, cls] = (mine || isReviewer())
        ? (badges[doc.status] || badges.private)
        : (readOnlyBadges[doc.status] || readOnlyBadges.private);
    const selfUploaded = currentUser && String(doc.uploaded_by) === String(currentUser.id);
    const showReview = kb_shared && doc.status === 'pending' && isReviewer();
    // Own uploads are reviewable only under the sole-administrator exception.
    const mayReview = showReview && (!selfUploaded || kb.sole_reviewer);

    return `
        <div class="p-3 flex items-start justify-between gap-3">
            <div class="min-w-0">
                <p class="text-sm text-gray-900 dark:text-white truncate">${escapeHtml(doc.filename)}</p>
                <p class="text-xs ${cls}">
                    ${label}${doc.reviewer_email ? ` by ${escapeHtml(doc.reviewer_email)}` : ''}
                    <span class="text-gray-400">&middot; ${doc.char_count.toLocaleString()} characters</span>
                </p>
                ${doc.self_approved ? `
                <p class="text-xs text-blue-600 dark:text-blue-400 mt-0.5">
                    Not independent — approved by the sole administrator
                </p>` : ''}
                ${doc.reason ? `<p class="text-xs text-gray-500 mt-1 italic">${escapeHtml(doc.reason)}</p>` : ''}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                ${showReview && selfUploaded && !kb.sole_reviewer ? `
                    <span class="text-xs text-gray-400 italic">You uploaded this — another reviewer must approve</span>` : ''}
                ${mayReview ? `
                    <button data-kb-approve="${escapeHtml(doc.id)}" class="px-2 py-1 text-xs rounded-md bg-green-600 hover:bg-green-700 text-white">Approve${selfUploaded ? ' (sole admin)' : ''}</button>
                    <button data-kb-reject="${escapeHtml(doc.id)}" class="px-2 py-1 text-xs rounded-md border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20">Reject</button>` : ''}
                ${mine ? `
                    <button data-kb-rmdoc="${escapeHtml(doc.id)}" title="Remove" class="p-1 text-gray-400 hover:text-red-600">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                    </button>` : ''}
            </div>
        </div>`;
}

function wireDocActions(kb) {
    const root = document.getElementById('kb-root');
    if (!root) return;

    root.querySelectorAll('[data-kb-rmdoc]').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Remove this document? The index will be rebuilt without it.')) return;
            await api.deleteKnowledgeBaseDocument(kb.id, btn.getAttribute('data-kb-rmdoc'));
            renderDetail();
        });
    });

    root.querySelectorAll('[data-kb-approve]').forEach(btn => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            try {
                await api.reviewKnowledgeBaseDocument(kb.id, btn.getAttribute('data-kb-approve'), 'approve');
            } catch (err) {
                alert(err.message || 'Could not approve.');
            }
            renderDetail();
        });
    });

    root.querySelectorAll('[data-kb-reject]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const reason = prompt('Why is this document being rejected? (required)');
            if (reason === null) return;
            if (!reason.trim()) {
                alert('A reason is required for a rejection.');
                return;
            }
            try {
                await api.reviewKnowledgeBaseDocument(kb.id, btn.getAttribute('data-kb-reject'), 'reject', reason);
            } catch (err) {
                alert(err.message || 'Could not reject.');
            }
            renderDetail();
        });
    });
}

// --- Polling --------------------------------------------------------------
// The indexer runs in its own container, so the only way this view learns a
// build finished is to ask. Stopped on every re-render and on tab change so a
// backgrounded Control Panel is not polling forever.

function startPolling(fn) {
    stopPolling();
    pollTimer = setTimeout(() => { pollTimer = null; fn(); }, 3000);
}

export function stopPolling() {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
}

function errorBox(message) {
    return `<div class="p-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 text-sm text-red-800 dark:text-red-300">${escapeHtml(message)}</div>`;
}
