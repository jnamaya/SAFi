import * as ui from '../ui.js';
import * as api from '../api.js';
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
                <div class="flex justify-between items-start">
                     <div>
                         <div class="flex items-center gap-2">
                            <h4 class="font-bold text-lg text-gray-900 dark:text-white">${p.name}</h4>
                            ${isReadOnly ? '<span class="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200 text-xs rounded-full font-bold">DEMO</span>' : ''}
                         </div>
                         <p class="text-xs text-gray-500 font-mono mt-1 mb-3">ID: ${p.id}</p>
                         <div class="flex gap-2">
                             <span class="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 text-xs rounded-full font-medium">
                                ${(p.values_weights || []).length} Values
                             </span>
                             <span class="px-2 py-1 bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300 text-xs rounded-full font-medium">
                                ${(p.will_rules || []).length} Constraints
                             </span>
                         </div>
                     </div>
                     <div class="flex gap-3">
                         <button class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white view-policy-btn" data-id="${p.id}">View</button>
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
            <div class="mb-8">
                <div class="mb-4">
                     <h3 class="text-xl font-bold">Organizational Policies</h3>
                     <p class="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-3xl">
                        Organizational AI policies are defined by Legal or IT departments to enforce strict behavioral governance across all agents built under this policy. 
                        These policies act as an immutable "Constitution" for your AI workforce.
                     </p>
                </div>
                ${canEditPolicy ? `
                <button id="btn-create-policy" class="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-colors flex items-center gap-2 shadow-sm">
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
                    // We could reuse the wizard success screen or just show an alert
                    try {
                        const res = await api.generateKey(btn.dataset.id, label);
                        if (res.ok) {
                            // Use a prompt to allow copying
                            prompt("API Key Generated. Copy it now, it won't be shown again:", res.api_key);
                        } else {
                            alert("Error: " + res.error);
                        }
                    } catch (e) {
                        alert(e.message);
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
                    renderProfileDetailsModal(policyAsProfile);
                    // Open the modal
                    const modal = document.getElementById('profile-details-modal');
                    if (modal) modal.classList.remove('hidden');
                }
            });
        });

    } catch (e) {
        container.innerHTML = `<div class="p-8 text-center text-red-500">Error loading policies: ${e.message}</div>`;
    }
}
