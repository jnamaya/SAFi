import * as api from '../../core/api.js';
import * as ui from './../ui.js';
import { renderModelSelector } from './ui-wizard-utils.js';

export function renderWillStep(container, agentData, availableModels) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
            <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Rules (Non-Negotiable)</h2>
                <p class="text-gray-500 text-sm">Hard rules. If the Intellect violates these, the Will forces a rewrite.</p>
            </div>
             <div class="flex flex-col items-end gap-2">
                <div>
                     <label class="block text-xs font-bold text-gray-500 uppercase text-right mb-1">AI Model</label>
                     <div id="will-model-container"></div>
                </div>
                <button id="wiz-gen-rules-btn" class="text-xs bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-full flex items-center gap-1 transition-colors shadow">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                    Suggest Rules
                </button>
            </div>
        </div>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="wiz-rule-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. Do not create Python scripts.">
            <button id="wiz-add-rule-btn" class="px-6 py-2 bg-neutral-800 dark:bg-neutral-700 text-white rounded-lg font-semibold hover:bg-black transition-colors shadow">
                Add Rule
            </button>
        </div>

        <ul id="wiz-rules-list" class="space-y-2">
            <!-- Rules go here -->
        </ul>
    `;

    // Inject Model Selector
    const modelContainer = document.getElementById('will-model-container');
    if (modelContainer) {
        modelContainer.innerHTML = renderModelSelector('wiz-will-model', agentData.will_model || '', 'support', availableModels);
        document.getElementById('wiz-will-model')?.addEventListener('change', (e) => agentData.will_model = e.target.value);
    }

    renderRulesList(agentData);

    // Add Manual Rule
    const addRule = () => {
        const input = document.getElementById('wiz-rule-input');
        const rule = input.value.trim();
        if (rule) {
            agentData.rules.push(rule);
            input.value = '';
            renderRulesList(agentData);
        }
    };

    document.getElementById('wiz-add-rule-btn').addEventListener('click', addRule);
    document.getElementById('wiz-rule-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addRule();
    });

    // Generate Rules Handler
    document.getElementById('wiz-gen-rules-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Analyzing...`;
        btn.disabled = true;

        try {
            // Use instructions (Step 3) as context, fallback to description (Step 1)
            const context = agentData.instructions || agentData.description || "General Assistant";
            const res = await api.generatePolicyContent('rules', context);

            if (res.ok && res.content) {
                let newRules = parseRulesOutput(res.content);

                if (newRules.length > 0) {
                    // Merge unique
                    agentData.rules = [...new Set([...agentData.rules, ...newRules])];
                    renderRulesList(agentData);
                    ui.showToast(`Added ${newRules.length} rules`, "success");
                }
            } else {
                ui.showToast("Failed to generate rules", "error");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("Generation error", "error");
        } finally {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    });
}

function parseRulesOutput(content) {
    let newRules = [];
    try {
        if (Array.isArray(content)) {
            newRules = content;
        } else if (typeof content === 'string') {
            try {
                const json = JSON.parse(content);
                if (Array.isArray(json)) newRules = json;
            } catch (e) {
                newRules = content.split('\n').filter(l => l.trim().length > 0);
            }
        }

        // Standardize format (Action-First)
        return newRules.map(r => {
            let clean = r.trim();
            clean = clean.replace(/^(The AI should|The AI must|The agent should|The agent must|Must|Will|Always)\s+/i, "");

            if (clean.match(/^(Refuse|Decline|Deny)\s+to\s+/i)) {
                clean = clean.replace(/^(Refuse|Decline|Deny)\s+to\s+/i, "Reject requests to ");
            }
            else if (clean.match(/^Never\s+/i)) {
                clean = clean.replace(/^Never\s+/i, "Reject requests to ");
            }

            if (!clean.match(/^(Reject|Require|Flag|Do not)/i)) {
                return "Reject " + clean;
            }

            return clean.charAt(0).toUpperCase() + clean.slice(1);
        });
    } catch (e) {
        console.error("Rules parsing error", e);
        return [];
    }
}

function renderRulesList(agentData) {
    const list = document.getElementById('wiz-rules-list');
    if (!list) return;
    list.innerHTML = '';

    agentData.rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-2 bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg shadow-sm group hover:border-red-300 transition-colors";

        // Editable Input
        item.innerHTML = `
            <div class="flex-1 flex items-center gap-3">
                <span class="text-lg">⛔</span>
                <input type="text" 
                    class="w-full bg-transparent border-none focus:ring-0 p-1 text-sm font-medium text-gray-800 dark:text-gray-200 placeholder-gray-400" 
                    value="${rule}" 
                    onchange="window.updateRule(${idx}, this.value)"
                    placeholder="Rule definition...">
            </div>
            <button class="text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity p-2" onclick="window.removeRule(${idx})">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        `;
        list.appendChild(item);
    });

    window.updateRule = (idx, val) => {
        agentData.rules[idx] = val;
    };

    window.removeRule = (idx) => {
        agentData.rules.splice(idx, 1);
        renderRulesList(agentData);
    };
}

export function validateWillStep(agentData) {
    if (!agentData.rules || agentData.rules.length === 0) {
        ui.showToast("Please add at least one rule to define the agent's operational constraints.", "error");
        return false;
    }
    return true;
}
