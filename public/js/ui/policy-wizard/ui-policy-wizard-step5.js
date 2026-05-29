import * as ui from '../ui.js';
import { loadToolCategories, renderToolGrid } from '../shared/tool-picker.js';

export function renderWillStep(container, policyData) {
    // Ensure shape
    if (!policyData.structural_requirements) {
        policyData.structural_requirements = {
            require_disclaimer: false,
            mandatory_disclaimer_substring: "",
            banned_markdown_syntaxes: [],
        };
    }
    if (!Array.isArray(policyData.structural_requirements.banned_markdown_syntaxes)) {
        policyData.structural_requirements.banned_markdown_syntaxes = [];
    }
    if (!Array.isArray(policyData.allowed_tools)) {
        policyData.allowed_tools = [];
    }
    if (!Array.isArray(policyData.will_rules)) {
        policyData.will_rules = [];
    }

    const sr = policyData.structural_requirements;

    container.innerHTML = `
        <div class="space-y-8">
            <div>
                <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Tools &amp; Guardrails</h2>
                <p class="text-gray-500 text-sm">Choose which tools agents under this policy may use, plus hard requirements checked on every response. If a response breaks a guardrail, the agent automatically tries once to fix it; if it still fails, the response is replaced with a safe, on-policy reply.</p>
            </div>

            <!-- AUTHORIZED TOOLS -->
            <div class="bg-white dark:bg-neutral-900 border border-green-200 dark:border-green-900/40 rounded-xl p-5">
                <div class="mb-4">
                    <h3 class="font-bold text-green-700 dark:text-green-300">Authorized Tools</h3>
                    <p class="text-xs text-gray-500 mt-0.5">The tools agents under this policy are allowed to use. An agent created under this policy can only enable tools you check here — anything else is blocked before it runs. <strong>Check nothing to authorize no tools at all.</strong></p>
                </div>
                <div id="pw-tools-loading" class="flex items-center gap-2 text-sm text-gray-500">
                    <span class="thinking-spinner w-4 h-4"></span> Loading tools…
                </div>
                <div id="pw-tools-grid" class="flex flex-col gap-3 hidden"></div>
            </div>

            <!-- DISCLAIMER -->
            <div class="bg-white dark:bg-neutral-900 border border-blue-200 dark:border-blue-900/40 rounded-xl p-5">
                <div class="flex items-center justify-between mb-3">
                    <div>
                        <h3 class="font-bold text-blue-700 dark:text-blue-300">Required Disclaimer</h3>
                        <p class="text-xs text-gray-500 mt-0.5">If enabled, every response must contain the substring below verbatim.</p>
                    </div>
                    <label class="flex items-center gap-2 cursor-pointer select-none">
                        <input type="checkbox" id="pw-require-disclaimer" ${sr.require_disclaimer ? 'checked' : ''} class="accent-blue-600 w-4 h-4">
                        <span class="text-xs uppercase font-bold text-gray-500">Enforce</span>
                    </label>
                </div>
                <input type="text" id="pw-disclaimer-substring" value="${escapeAttr(sr.mandatory_disclaimer_substring || '')}"
                    class="w-full p-2.5 rounded-lg border border-blue-200 dark:border-blue-900/50 bg-gray-50 dark:bg-neutral-800 text-sm focus:ring-2 focus:ring-blue-500 outline-none ${sr.require_disclaimer ? '' : 'opacity-60'}"
                    ${sr.require_disclaimer ? '' : 'disabled'}
                    placeholder="e.g. Disclaimer: This is for educational purposes only.">
                <p class="text-xs text-gray-400 mt-2">Match is substring, case-sensitive. Keep it short and stable.</p>
            </div>

            <!-- BANNED MARKDOWN -->
            <div class="bg-white dark:bg-neutral-900 border border-red-200 dark:border-red-900/40 rounded-xl p-5">
                <div>
                    <h3 class="font-bold text-red-700 dark:text-red-300">Prohibited Formatting</h3>
                    <p class="text-xs text-gray-500 mt-0.5 mb-3">Text or formatting that must never appear in a response. Common: <code class="font-mono">\`\`\`</code> to block all code blocks, <code class="font-mono">\`\`\`html</code> for raw HTML.</p>
                </div>
                <div class="flex gap-2 mb-3">
                    <input type="text" id="pw-banned-input"
                        class="flex-1 p-2.5 rounded-lg border border-red-200 dark:border-red-900/50 bg-gray-50 dark:bg-neutral-800 text-sm font-mono focus:ring-2 focus:ring-red-500 outline-none"
                        placeholder="e.g. \`\`\`html">
                    <button id="pw-add-banned-btn" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-semibold transition-colors">Add</button>
                </div>
                <ul id="pw-banned-list" class="space-y-2"></ul>
            </div>

            <!-- LEGACY FREE-TEXT RULES (optional) -->
            <details class="bg-gray-50 dark:bg-neutral-800/30 border border-gray-200 dark:border-neutral-700 rounded-xl p-5">
                <summary class="cursor-pointer font-semibold text-gray-700 dark:text-gray-300">Additional written rules (optional)</summary>
                <p class="text-xs text-gray-500 mt-2 mb-3">Plain-language rules for cases the options above don't cover (e.g. "The response must not promise specific outcomes."). Prefer the structured options above when they fit.</p>
                <div class="flex gap-2 mb-3">
                    <input type="text" id="pw-rule-input"
                        class="flex-1 p-2.5 rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-900 text-sm focus:ring-2 focus:ring-gray-400 outline-none"
                        placeholder="The response must not...">
                    <button id="pw-add-rule-btn" class="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg text-sm font-semibold transition-colors">Add</button>
                </div>
                <ul id="pw-rules-list" class="space-y-2"></ul>
            </details>
        </div>
    `;

    // --- AUTHORIZED TOOLS (checklist from backend registry) ---
    loadToolCategories().then(categories => {
        const loading = document.getElementById('pw-tools-loading');
        const grid = document.getElementById('pw-tools-grid');
        if (!grid) return; // step navigated away
        if (!categories) {
            if (loading) loading.innerText = 'Failed to load tools.';
            return;
        }
        if (loading) loading.classList.add('hidden');
        grid.classList.remove('hidden');
        renderToolGrid(grid, {
            categories,
            collapsible: true,
            isSelected: (name) => policyData.allowed_tools.includes(name),
            onToggle: (name, checked) => {
                if (checked) {
                    if (!policyData.allowed_tools.includes(name)) policyData.allowed_tools.push(name);
                } else {
                    policyData.allowed_tools = policyData.allowed_tools.filter(t => t !== name);
                }
            },
        });
    });

    // --- DISCLAIMER ---
    const reqEl = document.getElementById('pw-require-disclaimer');
    const subEl = document.getElementById('pw-disclaimer-substring');
    reqEl.addEventListener('change', (e) => {
        sr.require_disclaimer = !!e.target.checked;
        subEl.disabled = !sr.require_disclaimer;
        subEl.classList.toggle('opacity-60', !sr.require_disclaimer);
    });
    subEl.addEventListener('input', (e) => { sr.mandatory_disclaimer_substring = e.target.value; });

    // --- BANNED MARKDOWN ---
    renderList('pw-banned-list', sr.banned_markdown_syntaxes, 'red', (i) => {
        sr.banned_markdown_syntaxes.splice(i, 1);
    });
    const addBanned = () => {
        const input = document.getElementById('pw-banned-input');
        const val = input.value.trim();
        if (val) {
            sr.banned_markdown_syntaxes.push(val);
            input.value = '';
            renderList('pw-banned-list', sr.banned_markdown_syntaxes, 'red', (i) => sr.banned_markdown_syntaxes.splice(i, 1));
        }
    };
    document.getElementById('pw-add-banned-btn').addEventListener('click', addBanned);
    document.getElementById('pw-banned-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addBanned(); });

    // --- LEGACY RULES ---
    renderList('pw-rules-list', policyData.will_rules, 'gray', (i) => {
        policyData.will_rules.splice(i, 1);
    });
    const addRule = () => {
        const input = document.getElementById('pw-rule-input');
        const val = input.value.trim();
        if (val) {
            policyData.will_rules.push(val);
            input.value = '';
            renderList('pw-rules-list', policyData.will_rules, 'gray', (i) => policyData.will_rules.splice(i, 1));
        }
    };
    document.getElementById('pw-add-rule-btn').addEventListener('click', addRule);
    document.getElementById('pw-rule-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addRule(); });
}

function renderList(id, arr, color, onRemove) {
    const list = document.getElementById(id);
    if (!list) return;
    if (arr.length === 0) {
        list.innerHTML = `<li class="text-sm text-gray-400 italic text-center py-2">None yet.</li>`;
        return;
    }
    list.innerHTML = '';
    arr.forEach((item, idx) => {
        const li = document.createElement('li');
        const colorCls = {
            red:   'bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-900/30 text-red-900 dark:text-red-200',
            green: 'bg-green-50 dark:bg-green-900/10 border-green-100 dark:border-green-900/30 text-green-900 dark:text-green-200',
            gray:  'bg-gray-50 dark:bg-neutral-900 border-gray-200 dark:border-neutral-700 text-gray-800 dark:text-gray-200',
        }[color] || '';
        li.className = `flex items-center gap-2 p-2.5 border rounded-lg ${colorCls}`;
        li.innerHTML = `
            <input type="text" value="${escapeAttr(item)}" class="flex-1 bg-transparent text-sm font-mono outline-none">
            <button class="opacity-50 hover:opacity-100 transition-opacity" title="Remove">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
        `;
        li.querySelector('input').addEventListener('change', (e) => { arr[idx] = e.target.value; });
        li.querySelector('button').addEventListener('click', () => {
            onRemove(idx);
            renderList(id, arr, color, onRemove);
        });
        list.appendChild(li);
    });
}

function escapeAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

export function validateWillStep(policyData) {
    const sr = policyData.structural_requirements;
    if (sr.require_disclaimer && !(sr.mandatory_disclaimer_substring || '').trim()) {
        ui.showToast("Disclaimer enforcement is on — please provide the required substring.", "error");
        return false;
    }
    return true;
}
