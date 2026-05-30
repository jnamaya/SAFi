// Operational settings for the agent (a "role"). Values, scope, disclaimers,
// permitted tools and other guardrails are NOT set here — they are inherited
// from the agent's Governing Policy (Step 1) and the Organization's Charter.
// This step only holds agent-level operational settings.

export function renderSafetyStep(container, agentData) {
    const maxTurns = agentData.max_agent_turns || '';
    // Default ON for custom agents unless explicitly disabled.
    const trackWork = agentData.track_work_context !== false;

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

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <div class="flex items-start justify-between gap-4">
                    <div>
                        <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Work &amp; Task Memory</h4>
                        <p class="text-xs text-gray-500">When on, the agent remembers durable work context across conversations — ongoing projects, tasks, decisions, deadlines, team members, and vendors a user mentions — and uses it on future turns. Turn off for informational, Q&amp;A, or roleplay agents that have no project to track.</p>
                    </div>
                    <button type="button" id="track-work-context-toggle" role="switch" aria-checked="${trackWork}"
                        class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors outline-none focus:ring-2 focus:ring-blue-500 ${trackWork ? 'bg-blue-600' : 'bg-gray-300 dark:bg-neutral-600'}">
                        <span class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${trackWork ? 'translate-x-6' : 'translate-x-1'}"></span>
                    </button>
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

    // Normalize the default so the saved payload is explicit.
    agentData.track_work_context = trackWork;
    const trackToggle = container.querySelector('#track-work-context-toggle');
    if (trackToggle) {
        trackToggle.addEventListener('click', function() {
            const next = !(agentData.track_work_context !== false);
            agentData.track_work_context = next;
            trackToggle.setAttribute('aria-checked', String(next));
            trackToggle.classList.toggle('bg-blue-600', next);
            trackToggle.classList.toggle('bg-gray-300', !next);
            trackToggle.classList.toggle('dark:bg-neutral-600', !next);
            const knob = trackToggle.querySelector('span');
            if (knob) {
                knob.classList.toggle('translate-x-6', next);
                knob.classList.toggle('translate-x-1', !next);
            }
        });
    }
}

export function validateSafetyStep(agentData) {
    return true;
}
