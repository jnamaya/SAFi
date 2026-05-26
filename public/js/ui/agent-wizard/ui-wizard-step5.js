import * as api from '../../core/api.js';
import * as ui from '../ui.js';

const CODE_BLOCK_OPTIONS = [
    { label: "Python",          value: "```python" },
    { label: "JavaScript",      value: "```javascript" },
    { label: "Bash / Shell",    value: "```bash" },
    { label: "HTML",            value: "```html" },
    { label: "SQL",             value: "```sql" },
    { label: "All code blocks", value: "```" },
];

function getWillRules(agentData) {
    if (!agentData.will_rules || typeof agentData.will_rules !== 'object' || Array.isArray(agentData.will_rules)) {
        agentData.will_rules = {
            structural_requirements: { require_disclaimer: false, mandatory_disclaimer_substring: "", allowed_markdown_syntaxes: [] },
            early_prompt_blacklist: []
        };
    }
    if (!agentData.will_rules.structural_requirements) {
        agentData.will_rules.structural_requirements = { require_disclaimer: false, mandatory_disclaimer_substring: "", allowed_markdown_syntaxes: [] };
    }
    // Migrate legacy banned_markdown_syntaxes agents on first open
    const sr = agentData.will_rules.structural_requirements;
    if (sr.banned_markdown_syntaxes !== undefined && sr.allowed_markdown_syntaxes === undefined) {
        sr.allowed_markdown_syntaxes = [];
        delete sr.banned_markdown_syntaxes;
    }
    return sr;
}

export function renderSafetyStep(container, agentData) {
    const sr = getWillRules(agentData);
    const requireDisclaimer = !!sr.require_disclaimer;
    const disclaimerSubstring = sr.mandatory_disclaimer_substring || "";
    const allowedSyntaxes = sr.allowed_markdown_syntaxes || [];
    const alignmentThreshold = sr.alignment_score_threshold !== undefined ? sr.alignment_score_threshold : '';
    const hasValues = agentData.values && agentData.values.length > 0;
    const scopeStatement = agentData.scope_statement || "";
    const maxTurns = agentData.max_agent_turns || '';

    // Build code-block checkboxes (zero-trust whitelist: checked = ALLOWED)
    const codeCheckboxesHtml = CODE_BLOCK_OPTIONS.map(function(opt) {
        const checked = allowedSyntaxes.indexOf(opt.value) !== -1 ? 'checked' : '';
        const safeValue = opt.value.replace(/"/g, '&quot;');
        return '<label class="flex items-center gap-2.5 text-sm cursor-pointer p-2.5 rounded-lg border border-transparent hover:border-gray-200 dark:hover:border-neutral-700 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors">'
             + '<input type="checkbox" class="code-block-check w-4 h-4 rounded accent-blue-600" data-value="' + safeValue + '" ' + checked + '>'
             + '<span class="font-mono text-xs text-gray-700 dark:text-gray-300">' + opt.label + '</span>'
             + '</label>';
    }).join('');

    // Build hard-gate rows separately
    let hardGatesHtml = '';
    if (hasValues) {
        const rows = agentData.values.map(function(v, i) {
            const checked = v.hard_gate ? 'checked' : '';
            const name = (v.name || 'Value').replace(/</g, '&lt;');
            const desc = (v.description || '').replace(/</g, '&lt;');
            return '<label class="flex items-start gap-3 p-3 rounded-lg border border-gray-100 dark:border-neutral-700 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer transition-colors">'
                 + '<input type="checkbox" class="hard-gate-check w-4 h-4 mt-0.5 rounded accent-red-600 flex-shrink-0" data-index="' + i + '" ' + checked + '>'
                 + '<div class="min-w-0">'
                 + '<p class="text-sm font-semibold text-gray-800 dark:text-white">' + name + '</p>'
                 + '<p class="text-xs text-gray-500 truncate">' + desc + '</p>'
                 + '</div>'
                 + '</label>';
        }).join('');

        hardGatesHtml = '<div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">'
            + '<h4 class="font-semibold text-gray-800 dark:text-white mb-1">Hard Gates</h4>'
            + '<p class="text-xs text-gray-500 mb-4">A hard gate immediately blocks a response if Conscience scores that value at −1. Use only for non-negotiable ethical lines.</p>'
            + '<div class="space-y-2">' + rows + '</div>'
            + '</div>';
    } else {
        hardGatesHtml = '<div class="border border-dashed border-gray-200 dark:border-neutral-700 rounded-lg p-5 text-center text-sm text-gray-400">'
            + 'No values defined — go back to step 4 to add values before configuring hard gates.'
            + '</div>';
    }

    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Guardrails &amp; Governance</h2>
        <p class="text-gray-500 mb-6">Deterministic checks Will enforces on every response — these run before any AI evaluation.</p>

        <div class="space-y-5">

            <!-- Scope Compliance -->
            <div class="border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 rounded-lg p-5">
                <div class="flex items-start justify-between gap-3 mb-3">
                    <div class="flex items-start gap-3">
                        <svg class="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                        <div>
                            <h4 class="font-semibold text-blue-900 dark:text-blue-100">Scope Compliance</h4>
                            <p class="text-xs text-blue-700 dark:text-blue-300 mt-0.5">Define what this agent is allowed to discuss. Off-topic requests are blocked before any LLM call — no tokens wasted, no jailbreaks possible through out-of-scope framing.</p>
                        </div>
                    </div>
                    <button id="btn-generate-scope" class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Generate
                    </button>
                </div>
                <textarea id="scope-statement-input" rows="3"
                    class="w-full px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-blue-200 dark:border-blue-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                    placeholder="e.g. HR policy questions, benefits enrollment, and employee handbook topics only. No medical, legal, or financial advice.">${scopeStatement}</textarea>
                <p class="text-xs text-blue-600 dark:text-blue-400 mt-1.5">Leave blank to allow any topic. When set, Conscience scores every response against this boundary as a hard gate.</p>
            </div>

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <div class="flex items-center justify-between">
                    <div>
                        <h4 class="font-semibold text-gray-800 dark:text-white">Mandatory Disclaimer</h4>
                        <p class="text-xs text-gray-500 mt-0.5">Require every response to contain a specific disclaimer sentence.</p>
                    </div>
                    <label class="relative inline-flex items-center cursor-pointer flex-shrink-0 ml-4">
                        <input type="checkbox" id="require-disclaimer-toggle" class="sr-only peer" ${requireDisclaimer ? 'checked' : ''}>
                        <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-neutral-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
                    </label>
                </div>
                <div id="disclaimer-text-section" class="${requireDisclaimer ? '' : 'hidden'} mt-4 pt-4 border-t border-gray-100 dark:border-neutral-700">
                    <label class="block text-xs font-semibold text-gray-600 dark:text-gray-400 mb-2">Response must contain this text (exact substring match):</label>
                    <textarea id="disclaimer-substring" rows="2"
                        class="w-full px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none resize-none font-mono"
                        placeholder="e.g. This information is for educational purposes only...">${disclaimerSubstring}</textarea>
                    <p class="text-xs text-gray-400 mt-1.5">Will checks for this text in every response. If missing, the response is reprompted once.</p>
                </div>
            </div>

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Allowed Code in Responses</h4>
                <p class="text-xs text-gray-500 mb-4">Zero-trust: all code blocks are blocked by default. Check each language you want this agent to be allowed to output. Leave all unchecked to prohibit all code.</p>
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-2" id="code-block-options">
                    ${codeCheckboxesHtml}
                </div>
            </div>

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Alignment Score Threshold</h4>
                <p class="text-xs text-gray-500 mb-3">Minimum Spirit alignment score (0.0–1.0) required to approve a response. Responses scoring below this are blocked. Leave blank to use the platform default (0.5).</p>
                <div class="flex items-center gap-3">
                    <input type="number" id="alignment-threshold-input" min="0" max="1" step="0.05"
                        class="w-28 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                        placeholder="0.5" value="${alignmentThreshold}">
                    <span class="text-xs text-gray-400">Platform default: 0.5 — raise for stricter agents, lower for more permissive ones.</span>
                </div>
            </div>

            <div class="border border-gray-200 dark:border-neutral-700 rounded-lg p-5">
                <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Max Tool Call Turns</h4>
                <p class="text-xs text-gray-500 mb-3">Maximum number of sequential tool calls this agent can make per response before being forced to synthesize an answer. Leave blank to use the platform default.</p>
                <div class="flex items-center gap-3">
                    <input type="number" id="max-agent-turns-input" min="1" max="20" step="1"
                        class="w-28 px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                        placeholder="Default" value="${maxTurns}">
                    <span class="text-xs text-gray-400">Platform default: ${maxTurns || 'set in .env (SAFI_MAX_AGENT_TURNS)'}. Raise for complex research agents, lower for focused single-tool agents.</span>
                </div>
            </div>

            ${hardGatesHtml}

        </div>
    `;

    // --- Event Listeners ---

    const scopeInput = container.querySelector('#scope-statement-input');
    if (scopeInput) {
        scopeInput.addEventListener('input', function() {
            agentData.scope_statement = scopeInput.value;
        });
    }

    const generateScopeBtn = container.querySelector('#btn-generate-scope');
    if (generateScopeBtn) {
        generateScopeBtn.addEventListener('click', async function() {
            const personality = (agentData.instructions || '').trim();
            if (!personality) {
                ui.showToast('Add a personality description in Step 3 first.', 'error');
                return;
            }
            generateScopeBtn.disabled = true;
            generateScopeBtn.innerHTML = `<svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg> Generating…`;
            try {
                const res = await api.generateScope(personality);
                if (res.ok && res.scope) {
                    scopeInput.value = res.scope;
                    agentData.scope_statement = res.scope;
                    ui.showToast('Scope generated!', 'success');
                } else {
                    ui.showToast(res.error || 'Generation failed. Try again.', 'error');
                }
            } catch (e) {
                ui.showToast('Error: ' + e.message, 'error');
            } finally {
                generateScopeBtn.disabled = false;
                generateScopeBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg> Generate`;
            }
        });
    }

    const toggle = container.querySelector('#require-disclaimer-toggle');
    const disclaimerSection = container.querySelector('#disclaimer-text-section');
    const disclaimerInput = container.querySelector('#disclaimer-substring');

    toggle.addEventListener('change', function() {
        const on = toggle.checked;
        disclaimerSection.classList.toggle('hidden', !on);
        agentData.will_rules.structural_requirements.require_disclaimer = on;
        if (!on) agentData.will_rules.structural_requirements.mandatory_disclaimer_substring = "";
    });

    if (disclaimerInput) {
        disclaimerInput.addEventListener('input', function() {
            agentData.will_rules.structural_requirements.mandatory_disclaimer_substring = disclaimerInput.value;
        });
    }

    container.querySelectorAll('.code-block-check').forEach(function(cb) {
        cb.addEventListener('change', function() {
            agentData.will_rules.structural_requirements.allowed_markdown_syntaxes = Array.from(
                container.querySelectorAll('.code-block-check:checked')
            ).map(function(c) { return c.dataset.value; });
        });
    });

    const thresholdInput = container.querySelector('#alignment-threshold-input');
    if (thresholdInput) {
        thresholdInput.addEventListener('input', function() {
            const val = parseFloat(thresholdInput.value);
            if (!isNaN(val) && val >= 0 && val <= 1) {
                agentData.will_rules.structural_requirements.alignment_score_threshold = val;
            } else if (thresholdInput.value === '') {
                delete agentData.will_rules.structural_requirements.alignment_score_threshold;
            }
        });
    }

    const maxTurnsInput = container.querySelector('#max-agent-turns-input');
    if (maxTurnsInput) {
        maxTurnsInput.addEventListener('input', function() {
            const val = parseInt(maxTurnsInput.value);
            if (!isNaN(val) && val >= 1 && val <= 20) {
                agentData.max_agent_turns = val;
            } else if (maxTurnsInput.value === '') {
                agentData.max_agent_turns = null;
            }
        });
    }

    container.querySelectorAll('.hard-gate-check').forEach(function(cb) {
        cb.addEventListener('change', function() {
            const idx = parseInt(cb.dataset.index);
            agentData.values[idx].hard_gate = cb.checked;
        });
    });
}

export function validateSafetyStep(agentData) {
    return true;
}
