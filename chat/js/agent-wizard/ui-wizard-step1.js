import * as api from './../api.js';

export async function renderIdentityStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Profile & Governance</h2>
        <p class="text-gray-500 mb-6">Define the agent's identity and attach it to a compliance policy.</p>
        
        <div class="grid grid-cols-1 gap-6">
            <!-- Policy Section -->
            <div class="bg-blue-50 dark:bg-blue-900/10 p-5 rounded-xl border border-blue-200 dark:border-blue-800">
                <div class="flex items-center gap-2 mb-2">
                    <svg class="w-5 h-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                    <label class="block text-sm font-bold text-blue-900 dark:text-blue-100">Governing Policy</label>
                </div>
                
                <div class="flex gap-4">
                    <select id="wiz-policy" class="flex-1 p-2 rounded border border-blue-300 dark:border-blue-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500">
                        <option value="standalone">Loading Policies...</option>
                    </select>
                </div>
                <p class="text-xs text-blue-600 dark:text-blue-300 mt-2">
                    Policies define the "Constitution" (Values & Rules) that this agent must obey.
                </p>
                <div id="wiz-policy-preview" class="hidden mt-3 text-xs p-3 bg-white dark:bg-neutral-900 rounded border border-blue-100 dark:border-neutral-700 text-gray-600 dark:text-gray-400">
                    <!-- Preview populated by JS -->
                </div>
            </div>

            <!-- Basic Info -->
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Agent Name <span class="text-red-500">*</span></label>
                    <input type="text" id="wiz-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. The Stoic Coach" value="${agentData.name}">
                    ${agentData.key ? `<p class="text-xs text-gray-400 mt-1">Key: ${agentData.key} (Cannot be changed)</p>` : ''}
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Short Description</label>
                    <input type="text" id="wiz-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. A wise mentor based on Marcus Aurelius" value="${agentData.description}">
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Avatar URL (Optional)</label>
                    <input type="text" id="wiz-avatar" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="https://example.com/image.png" value="${agentData.avatar}">
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
            select.innerHTML = `<option value="standalone">No Governance (Standalone)</option>`;
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
                agentData.policy_id = select.value; // Save selection
                const pid = select.value;
                const preview = document.getElementById('wiz-policy-preview');

                if (pid === 'standalone') {
                    preview.classList.add('hidden');
                    return;
                }

                const policy = policies.find(p => p.id === pid);
                if (policy) {
                    preview.innerHTML = `
                        <strong class="block mb-1 text-blue-800 dark:text-blue-200">Policy: ${policy.name}</strong>
                        <div class="grid grid-cols-2 gap-4 mt-2">
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400">Values</span>
                                <ul class="list-disc list-inside mt-1">
                                    ${(policy.values_weights || []).slice(0, 2).map(v => {
                        const label = (typeof v === 'object' ? (v.name || v.value || 'Untitled') : v);
                        return `<li>${label}</li>`;
                    }).join('')}
                                </ul>
                            </div>
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400">Rules</span>
                                <ul class="list-disc list-inside mt-1 text-red-600 dark:text-red-400">
                                    ${(policy.will_rules || []).slice(0, 2).map(r => {
                        const text = (typeof r === 'object' ? (r.name || r.text || JSON.stringify(r)) : r);
                        return `<li>${String(text).substring(0, 30)}...</li>`;
                    }).join('')}
                                </ul>
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
    return true;
}
