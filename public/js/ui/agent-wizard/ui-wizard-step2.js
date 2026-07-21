import * as api from '../../core/api.js';
import { loadToolCategories, renderToolGrid } from '../shared/tool-picker.js';

export async function renderToolsStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Tools</h2>
        <p class="text-gray-500 mb-6">Select the tools and data sources this agent can access.</p>

        <div id="wiz-policy-note" class="hidden mb-6 flex items-start gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
            <svg class="w-4 h-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
            <p class="text-xs text-blue-800 dark:text-blue-300" id="wiz-policy-note-text"></p>
        </div>

        <div id="wiz-tools-loading" class="flex items-center gap-2 text-gray-500">
            <span class="thinking-spinner w-4 h-4"></span> Loading tools...
        </div>

        <div id="wiz-tools-container" class="grid grid-cols-1 gap-6 hidden">
            <!-- Tools injected here -->
        </div>
    `;

    const loader = document.getElementById('wiz-tools-loading');
    const containerEl = document.getElementById('wiz-tools-container');

    if (!agentData.tools) agentData.tools = [];

    try {
        const categories = await loadToolCategories();
        if (!categories) {
            loader.innerText = "Failed to load tools.";
            return;
        }

        // Determine the policy's authorized-tool universe.
        //   null  -> no governing policy (or legacy policy) -> full catalog
        //   []    -> policy authorizes no tools
        //   [...] -> policy authorizes exactly these tools
        const allow = await resolvePolicyAllowlist(agentData);

        let filter = null;
        if (allow !== null) {
            filter = new Set(allow);
            // Drop any previously-selected tools the policy no longer authorizes.
            agentData.tools = agentData.tools.filter(t => filter.has(t));

            const note = document.getElementById('wiz-policy-note');
            const noteText = document.getElementById('wiz-policy-note-text');
            note.classList.remove('hidden');

            if (allow.length === 0) {
                noteText.innerHTML = "This agent's governing policy authorizes <strong>no tools</strong>. It will run without tool access. Edit the policy's Tools &amp; Guardrails step to authorize tools.";
                loader.classList.add('hidden');
                return;
            }
            noteText.innerHTML = "Only tools authorized by this agent's governing policy are shown. Edit the policy to change what's available here.";
        }

        loader.classList.add('hidden');
        containerEl.classList.remove('hidden');

        renderToolGrid(containerEl, {
            categories,
            filter,
            isSelected: (name) => agentData.tools.includes(name),
            onToggle: (name, checked) => {
                if (checked) {
                    if (!agentData.tools.includes(name)) agentData.tools.push(name);
                } else {
                    agentData.tools = agentData.tools.filter(t => t !== name);
                }
            },
        });
    } catch (e) {
        console.error("Tools Fetch Error", e);
        loader.innerText = "Error loading tools.";
    }
}

// Resolve the governing policy's allowed-tools list for the agent being edited.
// Returns null when there is no governing policy (or the policy predates the
// structured tool allowlist), meaning the full catalog should be offered.
async function resolvePolicyAllowlist(agentData) {
    const pid = agentData.policy_id;
    if (!pid || pid === 'standalone') return null;

    // Step 1 stores the selected policy object here; fall back to a lookup.
    let policy = (agentData._policyData && agentData._policyData.id === pid)
        ? agentData._policyData
        : null;

    if (!policy) {
        try {
            const res = await api.fetchPolicies();
            if (res.ok && res.policies) policy = res.policies.find(p => p.id === pid);
        } catch (e) {
            console.error("Could not resolve policy for tool filtering", e);
        }
    }
    if (!policy) return null;

    const wr = policy.will_rules;
    // Only structured (dict) will_rules carry an allowlist. Legacy list-shaped
    // policies never declared tools, so leave them unrestricted.
    if (wr && typeof wr === 'object' && !Array.isArray(wr)) {
        return Array.isArray(wr.allowed_tools) ? wr.allowed_tools : [];
    }
    return null;
}

export function validateToolsStep(agentData) {
    // Tools are optional
    return true;
}
