import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { openPolicyWizard } from '../ui-policy-wizard.js';
import { renderProfileDetailsModal } from './ui-settings-agents.js';
import { escapeHtml, formatRelativeTime } from '../../core/utils.js';

// Constraint count must handle both shapes of will_rules: legacy
// list-of-rules, and the structured dict (whose .length is undefined).
function constraintCount(wr) {
    if (Array.isArray(wr)) return wr.length;
    if (wr && typeof wr === 'object') {
        const sr = wr.structural_requirements || {};
        return (wr.early_prompt_blacklist || []).length
            + (sr.banned_markdown_syntaxes || []).length
            + (sr.require_disclaimer ? 1 : 0)
            + (Array.isArray(wr.allowed_tools) ? 1 : 0);
    }
    return 0;
}

// --- NEW: Governance Tab Rendering ---
export async function renderSettingsGovernanceTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabGovernance;
    if (!container) return;

    container.innerHTML = `<div class="p-8 text-center"><div class="thinking-spinner w-8 h-8 mx-auto mb-4"></div><p>Loading Policies...</p></div>`;

    try {
        const [res, meRes] = await Promise.all([
            api.fetchPolicies(),
            api.getMe()
        ]);

        if (!res.ok) throw new Error(res.error || "Failed to fetch policies");

        const user = meRes && meRes.ok ? meRes.user : {};
        // RBAC: Admin & Editor have Write Access. Auditor is Read Only.
        const canEditPolicy = ['admin', 'editor'].includes(user.role);
        // RBAC: Only Admin can generate keys (implied by matrix "Create/Edit/Delete" for Editor, but Keys are sensitive). 
        // Matrix says Editor: "Create/Edit/Delete" for "AI Construction". Keys are arguably part of construction.
        // Let's allow Editors to generate keys too for consistency with "AI Construction".
        const canGenerateKey = ['admin', 'editor'].includes(user.role);

        const allPolicies = res.policies || []; // Ensure array

        // Split Policies
        const demoPolicies = allPolicies.filter(p => p.is_demo);
        const myPolicies = allPolicies.filter(p => !p.is_demo);

        const renderPolicyCard = (p, isReadOnly) => `
            <div class="bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-5 hover:shadow-md transition-shadow mb-3">
                <div class="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3">
                     <div class="min-w-0 sm:flex-1">
                         <div class="flex items-center flex-wrap gap-2">
                            <h4 class="font-bold text-lg text-gray-900 dark:text-white break-words min-w-0">${p.name}</h4>
                            ${isReadOnly ? '<span class="px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200 text-xs rounded-full font-bold shrink-0">EXAMPLE</span>' : ''}
                         </div>
                         <p class="text-xs text-gray-500 font-mono mt-1 mb-3 break-all">ID: ${p.id}</p>
                         <div class="flex gap-2">
                             <span class="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 text-xs rounded-full font-medium">
                                ${(p.values_weights || []).length} Values
                             </span>
                             <span class="px-2 py-1 bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 text-xs rounded-full font-medium">
                                ${constraintCount(p.will_rules)} Constraints
                             </span>
                         </div>
                     </div>
                     <div class="flex flex-wrap items-center gap-x-3 gap-y-2 sm:justify-end sm:shrink-0">
                         <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white view-policy-btn" data-id="${p.id}">View</button>
                         <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white history-policy-btn" data-id="${p.id}" data-name="${p.name}">History</button>
                         ${canEditPolicy ? `<button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white dup-policy-btn" data-id="${p.id}">Duplicate</button>` : ''}
                         ${canGenerateKey ? `<button class="text-sm text-green-600 hover:underline manage-keys-btn" data-id="${p.id}" data-name="${escapeHtml(p.name)}">API Keys</button>` : ''}
                         ${!isReadOnly && canEditPolicy ? `
                         <button class="text-sm text-gray-600 hover:text-green-600 edit-policy-btn" data-id="${p.id}">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                         </button>
                         <button class="text-sm text-red-500 hover:text-red-600 delete-policy-btn" data-id="${p.id}">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                         </button>` : ''}
                     </div>
                </div>
            </div>
        `;

        container.innerHTML = `
            <div class="settings-page-header">
                <h1>Policies</h1>
                <p>Create policies for specific business units, teams, or use cases — HR, Finance, Legal, Customer Service, and so on. Each agent is assigned one policy that defines its purpose &amp; voice, standards, scope, and rules.</p>
            </div>

            <!-- Policy-change approvals (backlog 57f): policy approvers see
                 pending activations here; empty for everyone else. -->
            <div id="policy-approvals-host"></div>
            <div class="mb-8">
                ${canEditPolicy ? `
                <button id="btn-create-policy" class="px-5 py-2.5 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition-colors flex items-center gap-2 shadow-sm">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" /></svg>
                    Create New Policy
                </button>` : ''}
            </div>

            <div class="space-y-8">
                <!-- YOUR POLICIES (lead — this is the org's real governance) -->
                <div>
                    <h4 class="text-sm font-bold text-gray-400 uppercase mb-3">Your Policies</h4>
                     ${myPolicies.length === 0 ? `
                        <div class="p-8 text-center border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl">
                            <p class="text-gray-500 mb-4">No policies defined yet. Create one above, or start from an example below.</p>
                        </div>
                    ` : myPolicies.map(p => renderPolicyCard(p, false)).join('')}
                </div>

                <!-- EXAMPLE POLICIES (read-only demos; collapsed once the org has its own) -->
                ${demoPolicies.length === 0 ? '' : `
                <details ${myPolicies.length === 0 ? 'open' : ''}>
                    <summary class="text-sm font-bold text-gray-400 uppercase mb-3 cursor-pointer select-none hover:text-gray-600 dark:hover:text-gray-300">Example Policies (${demoPolicies.length}) — read-only, duplicate to customize</summary>
                    ${demoPolicies.map(p => renderPolicyCard(p, true)).join('')}
                </details>`}
            </div>
        `;

        // Handlers
        const createBtn = document.getElementById('btn-create-policy');
        if (createBtn) {
            createBtn.addEventListener('click', () => {
                openPolicyWizard();
            });
        }

        container.querySelectorAll('.edit-policy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const policy = allPolicies.find(p => p.id === btn.dataset.id);
                if (policy) {
                    openPolicyWizard(policy);
                }
            });
        });

        container.querySelectorAll('.delete-policy-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (confirm('Are you sure you want to delete this policy? This may break agents using it.')) {
                    await api.deletePolicy(btn.dataset.id);
                    renderSettingsGovernanceTab(); // Refresh
                }
            });
        });

        container.querySelectorAll('.manage-keys-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                openManageKeysModal(btn.dataset.id, btn.dataset.name, canGenerateKey);
            });
        });

        container.querySelectorAll('.view-policy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const policy = allPolicies.find(p => p.id === btn.dataset.id);
                if (policy) {
                    // Reuse Profile Modal for displaying Policy Details
                    const policyAsProfile = {
                        name: policy.name,
                        description: `**Policy ID:** ${policy.id}\n\nThis policy is ${policy.is_demo ? 'a **DEMO/OFFICIAL** policy' : 'a **CUSTOM** policy'}.`,
                        worldview: policy.worldview,
                        style: "N/A (Policies do not enforce style directly, only logic)",
                        values: policy.values_weights,
                        will_rules: policy.will_rules
                    };
                    renderProfileDetailsModal(policyAsProfile, { isPolicy: true });
                    // Open the modal
                    const modal = document.getElementById('profile-details-modal');
                    if (modal) modal.classList.remove('hidden');
                }
            });
        });

        container.querySelectorAll('.history-policy-btn').forEach(btn => {
            btn.addEventListener('click', () => openPolicyHistory(btn.dataset.id, btn.dataset.name, canEditPolicy));
        });

        container.querySelectorAll('.dup-policy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const policy = allPolicies.find(p => p.id === btn.dataset.id);
                if (policy) openPolicyWizard({ ...policy, id: null, name: `Copy of ${policy.name}` });
            });
        });

        renderPolicyApprovals();

    } catch (e) {
        container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading policies: ${e.message}</div>`;
    }
}

// --- POLICY-CHANGE APPROVALS PANEL (backlog 57f) ---

function escGov(s) {
    const div = document.createElement('div');
    div.textContent = String(s ?? '');
    return div.innerHTML;
}

async function renderPolicyApprovals() {
    const host = document.getElementById('policy-approvals-host');
    if (!host) return;
    let requests = [];
    try {
        const res = await api.listPolicyChanges('pending');
        requests = res.requests || [];
    } catch (e) {
        return; // not a policy approver, or a transient failure: no panel
    }
    if (!requests.length) {
        host.innerHTML = '';
        return;
    }
    host.innerHTML = `
        <div class="mb-6 border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 rounded-xl overflow-hidden">
            <div class="px-5 py-3 border-b border-amber-200 dark:border-amber-800">
                <h3 class="text-sm font-semibold text-amber-800 dark:text-amber-300">Policy changes awaiting approval</h3>
                <p class="text-xs text-amber-700 dark:text-amber-400 mt-0.5">Each policy keeps its current content until a change is approved. Submitters cannot approve their own change.</p>
            </div>
            ${requests.map(r => `
                <div class="px-5 py-3 flex flex-wrap items-center gap-3 border-b border-amber-100 dark:border-amber-900/40 last:border-0 bg-white dark:bg-neutral-900">
                    <div class="min-w-0 flex-1">
                        <p class="text-sm font-medium text-gray-900 dark:text-white truncate">${escGov(r.policy_name || r.policy_id)}</p>
                        <p class="text-xs text-gray-500 truncate">submitted by ${escGov(r.requester_name || r.requested_by)} &middot; changes ${(r.changed || []).map(f => `<code class="bg-gray-100 dark:bg-neutral-800 px-1 py-0.5 rounded">${escGov(f)}</code>`).join(' ')}</p>
                    </div>
                    <div class="flex items-center gap-2 flex-shrink-0">
                        <button data-req="${escGov(r.id)}" class="policy-req-approve px-3 py-1.5 text-xs font-semibold text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors">Approve</button>
                        <button data-req="${escGov(r.id)}" class="policy-req-reject px-3 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors">Reject</button>
                    </div>
                </div>`).join('')}
        </div>`;

    host.querySelectorAll('.policy-req-approve').forEach(btn => btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
            const res = await api.approvePolicyChange(btn.dataset.req);
            ui.showToast(res.self_approved
                ? `Activated as version ${res.version} (recorded as non-independent: you are the only eligible approver).`
                : `Policy change activated as version ${res.version}.`, 'success');
            renderSettingsGovernanceTab();
        } catch (e) {
            ui.showToast(e.message || 'Approval failed', 'error');
            btn.disabled = false;
        }
    }));
    host.querySelectorAll('.policy-req-reject').forEach(btn => btn.addEventListener('click', async () => {
        const reason = prompt('Reason for rejecting (optional):') ?? null;
        if (reason === null) return;
        btn.disabled = true;
        try {
            await api.rejectPolicyChange(btn.dataset.req, reason);
            ui.showToast('Policy change rejected.', 'success');
            renderPolicyApprovals();
        } catch (e) {
            ui.showToast(e.message || 'Rejection failed', 'error');
            btn.disabled = false;
        }
    }));
}

// --- Policy Version History (modal) ---
async function openPolicyHistory(policyId, policyName, canEdit) {
    document.getElementById('policy-history-modal')?.remove();
    const modal = document.createElement('div');
    modal.id = 'policy-history-modal';
    modal.className = 'fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/50';
    modal.innerHTML = `
      <div class="bg-white dark:bg-neutral-900 rounded-2xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-neutral-800">
          <div>
            <h3 class="font-bold text-lg text-gray-900 dark:text-white">Version History</h3>
            <p class="text-xs text-gray-500 font-mono">${policyName}</p>
          </div>
          <button id="ph-close" class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
        <div id="ph-body" class="p-6 overflow-y-auto custom-scrollbar">
          <div class="text-center text-gray-500 py-8"><div class="thinking-spinner w-6 h-6 mx-auto mb-3"></div>Loading history…</div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    const close = () => modal.remove();
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    modal.querySelector('#ph-close').addEventListener('click', close);

    const body = modal.querySelector('#ph-body');
    try {
        const res = await api.getPolicyVersions(policyId);
        if (!res.ok) throw new Error(res.error || 'Failed to load history');
        const versions = res.versions || [];
        if (!versions.length) { body.innerHTML = '<p class="text-gray-500 text-center py-8">No history yet.</p>'; return; }
        const latest = versions[0].version;
        body.innerHTML = versions.map(v => `
          <div class="border border-gray-200 dark:border-neutral-800 rounded-xl p-4 mb-3">
            <div class="flex items-center justify-between gap-3">
              <div>
                <span class="font-semibold text-gray-900 dark:text-white">v${v.version}</span>
                ${v.version === latest ? '<span class="ml-2 px-2 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs rounded-full font-medium">current</span>' : ''}
                <div class="text-xs text-gray-500 mt-0.5">${v.note ? v.note + ' · ' : ''}${v.created_at ? new Date(v.created_at).toLocaleString() : ''}</div>
              </div>
              <div class="flex gap-3 shrink-0">
                <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white ph-view" data-v="${v.version}">View</button>
                ${(canEdit && v.version !== latest) ? `<button class="text-sm text-green-600 hover:underline ph-restore" data-v="${v.version}">Restore</button>` : ''}
              </div>
            </div>
            <pre class="ph-detail hidden mt-3 text-xs whitespace-pre-wrap bg-gray-50 dark:bg-neutral-800 rounded-lg p-3 text-gray-700 dark:text-gray-300 max-h-48 overflow-y-auto" data-v="${v.version}"></pre>
          </div>`).join('');

        body.querySelectorAll('.ph-view').forEach(b => b.addEventListener('click', async () => {
            const vno = b.dataset.v;
            const pre = body.querySelector(`.ph-detail[data-v="${vno}"]`);
            if (!pre.classList.contains('hidden')) { pre.classList.add('hidden'); return; }
            pre.textContent = 'Loading…'; pre.classList.remove('hidden');
            const r = await api.getPolicyVersion(policyId, vno);
            if (r.ok) {
                const v = r.version;
                const vals = (v.values_weights || []).map(x => x.name || x.value).filter(Boolean);
                pre.textContent =
                  `PURPOSE & MANDATE:\n${v.worldview || '(none)'}\n\n` +
                  `VALUES (${vals.length}): ${vals.join(', ') || '(none)'}\n` +
                  `CONSTRAINTS: ${constraintCount(v.will_rules)}\n` +
                  `SCOPE: ${(v.policy_config || {}).scope_statement || '(none)'}`;
            } else { pre.textContent = 'Failed to load version.'; }
        }));

        body.querySelectorAll('.ph-restore').forEach(b => b.addEventListener('click', async () => {
            if (!confirm(`Restore policy to v${b.dataset.v}? This creates a new version with that content; agents using this policy will pick it up.`)) return;
            b.disabled = true; b.textContent = 'Restoring…';
            const r = await api.restorePolicyVersion(policyId, b.dataset.v);
            if (r.ok) {
                if (r.pending_approval) {
                    ui.showToast('Restore submitted for approval. The policy keeps its current content until a policy approver activates it.', 'warning', 7000);
                }
                close(); renderSettingsGovernanceTab();
            }
            else { alert(r.error || 'Restore failed.'); b.disabled = false; b.textContent = 'Restore'; }
        }));
    } catch (e) {
        body.innerHTML = `<p class="text-red-500 text-center py-8">${e.message}</p>`;
    }
}

// --- API Keys Management (modal) ---
async function openManageKeysModal(policyId, policyName, canGenerateKey = true) {
    document.getElementById('policy-keys-modal')?.remove();
    const modal = document.createElement('div');
    modal.id = 'policy-keys-modal';
    modal.className = 'fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm';
    modal.innerHTML = `
      <div class="bg-white dark:bg-neutral-900 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden border border-gray-200 dark:border-neutral-800 text-gray-900 dark:text-neutral-100">
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-neutral-800 bg-white dark:bg-neutral-900">
          <div class="min-w-0 pr-4">
            <h3 class="font-bold text-lg text-gray-900 dark:text-white truncate">API Keys &mdash; ${escapeHtml(policyName || policyId)}</h3>
            <p class="text-xs text-gray-500 dark:text-neutral-400 font-mono mt-0.5 truncate">Policy ID: ${escapeHtml(policyId)}</p>
          </div>
          <button id="keys-modal-close" class="text-gray-400 hover:text-gray-700 dark:text-neutral-400 dark:hover:text-white p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-neutral-800 transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>

        <div class="p-6 overflow-y-auto custom-scrollbar space-y-6 bg-white dark:bg-neutral-900">
          ${canGenerateKey ? `
          <!-- Generate Key Card -->
          <div class="p-4 bg-gray-50 dark:bg-neutral-800/50 rounded-xl border border-gray-200 dark:border-neutral-700/80">
            <h4 class="text-sm font-bold text-gray-900 dark:text-white mb-1">Generate New API Key</h4>
            <p class="text-xs text-gray-500 dark:text-neutral-400 mb-3">Issue a named key for a developer, machine, or service account to identify them in the audit trail.</p>
            <div class="flex flex-col sm:flex-row gap-2">
              <input id="new-key-label" type="text" placeholder="Key Label (e.g. Nelson - Laptop, CI Pipeline)"
                     class="flex-1 px-3.5 py-2.5 bg-white dark:bg-neutral-900 border border-gray-300 dark:border-neutral-700 rounded-lg text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-green-500 dark:focus:ring-green-400">
              <button id="btn-submit-new-key" class="px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg transition-colors shrink-0 flex items-center justify-center gap-1.5 shadow-sm">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                Generate Key
              </button>
            </div>
            <div id="new-key-alert-container" class="mt-3 hidden"></div>
          </div>` : ''}

          <!-- Keys List -->
          <div>
            <div class="flex items-center justify-between mb-3">
              <h4 class="text-xs font-bold text-gray-400 dark:text-neutral-500 uppercase tracking-wider">Active Keys</h4>
              <span id="keys-count-badge" class="text-xs text-gray-500 dark:text-neutral-400 font-medium"></span>
            </div>
            <div id="keys-list-container" class="space-y-2">
              <div class="p-6 text-center text-gray-500 dark:text-neutral-400"><div class="thinking-spinner w-6 h-6 mx-auto mb-2"></div>Loading keys…</div>
            </div>
          </div>
        </div>

        <div class="px-6 py-3.5 bg-gray-50 dark:bg-neutral-900 border-t border-gray-200 dark:border-neutral-800 flex justify-end">
          <button id="keys-modal-done" class="px-4 py-2 bg-gray-200 hover:bg-gray-300 dark:bg-neutral-800 dark:hover:bg-neutral-700 text-gray-800 dark:text-neutral-200 text-sm font-medium rounded-lg transition-colors">Done</button>
        </div>
      </div>`;

    document.body.appendChild(modal);

    const close = () => {
        document.removeEventListener('keydown', onKeyDown);
        modal.remove();
    };
    const onKeyDown = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKeyDown);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    modal.querySelector('#keys-modal-close')?.addEventListener('click', close);
    modal.querySelector('#keys-modal-done')?.addEventListener('click', close);

    const listContainer = modal.querySelector('#keys-list-container');
    const countBadge = modal.querySelector('#keys-count-badge');

    const loadAndRenderKeys = async () => {
        try {
            const res = await api.listPolicyKeys(policyId);
            if (!res.ok) throw new Error(res.error || 'Failed to load keys');
            const keys = res.keys || [];
            countBadge.textContent = `${keys.length} key${keys.length === 1 ? '' : 's'}`;

            if (keys.length === 0) {
                listContainer.innerHTML = `
                  <div class="p-6 text-center border-2 border-dashed border-gray-200 dark:border-neutral-800 rounded-xl text-gray-400 dark:text-neutral-500 text-sm">
                    No active API keys found for this policy. Generate one above to connect the CLI or an agent.
                  </div>`;
                return;
            }

            listContainer.innerHTML = keys.map(k => {
                const relCreated = k.created_at ? formatRelativeTime(k.created_at) || new Date(k.created_at).toLocaleDateString() : '—';
                const relUsed = k.last_used_at ? formatRelativeTime(k.last_used_at) || new Date(k.last_used_at).toLocaleDateString() : 'Never used';
                const isNeverUsed = !k.last_used_at;

                return `
                  <div class="p-3.5 bg-white dark:bg-neutral-800/50 rounded-xl border border-gray-200 dark:border-neutral-700/80 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 hover:border-gray-300 dark:hover:border-neutral-600 transition-colors">
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-semibold text-sm text-gray-900 dark:text-white break-words">${escapeHtml(k.label)}</span>
                        <span class="text-xs font-mono px-2 py-0.5 bg-gray-100 dark:bg-neutral-800 border border-transparent dark:border-neutral-700 text-gray-600 dark:text-neutral-300 rounded font-normal" title="SHA-256 Key Hash Prefix">#${escapeHtml(k.key_hash_prefix || (k.key_hash || '').slice(0, 8))}</span>
                      </div>
                      <div class="text-xs text-gray-500 dark:text-neutral-400 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span>Created: <strong class="text-gray-700 dark:text-neutral-300 font-normal">${relCreated}</strong></span>
                        <span>&bull;</span>
                        <span>Last used: <strong class="${isNeverUsed ? 'text-gray-400 dark:text-neutral-500 font-normal' : 'text-green-600 dark:text-green-400 font-medium'}">${relUsed}</strong></span>
                      </div>
                    </div>
                    ${canGenerateKey ? `
                    <div class="shrink-0 flex items-center justify-end">
                      <button class="revoke-single-key-btn px-2.5 py-1.5 text-xs text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg font-medium transition-colors flex items-center gap-1.5 border border-transparent dark:border-red-900/30"
                              data-hash="${escapeHtml(k.key_hash)}" data-label="${escapeHtml(k.label)}">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        Revoke
                      </button>
                    </div>` : ''}
                  </div>`;
            }).join('');

            listContainer.querySelectorAll('.revoke-single-key-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const label = btn.dataset.label;
                    const hash = btn.dataset.hash;
                    if (!confirm(`Are you sure you want to revoke API key "${label}"?\n\nAny developer, CLI, or agent using this key will immediately lose access.`)) {
                        return;
                    }
                    btn.disabled = true;
                    btn.textContent = 'Revoking…';
                    try {
                        const revRes = await api.revokePolicyKey(policyId, hash);
                        if (revRes.ok) {
                            ui.showToast(`Revoked API key "${label}"`, 'info');
                            await loadAndRenderKeys();
                        } else {
                            alert(revRes.error || 'Failed to revoke key');
                            btn.disabled = false;
                            btn.textContent = 'Revoke';
                        }
                    } catch (e) {
                        alert('Error revoking key: ' + e.message);
                        btn.disabled = false;
                        btn.textContent = 'Revoke';
                    }
                });
            });
        } catch (e) {
            listContainer.innerHTML = `<div class="p-4 text-center text-red-500 text-sm">Error loading keys: ${escapeHtml(e.message)}</div>`;
        }
    };

    // Generate Key form handling
    const labelInput = modal.querySelector('#new-key-label');
    const submitBtn = modal.querySelector('#btn-submit-new-key');
    const alertContainer = modal.querySelector('#new-key-alert-container');

    if (submitBtn && labelInput) {
        const handleGen = async () => {
            const label = (labelInput.value || '').trim() || 'Default Key';
            submitBtn.disabled = true;
            submitBtn.textContent = 'Generating…';
            try {
                const res = await api.generateKey(policyId, label);
                if (res.ok && res.api_key) {
                    const rawKey = res.api_key.trim();
                    alertContainer.classList.remove('hidden');
                    alertContainer.innerHTML = `
                      <div class="p-3.5 bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/60 rounded-xl text-sm">
                        <div class="flex items-center justify-between mb-1.5">
                          <span class="font-bold text-xs uppercase tracking-wider text-green-800 dark:text-green-400">Key Created &mdash; Save Now</span>
                          <span class="text-xs text-amber-600 dark:text-amber-400 font-semibold">Will not be shown again</span>
                        </div>
                        <div class="flex items-center gap-2 mt-1">
                          <code id="new-key-display" class="flex-1 p-2.5 bg-white dark:bg-neutral-900 rounded-lg border border-green-300 dark:border-neutral-700 font-mono text-xs break-all select-all text-green-700 dark:text-green-400 font-bold">${escapeHtml(rawKey)}</code>
                          <button id="btn-copy-new-key" class="px-3.5 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-semibold shrink-0 transition-colors shadow-sm">Copy</button>
                        </div>
                      </div>`;
                    labelInput.value = '';

                    modal.querySelector('#btn-copy-new-key')?.addEventListener('click', async (e) => {
                        await navigator.clipboard.writeText(rawKey);
                        e.target.textContent = 'Copied!';
                        setTimeout(() => { if (e.target) e.target.textContent = 'Copy'; }, 2000);
                    });

                    try {
                        await navigator.clipboard.writeText(rawKey);
                        ui.showToast('New API key copied to clipboard!', 'success');
                    } catch (_) {}

                    await loadAndRenderKeys();
                } else {
                    alert(res.error || 'Failed to generate key.');
                }
            } catch (e) {
                alert('Error generating key: ' + e.message);
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg> Generate Key`;
            }
        };

        submitBtn.addEventListener('click', handleGen);
        labelInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleGen();
            }
        });
    }

    await loadAndRenderKeys();
}
