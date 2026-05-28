import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export function renderScopeStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <div class="md:col-span-2 space-y-6">
                <div>
                    <div class="flex justify-between items-end mb-4">
                        <div>
                            <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Scope</h2>
                            <p class="text-gray-500 text-sm">Define what this agent is allowed to handle. Anything outside this boundary will be politely refused.</p>
                        </div>
                        <button id="btn-gen-scope" class="shrink-0 text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                            Draft with AI
                        </button>
                    </div>

                    <textarea id="pw-scope-statement"
                        class="w-full h-64 p-5 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-base leading-relaxed text-gray-800 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 outline-none resize-y"
                        placeholder="e.g. Employee benefits, PTO requests, onboarding, and workplace policies only. No legal advice or medical guidance.">${policyData.scope_statement || ''}</textarea>

                    <p class="text-xs text-gray-400 mt-2">One clear sentence describing what the agent can help with. Use "only" to make the boundary explicit.</p>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-neutral-800 p-6 rounded-2xl border border-blue-100 dark:border-neutral-700 h-fit sticky top-6">
                <h4 class="font-bold text-lg text-gray-800 dark:text-gray-200 mb-4">Writing a good scope</h4>
                <div class="space-y-4 text-sm text-gray-600 dark:text-gray-400">
                    <p>Scope is the agent's lane. It tells the agent what it owns and what to redirect.</p>

                    <div class="p-3 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700">
                        <strong class="block text-gray-900 dark:text-gray-200 mb-1">Good</strong>
                        <span class="text-xs">"STEM education only — math, physics, chemistry, biology, engineering."</span>
                    </div>
                    <div class="p-3 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700">
                        <strong class="block text-gray-900 dark:text-gray-200 mb-1">Better</strong>
                        <span class="text-xs">"HR employee questions only — benefits, PTO, onboarding, workplace policies. No legal or medical advice."</span>
                    </div>

                    <p class="text-xs text-gray-400 leading-relaxed">Tip: Naming what's <em>excluded</em> at the end helps the agent refuse confidently.</p>
                </div>
            </div>
        </div>
    `;

    document.getElementById('pw-scope-statement')?.addEventListener('input', (e) => {
        policyData.scope_statement = e.target.value;
    });

    document.getElementById('btn-gen-scope')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block"></span> Drafting...`;
        btn.disabled = true;
        try {
            const ctx = policyData.context || policyData.business_unit || policyData.name || "General business unit";
            const res = await api.generatePolicyContent('scope', ctx);
            if (res.ok && res.content) {
                const text = typeof res.content === 'string' ? res.content.trim() : '';
                if (text) {
                    document.getElementById('pw-scope-statement').value = text;
                    policyData.scope_statement = text;
                    ui.showToast('Scope drafted!', 'success');
                }
            }
        } catch (err) {
            ui.showToast('Generation failed', 'error');
        }
        btn.innerHTML = original;
        btn.disabled = false;
    });
}

export function validateScopeStep(policyData) {
    return true; // Scope is optional but recommended
}
