import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export function renderConstitutionStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <div class="md:col-span-2 space-y-6">
                 <div>
                    <div class="flex justify-between items-end mb-4">
                         <div>
                            <label class="block text-2xl font-bold text-gray-900 dark:text-white mb-2">Global Worldview</label>
                            <p class="text-base text-gray-500 mb-4">The AI's core persona, tone, and your organization's mission.</p>
                         </div>
                         <button id="btn-gen-worldview" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-full flex items-center gap-2 transition-colors shadow-sm text-sm font-medium">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Draft with AI
                         </button>
                    </div>
                    <div class="relative">
                        <textarea id="pw-worldview" class="w-full h-[500px] p-6 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 font-mono text-base leading-relaxed text-gray-800 dark:text-gray-200 focus:ring-2 focus:ring-purple-500 shadow-sm resize-y" placeholder="You are an AI assistant governed by...
                        
Mission:
To serve the user while strictly adhering to safety protocols...

Tone:
Professional, concise, and objective...">${policyData.worldview}</textarea>
                        

                    </div>
                </div>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 p-8 rounded-2xl border border-gray-200 dark:border-neutral-700 h-fit">
                <h4 class="font-bold text-xl text-gray-800 dark:text-gray-200 mb-6 flex items-center gap-2">
                    <svg class="w-6 h-6 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    Expert Tips
                </h4>
                <ul class="space-y-6 text-sm text-gray-600 dark:text-gray-400">
                    <li>
                        <strong class="block text-gray-900 dark:text-gray-200 mb-1">The "Job Description"</strong>
                        This is the first prompt the AI sees. It defines who it is (e.g. "a helpful medical assistant") and who it serves.
                    </li>
                    <li>
                        <strong class="block text-gray-900 dark:text-gray-200 mb-1">Tone & Voice</strong>
                         Be specific. "Friendly but professional" is better than just "Nice".
                    </li>
                </ul>
            </div>
        </div>
    `;

    // Bind Handlers
    document.getElementById('pw-worldview')?.addEventListener('input', (e) => policyData.worldview = e.target.value);

    // GEN WORLDVIEW
    document.getElementById('btn-gen-worldview')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Generating...`;
        btn.disabled = true;

        try {
            const res = await api.generatePolicyContent('worldview', policyData.context || "General Organization");
            if (res.ok && res.content) {
                document.getElementById('pw-worldview').value = res.content;
                policyData.worldview = res.content;
                ui.showToast("Worldview generated!", "success");
            } else {
                ui.showToast("Failed to generate worldview", "error");
            }
        } catch (err) { console.error(err); }
        btn.innerHTML = original;
        btn.disabled = false;
    });
}

export function validateConstitutionStep(policyData) {
    if (!policyData.worldview || policyData.worldview.length < 10) {
        ui.showToast("A Worldview is required (at least 10 chars).", "error");
        return false;
    }
    return true;
}
