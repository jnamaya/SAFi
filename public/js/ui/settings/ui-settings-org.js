import * as ui from '../ui.js';
import * as api from '../../core/api.js';

let currentUser = null; // We need to set this if we want to check "isSelf"
// But how? 
// The original file had a module-level `currentUser`.
// We should probably export an update function here too, or fetch it.
// The `renderSettingsOrganizationTab` doesn't take user as param.
// BUT `renderMembersTable` uses `currentUser`. 
// I'll add an `updateCurrentUser` execution in core that calls this if needed, 
// OR just pass user into `renderSettingsOrganizationTab` from core?
// Original: `renderSettingsOrganizationTab()` called `api.getMyOrganization()`.
// `renderMembersTable` uses module-level `currentUser`.
// `ui-settings-core` has `updateCurrentUser`.
// I should export `updateCurrentUser` here as well and call it from core when core updates.
// OR better: `renderSettingsOrganizationTab` should just fetch the user itself or accept it.
// `api.getMe()` is cheap (cached usually?).
// Actually, `ui-settings-core` receives `updateCurrentUser`.
// We need to set this if we want to check "isSelf"
// We export a specific setter to avoid name conflict with core.
export function setOrgCurrentUser(u) {
    currentUser = u;
}

/**
 * Renders the Organization Settings tab (Admin Only).
 * Handles fetching org details and Domain Verification.
 */
export async function renderSettingsOrganizationTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabOrganization;
    if (!container) return;

    container.innerHTML = `
        <div class="flex items-center justify-center h-32">
            <div class="thinking-spinner"></div>
        </div>
    `;

    try {
        const res = await api.getMyOrganization();
        const org = res ? res.organization : null;

        if (!org) {
            container.innerHTML = `
                <div class="text-center p-8">
                    <h3 class="text-xl font-semibold mb-2">No Organization Found</h3>
                    <p class="text-neutral-500">You do not seem to belong to an organization yet.</p>
                </div>
            `;
            return;
        }

        renderOrganizationUI(container, org);

    } catch (error) {
        container.innerHTML = `<p class="text-red-500">Error loading organization: ${error.message}</p>`;
    }
}


function renderOrganizationUI(container, org) {
    const isVerified = org.domain_verified;
    const verificationSection = isVerified
        ? `
            <div class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6">
                <div class="flex items-center gap-3">
                    <div class="p-2 bg-green-100 dark:bg-green-800 rounded-full text-green-600 dark:text-green-300">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <div>
                        <h4 class="font-bold text-green-900 dark:text-green-100">Domain Verified</h4>
                        <p class="text-sm text-green-700 dark:text-green-300">
                            Users with <strong>@${org.domain_to_verify}</strong> emails will automatically join this organization.
                        </p>
                    </div>
                </div>
            </div>
        `
        : `
            <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
                <h4 class="font-bold text-blue-900 dark:text-blue-100 mb-2">Verify Your Domain</h4>
                <p class="text-sm text-blue-700 dark:text-blue-300 mb-4">
                    Claim <strong>${org.domain_to_verify || 'your domain'}</strong> to enable Auto-Join for your team.
                </p>
                
                ${org.verification_token
            ? `
                        <div class="mb-4 bg-white dark:bg-black p-3 rounded border border-neutral-200 dark:border-neutral-700 font-mono text-xs break-all">
                            TXT Record: <strong>${org.verification_token}</strong>
                        </div>
                        <div class="flex gap-2">
                             <button id="btn-check-verify" data-org-id="${org.id}" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold transition-colors">
                                Check DNS Records
                            </button>
                            <button id="btn-cancel-verify" data-org-id="${org.id}" class="px-4 py-2 bg-red-100 hover:bg-red-200 text-red-700 dark:bg-red-900/30 dark:hover:bg-red-900/50 dark:text-red-300 rounded-lg text-sm font-semibold transition-colors">
                                Cancel
                            </button>
                        </div>
                      `
            : `
                        <div class="flex gap-2">
                             <input type="text" id="domain-verify-input" class="w-full p-2 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm" placeholder="e.g. acme.com">
                             <button id="btn-start-verify" data-org-id="${org.id}" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold whitespace-nowrap transition-colors">
                                Verify
                             </button>
                        </div>
                      `
        }
            </div>
        `;

    container.innerHTML = `
        <div class="mb-6 border-b border-neutral-200 dark:border-neutral-800 pb-4">
            <div class="flex items-center justify-between">
                <div id="org-name-display-container" class="group flex items-center gap-3">
                    <h3 class="text-2xl font-bold text-neutral-900 dark:text-white">
                        ${org.name}
                    </h3>
                    <button id="btn-edit-org-name" class="p-1 text-gray-400 hover:text-blue-600 rounded opacity-0 group-hover:opacity-100 transition-opacity" title="Rename Organization">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
                    </button>
                    <div class="flex items-center gap-2 text-sm text-neutral-500 ml-2">
                        <span>ID:</span>
                        <code class="bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded select-all">${org.id}</code>
                    </div>
                </div>

                <div id="org-name-edit-container" class="hidden flex items-center gap-2 w-full max-w-md">
                    <input type="text" id="input-org-name" value="${org.name}" class="flex-1 px-3 py-2 bg-gray-50 dark:bg-neutral-800 border border-gray-300 dark:border-neutral-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none">
                    <button id="btn-save-org-name" class="p-2 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/30 rounded-lg">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                    </button>
                    <button id="btn-cancel-org-name" class="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
            </div>
        </div>

        ${verificationSection}

        <div class="mb-8 border-b border-neutral-200 dark:border-neutral-800 pb-8">
             <h4 class="text-lg font-semibold mb-4">AI Governance Configuration</h4>
             
             <div class="bg-gray-50 dark:bg-neutral-800/50 rounded-xl p-6 border border-gray-200 dark:border-neutral-800 space-y-8">
                 <!-- Authority Slider -->
                 <div>
                      <div class="flex justify-between items-end mb-2">
                          <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Organizational Authority</label>
                          <span id="lbl-gov-weight" class="text-sm font-mono bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">
                            ${Math.round((org.settings?.governance_split ?? 0.60) * 100)}%
                          </span>
                      </div>
                      <input type="range" id="sl-gov-weight" min="0" max="100" value="${Math.round((org.settings?.governance_split ?? 0.60) * 100)}" 
                        class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600">
                      <div class="flex justify-between text-xs text-gray-500 mt-2">
                          <span>Agent Autonomy (0%)</span>
                          <span class="font-bold text-gray-400">Balanced (60%)</span>
                          <span>Strict Compliance (100%)</span>
                      </div>
                      <p class="text-xs text-gray-500 mt-2">Determines how much weight is given to the Organization's Policy vs the Agent's Persona.</p>
                 </div>
                 
                 <!-- Memory Slider -->
                 <div>
                      <div class="flex justify-between items-end mb-2">
                          <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Ethical Memory (Retention)</label>
                          <span id="lbl-spirit-beta" class="text-sm font-mono bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">
                            ${(org.settings?.spirit_beta ?? 0.90)}
                          </span>
                      </div>
                      <input type="range" id="sl-spirit-beta" min="10" max="99" value="${Math.round((org.settings?.spirit_beta ?? 0.90) * 100)}" 
                        class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-purple-600">
                      <div class="flex justify-between text-xs text-gray-500 mt-2">
                          <span>Short Term (Adapts Fast)</span>
                          <span class="font-bold text-gray-400">Balanced</span>
                          <span>Long Term (Resists Change)</span>
                      </div>
                      <p class="text-xs text-gray-500 mt-2">Determines the weight of history. High values (0.9) mean the AI prioritizes its long-term training; low values (0.1) mean it is easily influenced by recent chats.</p>
                 </div>
                 
                 <div class="flex justify-end">
                     <button id="btn-save-gov-settings" class="px-5 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">
                        Save Configuration
                     </button>
                 </div>
             </div>
        </div>

        <div class="space-y-6">
            <section>
                <div class="flex items-center justify-between mb-3">
                     <h4 class="text-lg font-semibold">Members</h4>
                     <span class="text-xs text-neutral-500 bg-neutral-100 dark:bg-neutral-800 px-2 py-1 rounded-full" id="member-count-badge">...</span>
                </div>
                <div id="org-members-table-container" class="bg-white dark:bg-neutral-900 rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden min-h-[100px]">
                     <div class="p-8 text-center text-neutral-500">
                         <div class="animate-spin inline-block w-6 h-6 border-[3px] border-current border-t-transparent text-blue-600 rounded-full" role="status" aria-label="loading"></div>
                     </div>
                </div>
            </section>
        </div>
    `;

    // Attach Listeners

    // --- Org Name Editing ---
    const editBtn = document.getElementById('btn-edit-org-name');
    const saveBtn = document.getElementById('btn-save-org-name');
    const cancelBtn = document.getElementById('btn-cancel-org-name');
    const displayContainer = document.getElementById('org-name-display-container');
    const editContainer = document.getElementById('org-name-edit-container');
    const nameInput = document.getElementById('input-org-name');

    if (editBtn) {
        editBtn.addEventListener('click', () => {
            displayContainer.classList.add('hidden');
            editContainer.classList.remove('hidden');
            nameInput.focus();
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            editContainer.classList.add('hidden');
            displayContainer.classList.remove('hidden');
            nameInput.value = org.name; // Reset
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            const newName = nameInput.value.trim();
            if (!newName) return ui.showToast("Name cannot be empty", "error");
            if (newName === org.name) {
                cancelBtn.click();
                return;
            }

            // UI Loading state
            nameInput.disabled = true;
            saveBtn.disabled = true;

            try {
                const res = await api.updateOrganization(org.id, { name: newName });
                if (res && (res.ok || res.status === 'updated')) {
                    ui.showToast("Organization renamed!", "success");
                    renderSettingsOrganizationTab(); // Full Refresh
                } else {
                    throw new Error(res.error || "Update failed");
                }
            } catch (e) {
                ui.showToast(e.message, "error");
                nameInput.disabled = false;
                saveBtn.disabled = false;
            }
        });
    }

    // --- Domain Verification ---
    const startBtn = document.getElementById('btn-start-verify');
    if (startBtn) {
        startBtn.addEventListener('click', async () => {
            const domain = document.getElementById('domain-verify-input').value.trim();
            if (!domain) return ui.showToast("Please enter a domain", "error");

            startBtn.disabled = true;
            startBtn.textContent = "...";
            try {
                const res = await api.startDomainVerification(startBtn.dataset.orgId, domain);
                if (res && res.status === 'pending') {
                    ui.showToast("Verification started!", "success");
                    renderSettingsOrganizationTab(); // Refresh
                }
            } catch (e) {
                ui.showToast(e.message, "error");
                startBtn.disabled = false;
                startBtn.textContent = "Verify";
            }
        });
    }

    const checkBtn = document.getElementById('btn-check-verify');
    if (checkBtn) {
        checkBtn.addEventListener('click', async () => {
            checkBtn.disabled = true;
            checkBtn.textContent = "Checking...";
            try {
                const res = await api.checkDomainVerification(checkBtn.dataset.orgId);
                if (res && res.status === 'verified') {
                    ui.showToast("Domain Verified!", "success");
                    renderSettingsOrganizationTab(); // Refresh
                } else {
                    ui.showToast("TXT record not found yet. It may take a few minutes.", "warning");
                    checkBtn.disabled = false;
                    checkBtn.textContent = "Check Again";
                }
            } catch (e) {
                ui.showToast(e.message, "error");
                checkBtn.disabled = false;
                checkBtn.textContent = "Check Again";
            }
        });
    }

    const cancelVerifyBtn = document.getElementById('btn-cancel-verify');
    if (cancelVerifyBtn) {
        cancelVerifyBtn.addEventListener('click', async () => {
            if (!confirm("Are you sure you want to cancel the verification process? This will remove the TXT record requirement.")) return;

            cancelVerifyBtn.disabled = true;
            try {
                const res = await api.cancelDomainVerification(cancelVerifyBtn.dataset.orgId);
                if (res && (res.status === 'cancelled' || res.ok)) {
                    ui.showToast("Verification cancelled", "success");
                    renderSettingsOrganizationTab(); // Refresh
                } else {
                    throw new Error(res.error || "Cancellation failed");
                }
            } catch (e) {
                ui.showToast(e.message, "error");
                cancelVerifyBtn.disabled = false;
            }
        });
    }

    // --- Governance Settings ---
    const slGov = document.getElementById('sl-gov-weight');
    const lblGov = document.getElementById('lbl-gov-weight');
    const slBeta = document.getElementById('sl-spirit-beta');
    const lblBeta = document.getElementById('lbl-spirit-beta');
    const btnSaveGov = document.getElementById('btn-save-gov-settings');

    if (slGov && lblGov) {
        slGov.addEventListener('input', (e) => {
            lblGov.textContent = `${e.target.value}%`;
        });
    }

    if (slBeta && lblBeta) {
        slBeta.addEventListener('input', (e) => {
            const val = (parseInt(e.target.value) / 100).toFixed(2);
            lblBeta.textContent = val;
        });
    }

    if (btnSaveGov) {
        btnSaveGov.addEventListener('click', async () => {
            btnSaveGov.disabled = true;
            btnSaveGov.textContent = "Saving...";

            const settings = {
                governance_split: parseInt(slGov.value) / 100,
                spirit_beta: parseFloat((parseInt(slBeta.value) / 100).toFixed(2))
            };

            try {
                const res = await api.updateOrganization(org.id, { settings });
                if (res && (res.ok || res.status === 'updated')) {
                    ui.showToast("Governance settings saved!", "success");
                    // Update local org object reference potentially, or just wait for reload
                } else {
                    throw new Error(res.error || "Save failed");
                }
            } catch (e) {
                ui.showToast(e.message, "error");
            } finally {
                btnSaveGov.disabled = false;
                btnSaveGov.textContent = "Save Configuration";
            }
        });
    }

    // --- Load Members ---
    loadOrganizationMembers(org.id);
}

async function loadOrganizationMembers(orgId) {
    const container = document.getElementById('org-members-table-container');
    const countBadge = document.getElementById('member-count-badge');
    if (!container) return;

    try {
        const res = await api.getOrganizationMembers(orgId);
        if (res && res.members) {
            renderMembersTable(container, res.members, orgId);
            if (countBadge) countBadge.textContent = `${res.members.length} Users`;
        } else {
            container.innerHTML = `<div class="p-4 text-center text-red-500">Failed to load members</div>`;
        }
    } catch (e) {
        console.error("Error loading members:", e);
        // Only show error if we are admin/editor having expected access, otherwise it might just be Forbidden
        container.innerHTML = `<div class="p-4 text-center text-neutral-400 text-sm">Unable to view member list.</div>`;
    }
}

function renderMembersTable(container, members, orgId) {
    if (!members.length) {
        container.innerHTML = `<div class="p-8 text-center text-neutral-500">No members found.</div>`;
        return;
    }

    const rows = members.map(m => {
        // Can edit? Only admins can edit others.
        // We assume the current user is admin if they can see this, but let's be safe.
        // Also, you can't edit your OWN role usually to prevent lockout, or maybe you can?
        // Let's allow editing everyone for now, backend enforces permission.

        const isSelf = (currentUser && m.id === currentUser.id);
        const roleOptions = ['admin', 'editor', 'auditor', 'member'].map(r =>
            `<option value="${r}" ${m.role === r ? 'selected' : ''}>${r.charAt(0).toUpperCase() + r.slice(1)}</option>`
        ).join('');

        return `
            <tr class="border-b border-neutral-100 dark:border-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors">
                <td class="px-4 py-3">
                    <div class="font-medium text-neutral-900 dark:text-neutral-100">${m.name || 'Unknown'}</div>
                    <div class="text-xs text-neutral-500">${m.email || ''}</div>
                </td>
                <td class="px-4 py-3">
                     <select class="role-select bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 text-xs rounded px-2 py-1 outline-none focus:border-blue-500"
                             data-user-id="${m.id}"
                             ${isSelf ? 'disabled title="You cannot change your own role"' : ''}>
                         ${roleOptions}
                     </select>
                </td>
                <td class="px-4 py-3 text-right">
                    ${!isSelf ? `
                        <button class="btn-remove-member text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/30 p-1 rounded transition-colors"
                            data-user-id="${m.id}" title="Remove from Organization">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    ` : ''}
                </td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <table class="w-full text-left border-collapse">
            <thead>
                <tr class="text-xs text-neutral-500 border-b border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
                    <th class="px-4 py-2 font-medium">User</th>
                    <th class="px-4 py-2 font-medium">Role</th>
                    <th class="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    // Attach Change Listeners
    container.querySelectorAll('.role-select').forEach(select => {
        select.addEventListener('change', async (e) => {
            const userId = e.target.dataset.userId;
            const newRole = e.target.value;
            const originalRole = Array.from(e.target.options).find(o => o.defaultSelected)?.value || newRole;

            e.target.disabled = true; // Lock during update

            try {
                const res = await api.updateMemberRole(orgId, userId, newRole);
                if (res && (res.status === 'updated' || res.ok)) {
                    ui.showToast(`Role updated to ${newRole}`, "success");
                    e.target.disabled = false;
                    // Update defaultSelected to current
                    Array.from(e.target.options).forEach(o => o.defaultSelected = (o.value === newRole));
                } else {
                    throw new Error(res.error || "Update failed");
                }
            } catch (err) {
                ui.showToast(err.message, "error");
                e.target.value = originalRole; // Revert
                e.target.disabled = false;
            }
        });
    });

    // Attach Remove Listeners
    container.querySelectorAll('.btn-remove-member').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            if (!confirm("Are you sure you want to remove this member from the organization?")) return;
            const userId = e.currentTarget.dataset.userId; // Use currentTarget for button

            try {
                const res = await api.removeMember(orgId, userId);
                if (res && (res.status === 'removed' || res.ok)) {
                    ui.showToast("Member removed", "success");
                    // Reload list
                    loadOrganizationMembers(orgId);
                } else {
                    throw new Error(res.error || "Removal failed");
                }
            } catch (err) {
                ui.showToast(err.message, "error");
            }
        });
    });
}
