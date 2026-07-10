import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { openPolicyWizard } from '../ui-policy-wizard.js';
import { renderProfileDetailsModal } from './ui-settings-agents.js';

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
                <div class="flex justify-between items-start gap-3">
                     <div class="min-w-0 flex-1">
                         <div class="flex items-center flex-wrap gap-2">
                            <h4 class="font-bold text-lg text-gray-900 dark:text-white break-words min-w-0">${p.name}</h4>
                            ${isReadOnly ? '<span class="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200 text-xs rounded-full font-bold shrink-0">DEMO</span>' : ''}
                         </div>
                         <p class="text-xs text-gray-500 font-mono mt-1 mb-3 break-all">ID: ${p.id}</p>
                         <div class="flex gap-2">
                             <span class="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 text-xs rounded-full font-medium">
                                ${(p.values_weights || []).length} Values
                             </span>
                             <span class="px-2 py-1 bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 text-xs rounded-full font-medium">
                                ${(p.will_rules || []).length} Constraints
                             </span>
                         </div>
                     </div>
                     <div class="flex flex-wrap gap-x-3 gap-y-2 justify-end shrink-0">
                         <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white view-policy-btn" data-id="${p.id}">View</button>
                         <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white history-policy-btn" data-id="${p.id}" data-name="${p.name}">History</button>
                         ${canEditPolicy ? `<button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white dup-policy-btn" data-id="${p.id}">Duplicate</button>` : ''}
                         ${canGenerateKey ? `<button class="text-sm text-blue-600 hover:underline gen-key-btn" data-id="${p.id}" data-name="${p.name}">Generate Key</button>` : ''}
                         ${!isReadOnly && canEditPolicy ? `
                         <button class="text-sm text-gray-600 hover:text-blue-600 edit-policy-btn" data-id="${p.id}">
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
            <div class="mb-8">
                ${canEditPolicy ? `
                <button id="btn-create-policy" class="px-5 py-2.5 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition-colors flex items-center gap-2 shadow-sm">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" /></svg>
                    Create New Policy
                </button>` : ''}
            </div>

            <div class="space-y-8">
                <!-- DEMO POLICIES -->
                <div>
                    <h4 class="text-sm font-bold text-gray-400 uppercase mb-3">DEMO Policy</h4>
                    ${demoPolicies.length === 0 ? '<p class="text-sm text-gray-400 italic">No demo policies available.</p>' : demoPolicies.map(p => renderPolicyCard(p, true)).join('')}
                </div>

                <!-- MY POLICIES -->
                <div>
                    <h4 class="text-sm font-bold text-gray-400 uppercase mb-3">Custom Policies</h4>
                     ${myPolicies.length === 0 ? `
                        <div class="p-8 text-center border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl">
                            <p class="text-gray-500 mb-4">No custom policies defined yet.</p>
                        </div>
                    ` : myPolicies.map(p => renderPolicyCard(p, false)).join('')}
                </div>
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

        container.querySelectorAll('.gen-key-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const label = prompt(`Enter a label for this new key (e.g. "Marketing Bot"):`, "New Key");
                if (label) {
                    try {
                        const res = await api.generateKey(btn.dataset.id, label);
                        if (res.ok) {
                            const key = res.api_key.trim();
                            await navigator.clipboard.writeText(key);
                            alert(`Secure Key Generated & Copied to Clipboard!\n\n${key}\n\nPlease paste this immediately.`);
                        } else {
                            alert("Failed to generate key. Please try again.");
                        }
                    } catch (e) {
                        alert("An error occurred. Please try again.");
                    }
                }
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

    } catch (e) {
        container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading policies: ${e.message}</div>`;
    }
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
                ${(canEdit && v.version !== latest) ? `<button class="text-sm text-blue-600 hover:underline ph-restore" data-v="${v.version}">Restore</button>` : ''}
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
                  `CONSTRAINTS: ${(v.will_rules || []).length}\n` +
                  `SCOPE: ${(v.policy_config || {}).scope_statement || '(none)'}`;
            } else { pre.textContent = 'Failed to load version.'; }
        }));

        body.querySelectorAll('.ph-restore').forEach(b => b.addEventListener('click', async () => {
            if (!confirm(`Restore policy to v${b.dataset.v}? This creates a new version with that content; agents using this policy will pick it up.`)) return;
            b.disabled = true; b.textContent = 'Restoring…';
            const r = await api.restorePolicyVersion(policyId, b.dataset.v);
            if (r.ok) { close(); renderSettingsGovernanceTab(); }
            else { alert(r.error || 'Restore failed.'); b.disabled = false; b.textContent = 'Restore'; }
        }));
    } catch (e) {
        body.innerHTML = `<p class="text-red-500 text-center py-8">${e.message}</p>`;
    }
}
