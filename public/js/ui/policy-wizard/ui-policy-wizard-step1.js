export function renderDefinitionStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Identity</h2>
                <p class="text-gray-500 mb-6">Tell us what this policy is for. The more specific you are, the better the AI can draft your worldview, values, and rules in the next steps.</p>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Policy Name <span class="text-red-500">*</span></label>
                        <input type="text" id="pw-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. HR Policy, Finance Policy, Customer Service" value="${policyData.name}">
                    </div>

                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Business Unit / Department</label>
                        <input type="text" id="pw-business-unit" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. Human Resources, Finance, Customer Success" value="${policyData.business_unit || ''}">
                        <p class="text-xs text-gray-400 mt-1">The team or department this policy governs.</p>
                    </div>

                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Description</label>
                        <p class="text-xs text-gray-400 mb-2">What is this policy for? Give the AI enough context to generate relevant values and rules.</p>
                        <textarea id="pw-context" class="w-full h-28 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. This policy governs the HR agent that helps employees navigate benefits, policies, and workplace procedures...">${policyData.context}</textarea>
                        <div class="mt-2 flex items-start gap-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                            <p class="text-xs text-green-800 dark:text-green-300"><strong>Tip:</strong> Already have written guidelines for this team? Paste them here — the AI will use them to draft the worldview, values, and rules in the next steps.</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-blue-900/20 p-6 rounded-xl border border-blue-200 dark:border-blue-800 flex flex-col justify-center">
                <div class="text-blue-600 dark:text-blue-400">
                    <svg class="w-10 h-10 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
                    <h4 class="font-bold text-lg mb-2 text-blue-900 dark:text-blue-100">Tips for great policies</h4>
                    <ul class="text-sm leading-relaxed text-blue-800 dark:text-blue-200 space-y-3">
                        <li><strong class="text-blue-900 dark:text-blue-100 block">Name it after its purpose</strong> "HR Assistant Policy" is clearer than "Policy v2."</li>
                        <li><strong class="text-blue-900 dark:text-blue-100 block">Be specific in the description</strong> The AI uses it to draft your worldview and values — generic input gives generic results.</li>
                        <li><strong class="text-blue-900 dark:text-blue-100 block">One policy per use case</strong> Don't try to cover every scenario in one. Smaller, focused policies are easier to maintain.</li>
                    </ul>
                </div>
            </div>
        </div>
    `;

    // Listeners
    document.getElementById('pw-name')?.addEventListener('input', (e) => policyData.name = e.target.value);
    document.getElementById('pw-business-unit')?.addEventListener('input', (e) => policyData.business_unit = e.target.value);
    document.getElementById('pw-context')?.addEventListener('input', (e) => policyData.context = e.target.value);
}

export function validateDefinitionStep(policyData) {
    if (!policyData.name || !policyData.name.trim()) {
        alert("Policy Name is required");
        return false;
    }
    return true;
}
