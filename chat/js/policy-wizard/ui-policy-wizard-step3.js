import * as api from './../api.js';
import * as ui from './../ui.js';

export function renderRulesStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div class="md:col-span-2">
                <div class="flex justify-between items-center mb-4">
                     <div>
                        <h2 class="text-2xl font-bold text-gray-900 dark:text-white">Rules (Non-Negotiable)</h2>
                        <p class="text-gray-500 text-sm">These are absolute boundaries. The AI will strictly reject any user request that violates these rules.</p>
                     </div>
                     <button id="btn-gen-rules" class="text-xs bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-full flex items-center gap-1 transition-colors shadow">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Suggest Rules
                     </button>
                </div>
                
                <div class="flex gap-4 mb-6">
                    <input type="text" id="pw-rule-input" class="flex-1 p-3 rounded-lg border border-red-200 dark:border-red-900/50 bg-white dark:bg-neutral-800 focus:ring-2 focus:ring-red-500 placeholder-gray-400" placeholder="e.g. Reject financial advice.">
                    <button id="pw-add-rule-btn" class="px-6 py-2 bg-red-600 text-white rounded-lg font-semibold hover:bg-red-700 transition-colors">
                        Block
                    </button>
                </div>

                <ul id="pw-rules-list" class="space-y-2"></ul>
            </div>

            <div class="bg-red-50 dark:bg-red-900/10 p-6 rounded-xl border border-red-200 dark:border-red-800/50 h-fit">
                <h4 class="font-bold text-red-700 dark:text-red-400 mb-4 flex items-center gap-2">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                    When to use this?
                </h4>
                <p class="text-xs text-red-800/80 dark:text-red-200/80 mb-4 leading-relaxed">
                    <strong>Rules (Non-Negotiable)</strong> are hard stops.
                </p>
                <p class="text-xs text-red-800/80 dark:text-red-200/80 leading-relaxed">
                    If a user asks the AI to break a rule here, the system <strong>intercepts and blocks</strong> the request entirely. Use this for legal or safety boundaries where no flexibility is allowed.
                </p>
            </div>
        </div>
    `;

    renderRulesList(policyData);

    // Handlers
    const addRule = () => {
        const input = document.getElementById('pw-rule-input');
        const rule = input.value.trim();
        if (rule) {
            policyData.will_rules.push(rule);
            input.value = '';
            renderRulesList(policyData);
        }
    };

    document.getElementById('pw-add-rule-btn').addEventListener('click', addRule);
    document.getElementById('pw-rule-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addRule();
    });

    document.getElementById('btn-gen-rules').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block"></span>`;
        btn.disabled = true;

        try {
            const res = await api.generatePolicyContent('rules', policyData.context || "General Organization");
            if (res.ok && res.content) {
                let json;
                if (typeof res.content === 'string') {
                    try { json = JSON.parse(res.content); } catch { json = [res.content]; }
                } else {
                    json = res.content;
                }

                if (Array.isArray(json)) {
                    const processedRules = json.map(r => {
                        let clean = r.trim().replace(/^(The AI should|The AI must|Must|Will|Always)\s+/i, "");
                        if (!clean.match(/^(Reject|Require|Flag|Do not)/i)) return "Reject " + clean;
                        return clean.charAt(0).toUpperCase() + clean.slice(1);
                    });
                    policyData.will_rules = [...new Set([...policyData.will_rules, ...processedRules])];
                    renderRulesList(policyData);
                }
            }
        } catch (err) { console.error(err); }
        btn.innerHTML = original;
        btn.disabled = false;
    });
}

function renderRulesList(policyData) {
    const list = document.getElementById('pw-rules-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.will_rules.length === 0) {
        list.innerHTML = `<p class="text-sm text-gray-400 text-center italic py-2">No hard rules yet.</p>`;
        return;
    }

    policyData.will_rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-3 bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 rounded-lg shadow-sm group hover:border-red-300 transition-colors";

        item.innerHTML = `
            <div class="flex-1 flex items-center gap-3">
                <svg class="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
                <input type="text" 
                    id="pw-rule-val-${idx}"
                    class="w-full bg-transparent border-none focus:ring-0 p-1 text-sm font-medium text-red-900 dark:text-red-200 placeholder-red-300" 
                    value="${rule}" 
                    placeholder="Rule definition...">
            </div>
            <button class="text-red-300 hover:text-red-600 dark:hover:text-red-400 transition-colors" onclick="window.removePolicyRule(${idx})">
                 <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
        `;
        list.appendChild(item);

        item.querySelector(`#pw-rule-val-${idx}`).addEventListener('change', (e) => policyData.will_rules[idx] = e.target.value);
    });

    window.removePolicyRule = (idx) => {
        policyData.will_rules.splice(idx, 1);
        renderRulesList(policyData);
    };
}

export function validateRulesStep(policyData) {
    return true;
}
