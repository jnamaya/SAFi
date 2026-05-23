export function renderReviewStep(container, policyData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Review</h2>
        <p class="text-gray-500 mb-6">Your policy is ready. Review the details below before activating it for your agents.</p>

        <div class="space-y-6">

            <div class="bg-blue-50 dark:bg-blue-900/10 rounded-lg p-6 border border-blue-100 dark:border-blue-800/30">
                <h3 class="font-bold text-xl text-blue-900 dark:text-blue-100 mb-1">${policyData.name || 'Untitled Policy'}</h3>
                <p class="text-sm text-blue-700 dark:text-blue-300 opacity-80">${policyData.context || 'No description provided.'}</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                    <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">Summary</h4>
                    <ul class="space-y-2 text-sm">
                        <li class="flex justify-between items-center bg-gray-50 dark:bg-neutral-800 p-2 rounded">
                            <span>Mission</span>
                            <span class="font-mono font-bold">${policyData.worldview ? policyData.worldview.length + ' chars' : 'Empty'}</span>
                        </li>
                        <li class="flex justify-between items-center bg-gray-50 dark:bg-neutral-800 p-2 rounded">
                            <span>Core Values</span>
                            <span class="font-mono font-bold">${policyData.values.length}</span>
                        </li>
                    </ul>
                </div>

                <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-4">
                    <h4 class="font-bold text-sm text-gray-500 uppercase mb-3">Core Values</h4>
                    <ul class="text-sm space-y-1 list-disc list-inside text-gray-700 dark:text-gray-300">
                        ${policyData.values.slice(0, 3).map(v => `<li>${v.name}</li>`).join('')}
                        ${policyData.values.length > 3 ? `<li class="text-gray-400">...and ${policyData.values.length - 3} more</li>` : ''}
                        ${policyData.values.length === 0 ? `<li class="text-gray-400 list-none italic">No values defined.</li>` : ''}
                    </ul>
                </div>
            </div>

        </div>
    `;
}

export function validateReviewStep(policyData) {
    return true;
}
