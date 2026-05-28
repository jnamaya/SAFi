import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export function renderRulesStep(container, policyData) {
    container.innerHTML = `
        <div class="space-y-8">
            <div>
                <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Rules & Guardrails</h2>
                <p class="text-gray-500 text-sm">Define what this agent will never do and how it should behave at the boundaries.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

                <!-- HARD RULES -->
                <div class="bg-white dark:bg-neutral-900 border border-red-200 dark:border-red-900/50 rounded-xl p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div>
                            <h3 class="font-bold text-red-700 dark:text-red-400">Hard Rules</h3>
                            <p class="text-xs text-gray-500 mt-0.5">Absolute — intercepted before the user sees the response.</p>
                        </div>
                        <button id="btn-gen-rules" class="text-xs bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                            Suggest
                        </button>
                    </div>
                    <div class="flex gap-2 mb-3">
                        <input type="text" id="pw-rule-input"
                            class="flex-1 p-2.5 rounded-lg border border-red-200 dark:border-red-900/50 bg-gray-50 dark:bg-neutral-800 text-sm focus:ring-2 focus:ring-red-500 outline-none"
                            placeholder="The agent must never...">
                        <button id="pw-add-rule-btn" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-semibold transition-colors">Add</button>
                    </div>
                    <ul id="pw-rules-list" class="space-y-2"></ul>
                </div>

                <!-- GUARDRAILS -->
                <div class="bg-white dark:bg-neutral-900 border border-amber-200 dark:border-amber-900/50 rounded-xl p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div>
                            <h3 class="font-bold text-amber-700 dark:text-amber-400">Guardrails</h3>
                            <p class="text-xs text-gray-500 mt-0.5">Behavioral guidance — softer boundaries the agent should respect.</p>
                        </div>
                        <button id="btn-gen-guardrails" class="text-xs bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors font-medium">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                            Suggest
                        </button>
                    </div>
                    <div class="flex gap-2 mb-3">
                        <input type="text" id="pw-guardrail-input"
                            class="flex-1 p-2.5 rounded-lg border border-amber-200 dark:border-amber-900/50 bg-gray-50 dark:bg-neutral-800 text-sm focus:ring-2 focus:ring-amber-500 outline-none"
                            placeholder="Always recommend consulting...">
                        <button id="pw-add-guardrail-btn" class="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-sm font-semibold transition-colors">Add</button>
                    </div>
                    <ul id="pw-guardrails-list" class="space-y-2"></ul>
                </div>

            </div>

            <div class="bg-gray-50 dark:bg-neutral-800/50 border border-gray-200 dark:border-neutral-700 rounded-xl p-4 text-xs text-gray-500 dark:text-gray-400">
                <strong class="text-gray-700 dark:text-gray-300">Hard Rules vs Guardrails:</strong>
                Hard rules are enforced mechanically — a violation stops the response entirely. Guardrails shape behavior but allow the agent to use judgment. Use hard rules for legal and compliance lines, guardrails for tone and best-practice guidance.
            </div>
        </div>
    `;

    renderRulesList(policyData);
    renderGuardrailsList(policyData);

    // Hard rules
    const addRule = () => {
        const input = document.getElementById('pw-rule-input');
        const val = input.value.trim();
        if (val) { policyData.will_rules.push(val); input.value = ''; renderRulesList(policyData); }
    };
    document.getElementById('pw-add-rule-btn').addEventListener('click', addRule);
    document.getElementById('pw-rule-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addRule(); });

    document.getElementById('btn-gen-rules').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const orig = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block"></span>`;
        btn.disabled = true;
        try {
            const res = await api.generatePolicyContent('rules', policyData.context || policyData.name || 'General');
            if (res.ok && res.content) {
                let json = typeof res.content === 'string' ? JSON.parse(res.content) : res.content;
                if (Array.isArray(json)) {
                    policyData.will_rules = [...new Set([...policyData.will_rules, ...json.map(r => r.trim())])];
                    renderRulesList(policyData);
                    ui.showToast('Hard rules suggested!', 'success');
                }
            }
        } catch (err) { ui.showToast('Generation failed', 'error'); }
        btn.innerHTML = orig;
        btn.disabled = false;
    });

    // Guardrails
    const addGuardrail = () => {
        const input = document.getElementById('pw-guardrail-input');
        const val = input.value.trim();
        if (val) { policyData.guardrails.push(val); input.value = ''; renderGuardrailsList(policyData); }
    };
    document.getElementById('pw-add-guardrail-btn').addEventListener('click', addGuardrail);
    document.getElementById('pw-guardrail-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addGuardrail(); });

    document.getElementById('btn-gen-guardrails').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const orig = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block"></span>`;
        btn.disabled = true;
        try {
            const res = await api.generatePolicyContent('guardrails', policyData.context || policyData.name || 'General');
            if (res.ok && res.content) {
                let json = typeof res.content === 'string' ? JSON.parse(res.content) : res.content;
                if (Array.isArray(json)) {
                    policyData.guardrails = [...new Set([...policyData.guardrails, ...json.map(r => r.trim())])];
                    renderGuardrailsList(policyData);
                    ui.showToast('Guardrails suggested!', 'success');
                }
            }
        } catch (err) { ui.showToast('Generation failed', 'error'); }
        btn.innerHTML = orig;
        btn.disabled = false;
    });
}

function renderRulesList(policyData) {
    const list = document.getElementById('pw-rules-list');
    if (!list) return;
    list.innerHTML = policyData.will_rules.length
        ? ''
        : '<li class="text-sm text-gray-400 italic text-center py-2">No hard rules yet.</li>';

    policyData.will_rules.forEach((rule, idx) => {
        const li = document.createElement('li');
        li.className = 'flex items-center gap-2 p-2.5 bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 rounded-lg';
        li.innerHTML = `
            <svg class="w-4 h-4 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/></svg>
            <input type="text" value="${rule}" class="flex-1 bg-transparent text-sm text-red-900 dark:text-red-200 outline-none">
            <button class="text-red-300 hover:text-red-600 transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
        `;
        li.querySelector('input').addEventListener('change', (e) => policyData.will_rules[idx] = e.target.value);
        li.querySelector('button').addEventListener('click', () => { policyData.will_rules.splice(idx, 1); renderRulesList(policyData); });
        list.appendChild(li);
    });
}

function renderGuardrailsList(policyData) {
    const list = document.getElementById('pw-guardrails-list');
    if (!list) return;
    list.innerHTML = policyData.guardrails.length
        ? ''
        : '<li class="text-sm text-gray-400 italic text-center py-2">No guardrails yet.</li>';

    policyData.guardrails.forEach((g, idx) => {
        const li = document.createElement('li');
        li.className = 'flex items-center gap-2 p-2.5 bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-900/30 rounded-lg';
        li.innerHTML = `
            <svg class="w-4 h-4 text-amber-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
            <input type="text" value="${g}" class="flex-1 bg-transparent text-sm text-amber-900 dark:text-amber-200 outline-none">
            <button class="text-amber-300 hover:text-amber-600 transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
        `;
        li.querySelector('input').addEventListener('change', (e) => policyData.guardrails[idx] = e.target.value);
        li.querySelector('button').addEventListener('click', () => { policyData.guardrails.splice(idx, 1); renderGuardrailsList(policyData); });
        list.appendChild(li);
    });
}

export function validateRulesStep(policyData) {
    return true; // Rules optional — policy can be values-only
}
