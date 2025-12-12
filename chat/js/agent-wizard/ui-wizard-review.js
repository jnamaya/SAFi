export function renderReviewStep(container, agentData) {
    const valuesCount = agentData.values.length;
    const rulesCount = agentData.rules.length;
    const hasRAG = !!agentData.rag_knowledge_base;

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

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <!-- Config Stats -->
                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                     <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">Configuration</h4>
                     <ul class="space-y-2 text-sm">
                        <li class="flex justify-between">
                            <span>Values</span>
                            <span class="font-mono font-bold">${valuesCount}</span>
                        </li>
                        <li class="flex justify-between">
                            <span>Rules</span>
                            <span class="font-mono font-bold">${rulesCount}</span>
                        </li>
                        <li class="flex justify-between">
                            <span>Knowledge Base</span>
                            <span class="font-mono font-bold ${hasRAG ? 'text-green-600' : 'text-gray-400'}">${hasRAG ? 'Active' : 'None'}</span>
                        </li>
                     </ul>
                </div>

                <!-- Models -->
                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                     <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">AI Models</h4>
                     <ul class="space-y-2 text-sm">
                        <li class="flex justify-between">
                            <span>Intellect</span>
                            <span class="font-mono text-xs text-gray-600 dark:text-gray-400">${agentData.intellect_model || 'Default'}</span>
                        </li>
                         <li class="flex justify-between">
                            <span>Conscience</span>
                            <span class="font-mono text-xs text-gray-600 dark:text-gray-400">${agentData.conscience_model || 'Default'}</span>
                        </li>
                         <li class="flex justify-between">
                            <span>Will</span>
                            <span class="font-mono text-xs text-gray-600 dark:text-gray-400">${agentData.will_model || 'Default'}</span>
                        </li>
                     </ul>
                </div>
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
