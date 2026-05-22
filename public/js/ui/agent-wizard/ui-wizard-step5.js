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
            structural_requirements: { require_disclaimer: false, mandatory_disclaimer_substring: "", banned_markdown_syntaxes: [] },
            early_prompt_blacklist: []
        };
    }
    if (!agentData.will_rules.structural_requirements) {
        agentData.will_rules.structural_requirements = { require_disclaimer: false, mandatory_disclaimer_substring: "", banned_markdown_syntaxes: [] };
    }
    return agentData.will_rules.structural_requirements;
}

export function renderSafetyStep(container, agentData) {
    const sr = getWillRules(agentData);
    const requireDisclaimer = !!sr.require_disclaimer;
    const disclaimerSubstring = sr.mandatory_disclaimer_substring || "";
    const bannedSyntaxes = sr.banned_markdown_syntaxes || [];
    const hasValues = agentData.values && agentData.values.length > 0;

    // Build code-block checkboxes separately to avoid deep template nesting
    const codeCheckboxesHtml = CODE_BLOCK_OPTIONS.map(function(opt) {
        const checked = bannedSyntaxes.indexOf(opt.value) !== -1 ? 'checked' : '';
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
        <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Safety &amp; Governance</h2>
        <p class="text-gray-500 mb-6">Deterministic checks Will enforces on every response — these run before any AI evaluation.</p>

        <div class="space-y-5">

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
                <h4 class="font-semibold text-gray-800 dark:text-white mb-1">Block Code in Responses</h4>
                <p class="text-xs text-gray-500 mb-4">Prevent the agent from including code blocks. Useful for non-technical or compliance-sensitive agents.</p>
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-2" id="code-block-options">
                    ${codeCheckboxesHtml}
                </div>
            </div>

            ${hardGatesHtml}

        </div>
    `;

    // --- Event Listeners ---

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
            agentData.will_rules.structural_requirements.banned_markdown_syntaxes = Array.from(
                container.querySelectorAll('.code-block-check:checked')
            ).map(function(c) { return c.dataset.value; });
        });
    });

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
