export function renderReviewStep(container, agentData) {
    const hasRAG = !!agentData.rag_knowledge_base;
    const hasPolicy = !!(agentData.policy_id && agentData.policy_id !== 'standalone');
    const policyLabel = hasPolicy ? (agentData._policyData?.name || agentData.policy_id) : 'None (Charter only)';
    const maxTurns = agentData.max_agent_turns || 'Default';
    const trackWork = agentData.track_work_context !== false;

    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Review & Create</h2>
        <p class="text-gray-500 mb-6">Review your agent configuration before saving.</p>
        
        <div class="space-y-6">
            
             <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg p-4 border border-gray-200 dark:border-neutral-700 flex gap-4">
                <div class="w-16 h-16 rounded-full bg-blue-100 flex items-center justify-center overflow-hidden shrink-0">
                     ${agentData.avatar ? `<img src="${agentData.avatar}" class="w-full h-full object-cover">` : `<span class="text-2xl">🤖</span>`}
                </div>
                <div>
                     <h3 class="font-bold text-lg dark:text-white">${agentData.name || 'Unnamed Agent'}</h3>
                     <p class="text-sm text-gray-500">${agentData.description || 'No description'}</p>
                     <div class="flex gap-2 mt-2 items-center flex-wrap">
                        <span class="text-xs px-2 py-1 bg-blue-100 text-blue-800 rounded-full font-mono">ID: ${agentData.key}</span>
                        <span class="text-xs px-2 py-1 bg-gray-100 text-gray-800 rounded-full">Visibility: ${agentData.visibility}</span>
                        <span class="text-xs px-2 py-1 bg-gray-100 text-gray-800 rounded-full">Policy: ${agentData.policy_id}</span>
                     </div>
                </div>
            </div>

            <!-- Config Stats -->
            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                 <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">Configuration</h4>
                 <ul class="space-y-2 text-sm">
                    <li class="flex justify-between">
                        <span>Governing Policy</span>
                        <span class="font-mono font-bold ${hasPolicy ? 'text-blue-600' : 'text-gray-400'}">${policyLabel}</span>
                    </li>
                    <li class="flex justify-between">
                        <span>Knowledge Base</span>
                        <span class="font-mono font-bold ${hasRAG ? 'text-green-600' : 'text-gray-400'}">${hasRAG ? 'Active' : 'None'}</span>
                    </li>
                    <li class="flex justify-between">
                        <span>Max Tool Turns</span>
                        <span class="font-mono font-bold">${maxTurns}</span>
                    </li>
                    <li class="flex justify-between">
                        <span>Work &amp; Task Memory</span>
                        <span class="font-mono font-bold ${trackWork ? 'text-green-600' : 'text-gray-400'}">${trackWork ? 'On' : 'Off'}</span>
                    </li>
                 </ul>
            </div>
            
            <!-- Governance Summary -->
            <div class="border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 rounded-lg p-4">
                <h4 class="font-bold text-sm text-blue-800 dark:text-blue-200 uppercase mb-2">Governance</h4>
                <p class="text-sm text-blue-700 dark:text-blue-300">
                    ${hasPolicy
                        ? `This agent is governed by the <strong>${policyLabel}</strong> policy plus your Organization's Charter. Its values, standards, scope, required disclaimers, and permitted tools are inherited from them.`
                        : `This agent has no policy attached, so it is governed by your Organization's Charter alone. Attach a policy in Step 1 to give it business-unit standards and rules.`}
                </p>
            </div>

            <!-- Instructions Preview -->
            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                <h4 class="font-bold text-sm text-gray-500 uppercase mb-2">System Instructions (Preview)</h4>
                <div class="text-xs font-mono bg-gray-50 dark:bg-neutral-900 p-3 rounded max-h-32 overflow-y-auto whitespace-pre-wrap text-gray-700 dark:text-gray-300">
${agentData.instructions || '(Empty instructions)'}
                </div>
            </div>

        </div>
    `;
}

export function validateReviewStep(agentData) {
    return true;
}
