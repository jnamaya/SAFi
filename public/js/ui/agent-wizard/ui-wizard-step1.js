import * as api from '../../core/api.js';
import * as ui from '../ui.js';
import { escapeHtml } from '../../core/utils.js';

export async function renderIdentityStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Identity</h2>
        <p class="text-gray-500 mb-6">Define the agent's identity and attach it to a compliance policy.</p>
        
        <div class="grid grid-cols-1 gap-6">
            <!-- Policy Section -->
            <div class="bg-blue-50 dark:bg-blue-900/10 p-5 rounded-xl border border-blue-200 dark:border-blue-800">
                <div class="flex items-center gap-2 mb-2">
                    <svg class="w-5 h-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                    <label class="block text-sm font-bold text-blue-900 dark:text-blue-100">Governing Policy</label>
                </div>
                
                <select id="wiz-policy" class="w-full p-2 rounded border border-blue-300 dark:border-blue-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500">
                    <option value="standalone">Loading Policies...</option>
                </select>
                <p class="text-xs text-blue-600 dark:text-blue-300 mt-2">
                    A policy gives this agent its business-unit standards and rules. With no policy, the agent is governed by your Organization's Charter alone — so you need <strong>at least a Charter or a Policy</strong> for the agent to be governed.
                </p>
                <div id="wiz-policy-preview" class="hidden mt-3 text-xs p-3 bg-white dark:bg-neutral-900 rounded border border-blue-100 dark:border-neutral-700 text-gray-600 dark:text-gray-400">
                    <!-- Preview populated by JS -->
                </div>
                <div id="wiz-gov-warning" class="hidden mt-3 flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 rounded-lg">
                    <svg class="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z" /></svg>
                    <p class="text-xs text-amber-800 dark:text-amber-300">This agent would have <strong>no governance</strong>: your organization has no Charter and no policy is attached. Set an Organization Charter (<strong>Settings → Organization</strong>) or choose a policy above before continuing.</p>
                </div>
            </div>

            <!-- Basic Info -->
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Agent Name <span class="text-red-500">*</span></label>
                    <input type="text" id="wiz-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. The Stoic Coach" value="${escapeHtml(agentData.name)}">
                    ${agentData.is_update_mode && agentData.key ? `<p class="text-xs text-gray-400 mt-1">Key: ${escapeHtml(agentData.key)} (Cannot be changed)</p>` : ''}
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Short Description</label>
                    <input type="text" id="wiz-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. A wise mentor based on Marcus Aurelius" value="${escapeHtml(agentData.description)}">
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Avatar URL (Optional)</label>
                    <input type="text" id="wiz-avatar" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="https://example.com/image.png" value="${escapeHtml(agentData.avatar)}">
                </div>
            </div>

            <!-- VISIBILITY -->
            <div>
                <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Visibility</label>
                <div class="relative">
                    <select id="wiz-visibility" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 appearance-none">
                        <option value="private" ${agentData.visibility === 'private' ? 'selected' : ''}>Private (Testing only)</option>
                        <option value="member" ${agentData.visibility === 'member' ? 'selected' : ''}>Organization (Everyone)</option>
                        <option value="auditor" ${agentData.visibility === 'auditor' ? 'selected' : ''}>Auditors & Admins Only</option>
                        <option value="admin" ${agentData.visibility === 'admin' ? 'selected' : ''}>Admins Only</option>
                    </select>
                    <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700 dark:text-gray-300">
                        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Bind Auto-Save Events
    attachListeners(agentData);

    // Load Policies
    await loadPolicies(agentData);

    // Resolve charter status so we can warn early if the agent would be ungoverned
    await refreshCharterStatus(agentData);
}

// An agent must inherit governance from either a Policy or the org Charter.
// Mirror the backend guard (agent_api_routes.py) so we fail fast on Step 1
// instead of at save time.
async function refreshCharterStatus(agentData) {
    try {
        const orgRes = await api.getMyOrganization();
        const org = orgRes && orgRes.organization;
        if (org && org.id) {
            const cRes = await api.getCharter(org.id).catch(() => null);
            agentData._hasCharter = !!(cRes && cRes.charter);
        } else {
            agentData._hasCharter = false;
        }
    } catch (e) {
        // Unknown — leave undefined so we neither warn nor block prematurely.
        agentData._hasCharter = undefined;
    }
    updateGovernanceWarning(agentData);
}

function isUngoverned(agentData) {
    const standalone = !agentData.policy_id || agentData.policy_id === 'standalone';
    return standalone && agentData._hasCharter === false;
}

function updateGovernanceWarning(agentData) {
    const warn = document.getElementById('wiz-gov-warning');
    if (!warn) return;
    warn.classList.toggle('hidden', !isUngoverned(agentData));
}

function attachListeners(agentData) {
    document.getElementById('wiz-name')?.addEventListener('input', (e) => agentData.name = e.target.value);
    document.getElementById('wiz-desc')?.addEventListener('input', (e) => agentData.description = e.target.value);
    document.getElementById('wiz-avatar')?.addEventListener('input', (e) => agentData.avatar = e.target.value);
    document.getElementById('wiz-visibility')?.addEventListener('change', (e) => agentData.visibility = e.target.value);
}

async function loadPolicies(agentData) {
    try {
        const res = await api.fetchPolicies();
        const policies = (res.ok && res.policies) ? res.policies : [];
        const select = document.getElementById('wiz-policy');

        if (select) {
            select.innerHTML = `<option value="standalone">Charter only — no specific policy</option>`;
            policies.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name} ${p.is_demo ? '(Official)' : ''}`;
                select.appendChild(opt);
            });

            // Set current value
            select.value = agentData.policy_id || "standalone";

            // Change Listener
            select.addEventListener('change', () => {
                agentData.policy_id = select.value;
                const pid = select.value;
                const preview = document.getElementById('wiz-policy-preview');

                if (pid === 'standalone') {
                    agentData._policyData = null;
                    preview.classList.add('hidden');
                    updateGovernanceWarning(agentData);
                    return;
                }

                updateGovernanceWarning(agentData);

                const policy = policies.find(p => p.id === pid);
                if (policy) {
                    agentData._policyData = policy; // Store for Values step to read

                    const missionSnippet = policy.worldview
                        ? policy.worldview.replace(/<!-- CONTEXT:.*?-->\n?/, '').trim().substring(0, 120) + '…'
                        : 'No mission defined.';

                    const policyValues = policy.values_weights || [];
                    const valuesHtml = policyValues.slice(0, 3).map(v => {
                        const label = typeof v === 'object' ? (v.name || v.value || 'Untitled') : v;
                        return `<li>${escapeHtml(String(label))}</li>`;
                    }).join('');
                    const moreHtml = policyValues.length > 3
                        ? `<li class="text-gray-400">+${policyValues.length - 3} more</li>` : '';

                    preview.innerHTML = `
                        <strong class="block mb-2 text-blue-800 dark:text-blue-200">${escapeHtml(policy.name)}</strong>
                        <div class="space-y-2">
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400 block mb-1">Purpose</span>
                                <p class="italic">${escapeHtml(missionSnippet)}</p>
                            </div>
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400 block mb-1">Standards (inherited)</span>
                                <ul class="list-disc list-inside">${valuesHtml}${moreHtml}</ul>
                            </div>
                        </div>
                    `;
                    preview.classList.remove('hidden');
                }
            });

            // Trigger once
            select.dispatchEvent(new Event('change'));
        }

    } catch (e) {
        console.error("Failed to load policies", e);
    }
}

export function validateIdentityStep(agentData) {
    const name = document.getElementById('wiz-name')?.value;
    if (!name || !name.trim()) {
        alert("Agent Name is required");
        return false;
    }
    if (isUngoverned(agentData)) {
        updateGovernanceWarning(agentData);
        ui.showToast("This agent would have no governance. Set an Organization Charter (Settings → Organization) or attach a Policy to continue.", "error");
        return false;
    }
    return true;
}
