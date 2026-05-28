export function renderGovernanceStep(container, policyData) {
    const authPct  = Math.round((policyData.org_authority  ?? 0.60) * 100);
    const memPct   = Math.round((policyData.ethical_memory ?? 0.90) * 100);

    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">

            <!-- GOVERNANCE SLIDERS -->
            <div class="space-y-8">
                <div>
                    <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Governance & Review</h2>
                    <p class="text-gray-500 text-sm">Set the governance parameters for this policy, then review before saving.</p>
                </div>

                <div class="bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 rounded-xl p-6 space-y-8">

                    <div>
                        <div class="flex justify-between items-end mb-2">
                            <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Policy Authority</label>
                            <span id="lbl-pw-auth" class="text-sm font-mono bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">${authPct}%</span>
                        </div>
                        <input type="range" id="sl-pw-auth" min="0" max="100" value="${authPct}"
                            class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600">
                        <div class="flex justify-between text-xs text-gray-400 mt-1.5">
                            <span>Agent Autonomy (0%)</span>
                            <span>Strict Compliance (100%)</span>
                        </div>
                        <p class="text-xs text-gray-400 mt-2">How much this policy's rules override the agent's own judgment. Higher = stricter enforcement.</p>
                    </div>

                    <div>
                        <div class="flex justify-between items-end mb-2">
                            <label class="text-sm font-bold text-gray-700 dark:text-gray-300">Ethical Memory</label>
                            <span id="lbl-pw-mem" class="text-sm font-mono bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">${(memPct / 100).toFixed(2)}</span>
                        </div>
                        <input type="range" id="sl-pw-mem" min="10" max="99" value="${memPct}"
                            class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-purple-600">
                        <div class="flex justify-between text-xs text-gray-400 mt-1.5">
                            <span>Adapts fast (0.1)</span>
                            <span>Resists change (0.99)</span>
                        </div>
                        <p class="text-xs text-gray-400 mt-2">How heavily the agent weighs past interactions. High values mean long-term consistency; low values mean faster adaptation.</p>
                    </div>

                </div>
            </div>

            <!-- REVIEW SUMMARY -->
            <div class="space-y-4">
                <h3 class="text-lg font-semibold text-gray-700 dark:text-gray-300">Policy Summary</h3>

                <div class="bg-blue-50 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-800/30 rounded-xl p-4">
                    <h4 class="font-bold text-lg text-blue-900 dark:text-blue-100">${policyData.name || 'Untitled Policy'}</h4>
                    ${policyData.business_unit ? `<p class="text-xs text-blue-600 dark:text-blue-400 mt-0.5">${policyData.business_unit}</p>` : ''}
                    <p class="text-sm text-blue-700 dark:text-blue-300 opacity-80 mt-1">${policyData.context || 'No description.'}</p>
                </div>

                <div class="space-y-2 text-sm">

                    <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
                        <span class="text-gray-600 dark:text-gray-400">Worldview</span>
                        <span class="font-mono font-bold text-gray-700 dark:text-gray-300">${policyData.worldview ? policyData.worldview.length + ' chars' : '—'}</span>
                    </div>
                    <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
                        <span class="text-gray-600 dark:text-gray-400">Core Values</span>
                        <span class="font-mono font-bold text-gray-700 dark:text-gray-300">${policyData.values.length}</span>
                    </div>
                    <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
                        <span class="text-gray-600 dark:text-gray-400">Scope</span>
                        <span class="font-mono font-bold ${policyData.scope_statement ? 'text-gray-700 dark:text-gray-300' : 'text-gray-400'}">${policyData.scope_statement ? policyData.scope_statement.length + ' chars' : '—'}</span>
                    </div>
                    <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
                        <span class="text-gray-600 dark:text-gray-400">Hard Rules</span>
                        <span class="font-mono font-bold ${policyData.will_rules.length ? 'text-red-600' : 'text-gray-400'}">${policyData.will_rules.length}</span>
                    </div>
                    <div class="flex justify-between items-center p-3 bg-gray-50 dark:bg-neutral-800 rounded-lg border border-gray-100 dark:border-neutral-700">
                        <span class="text-gray-600 dark:text-gray-400">Guardrails</span>
                        <span class="font-mono font-bold ${policyData.guardrails.length ? 'text-amber-600' : 'text-gray-400'}">${policyData.guardrails.length}</span>
                    </div>

                </div>
            </div>

        </div>
    `;

    const slAuth = document.getElementById('sl-pw-auth');
    const lblAuth = document.getElementById('lbl-pw-auth');
    slAuth?.addEventListener('input', (e) => {
        const pct = parseInt(e.target.value);
        policyData.org_authority = pct / 100;
        lblAuth.textContent = pct + '%';
    });

    const slMem = document.getElementById('sl-pw-mem');
    const lblMem = document.getElementById('lbl-pw-mem');
    slMem?.addEventListener('input', (e) => {
        const val = parseInt(e.target.value) / 100;
        policyData.ethical_memory = val;
        lblMem.textContent = val.toFixed(2);
    });
}

export function validateGovernanceStep(policyData) {
    return true;
}
