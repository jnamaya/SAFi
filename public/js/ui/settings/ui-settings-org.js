import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { loadToolCategories, renderToolGrid } from '../shared/tool-picker.js';

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
 * Renders the Org Settings tab, first in the Organization group
 * (historically "Organization Settings"). Admin only.
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

        // Two independent artifacts: an org may have either, both or neither.
        const [charterRes, standardsRes] = await Promise.all([
            api.getCharter(org.id).catch(() => null),
            api.getAiStandards(org.id).catch(() => null),
        ]);
        const charter = charterRes ? charterRes.charter : null;
        const aiStandards = standardsRes ? standardsRes.ai_standards : null;

        renderOrganizationUI(container, org, charter, aiStandards);

    } catch (error) {
        container.innerHTML = `<p class="text-red-500">Error loading organization: ${error.message}</p>`;
    }
}


function renderOrganizationUI(container, org, charter, aiStandards) {
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
            <div class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6">
                <h4 class="font-bold text-green-900 dark:text-green-100 mb-2">Verify Your Domain</h4>
                <p class="text-sm text-green-700 dark:text-green-300 mb-4">
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
    const structuralData = aiStandards ? { ...(aiStandards.structural_requirements || {}) } : {};
    const blacklistData = aiStandards ? [...(aiStandards.early_prompt_blacklist || [])] : [];
    const aiStandardsData = aiStandards ? [...(aiStandards.values || [])] : [];
    // null (not []) means "no org-wide tool cap". An empty array would read as
    // one, and authorized_tools treats empty as "does not narrow" anyway.
    let allowedToolsData = aiStandards && Array.isArray(aiStandards.allowed_tools)
        ? [...aiStandards.allowed_tools]
        : null;

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
                            <button id="btn-gen-charter-values" class="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
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

        <div class="settings-card">
            <div class="flex items-start justify-between gap-4 mb-1">
                <div>
                    <h4 class="text-lg font-semibold">AI Standards</h4>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 max-w-xl">Rules you want enforced on <strong>every agent</strong> in your organization &mdash; for example, never revealing personal information such as a social security or bank account number, and never sharing private company data. Optional &mdash; most organizations start with two or three.</p>
                </div>
                ${aiStandards
                    ? '<span class="px-2.5 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs font-semibold rounded-full mt-1 shrink-0">Active</span>'
                    : '<span class="px-2.5 py-1 bg-gray-100 dark:bg-neutral-800 text-gray-500 text-xs font-semibold rounded-full mt-1 shrink-0">Not set</span>'
                }
            </div>

            <div class="space-y-5 mt-4">
                <div>
                    <div class="flex items-center justify-end mb-3">
                        <div class="flex items-center gap-2">
                            <button id="btn-gen-ai-standards" class="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                                Suggest standards
                            </button>
                            <button id="btn-add-ai-standard" class="text-xs text-green-600 dark:text-green-400 border border-green-300 dark:border-green-700 hover:bg-green-50 dark:hover:bg-green-900/20 px-3 py-1.5 rounded-full transition-colors">Add standard</button>
                        </div>
                    </div>
                    <p class="text-xs text-gray-500 -mt-2 mb-3">Each one is judged by the auditor on <em>every</em> response, so each needs criteria it can actually apply. Tick <strong>Non-negotiable</strong> only for absolutes &mdash; any violation then blocks the response outright, however well it scores elsewhere, and several of them make ordinary answers more likely to be stopped.</p>
                    <div id="ai-standards-list" class="space-y-4"></div>
                </div>

                <!-- Deterministic Will checks: no model involved in any of these. -->
                <div class="border-t border-gray-200 dark:border-neutral-700 pt-5">
                    <p class="text-xs text-gray-500 mb-4">A business-unit policy can add to these but cannot switch them off.</p>

                    <div class="space-y-5">
                        <div class="p-4 rounded-xl border border-green-200 dark:border-green-900/40 bg-green-50/50 dark:bg-green-900/10">
                            <label class="flex items-center gap-2 cursor-pointer select-none">
                                <input type="checkbox" id="charter-require-disclaimer" class="accent-green-600 w-4 h-4"
                                    ${structuralData.require_disclaimer ? 'checked' : ''}>
                                <span class="text-sm font-semibold text-green-800 dark:text-green-200">Require a disclaimer on every response</span>
                            </label>
                            <input type="text" id="charter-disclaimer-text"
                                class="w-full mt-3 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-green-200 dark:border-green-900/50 rounded-lg focus:ring-2 focus:ring-green-500 outline-none"
                                placeholder="Disclaimer: this response was generated by AI."
                                value="${escapeHtml(structuralData.mandatory_disclaimer_substring || '')}">
                            <p class="text-xs text-gray-500 mt-2">Matched as a case-sensitive substring, so keep it short and stable. <strong>This replaces any disclaimer set by a business-unit policy</strong> — only one can be checked, and the organization's is the one enforced.</p>
                        </div>

                        <div class="p-4 rounded-xl border border-amber-200 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10">
                            <h5 class="text-sm font-semibold text-amber-800 dark:text-amber-200">Blocked phrases</h5>
                            <p class="text-xs text-gray-500 mt-0.5 mb-3">Checked against every message <em>before</em> any agent runs. Matching is literal and case-insensitive, so keep phrases short and distinctive. Added to whatever each policy blocks.</p>
                            <div class="flex gap-2 mb-3">
                                <input type="text" id="charter-blacklist-input"
                                    class="flex-1 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-amber-200 dark:border-amber-900/50 rounded-lg focus:ring-2 focus:ring-amber-500 outline-none"
                                    placeholder="e.g. insider trading tips">
                                <button id="charter-add-blacklist" class="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-semibold transition-colors">Add</button>
                            </div>
                            <ul id="charter-blacklist-list" class="space-y-2"></ul>
                        </div>

                        <div class="p-4 rounded-xl border border-gray-200 dark:border-neutral-700">
                            <h5 class="text-sm font-semibold text-gray-700 dark:text-gray-200">Minimum alignment score</h5>
                            <p class="text-xs text-gray-500 mt-0.5 mb-3">Responses scoring below this are blocked. A policy may demand a higher score, never a lower one. Leave blank for no organization-wide floor.</p>
                            <input type="number" id="charter-alignment-threshold" min="0" max="1" step="0.05"
                                class="w-32 px-3 py-2 text-sm bg-gray-50 dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg focus:ring-2 focus:ring-green-500 outline-none"
                                placeholder="none"
                                value="${structuralData.alignment_score_threshold ?? ''}">
                        </div>

                        <div class="p-4 rounded-xl border border-green-200 dark:border-green-900/40 bg-green-50/50 dark:bg-green-900/10">
                            <label class="flex items-center gap-2 cursor-pointer select-none">
                                <input type="checkbox" id="charter-restrict-tools" class="accent-green-600 w-4 h-4"
                                    ${allowedToolsData ? 'checked' : ''}>
                                <span class="text-sm font-semibold text-green-800 dark:text-green-200">Limit which tools any agent may use</span>
                            </label>
                            <p class="text-xs text-gray-500 mt-1.5">Off means the organization sets no limit and each policy decides. On means <strong>only</strong> the tools ticked here are available anywhere — a policy can narrow further but cannot add one back.</p>
                            <div id="charter-tools-panel" class="mt-3 ${allowedToolsData ? '' : 'hidden'}">
                                <p id="charter-tools-loading" class="text-xs text-gray-500">Loading tools...</p>
                                <div id="charter-tools-grid" class="hidden"></div>
                            </div>
                        </div>
                    </div>
                </div>


                <div class="flex items-center justify-between pt-2">
                    ${aiStandards
                        ? `<button id="btn-delete-ai-standards" class="text-sm text-red-500 hover:text-red-600 hover:underline">Delete AI standards</button>`
                        : '<span></span>'
                    }
                    <button id="btn-save-ai-standards" class="px-5 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg transition-colors">
                        Save AI Standards
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
                          <span id="lbl-spirit-beta" class="text-sm font-mono bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
                            ${(org.settings?.spirit_beta ?? 0.90)}
                          </span>
                      </div>
                      <input type="range" id="sl-spirit-beta" min="10" max="99" value="${Math.round((org.settings?.spirit_beta ?? 0.90) * 100)}" 
                        class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-green-600">
                      <div class="flex justify-between text-xs text-gray-500 mt-2">
                          <span>Short Term (Adapts Fast)</span>
                          <span class="font-bold text-gray-400">Balanced</span>
                          <span>Long Term (Resists Change)</span>
                      </div>
                      <p class="text-xs text-gray-500 mt-2">Determines the weight of history. High values (0.9) mean the AI prioritizes its long-term training; low values (0.1) mean it is easily influenced by recent conversations.</p>
                 </div>
                 
                 <div class="flex justify-end">
                     <button id="btn-save-gov-settings" class="px-5 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">
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
                         <option value="true">Required</option>
                     </select>
                     <span class="block text-xs text-gray-400 mt-1">Password accounts must enroll an authenticator app. Microsoft sign-ins must present MFA evidence (amr) from Entra. Google MFA is enforced at Workspace.</span>
                 </label>
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Microsoft tenant ID</span>
                     <input type="text" id="inp-ms-tenant" placeholder="not restricted" spellcheck="false"
                         class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm font-mono">
                     <span class="block text-xs text-gray-400 mt-1">Entra directory (tenant) GUID. When set, only Microsoft sign-ins from this tenant are accepted — a wrong value locks out Microsoft logins.</span>
                 </label>
                 <label class="block">
                     <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Google Workspace domain</span>
                     <input type="text" id="inp-google-hd" placeholder="not restricted" spellcheck="false"
                         class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm font-mono">
                     <span class="block text-xs text-gray-400 mt-1">When set, only Google sign-ins from this Workspace domain are accepted; consumer Gmail accounts are rejected.</span>
                 </label>
             </div>
             <div class="flex justify-end mt-4">
                 <button id="btn-save-identity" class="px-5 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">Save Identity Settings</button>
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
                        <button id="btn-send-invite" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold">Invite</button>
                    </div>
                    <p class="text-xs text-gray-400 mt-1">No email is sent — share the app link yourself. The invite is applied automatically when that address signs in (Google or Microsoft), regardless of join policy. Expires after 14 days.</p>
                    <div id="pending-invites-list" class="mt-3 text-sm text-gray-500"></div>
                </div>
            </section>
        </div>

        ${(currentUser && currentUser.role === 'admin') ? `
        <div class="settings-card">
            <section>
                <div class="flex items-center justify-between mb-3">
                     <h4 class="text-lg font-semibold">Groups</h4>
                     <span class="text-xs text-neutral-500 bg-neutral-100 dark:bg-neutral-800 px-2 py-1 rounded-full" id="group-count-badge">...</span>
                </div>
                <p class="text-xs text-gray-400 mb-3">Groups collect members for agent sharing. Sharing an agent with a group lets every member of that group use it in chat.</p>
                <div id="org-groups-list" class="bg-white dark:bg-neutral-900 rounded-lg border border-neutral-200 dark:border-neutral-800 overflow-hidden min-h-[60px]">
                     <div class="p-6 text-center text-neutral-500">
                         <div class="animate-spin inline-block w-6 h-6 border-[3px] border-current border-t-transparent text-green-600 rounded-full" role="status" aria-label="loading"></div>
                     </div>
                </div>
                <div class="border-t border-gray-200 dark:border-neutral-700 pt-4 mt-4">
                    <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Create a group</span>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                        <input type="text" id="inp-group-name" placeholder="e.g. Finance team" maxlength="100"
                            class="flex-1 min-w-[200px] rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                        <button id="btn-create-group" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold">Create</button>
                    </div>
                </div>
            </section>
        </div>
        ` : ''}
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

    // --- Org-wide rules: blocked phrases ---
    const renderCharterBlacklist = () => {
        const list = document.getElementById('charter-blacklist-list');
        if (!list) return;
        if (!blacklistData.length) {
            list.innerHTML = `<li class="text-xs text-gray-400 italic py-1">None yet.</li>`;
            return;
        }
        list.innerHTML = blacklistData.map((p, i) => `
            <li class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-white dark:bg-neutral-900 border border-amber-100 dark:border-amber-900/30">
                <span class="text-sm text-gray-800 dark:text-gray-200 break-all">${escapeHtml(p)}</span>
                <button data-blacklist-remove="${i}" class="text-red-500 hover:text-red-600 text-xs font-semibold shrink-0">Remove</button>
            </li>`).join('');
        list.querySelectorAll('[data-blacklist-remove]').forEach(btn => {
            btn.addEventListener('click', () => {
                blacklistData.splice(Number(btn.dataset.blacklistRemove), 1);
                renderCharterBlacklist();
            });
        });
    };
    renderCharterBlacklist();

    const addCharterPhrase = () => {
        const input = document.getElementById('charter-blacklist-input');
        const val = input?.value.trim();
        if (!val) return;
        if (!blacklistData.includes(val)) blacklistData.push(val);
        input.value = '';
        renderCharterBlacklist();
    };
    document.getElementById('charter-add-blacklist')?.addEventListener('click', addCharterPhrase);
    document.getElementById('charter-blacklist-input')?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); addCharterPhrase(); }
    });

    // --- Org-wide rules: tool cap ---
    const toolsToggle = document.getElementById('charter-restrict-tools');
    const toolsPanel = document.getElementById('charter-tools-panel');
    let toolsLoaded = false;

    const loadCharterTools = async () => {
        if (toolsLoaded) return;
        toolsLoaded = true;
        const categories = await loadToolCategories();
        const loading = document.getElementById('charter-tools-loading');
        const grid = document.getElementById('charter-tools-grid');
        if (!grid) return;                       // tab navigated away mid-load
        if (!categories) {
            if (loading) loading.textContent = 'Failed to load tools.';
            toolsLoaded = false;                 // let a reopen retry
            return;
        }
        if (loading) loading.classList.add('hidden');
        grid.classList.remove('hidden');
        renderToolGrid(grid, {
            categories,
            isSelected: (id) => Array.isArray(allowedToolsData) && allowedToolsData.includes(id),
            onToggle: (id, on) => {
                if (!Array.isArray(allowedToolsData)) allowedToolsData = [];
                const at = allowedToolsData.indexOf(id);
                if (on && at < 0) allowedToolsData.push(id);
                if (!on && at >= 0) allowedToolsData.splice(at, 1);
            },
            collapsible: true,
        });
    };
    if (allowedToolsData) loadCharterTools();

    toolsToggle?.addEventListener('change', (e) => {
        if (e.target.checked) {
            allowedToolsData = Array.isArray(allowedToolsData) ? allowedToolsData : [];
            toolsPanel?.classList.remove('hidden');
            loadCharterTools();
        } else {
            // null, not [] — an empty list would still read as "a cap exists".
            allowedToolsData = null;
            toolsPanel?.classList.add('hidden');
        }
    });

    // --- AI Standards: non-negotiable standards list ---
    // Reuses the charter value editor: same shape (name, description, rubric),
    // and it already renders a hard gate with the weight slider disabled.
    function renderAiStandards() {
        const list = document.getElementById('ai-standards-list');
        if (!list) return;
        renderCharterValues(aiStandardsData, list, 'standard');
    }
    renderAiStandards();

    document.getElementById('btn-gen-ai-standards')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Suggesting...`;
        try {
            const ctx = [org.name, document.getElementById('charter-mission')?.value.trim()]
                .filter(Boolean).join(' — ') || 'General organization';
            const res = await api.generatePolicyContent('ai_standards', ctx);
            if (!res.ok || !res.content) throw new Error(res.error || 'Could not suggest standards.');
            let list = typeof res.content === 'string' ? JSON.parse(res.content.trim()) : res.content;
            if (!Array.isArray(list)) list = [list];

            // Appended, never replacing: these are suggestions on top of whatever
            // the admin has already written. Scored by default, like a
            // hand-added one — promoting a standard to blocking is a decision.
            const existing = new Set(aiStandardsData.map(v => String(v.name || '').trim().toLowerCase()));
            let added = 0;
            list.forEach(v => {
                const name = String(v.name || '').trim();
                if (!name || existing.has(name.toLowerCase())) return;
                existing.add(name.toLowerCase());
                aiStandardsData.push({
                    name,
                    description: v.description || '',
                    weight: 1,
                    hard_gate: false,
                    rubric: v.rubric || { scoring_guide: [] },
                });
                added++;
            });
            renderAiStandards();
            ui.showToast(
                added ? `${added} suggested. Edit them, then press Save AI Standards.`
                      : 'Nothing new suggested — these are already on the list.',
                added ? 'success' : 'warning', 6000);
        } catch (err) {
            ui.showToast(err.message || 'Could not suggest standards.', 'error');
        }
        btn.disabled = false;
        btn.innerHTML = original;
    });

    document.getElementById('btn-add-ai-standard')?.addEventListener('click', () => {
        aiStandardsData.push({ name: '', description: '', weight: 1, hard_gate: false, rubric: { scoring_guide: [] } });
        renderAiStandards();
    });

    document.getElementById('btn-save-ai-standards')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-save-ai-standards');
        const requireDisclaimer = !!document.getElementById('charter-require-disclaimer')?.checked;
        const disclaimerText = document.getElementById('charter-disclaimer-text')?.value.trim() || '';
        const thresholdRaw = document.getElementById('charter-alignment-threshold')?.value.trim() || '';

        // The server rejects these too; catching them here keeps the typed
        // values on screen instead of bouncing the whole form.
        if (requireDisclaimer && !disclaimerText) {
            ui.showToast('Enter the disclaimer text to check for, or untick the requirement.', 'error');
            return;
        }
        const structural = {};
        if (requireDisclaimer) {
            structural.require_disclaimer = true;
            structural.mandatory_disclaimer_substring = disclaimerText;
        }
        if (thresholdRaw !== '') {
            const t = Number(thresholdRaw);
            if (Number.isNaN(t) || t < 0 || t > 1) {
                ui.showToast('Minimum alignment score must be between 0 and 1.', 'error');
                return;
            }
            structural.alignment_score_threshold = t;
        }

        btn.disabled = true;
        btn.textContent = 'Saving...';
        try {
            const res = await api.saveAiStandards(org.id, {
                values: aiStandardsData.filter(v => v.name && v.name.trim()),
                structural_requirements: structural,
                early_prompt_blacklist: blacklistData,
                allowed_tools: allowedToolsData,
            });
            if (res && res.status === 'saved') {
                ui.showToast('AI standards saved', 'success');
                renderSettingsOrganizationTab();
            } else {
                throw new Error(res.error || 'Save failed');
            }
        } catch (e) {
            ui.showToast(e.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Save AI Standards';
        }
    });

    document.getElementById('btn-delete-ai-standards')?.addEventListener('click', async () => {
        // Deleting standards must not touch the charter — that separation is the
        // whole point of them being different artifacts.
        if (!confirm('Delete the organization AI standards? Your Charter is not affected.')) return;
        try {
            await api.deleteAiStandards(org.id);
            ui.showToast('AI standards deleted', 'success');
            renderSettingsOrganizationTab();
        } catch (e) {
            ui.showToast(e.message || 'Delete failed', 'error');
        }
    });

    document.getElementById('btn-save-charter')?.addEventListener('click', async () => {
        const btn = document.getElementById('btn-save-charter');
        const mission = document.getElementById('charter-mission')?.value.trim() || '';
        btn.disabled = true;
        btn.textContent = 'Saving...';
        try {
            // Mission and core values only. AI conduct rules save separately —
            // see the AI Standards card.
            const res = await api.saveCharter(org.id, {
                mission,
                core_values: charterValuesData.filter(v => v.name),
            });
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
            container.querySelector('#inp-ms-tenant').value = cfg.ms_tenant_id || '';
            container.querySelector('#inp-google-hd').value = cfg.google_hd || '';
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
                    ms_tenant_id: container.querySelector('#inp-ms-tenant').value.trim() || null,
                    google_hd: container.querySelector('#inp-google-hd').value.trim() || null,
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

    // --- Groups (admin only; the card is only rendered for admins) ---
    if (currentUser && currentUser.role === 'admin') {
        document.getElementById('btn-create-group')?.addEventListener('click', async () => {
            const inp = document.getElementById('inp-group-name');
            const name = (inp?.value || '').trim();
            if (!name) return;
            try {
                await api.createGroup(name);
                inp.value = '';
                ui.showToast('Group created.', 'success');
                loadOrgGroups(org.id);
            } catch (e) {
                ui.showToast(e.message || 'Create failed', 'error');
            }
        });
        loadOrgGroups(org.id);
    }
}

async function loadOrgGroups(orgId) {
    const el = document.getElementById('org-groups-list');
    const badge = document.getElementById('group-count-badge');
    if (!el) return;
    try {
        const res = await api.listGroups();
        const groups = res.groups || [];
        if (badge) badge.textContent = `${groups.length} group${groups.length === 1 ? '' : 's'}`;
        if (!groups.length) {
            el.innerHTML = `<p class="p-4 text-sm text-gray-500">No groups yet. Create one below, then share agents with it from the Agents tab.</p>`;
            return;
        }
        el.innerHTML = groups.map(g => `
            <div class="border-b border-gray-100 dark:border-neutral-800 last:border-0">
                <div class="flex items-center justify-between px-4 py-2.5">
                    <div class="min-w-0">
                        <p class="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">${escapeHtml(g.name)}</p>
                        <p class="text-xs text-gray-400">${g.member_count} member${g.member_count === 1 ? '' : 's'}</p>
                    </div>
                    <div class="flex items-center gap-3 flex-shrink-0 ml-3">
                        <button data-group="${escapeHtml(g.id)}" class="grp-members-btn text-xs text-green-600 hover:underline">Members</button>
                        <button data-group-del="${escapeHtml(g.id)}" data-name="${escapeHtml(g.name)}" class="text-xs text-red-500 hover:underline">Delete</button>
                    </div>
                </div>
                <div id="grp-panel-${escapeHtml(g.id)}" class="hidden px-4 pb-3"></div>
            </div>`).join('');

        el.querySelectorAll('.grp-members-btn').forEach(btn => btn.addEventListener('click', () => {
            toggleGroupPanel(orgId, btn.getAttribute('data-group'));
        }));
        el.querySelectorAll('[data-group-del]').forEach(btn => btn.addEventListener('click', async () => {
            const name = btn.getAttribute('data-name');
            if (!confirm(`Delete the group "${name}"? Agents shared with it will no longer be shared through it.`)) return;
            try {
                await api.deleteGroup(btn.getAttribute('data-group-del'));
                ui.showToast('Group deleted.', 'success');
                loadOrgGroups(orgId);
            } catch (e) {
                ui.showToast(e.message || 'Delete failed', 'error');
            }
        }));
    } catch (e) {
        el.innerHTML = `<p class="p-4 text-sm text-red-500">${escapeHtml(e.message || 'Could not load groups.')}</p>`;
    }
}

async function toggleGroupPanel(orgId, groupId) {
    const panel = document.getElementById(`grp-panel-${groupId}`);
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
        return;
    }
    panel.classList.remove('hidden');
    panel.innerHTML = `<div class="py-2 text-sm text-gray-400">Loading...</div>`;
    try {
        const [grpRes, orgRes] = await Promise.all([
            api.listGroupMembers(groupId),
            api.getOrganizationMembers(orgId),
        ]);
        const inGroup = grpRes.members || [];
        const inGroupIds = new Set(inGroup.map(m => m.user_id));
        const candidates = (orgRes.members || []).filter(m => !inGroupIds.has(m.id));

        const rows = inGroup.length ? inGroup.map(m => `
            <div class="flex items-center justify-between py-1.5 border-b border-gray-100 dark:border-neutral-800 last:border-0">
                <span class="text-sm text-gray-700 dark:text-gray-300 truncate">${escapeHtml(m.name || m.user_id)} <span class="text-xs text-gray-400">${escapeHtml(m.email || '')}</span></span>
                <button data-member="${escapeHtml(m.user_id)}" class="grp-remove-member text-xs text-red-500 hover:underline flex-shrink-0 ml-3">Remove</button>
            </div>`).join('')
            : `<p class="py-1.5 text-sm text-gray-400">No members yet.</p>`;

        panel.innerHTML = `
            <div class="bg-gray-50 dark:bg-neutral-800/50 rounded-lg p-3">
                ${rows}
                <div class="flex gap-2 mt-2 pt-2 border-t border-gray-200 dark:border-neutral-700">
                    <select class="grp-add-select settings-modal-select flex-1 text-sm">
                        <option value="">Add a member...</option>
                        ${candidates.map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.email || m.id)}</option>`).join('')}
                    </select>
                    <button class="grp-add-btn px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-bold">Add</button>
                </div>
            </div>`;

        panel.querySelector('.grp-add-btn').addEventListener('click', async () => {
            const sel = panel.querySelector('.grp-add-select');
            if (!sel.value) return;
            try {
                await api.addGroupMember(groupId, sel.value);
                await loadOrgGroups(orgId);
                await toggleGroupPanel(orgId, groupId);
            } catch (e) {
                ui.showToast(e.message || 'Add failed', 'error');
            }
        });
        panel.querySelectorAll('.grp-remove-member').forEach(btn => btn.addEventListener('click', async () => {
            try {
                await api.removeGroupMember(groupId, btn.getAttribute('data-member'));
                await loadOrgGroups(orgId);
                await toggleGroupPanel(orgId, groupId);
            } catch (e) {
                ui.showToast(e.message || 'Remove failed', 'error');
            }
        }));
    } catch (e) {
        panel.innerHTML = `<p class="py-2 text-sm text-red-500">${escapeHtml(e.message || 'Could not load members.')}</p>`;
    }
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

function renderCharterValues(valuesData, container, mode = 'charter') {
    // `mode` decides whether a value may block. Charter values are organizational
    // identity and are SCORED — letting one be flagged non-negotiable by hand is
    // exactly how a required disclosure once became a value that blocked every
    // turn. Gates belong to AI Standards, where every entry is one by definition.
    if (!container) return;
    container.innerHTML = '';

    if (!valuesData.length) {
        // Each mode names its own thing and its own button. The charter's
        // wording used to show here, telling an admin on the AI Standards card
        // that no "values" were defined and to press a button on another card.
        const empty = mode === 'standard'
            ? { what: 'No standards yet.',
                how: 'Click <strong>Suggest standards</strong> for a starting set, or <strong>Add standard</strong> to write your own.' }
            : { what: 'No core values defined yet.',
                how: 'Click <strong>Generate Values</strong> to let AI draft them from your mission.' };
        container.innerHTML = `
            <div class="text-center py-10 bg-gray-50 dark:bg-neutral-900 rounded-xl border-2 border-dashed border-gray-200 dark:border-neutral-800">
                <p class="text-gray-400 mb-1">${empty.what}</p>
                <p class="text-xs text-gray-400">${empty.how}</p>
            </div>`;
        return;
    }

    valuesData.forEach((v, idx) => {
        if (!v.rubric) v.rubric = { scoring_guide: [] };
        if (Array.isArray(v.rubric)) v.rubric = { scoring_guide: v.rubric };
        if (!v.rubric.scoring_guide) v.rubric.scoring_guide = [];

        const hasRubric = v.rubric.scoring_guide.length > 0;
        const weightPct = v.weight <= 1.0 ? Math.round(v.weight * 100) : (v.weight || 100);

        // Same editor, two artifacts. A charter value is something the
        // organization stands for; an AI standard is a rule its agents follow.
        // Reusing the widget is fine — reusing its wording is not.
        const copy = mode === 'standard'
            ? { name: 'Standard name (e.g. Personal Data Protection)',
                desc: 'What must the agent do, or never do? e.g. "Never reveal a person\u2019s social security, bank account or passport number."' }
            : { name: 'Value name (e.g. Integrity)',
                desc: 'Brief description of this value...' };

        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-5 shadow-sm';
        card.innerHTML = `
            <div class="flex items-start justify-between gap-4 mb-3">
                <input type="text" value="${v.name || ''}" placeholder="${copy.name}"
                    class="cv-name flex-1 font-semibold text-base bg-transparent border-b border-transparent hover:border-gray-300 focus:border-green-500 outline-none text-gray-900 dark:text-white px-1 py-0.5 transition-all"/>
                <button class="btn-remove-cv p-1.5 text-gray-400 hover:text-red-500 rounded transition-colors shrink-0">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <textarea placeholder="${copy.desc}" rows="2"
                class="cv-desc w-full text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 rounded-lg p-2.5 resize-none outline-none focus:border-green-500 mb-3">${v.description || ''}</textarea>

            <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
                <div class="flex items-center gap-2">
                    ${hasRubric
                        ? `<span class="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 px-2 py-0.5 rounded-full font-medium">✓ Rubric ready</span>`
                        : `<span class="text-xs bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 px-2 py-0.5 rounded-full font-medium">Needs rubric</span>`
                    }
                    <button class="btn-toggle-rubric text-xs text-green-600 dark:text-green-400 hover:underline">View / Edit Rubric</button>
                </div>
                <div class="flex items-center gap-2 flex-wrap">
                    ${mode === 'standard'
                        ? `<label class="flex items-center gap-2 cursor-pointer select-none bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800" title="Scored: counts toward the alignment score alongside the other standards. Non-negotiable: any violation blocks the response outright, however well it scores elsewhere. Reserve it for absolutes — each one is judged on every request, so several make ordinary answers more likely to be stopped.">
                             <input type="checkbox" class="cv-blocking accent-red-600 w-4 h-4" ${v.hard_gate ? 'checked' : ''}/>
                             <span class="text-xs uppercase font-bold ${v.hard_gate ? 'text-red-600 dark:text-red-400' : 'text-gray-500'}">Non-negotiable</span>
                           </label>`
                        : (v.hard_gate
                            ? `<span class="text-[10px] uppercase font-bold tracking-wider bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 px-2 py-1 rounded-full" title="This core value blocks on violation. Non-negotiable rules belong in AI Standards; this one is kept working, but new ones should be added there.">Legacy gate</span>`
                            : '')}
                    <div class="flex items-center gap-2 bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800"
                        title="Weight is relative, not absolute. Values are weighed against each other and rescaled to the organization's share of the score, so 50 next to 100 counts half as much, and equal numbers count equally, whatever they are.">
                        <label class="text-xs font-bold text-gray-500 uppercase">Weight</label>
                        <input type="range" min="1" max="100" value="${weightPct}" class="cv-weight-slider w-20 h-1.5 accent-green-600 cursor-pointer"/>
                        <span class="cv-weight-lbl text-xs font-mono font-bold text-gray-700 dark:text-gray-300 w-8 text-right">${weightPct}%</span>
                    </div>
                </div>
            </div>

            <div class="cv-rubric-panel hidden mt-4 pt-4 border-t border-dashed border-gray-200 dark:border-neutral-700 space-y-2">
                <p class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Scoring criteria (traffic light)</p>
                ${[
                    { score: 1.0,  icon: '✅', label: 'Positive (+1)', color: 'green',  bg: 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900',
                      hint: mode === 'standard' ? 'A response that respects this. Word it so an answer that never touched the topic still counts.' : 'What an excellent response looks like...' },
                    { score: 0.0,  icon: '⚪', label: 'Neutral (0)',   color: 'gray',   bg: 'bg-white dark:bg-neutral-800 border-gray-200 dark:border-neutral-700',
                      hint: mode === 'standard' ? 'Optional. Leave blank for a pass/fail standard.' : 'Acceptable, neither good nor bad...' },
                    { score: -1.0, icon: '🚫', label: 'Violation (−1)', color: 'red',   bg: 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900',
                      // The trap that broke a live agent: "does not include X" fires
                      // on every answer that never raised the topic.
                      hint: mode === 'standard' ? 'Something the response actually DID — "reveals a bank account number". Never "fails to mention…", which would flag every unrelated answer.' : 'What a violation looks like...' }
                ].map(def => {
                    const item = v.rubric.scoring_guide.find(g => Math.abs(g.score - def.score) < 0.1);
                    const text = item ? (item.criteria || item.descriptor || '') : '';
                    return `
                        <div class="flex gap-3 items-start">
                            <span class="w-28 shrink-0 text-xs font-bold text-gray-500 pt-2.5 text-right">${def.icon} ${def.label}</span>
                            <textarea data-score="${def.score}" rows="2"
                                class="cv-rubric-text flex-1 text-sm p-2.5 rounded-lg border resize-none outline-none focus:ring-2 focus:ring-green-500 ${def.bg}"
                                placeholder="${def.hint}">${text}</textarea>
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

        // The non-negotiable toggle exists only for AI standards. A charter value is
        // organizational identity and is always scored; letting one block by
        // hand is what produced a required disclosure that stopped every turn.
        const blockingToggle = card.querySelector('.cv-blocking');
        if (blockingToggle) {
            blockingToggle.addEventListener('change', e => {
                const on = !!e.target.checked;
                valuesData[idx].hard_gate = on;
                // A blocking standard sits outside the weight split; a scored one
                // needs a positive weight to be normalized against.
                valuesData[idx].weight = on ? 0 : (valuesData[idx].weight || 1);
                renderCharterValues(valuesData, container, mode);
            });
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
                     <select class="role-select bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 text-xs rounded px-2 py-1 outline-none focus:border-green-500"
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
