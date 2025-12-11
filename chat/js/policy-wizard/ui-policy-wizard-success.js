import * as ui from './../ui.js';

export function renderSuccessStep(container, policyData, generatedCredentials) {
    if (!generatedCredentials) {
        container.innerHTML = `<div class="text-red-500 text-center">Error: No credentials returned.</div>`;
        return;
    }

    const { policy_id, api_key } = generatedCredentials;
    const publicUrl = "https://safi.selfalignmentfrmework.com";
    const endpointUrl = `${publicUrl}/api/bot/process_prompt`;

    container.innerHTML = `
        <div class="text-center py-8">
            <div class="w-20 h-20 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-6">
                <svg class="w-10 h-10 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-3xl font-bold mb-2 text-gray-900 dark:text-white">Policy Active!</h2>
            <p class="text-gray-500 text-lg">Your governance firewall is ready.</p>
        </div>

        <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 text-left">
            <h4 class="font-bold text-lg mb-4 text-gray-800 dark:text-gray-200">Integration Credentials</h4>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Public Endpoint</label>
                    <code class="block p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-xs truncate text-gray-600 dark:text-gray-300" title="${endpointUrl}">${endpointUrl}</code>
                </div>
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">API Key</label>
                    <div class="flex gap-2">
                        <code class="flex-1 p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm text-green-600 font-bold truncate">${api_key}</code>
                        <button class="px-3 bg-gray-200 hover:bg-gray-300 dark:bg-neutral-700 dark:hover:bg-neutral-600 rounded text-black dark:text-white font-bold transition-colors" onclick="navigator.clipboard.writeText('${api_key}'); ui.showToast('Copied!', 'success');">Copy</button>
                    </div>
                </div>
            </div>
            
             <div class="mt-6 pt-6 border-t border-gray-200 dark:border-neutral-700 text-center">
                 <button onclick="window.location.reload()" class="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-bold">Done</button>
             </div>
        </div>
    `;
}
