export function renderReviewStep(container, policyData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Review & Create</h2>
        <p class="text-gray-500 mb-6">Review your policy rules before enabling this governance layer.</p>

        <div class="space-y-6">
            
            <div class="bg-blue-50 dark:bg-blue-900/10 rounded-lg p-6 border border-blue-100 dark:border-blue-800/30">
                 <h3 class="font-bold text-xl text-blue-900 dark:text-blue-100 mb-1">${policyData.name || 'Untitled Policy'}</h3>
                 <p class="text-sm text-blue-700 dark:text-blue-300 opacity-80">${policyData.context || 'No context description.'}</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                     <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">Constitution</h4>
                     <div class="text-xs text-gray-600 dark:text-gray-400 mb-2">
                        <strong>Worldview Length:</strong> ${policyData.worldview ? policyData.worldview.length + ' chars' : 'Empty'}
                     </div>
                     <ul class="space-y-2 text-sm">
                        <li class="flex justify-between items-center bg-gray-50 dark:bg-neutral-800 p-2 rounded">
                            <span>Core Values</span>
                            <span class="font-mono font-bold">${policyData.values.length}</span>
                        </li>
                        <li class="flex justify-between items-center bg-red-50 dark:bg-red-900/10 p-2 rounded">
                            <span class="text-red-700 dark:text-red-300">Hard Rules (Will)</span>
                            <span class="font-mono font-bold text-red-700 dark:text-red-300">${policyData.will_rules.length}</span>
                        </li>
                     </ul>
                </div>

                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                    <h4 class="font-bold text-sm text-gray-500 uppercase mb-2">Detailed Preview</h4>
                    <p class="text-xs text-gray-400 italic mb-2">First 3 values:</p>
                    <ul class="text-xs space-y-1 list-disc list-inside text-gray-700 dark:text-gray-300">
                        ${policyData.values.slice(0, 3).map(v => `<li>${v.name}</li>`).join('')}
                        ${policyData.values.length > 3 ? `<li>...and ${policyData.values.length - 3} more</li>` : ''}
                    </ul>
                </div>
            </div>

        </div>
    `;
}

export function validateReviewStep(policyData) {
    return true;
}
