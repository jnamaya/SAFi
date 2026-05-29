export function renderGovernanceStep(container, policyData) {
    // Hydrate defaults
    if (policyData.alignment_threshold === undefined) policyData.alignment_threshold = 0.5;
    if (policyData.ethical_memory === undefined)      policyData.ethical_memory      = 0.90;

    const threshPct = Math.round(policyData.alignment_threshold * 100);
    const memPct    = Math.round(policyData.ethical_memory      * 100);

    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">

            <!-- SLIDERS -->
            <div class="space-y-8">
                <div>
                    <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Review &amp; Settings</h2>
                    <p class="text-gray-500 text-sm">Two final dials, plus a summary of everything in this policy. Review it, then save.</p>
                </div>

                <div class="bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 rounded-xl p-6 space-y-8">

                    <div>
                        <div class="flex justify-between items-end mb-2">
                            <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Minimum approval score</label>
                            <span id="lbl-pw-thresh" class="text-sm font-mono bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">${policyData.alignment_threshold.toFixed(2)}</span>
                        </div>
                        <input type="range" id="sl-pw-thresh" min="0" max="100" value="${threshPct}"
                            class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600">
                        <div class="flex justify-between text-xs text-gray-400 mt-1.5">
                            <span>Permissive (0.0)</span>
                            <span>Strict (1.0)</span>
                        </div>
                        <p class="text-xs text-gray-400 mt-2">How well a response must score against your standards to be approved. A response that scores below this is rewritten once; if it still falls short, it's replaced with a safe, on-policy reply. Default: 0.5.</p>
                    </div>

                    <div>
                        <div class="flex justify-between items-end mb-2">
                            <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Consistency over time</label>
                            <span id="lbl-pw-mem" class="text-sm font-mono bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">${policyData.ethical_memory.toFixed(2)}</span>
                        </div>
                        <input type="range" id="sl-pw-mem" min="10" max="99" value="${memPct}"
                            class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-purple-600">
                        <div class="flex justify-between text-xs text-gray-400 mt-1.5">
                            <span>Adapts fast (0.10)</span>
                            <span>Resists change (0.99)</span>
                        </div>
                        <p class="text-xs text-gray-400 mt-2">How much the agent's past behavior steadies its character. Higher means it stays consistent and changes slowly; lower means it adapts quickly to recent interactions. Default: 0.90.</p>
                    </div>

                </div>
            </div>

            <!-- REVIEW SUMMARY -->
            <div class="space-y-4">
                <h3 class="text-lg font-semibold text-gray-700 dark:text-gray-300">Policy Summary</h3>

                <div class="bg-blue-50 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-800/30 rounded-xl p-4">
                    <h4 class="font-bold text-lg text-blue-900 dark:text-blue-100">${escapeHtml(policyData.name || 'Untitled Policy')}</h4>
                    ${policyData.business_unit ? `<p class="text-xs text-blue-600 dark:text-blue-400 mt-0.5">${escapeHtml(policyData.business_unit)}</p>` : ''}
                    <p class="text-sm text-blue-700 dark:text-blue-300 opacity-80 mt-1">${escapeHtml(policyData.context || 'No description.')}</p>
                </div>

                <div class="space-y-2 text-sm">
                    ${summaryRow('Purpose & Voice', policyData.worldview ? policyData.worldview.length + ' chars' : '—', policyData.worldview)}
                    ${summaryRow('Scope', policyData.scope_statement ? policyData.scope_statement.length + ' chars' : '—', policyData.scope_statement)}
                    ${summaryRow('Standards', (policyData.values || []).length, (policyData.values || []).length > 0)}
                    ${summaryRow('Non-negotiable standards', (policyData.values || []).filter(v => v.hard_gate).length, (policyData.values || []).some(v => v.hard_gate), 'red')}
                    ${summaryRow('Required disclaimer', policyData.structural_requirements?.require_disclaimer ? 'On' : '—', policyData.structural_requirements?.require_disclaimer)}
                    ${summaryRow('Prohibited formatting', (policyData.structural_requirements?.banned_markdown_syntaxes || []).length, (policyData.structural_requirements?.banned_markdown_syntaxes || []).length > 0)}
                    ${summaryRow('Authorized tools', (policyData.allowed_tools || []).length, (policyData.allowed_tools || []).length > 0)}
                    ${summaryRow('Written rules', (policyData.will_rules || []).length, (policyData.will_rules || []).length > 0)}
                </div>
            </div>

        </div>
    `;

    const slThresh = document.getElementById('sl-pw-thresh');
    const lblThresh = document.getElementById('lbl-pw-thresh');
    slThresh?.addEventListener('input', (e) => {
        const v = parseInt(e.target.value) / 100;
        policyData.alignment_threshold = v;
        lblThresh.textContent = v.toFixed(2);
    });

    const slMem = document.getElementById('sl-pw-mem');
    const lblMem = document.getElementById('lbl-pw-mem');
    slMem?.addEventListener('input', (e) => {
        const v = parseInt(e.target.value) / 100;
        policyData.ethical_memory = v;
        lblMem.textContent = v.toFixed(2);
    });
}

function summaryRow(label, value, hasValue, color) {
    const cls = hasValue
        ? (color === 'red' ? 'text-red-600' : 'text-gray-700 dark:text-gray-300')
        : 'text-gray-400';
    return `
        <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
            <span class="text-gray-600 dark:text-gray-400">${escapeHtml(label)}</span>
            <span class="font-mono font-bold ${cls}">${escapeHtml(String(value))}</span>
        </div>
    `;
}

function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

export function validateGovernanceStep(_policyData) {
    return true;
}
