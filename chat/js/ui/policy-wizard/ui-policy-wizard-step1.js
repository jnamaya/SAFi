export function renderDefinitionStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Define Context</h2>
                <p class="text-gray-500 mb-6">Tell us about your organization. This helps our AI suggest rules.</p>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Policy Name <span class="text-red-500">*</span></label>
                        <input type="text" id="pw-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. Global Standard, HR Safe Mode" value="${policyData.name}">
                    </div>

                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Organization Description</label>
                        <p class="text-xs text-gray-400 mb-2">E.g. "We are a Fintech company dealing with sensitive user data."</p>
                        <textarea id="pw-context" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="We are a...">${policyData.context}</textarea>
                    </div>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-blue-900/20 p-6 rounded-xl border border-blue-200 dark:border-blue-800 flex flex-col justify-center">
                <div class="mb-4 text-blue-600 dark:text-blue-400">
                    <svg class="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <h4 class="font-bold text-lg mb-2">Why does this matter?</h4>
                    <p class="text-sm leading-relaxed opacity-90 text-blue-800 dark:text-blue-200">
                        Unlike traditional chatbots that just "answer questions", SAFi uses a 
                        <strong>Governance Layer</strong>. 
                        By defining your organization's context here, we can auto-generate a "Constitution" 
                        that ensures every AI agent speaks with your brand's voice and obeys your safety rules.
                    </p>
                </div>
            </div>
        </div>
    `;

    // Listeners
    document.getElementById('pw-name')?.addEventListener('input', (e) => policyData.name = e.target.value);
    document.getElementById('pw-context')?.addEventListener('input', (e) => policyData.context = e.target.value);
}

export function validateDefinitionStep(policyData) {
    if (!policyData.name || !policyData.name.trim()) {
        alert("Policy Name is required");
        return false;
    }
    return true;
}
