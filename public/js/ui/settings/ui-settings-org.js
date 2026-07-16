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

        const charterRes = await api.getCharter(org.id).catch(() => null);
        const charter = charterRes ? charterRes.charter : null;

        renderOrganizationUI(container, org, charter);

    } catch (error) {
        container.innerHTML = `<p class="text-red-500">Error loading organization: ${error.message}</p>`;
    }
}


function renderOrganizationUI(container, org, charter) {
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
                             <button id="btn-check-verify" data-org-id="${org.id}" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition-colors">
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
                             <button id="btn-start-verify" data-org-id="${org.id}" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold whitespace-nowrap transition-colors">
                                Verify
                             </button>
                        </div>
                      `
        }
            </div>
        `;

    const charterValuesData = charter ? (charter.core_values || []) : [];

    container.innerHTML = `
        <div class="settings-page-header">
            <h1>Organization</h1>
            <p>Your organization's identity, charter, domain, and members — applied across all agents.</p>
        </div>

        <div class="settings-card">
            <div class="flex items-center justify-between">
                <div id="org-name-display-container" class="group flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0">
                    <h3 class="text-2xl font-bold text-neutral-900 dark:text-white">
                        ${org.name}
                    </h3>
                    <button id="btn-edit-org-name" class="p-1 text-gray-400 hover:text-green-600 rounded opacity-0 group-hover:opacity-100 transition-opacity shrink-0" title="Rename Organization">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
                    </button>
                    <div class="flex items-center gap-2 text-sm text-neutral-500 min-w-0 w-full sm:w-auto">
                        <span class="shrink-0">ID:</span>
                        <code class="bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded select-all break-all min-w-0">${org.id}</code>
                    </div>
                </div>

                <div id="org-name-edit-container" class="hidden flex items-center gap-2 w-full max-w-md">
                    <input type="text" id="input-org-name" value="${org.name}" class="flex-1 px-3 py-2 bg-gray-50 dark:bg-neutral-800 border border-gray-300 dark:border-neutral-700 rounded-lg focus:ring-2 focus:ring-green-500 outline-none">
                    <button id="btn-save-org-name" class="p-2 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/30 rounded-lg">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                    </button>
                    <button id="btn-cancel-org-name" class="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
            </div>
        </div>

        <!-- CHARTER SECTION -->
        <div class="settings-card">
            <div class="flex items-start justify-between mb-4">
                <div>
                    <h4 class="text-lg font-semibold">Organization Identity / Charter</h4>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 max-w-xl">The mission and core values of your organization. Once set, it applies to all agents. This will force all agents to speak with your brand and culture.</p>
                </div>
                ${charter
                    ? '<span class="px-2.5 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs font-semibold rounded-full mt-1 shrink-0">Active</span>'
                    : '<span class="px-2.5 py-1 bg-gray-100 dark:bg-neutral-800 text-gray-500 text-xs font-semibold rounded-full mt-1 shrink-0">Not set</span>'
                }
            </div>

            <div class="space-y-5">
                <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Mission</label>
                    <textarea id="charter-mission" rows="3"
                        class="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg focus:ring-2 focus:ring-green-500 outline-none resize-none"
                        placeholder="Why your organization exists and what it stands for..."
                    >${charter ? (charter.mission || '') : ''}</textarea>
                </div>

                <div>
                    <div class="flex items-center justify-between mb-3">
                        <label class="text-sm font-medium text-gray-700 dark:text-gray-300">Core Values & Rubrics</label>
                        <div class="flex items-center gap-2">
                            <button id="btn-gen-charter-values" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                                Generate Values
                            </button>
                            <button id="btn-add-charter-value" class="text-xs text-green-600 dark:text-green-400 border border-green-300 dark:border-green-700 hover:bg-green-50 dark:hover:bg-green-900/20 px-3 py-1.5 rounded-full flex items-center gap-1 transition-colors">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                                Add value
                            </button>
                        </div>
                    </div>
                    <div id="charter-values-list" class="space-y-4"></div>
                </div>

                <div class="flex items-center justify-between pt-2">
                    ${charter
                        ? `<button id="btn-delete-charter" class="text-sm text-red-500 hover:text-red-600 hover:underline">Delete charter</button>`
                        : '<span></span>'
                    }
                    <button id="btn-save-charter" class="px-5 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg transition-colors">
                        Save Charter
                    </button>
                </div>
            </div>
        </div>

        ${verificationSection}

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-4">AI Governance Configuration</h4>
             
             <div class="space-y-8">
                 <!-- Charter vs Policy Slider -->
                 <div>
                      <div class="flex justify-between items-end mb-2">
                          <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Charter vs Policy weighting</label>
                          <span id="lbl-gov-weight" class="text-sm font-mono bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
                            ${Math.round((org.settings?.governance_split ?? 0.40) * 100)}%
                          </span>
                      </div>
                      <input type="range" id="sl-gov-weight" min="0" max="100" value="${Math.round((org.settings?.governance_split ?? 0.40) * 100)}"
                        class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-green-600">
                      <div class="flex justify-between text-xs text-gray-500 mt-2">
                          <span>All Policy (0%)</span>
                          <span class="font-bold text-gray-400">Balanced (40%)</span>
                          <span>All Charter (100%)</span>
                      </div>
                      <p class="text-xs text-gray-500 mt-2">How much of an agent's scored values come from your organization's Charter vs the business-unit Policy. Shown value is the Charter's share.</p>
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

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">Identity &amp; Sessions</h4>
             <p class="text-xs text-gray-500 mb-4">How members join and how long their sessions live. Changes are journaled to the auth events log. Sessions are revocable server-side — removing a member or changing a role ends their access on the next request.</p>
             <div class="grid md:grid-cols-3 gap-4">
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Join policy</span>
                     <select id="sel-join-policy" class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                         <option value="domain_auto_join">Domain auto-join</option>
                         <option value="invite_only">Invite only</option>
                         <option value="both">Invites + domain auto-join</option>
                     </select>
                     <span class="block text-xs text-gray-400 mt-1">Auto-join admits every account on your verified domain, including contractors and shared mailboxes.</span>
                 </label>
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Idle timeout (minutes)</span>
                     <input type="number" id="inp-idle-timeout" min="5" max="43200" placeholder="platform default: 10080"
                         class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                     <span class="block text-xs text-gray-400 mt-1">Regulated orgs typically use 30.</span>
                 </label>
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Session lifetime (hours)</span>
                     <input type="number" id="inp-session-lifetime" min="1" max="720" placeholder="platform default: 720"
                         class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                     <span class="block text-xs text-gray-400 mt-1">Absolute cap; forces a fresh IdP login. Regulated orgs typically use 12.</span>
                 </label>
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Require MFA</span>
                     <select id="sel-require-mfa" class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                         <option value="false">Off</option>
                         <option value="true">Required for local accounts</option>
                     </select>
                     <span class="block text-xs text-gray-400 mt-1">Password accounts must enroll an authenticator app before using SAFi. SSO accounts should enforce MFA at your identity provider.</span>
                 </label>
             </div>
             <div class="flex justify-end mt-4">
                 <button id="btn-save-identity" class="px-5 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">Save Identity Settings</button>
             </div>
        </div>

        <div class="settings-card">
            <section>
                <div class="flex items-center justify-between mb-3">
                     <h4 class="text-lg font-semibold">Members</h4>
                     <span class="text-xs text-neutral-500 bg-neutral-100 dark:bg-neutral-800 px-2 py-1 rounded-full" id="member-count-badge">...</span>
                </div>
                <div id="org-members-table-container" class="bg-white dark:bg-neutral-900 rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden min-h-[100px]">
                     <div class="p-8 text-center text-neutral-500">
                         <div class="animate-spin inline-block w-6 h-6 border-[3px] border-current border-t-transparent text-green-600 rounded-full" role="status" aria-label="loading"></div>
                     </div>
                </div>
                <div class="border-t border-gray-200 dark:border-neutral-700 pt-4 mt-4">
                    <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Invite a member</span>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                        <input type="email" id="inp-invite-email" placeholder="person@company.com"
                            class="flex-1 min-w-[200px] rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                        <select id="sel-invite-role" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                            <option value="member">member</option>
                            <option value="auditor">auditor</option>
                            <option value="editor">editor</option>
                            <option value="admin">admin</option>
                        </select>
                        <button id="btn-send-invite" class="px-4 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold">Invite</button>
                    </div>
                    <p class="text-xs text-gray-400 mt-1">No email is sent — share the app link yourself. The invite is applied automatically when that address signs in (Google or Microsoft), regardless of join policy. Expires after 14 days.</p>
                    <div id="pending-invites-list" class="mt-3 text-sm text-gray-500"></div>
                </div>
            </section>
        </div>
    `;

    // Attach Listeners

    // --- Charter ---
    const valuesList = document.getElementById('charter-values-list');
    renderCharterValues(charterValuesData, valuesList);

    document.getElementById('btn-gen-charter-values')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const mission = document.getElementById('charter-mission')?.value.trim() || org.name;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Generating...`;
        btn.disabled = true;
        try {
            const res = await api.generatePolicyContent('values', mission);
            if (res.ok && res.content) {
                let json = typeof res.content === 'string' ? JSON.parse(res.content.trim()) : res.content;
                if (!Array.isArray(json)) json = [json];
                charterValuesData.length = 0;
                json.forEach(v => charterValuesData.push({ ...v, weight: v.weight || 1.0 }));
                renderCharterValues(charterValuesData, valuesList);
                ui.showToast('Values generated!', 'success');
            }
        } catch (err) {
            ui.showToast('Generation failed — try again', 'error');
        }
        btn.innerHTML = original;
        btn.disabled = false;
    });

    document.getElementById('btn-add-charter-value')?.addEventListener('click', () => {
        charterValuesData.push({ name: '', description: '', weight: 1.0, hard_gate: false, rubric: { scoring_guide: [] } });
        renderCharterValues(charterValuesData, valuesList);
    });

    document.getElementById('btn-save-charter')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-save-charter');
        const mission = document.getElementById('charter-mission')?.value.trim() || '';
        btn.disabled = true;
        btn.textContent = 'Saving...';
        try {
            const res = await api.saveCharter(org.id, { mission, core_values: charterValuesData.filter(v => v.name) });
            if (res && res.status === 'saved') {
                ui.showToast('Charter saved', 'success');
                renderSettingsOrganizationTab();
            } else {
                throw new Error(res.error || 'Save failed');
            }
        } catch (e) {
            ui.showToast(e.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Save Charter';
        }
    });

    document.getElementById('btn-delete-charter')?.addEventListener('click', async () => {
        if (!confirm('Delete the organizational charter? This cannot be undone.')) return;
        try {
            const res = await api.deleteCharter(org.id);
            if (res && res.status === 'deleted') {
                ui.showToast('Charter deleted', 'success');
                renderSettingsOrganizationTab();
            }
        } catch (e) {
            ui.showToast(e.message, 'error');
        }
    });

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

    // --- Identity & Sessions ---
    const selPolicy = container.querySelector('#sel-join-policy');
    if (selPolicy) {
        api.getOrgIdentity(org.id).then(cfg => {
            selPolicy.value = cfg.join_policy || 'domain_auto_join';
            container.querySelector('#inp-idle-timeout').value = cfg.idle_timeout_minutes ?? '';
            container.querySelector('#inp-session-lifetime').value = cfg.session_lifetime_hours ?? '';
            container.querySelector('#sel-require-mfa').value = String(!!cfg.require_mfa);
        }).catch(() => {});
        container.querySelector('#btn-save-identity').addEventListener('click', async () => {
            const idleRaw = container.querySelector('#inp-idle-timeout').value;
            const lifeRaw = container.querySelector('#inp-session-lifetime').value;
            try {
                await api.updateOrgIdentity(org.id, {
                    join_policy: selPolicy.value,
                    idle_timeout_minutes: idleRaw ? parseInt(idleRaw) : null,
                    session_lifetime_hours: lifeRaw ? parseInt(lifeRaw) : null,
                    require_mfa: container.querySelector('#sel-require-mfa').value === 'true',
                });
                ui.showToast('Identity settings saved', 'success');
            } catch (e) {
                ui.showToast(e.message || 'Save failed', 'error');
            }
        });
    }

    // --- Invitations ---
    const btnInvite = container.querySelector('#btn-send-invite');
    if (btnInvite) {
        btnInvite.addEventListener('click', async () => {
            const email = container.querySelector('#inp-invite-email').value.trim();
            if (!email) { ui.showToast('Enter an email address', 'error'); return; }
            try {
                const res = await api.createInvitation(org.id, email, container.querySelector('#sel-invite-role').value);
                ui.showToast(res.invitation?.external_domain
                    ? 'Invite created (outside your verified domain) — no email is sent; it applies when they sign in'
                    : 'Invite created — no email is sent; it applies when they sign in', 'success');
                container.querySelector('#inp-invite-email').value = '';
                loadPendingInvites(org.id);
            } catch (e) {
                ui.showToast(e.message || 'Invite failed', 'error');
            }
        });
        loadPendingInvites(org.id);
    }

    // --- Load Members ---
    // (Retention, legal hold, examiner export, evidence log, and the provider
    // allow-list moved to the Compliance tab — ui-settings-compliance.js.)
    loadOrganizationMembers(org.id);
}

async function loadPendingInvites(orgId) {
    const el = document.getElementById('pending-invites-list');
    if (!el) return;
    try {
        const res = await api.listInvitations(orgId);
        const invites = res.invitations || [];
        if (!invites.length) { el.innerHTML = ''; return; }
        el.innerHTML = `<span class="text-xs font-bold text-gray-400 uppercase">Pending invites</span>` +
            invites.map(i => `
            <div class="flex items-center justify-between py-1.5 border-b border-gray-100 dark:border-neutral-800 last:border-0">
                <span>${i.email} <span class="text-xs text-gray-400">(${i.role}, expires ${new Date(i.expires_at).toLocaleDateString()})</span></span>
                <button data-invite="${i.id}" class="text-xs text-red-500 hover:underline">Revoke</button>
            </div>`).join('');
        el.querySelectorAll('[data-invite]').forEach(btn => btn.addEventListener('click', async () => {
            try {
                await api.revokeInvitation(orgId, btn.getAttribute('data-invite'));
                loadPendingInvites(orgId);
            } catch (e) {
                ui.showToast(e.message || 'Revoke failed', 'error');
            }
        }));
    } catch (e) {
        el.innerHTML = '';
    }
}

function renderCharterValues(valuesData, container) {
    if (!container) return;
    container.innerHTML = '';

    if (!valuesData.length) {
        container.innerHTML = `
            <div class="text-center py-10 bg-gray-50 dark:bg-neutral-900 rounded-xl border-2 border-dashed border-gray-200 dark:border-neutral-800">
                <p class="text-gray-400 mb-1">No values defined yet.</p>
                <p class="text-xs text-gray-400">Click <strong>Generate Values</strong> to let AI draft them from your mission.</p>
            </div>`;
        return;
    }

    valuesData.forEach((v, idx) => {
        if (!v.rubric) v.rubric = { scoring_guide: [] };
        if (Array.isArray(v.rubric)) v.rubric = { scoring_guide: v.rubric };
        if (!v.rubric.scoring_guide) v.rubric.scoring_guide = [];

        const hasRubric = v.rubric.scoring_guide.length > 0;
        const weightPct = v.weight <= 1.0 ? Math.round(v.weight * 100) : (v.weight || 100);

        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-5 shadow-sm';
        card.innerHTML = `
            <div class="flex items-start justify-between gap-4 mb-3">
                <input type="text" value="${v.name || ''}" placeholder="Value name (e.g. Integrity)"
                    class="cv-name flex-1 font-semibold text-base bg-transparent border-b border-transparent hover:border-gray-300 focus:border-green-500 outline-none text-gray-900 dark:text-white px-1 py-0.5 transition-all"/>
                <button class="btn-remove-cv p-1.5 text-gray-400 hover:text-red-500 rounded transition-colors shrink-0">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <textarea placeholder="Brief description of this value..." rows="2"
                class="cv-desc w-full text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 rounded-lg p-2.5 resize-none outline-none focus:border-green-500 mb-3">${v.description || ''}</textarea>

            <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
                <div class="flex items-center gap-2">
                    ${hasRubric
                        ? `<span class="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-0.5 rounded-full font-medium">✓ Rubric ready</span>`
                        : `<span class="text-xs bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 px-2 py-0.5 rounded-full font-medium">Needs rubric</span>`
                    }
                    <button class="btn-toggle-rubric text-xs text-blue-600 dark:text-blue-400 hover:underline">View / Edit Rubric</button>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                    <label class="flex items-center gap-2 cursor-pointer select-none bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800" title="If checked, any violation of this value blocks the response outright, regardless of other scores.">
                        <input type="checkbox" class="cv-hardgate accent-red-600 w-4 h-4" ${v.hard_gate ? 'checked' : ''}/>
                        <span class="text-xs uppercase font-bold text-gray-500">Non-negotiable</span>
                    </label>
                    <div class="flex items-center gap-2 bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800">
                        <label class="text-xs font-bold text-gray-500 uppercase">Weight</label>
                        <input type="range" min="1" max="100" value="${weightPct}" class="cv-weight-slider w-20 h-1.5 accent-green-600 cursor-pointer"/>
                        <span class="cv-weight-lbl text-xs font-mono font-bold text-gray-700 dark:text-gray-300 w-8 text-right">${weightPct}%</span>
                    </div>
                </div>
            </div>

            <div class="cv-rubric-panel hidden mt-4 pt-4 border-t border-dashed border-gray-200 dark:border-neutral-700 space-y-2">
                <p class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Scoring criteria (traffic light)</p>
                ${[
                    { score: 1.0,  icon: '✅', label: 'Positive (+1)', color: 'green',  bg: 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900' },
                    { score: 0.0,  icon: '⚪', label: 'Neutral (0)',   color: 'gray',   bg: 'bg-white dark:bg-neutral-800 border-gray-200 dark:border-neutral-700' },
                    { score: -1.0, icon: '🚫', label: 'Violation (−1)', color: 'red',   bg: 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900' }
                ].map(def => {
                    const item = v.rubric.scoring_guide.find(g => Math.abs(g.score - def.score) < 0.1);
                    const text = item ? (item.criteria || item.descriptor || '') : '';
                    return `
                        <div class="flex gap-3 items-start">
                            <span class="w-28 shrink-0 text-xs font-bold text-gray-500 pt-2.5 text-right">${def.icon} ${def.label}</span>
                            <textarea data-score="${def.score}" rows="2"
                                class="cv-rubric-text flex-1 text-sm p-2.5 rounded-lg border resize-none outline-none focus:ring-2 focus:ring-green-500 ${def.bg}"
                                placeholder="Describe this outcome...">${text}</textarea>
                        </div>`;
                }).join('')}
            </div>
        `;

        container.appendChild(card);

        // Bind name/description changes
        card.querySelector('.cv-name').addEventListener('input', e => { valuesData[idx].name = e.target.value; });
        card.querySelector('.cv-desc').addEventListener('input', e => { valuesData[idx].description = e.target.value; });

        // Weight slider
        const slider = card.querySelector('.cv-weight-slider');
        const lbl    = card.querySelector('.cv-weight-lbl');
        slider.addEventListener('input', e => {
            const pct = parseInt(e.target.value);
            valuesData[idx].weight = pct / 100;
            lbl.textContent = pct + '%';
        });

        // Non-negotiable (hard gate) toggle
        const hgToggle = card.querySelector('.cv-hardgate');
        if (hgToggle) {
            hgToggle.addEventListener('change', e => { valuesData[idx].hard_gate = !!e.target.checked; });
        }

        // Rubric toggle
        const rubricPanel = card.querySelector('.cv-rubric-panel');
        card.querySelector('.btn-toggle-rubric').addEventListener('click', () => rubricPanel.classList.toggle('hidden'));

        // Rubric text changes
        card.querySelectorAll('.cv-rubric-text').forEach(ta => {
            ta.addEventListener('input', e => {
                const score = parseFloat(e.target.dataset.score);
                const text  = e.target.value.trim();
                valuesData[idx].rubric.scoring_guide = valuesData[idx].rubric.scoring_guide.filter(g => Math.abs(g.score - score) >= 0.1);
                if (text) valuesData[idx].rubric.scoring_guide.push({ score, criteria: text });
            });
        });

        // Remove
        card.querySelector('.btn-remove-cv').addEventListener('click', () => {
            valuesData.splice(idx, 1);
            renderCharterValues(valuesData, container);
        });
    });
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
