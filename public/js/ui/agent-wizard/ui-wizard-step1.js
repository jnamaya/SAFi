import * as api from '../../core/api.js';
import * as ui from '../ui.js';
import { escapeHtml } from '../../core/utils.js';

export async function renderIdentityStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Identity</h2>
        <p class="text-gray-500 mb-6">Define the agent's identity and attach it to a compliance policy.</p>
        
        <div class="grid grid-cols-1 gap-6">
            <!-- Policy Section -->
            <div class="bg-green-50 dark:bg-green-900/10 p-5 rounded-xl border border-green-200 dark:border-green-800">
                <div class="flex items-center gap-2 mb-2">
                    <svg class="w-5 h-5 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                    <label class="block text-sm font-bold text-green-900 dark:text-green-100">Governing Policy</label>
                </div>
                
                <select id="wiz-policy" class="w-full p-2 rounded border border-green-300 dark:border-green-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500">
                    <option value="standalone">Loading Policies...</option>
                </select>
                <p class="text-xs text-green-600 dark:text-green-300 mt-2">
                    A policy gives this agent its business-unit standards and rules. With no policy, the agent is governed by your Organization's Charter alone — so you need <strong>at least a Charter or a Policy</strong> for the agent to be governed.
                </p>
                <div id="wiz-policy-preview" class="hidden mt-3 text-xs p-3 bg-white dark:bg-neutral-900 rounded border border-green-100 dark:border-neutral-700 text-gray-600 dark:text-gray-400">
                    <!-- Preview populated by JS -->
                </div>
                <div id="wiz-gov-warning" class="hidden mt-3 flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 rounded-lg">
                    <svg class="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4a2 2 0 00-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z" /></svg>
                    <p class="text-xs text-amber-800 dark:text-amber-300">This agent would have <strong>no governance</strong>: your organization has no Charter and no policy is attached. Set an Organization Charter (<strong>Control Panel → Organization</strong>) or choose a policy above before continuing.</p>
                </div>
            </div>

            <!-- Basic Info -->
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Agent Name <span class="text-red-500">*</span></label>
                    <input type="text" id="wiz-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500" placeholder="e.g. The Stoic Coach" value="${escapeHtml(agentData.name)}">
                    ${agentData.is_update_mode && agentData.key ? `<p class="text-xs text-gray-400 mt-1">Key: ${escapeHtml(agentData.key)} (Cannot be changed)</p>` : ''}
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Short Description</label>
                    <input type="text" id="wiz-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500" placeholder="e.g. A wise mentor based on Marcus Aurelius" value="${escapeHtml(agentData.description)}">
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Avatar URL (Optional)</label>
                    <input type="text" id="wiz-avatar" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500" placeholder="https://example.com/image.png" value="${escapeHtml(agentData.avatar)}">
                </div>
            </div>

            <!-- ACCESS PERMISSIONS (WINDOWS / DRIVE ACL MODEL) -->
            <div class="rounded-xl border border-gray-200 dark:border-neutral-700 bg-gray-50/50 dark:bg-neutral-800/40 p-4 space-y-4">
                <div>
                    <label class="block text-sm font-bold text-gray-800 dark:text-neutral-200 mb-1">Access Control</label>
                    <p class="text-xs text-gray-500 dark:text-gray-400">Manage who can chat with this agent, like sharing a folder with specific people or groups.</p>
                </div>

                <!-- ACCESS SCOPE -->
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <label class="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 cursor-pointer hover:border-green-500 transition-colors">
                        <input type="radio" name="wiz-access-scope" value="private" class="mt-0.5 text-green-600 focus:ring-green-500" ${agentData.visibility !== 'member' ? 'checked' : ''}>
                        <div>
                            <span class="block text-sm font-semibold text-gray-900 dark:text-white">Restricted</span>
                            <span class="block text-xs text-gray-500 dark:text-gray-400 mt-0.5">Only you and the specific groups or people added below.</span>
                        </div>
                    </label>

                    <label class="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 cursor-pointer hover:border-green-500 transition-colors">
                        <input type="radio" name="wiz-access-scope" value="member" class="mt-0.5 text-green-600 focus:ring-green-500" ${agentData.visibility === 'member' ? 'checked' : ''}>
                        <div>
                            <span class="block text-sm font-semibold text-gray-900 dark:text-white">Everyone in Organization</span>
                            <span class="block text-xs text-gray-500 dark:text-gray-400 mt-0.5">All organization members can chat with this agent.</span>
                        </div>
                    </label>
                </div>

                <!-- ADD USERS / GROUPS SELECTOR -->
                <div>
                    <label class="block text-xs font-bold uppercase text-gray-500 dark:text-gray-400 mb-1.5">Add User or Group</label>
                    <div class="relative">
                        <select id="wiz-acl-select" class="w-full p-2.5 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-green-500 appearance-none">
                            <option value="">Select a group or person to add...</option>
                        </select>
                        <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-gray-500">
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                        </div>
                    </div>

                    <!-- WHO HAS ACCESS LIST -->
                    <div class="mt-3">
                        <span class="text-xs font-bold uppercase text-gray-400 block mb-1.5">Who Has Access</span>
                        <div id="wiz-grantees-list" class="space-y-1.5 min-h-[36px]"></div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Bind Auto-Save Events
    attachListeners(agentData);

    // Load Policies & Access Control
    await Promise.all([
        loadPolicies(agentData),
        loadAccessControl(agentData)
    ]);

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
    document.querySelectorAll('input[name="wiz-access-scope"]').forEach(r => {
        r.addEventListener('change', () => {
            agentData.visibility = r.value;
        });
    });
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
                        ? policy.worldview.replace(/<!-- CONTEXT:[\s\S]*?-->\n?/g, '').trim().substring(0, 120) + '…'
                        : 'No mission defined.';

                    const policyValues = policy.values_weights || [];
                    const valuesHtml = policyValues.slice(0, 3).map(v => {
                        const label = typeof v === 'object' ? (v.name || v.value || 'Untitled') : v;
                        return `<li>${escapeHtml(String(label))}</li>`;
                    }).join('');
                    const moreHtml = policyValues.length > 3
                        ? `<li class="text-gray-400">+${policyValues.length - 3} more</li>` : '';

                    preview.innerHTML = `
                        <strong class="block mb-2 text-green-800 dark:text-green-200">${escapeHtml(policy.name)}</strong>
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

async function loadAccessControl(agentData) {
    const select = document.getElementById('wiz-acl-select');
    const granteesList = document.getElementById('wiz-grantees-list');
    if (!select || !granteesList) return;

    let groups = [];
    let members = [];

    try {
        const orgRes = await api.getMyOrganization().catch(() => null);
        const orgId = orgRes?.organization?.id;
        const [groupsRes, membersRes] = await Promise.all([
            api.listGroups().catch(() => ({ groups: [] })),
            orgId ? api.getOrganizationMembers(orgId).catch(() => ({ members: [] })) : Promise.resolve({ members: [] })
        ]);
        groups = groupsRes?.groups || [];
        members = membersRes?.members || [];
    } catch (e) {
        console.error("Failed to load access candidates", e);
    }

    agentData.grants = agentData.grants || [];

    // If agentData had shared_groups but no grants, bridge them
    if (agentData.shared_groups && agentData.shared_groups.length && !agentData.grants.length) {
        agentData.grants = agentData.shared_groups.map(gid => {
            const grp = groups.find(g => g.id === gid);
            return {
                grantee_type: 'group',
                grantee_id: gid,
                grantee_name: grp ? grp.name : gid
            };
        });
    }

    function renderAclUI() {
        const grantedKeys = new Set((agentData.grants || []).map(g => `${g.grantee_type}:${g.grantee_id}`));
        const availGroups = groups.filter(g => !grantedKeys.has(`group:${g.id}`));
        const availMembers = members.filter(m => !grantedKeys.has(`user:${m.id}`));

        const groupOpts = availGroups.map(g =>
            `<option value="group:${escapeHtml(g.id)}">${escapeHtml(g.name)} (${g.member_count || 0} members)</option>`
        ).join('');
        const memberOpts = availMembers.map(m =>
            `<option value="user:${escapeHtml(m.id)}">${escapeHtml(m.name || m.email || m.id)}${m.email ? ` (${escapeHtml(m.email)})` : ''}</option>`
        ).join('');

        select.innerHTML = `
            <option value="">Select a group or person to add...</option>
            ${groupOpts ? `<optgroup label="Groups">${groupOpts}</optgroup>` : ''}
            ${memberOpts ? `<optgroup label="People">${memberOpts}</optgroup>` : ''}
        `;

        const grantRows = (agentData.grants || []).map(g => {
            const isGroup = g.grantee_type === 'group';
            const iconSvg = isGroup
                ? `<svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>`
                : `<svg class="w-4 h-4 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>`;

            let label = g.grantee_name || g.grantee_id;
            if (isGroup) {
                const grp = groups.find(x => x.id === g.grantee_id);
                if (grp) label = `${grp.name} (${grp.member_count || 0} members)`;
            } else {
                const mem = members.find(x => x.id === g.grantee_id);
                if (mem) label = `${mem.name || mem.email || mem.id}${mem.email ? ` (${mem.email})` : ''}`;
            }

            return `
                <div class="flex items-center justify-between p-2 rounded-lg bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 text-xs">
                    <div class="flex items-center gap-2 min-w-0">
                        ${iconSvg}
                        <span class="font-medium text-gray-800 dark:text-neutral-200 truncate">${escapeHtml(label)}</span>
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-neutral-700 text-gray-500 uppercase">${isGroup ? 'Group' : 'User'}</span>
                    </div>
                    <button type="button" data-remove-grant="${escapeHtml(g.grantee_type)}:${escapeHtml(g.grantee_id)}" class="text-red-500 hover:text-red-700 hover:underline font-semibold ml-2 flex-shrink-0">Remove</button>
                </div>
            `;
        }).join('');

        granteesList.innerHTML = `
            <div class="flex items-center justify-between p-2 rounded-lg bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 text-xs">
                <div class="flex items-center gap-2">
                    <svg class="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
                    <span class="font-medium text-gray-800 dark:text-neutral-200">Owner (Creator)</span>
                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 uppercase">Full Access</span>
                </div>
            </div>
            ${grantRows}
        `;

        granteesList.querySelectorAll('[data-remove-grant]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const [gtype, gid] = btn.getAttribute('data-remove-grant').split(':');
                agentData.grants = (agentData.grants || []).filter(g => !(g.grantee_type === gtype && g.grantee_id === gid));
                agentData.shared_groups = (agentData.grants || []).filter(g => g.grantee_type === 'group').map(g => g.grantee_id);
                renderAclUI();
            });
        });
    }

    select.addEventListener('change', () => {
        if (!select.value) return;
        const [granteeType, granteeId] = select.value.split(':');
        agentData.grants = agentData.grants || [];
        if (!agentData.grants.some(g => g.grantee_type === granteeType && g.grantee_id === granteeId)) {
            let label = granteeId;
            if (granteeType === 'group') {
                const grp = groups.find(x => x.id === granteeId);
                if (grp) label = grp.name;
            } else {
                const mem = members.find(x => x.id === granteeId);
                if (mem) label = mem.name || mem.email || granteeId;
            }
            agentData.grants.push({
                grantee_type: granteeType,
                grantee_id: granteeId,
                grantee_name: label
            });
            agentData.shared_groups = agentData.grants.filter(g => g.grantee_type === 'group').map(g => g.grantee_id);
        }
        renderAclUI();
    });

    renderAclUI();
}

export function validateIdentityStep(agentData) {
    const name = document.getElementById('wiz-name')?.value;
    if (!name || !name.trim()) {
        alert("Agent Name is required");
        return false;
    }
    if (isUngoverned(agentData)) {
        updateGovernanceWarning(agentData);
        ui.showToast("This agent would have no governance. Set an Organization Charter (Control Panel → Organization) or attach a Policy to continue.", "error");
        return false;
    }
    return true;
}
