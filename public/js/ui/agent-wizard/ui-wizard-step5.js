// Operational settings for the agent (a "role"). Values, scope, disclaimers,
// permitted tools and other guardrails are NOT set here — they are inherited
// from the agent's Governing Policy (Step 1) and the Organization's Charter.
// This step only holds agent-level operational settings.

export function renderSafetyStep(container, agentData) {
    const maxTurns = agentData.max_agent_turns || '';

    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Operational Settings</h2>
        <p class="text-gray-500 mb-6">Agent-level operational limits. Values, scope, disclaimers, and other guardrails are governed by this agent's Policy and your Organization's Charter.</p>

        <div class="space-y-5">

            <!-- Governance notice -->
            <div class="border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 rounded-lg p-5">
                <div class="flex items-start gap-3">
                    <svg class="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                    <div>
                        <h4 class="font-semibold text-blue-900 dark:text-blue-100">Governed by Charter + Policy</h4>
                        <p class="text-xs text-blue-700 dark:text-blue-300 mt-0.5">This agent's values, standards, scope, required disclaimers, prohibited formatting, and permitted tools all come from its <strong>Governing Policy</strong> (Step 1) and your <strong>Organization's Charter</strong>. To change them, edit the Policy or the Charter in Organization settings.</p>
                    </div>
                </div>
            </div>

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Max Tool Call Turns</h4>
                <p class="text-xs text-gray-500 mb-3">Maximum number of sequential tool calls this agent can make per response before being forced to synthesize an answer. Leave blank to use the platform default.</p>
                <div class="flex items-center gap-3">
                    <input type="number" id="max-agent-turns-input" min="1" max="20" step="1"
                        class="w-28 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                        placeholder="Default" value="${maxTurns}">
                    <span class="text-xs text-gray-400">Platform default applies when blank. Raise for complex research agents, lower for focused single-tool agents.</span>
                </div>
            </div>

        </div>
    `;

    const maxTurnsInput = container.querySelector('#max-agent-turns-input');
    if (maxTurnsInput) {
        maxTurnsInput.addEventListener('input', function() {
            const val = parseInt(maxTurnsInput.value);
            if (!isNaN(val) && val >= 1 && val <= 20) {
                agentData.max_agent_turns = val;
            } else if (maxTurnsInput.value === '') {
                agentData.max_agent_turns = null;
            }
        });
    }
}

export function validateSafetyStep(agentData) {
    return true;
}
