export function renderKnowledgeStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Knowledge & Retrieval</h2>
        <p class="text-gray-500 mb-6">Connect this agent to a Knowledge Base (RAG) to ground its responses in specific documents.</p>
        
        <div class="grid grid-cols-1 gap-6">
            
            <div class="bg-purple-50 dark:bg-purple-900/10 p-6 rounded-xl border border-purple-200 dark:border-purple-800">
                <div class="flex items-center gap-2 mb-4">
                    <svg class="w-6 h-6 text-purple-600 dark:text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" /></svg>
                    <h3 class="text-lg font-bold text-purple-900 dark:text-purple-100">Knowledge Base Configuration</h3>
                </div>

                <div class="space-y-6">
                    <div>
                        <div class="flex items-center gap-2 mb-2">
                             <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Knowledge Base ID</label>
                             <div class="relative group">
                                <svg class="w-4 h-4 text-gray-400 cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                                <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-64 p-2 bg-black/90 text-white text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                                    The unique identifier of the vector database collection (e.g., 'bible_bsb_v1'). Leave empty to disable RAG.
                                </div>
                             </div>
                        </div>
                        <input type="text" id="wiz-rag-kb" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="e.g. bible_bsb_v1" value="${agentData.rag_knowledge_base || ''}">
                    </div>

                    <div>
                        <div class="flex items-center gap-2 mb-2">
                             <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Format String</label>
                             <div class="relative group">
                                <svg class="w-4 h-4 text-gray-400 cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                                <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-64 p-2 bg-black/90 text-white text-xs rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                                    Template for inserting retrieved document chunks into the prompt. Use placeholders {reference} and {text_chunk}.
                                </div>
                             </div>
                        </div>
                        <textarea id="wiz-rag-fmt" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500 font-mono text-xs h-[120px]" placeholder="REFERENCE: {reference}\nCONTENT:\n{text_chunk}\n---">${agentData.rag_format_string || 'REFERENCE: {reference}\nCONTENT:\n{text_chunk}\n---'}</textarea>
                    </div>
                </div>
            </div>

            <div class="p-4 bg-yellow-50 dark:bg-yellow-900/10 border border-yellow-200 dark:border-yellow-800 rounded-lg flex gap-3">
                 <svg class="w-6 h-6 text-yellow-600 dark:text-yellow-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                 <div class="text-sm text-yellow-800 dark:text-yellow-200">
                    <strong>Note:</strong> Retrieving knowledge adds context but consumes tokens. Ensure your prompt format string is concise.
                 </div>
            </div>

        </div>
    `;

    // Attach Listeners
    document.getElementById('wiz-rag-kb')?.addEventListener('input', (e) => agentData.rag_knowledge_base = e.target.value);
    document.getElementById('wiz-rag-fmt')?.addEventListener('input', (e) => agentData.rag_format_string = e.target.value);
}

export function validateKnowledgeStep(agentData) {
    // RAG is optional, so no strict validation needed unless KB ID is set but Format is empty?
    // We'll allow defaults.
    return true;
}
