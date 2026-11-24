import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { loadToolCategories, renderToolGrid } from '../shared/tool-picker.js';
import { escapeHtml } from '../../core/utils.js';

async function loadKnowledgeBaseChecklist(policyData) {
    const loading = document.getElementById('pw-kb-loading');
    const list = document.getElementById('pw-kb-list');
    if (!list) return;

    let bases = [];
    try {
        const res = await api.listAvailableKnowledgeBases({ includeBuiltin: true });
        bases = (res && res.knowledge_bases) || [];
    } catch (e) {
        console.error('policy wizard: failed to load knowledge bases', e);
        if (loading) loading.innerText = 'Failed to load knowledge bases.';
        return;
    }

    if (loading) loading.classList.add('hidden');
    list.classList.remove('hidden');

    if (!bases.length) {
        list.innerHTML = `<p class="text-xs text-gray-500">No knowledge bases exist yet. Create one under <strong>Knowledge</strong>; until then this policy authorizes none.</p>`;
        return;
    }

    const selected = new Set(policyData.allowed_knowledge_bases || []);
    list.innerHTML = bases.map(kb => `
        <label class="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-neutral-700 hover:border-green-300 dark:hover:border-green-700 cursor-pointer">
            <input type="checkbox" data-kb-allow="${escapeHtml(kb.id)}"
                class="accent-green-600 w-4 h-4 mt-0.5" ${selected.has(kb.id) ? 'checked' : ''}>
            <span class="min-w-0">
                <span class="block text-sm text-gray-900 dark:text-white">${escapeHtml(kb.name)}</span>
                <span class="block text-xs text-gray-400">
                    ${kb.builtin ? 'Built-in corpus' : `${kb.chunk_count} chunk${kb.chunk_count === 1 ? '' : 's'}`}
                </span>
            </span>
        </label>`).join('');

    list.querySelectorAll('[data-kb-allow]').forEach(box => {
        box.addEventListener('change', (e) => {
            const id = e.target.getAttribute('data-kb-allow');
            if (!Array.isArray(policyData.allowed_knowledge_bases)) {
                policyData.allowed_knowledge_bases = [];
            }
            if (e.target.checked) {
                if (!policyData.allowed_knowledge_bases.includes(id)) {
                    policyData.allowed_knowledge_bases.push(id);
                }
            } else {
                policyData.allowed_knowledge_bases =
                    policyData.allowed_knowledge_bases.filter(k => k !== id);
            }
        });
    });
}

export function renderWillStep(container, policyData) {
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
    if (!Array.isArray(policyData.early_prompt_blacklist)) {
        policyData.early_prompt_blacklist = [];
    }
    if (!Array.isArray(policyData.forbidden_paths)) {
        policyData.forbidden_paths = [];
    }
    if (!Array.isArray(policyData.forbidden_executables)) {
        policyData.forbidden_executables = [];
    }
    if (!Array.isArray(policyData.forbidden_shell_patterns)) {
        policyData.forbidden_shell_patterns = [];
    }

    const sr = policyData.structural_requirements;

    container.innerHTML = `
        <div class="space-y-8">
            <div>
                <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-1">Tools &amp; Controls</h2>
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

            <!-- AUTHORIZED KNOWLEDGE BASES -->
            <!--
              Master toggle + list, matching the org connector allow-list card.
              Unchecked master = the policy does not narrow, which is what every
              policy written before this existed means. Without the toggle,
              merely opening and saving an unrelated policy would write an empty
              list and silently un-ground every agent under it.

              The "tick = authorized" hint lives INSIDE the panel, not above it:
              a hint placed above a list is read as describing the list whatever
              it is attached to in the markup (learned the hard way on the
              connector card, 19982c7).
            -->
            <div class="bg-white dark:bg-neutral-900 border border-green-200 dark:border-green-900/40 rounded-xl p-5">
                <div class="flex items-start justify-between gap-4 mb-3">
                    <div>
                        <h3 class="font-bold text-green-700 dark:text-green-300">Authorized Knowledge</h3>
                        <p class="text-xs text-gray-500 mt-0.5">Which document repositories agents under this policy may be grounded in. Leave unrestricted to allow any knowledge base the agent's builder can access.</p>
                    </div>
                    <label class="flex items-center gap-2 cursor-pointer select-none shrink-0">
                        <input type="checkbox" id="pw-kb-restrict" class="accent-green-600 w-4 h-4"
                            ${Array.isArray(policyData.allowed_knowledge_bases) ? 'checked' : ''}>
                        <span class="text-xs uppercase font-bold text-gray-500">Restrict</span>
                    </label>
                </div>
                <div id="pw-kb-panel" class="${Array.isArray(policyData.allowed_knowledge_bases) ? '' : 'hidden'}">
                    <p class="text-xs text-gray-500 mb-3">Tick a knowledge base to authorize it. <strong>Ticking none authorizes no knowledge at all</strong> — agents under this policy will answer without retrieval.</p>
                    <div id="pw-kb-loading" class="flex items-center gap-2 text-sm text-gray-500">
                        <span class="thinking-spinner w-4 h-4"></span> Loading knowledge bases…
                    </div>
                    <div id="pw-kb-list" class="flex flex-col gap-2 hidden"></div>
                </div>
            </div>

            <!-- DISCLAIMER -->
            <div class="bg-white dark:bg-neutral-900 border border-green-200 dark:border-green-900/40 rounded-xl p-5">
                <div class="flex items-center justify-between mb-3">
                    <div>
                        <h3 class="font-bold text-green-700 dark:text-green-300">Required Disclaimer</h3>
                        <p class="text-xs text-gray-500 mt-0.5">If enabled, every response must contain the substring below verbatim.</p>
                    </div>
                    <label class="flex items-center gap-2 cursor-pointer select-none">
                        <input type="checkbox" id="pw-require-disclaimer" ${sr.require_disclaimer ? 'checked' : ''} class="accent-green-600 w-4 h-4">
                        <span class="text-xs uppercase font-bold text-gray-500">Enforce</span>
                    </label>
                </div>
                <input type="text" id="pw-disclaimer-substring" value="${escapeAttr(sr.mandatory_disclaimer_substring || '')}"
                    class="w-full p-2.5 rounded-lg border border-green-200 dark:border-green-900/50 bg-gray-50 dark:bg-neutral-800 text-sm focus:ring-2 focus:ring-green-500 outline-none ${sr.require_disclaimer ? '' : 'opacity-60'}"
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
                        class="flex-1 min-w-0 p-2.5 rounded-lg border border-red-200 dark:border-red-900/50 bg-gray-50 dark:bg-neutral-800 text-sm font-mono focus:ring-2 focus:ring-red-500 outline-none"
                        placeholder="e.g. \`\`\`html">
                    <button id="pw-add-banned-btn" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-semibold transition-colors shrink-0">Add</button>
                </div>
                <ul id="pw-banned-list" class="space-y-2"></ul>
            </div>

            <!-- BLOCKED PHRASES (Phase Zero prompt blacklist) -->
            <div class="bg-white dark:bg-neutral-900 border border-amber-200 dark:border-amber-900/40 rounded-xl p-5">
                <div>
                    <h3 class="font-bold text-amber-700 dark:text-amber-300">Blocked Phrases</h3>
                    <p class="text-xs text-gray-500 mt-0.5 mb-3">Phrases checked against every user message <em>before</em> the agent runs. If a message contains one (case-insensitive), the agent politely redirects without processing it. Use for topics agents under this policy must never engage with — matching is literal, so keep phrases short and distinctive.</p>
                </div>
                <div class="flex gap-2 mb-3">
                    <input type="text" id="pw-blacklist-input"
                        class="flex-1 min-w-0 p-2.5 rounded-lg border border-amber-200 dark:border-amber-900/50 bg-gray-50 dark:bg-neutral-800 text-sm focus:ring-2 focus:ring-amber-500 outline-none"
                        placeholder="e.g. insider trading tips">
                    <button id="pw-add-blacklist-btn" class="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-sm font-semibold transition-colors shrink-0">Add</button>
                </div>
                <ul id="pw-blacklist-list" class="space-y-2"></ul>
            </div>

            <!-- RESTRICTED PATHS (path-gate denylist) -->
            <div class="bg-white dark:bg-neutral-900 border border-purple-200 dark:border-purple-900/40 rounded-xl p-5 shadow-sm">
                <div class="flex items-start gap-3 mb-4">
                    <span class="shrink-0 w-9 h-9 rounded-lg bg-purple-100 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-800 flex items-center justify-center">
                        <svg class="w-5 h-5 text-purple-600 dark:text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2h-.5A2.5 2.5 0 0015 8.5v-1A2.5 2.5 0 0012.5 5h-1A2.5 2.5 0 009 7.5v1A2.5 2.5 0 016.5 11H6a2 2 0 00-2 2v6a2 2 0 002 2z"/></svg>
                    </span>
                    <div class="min-w-0">
                        <h3 class="font-bold text-purple-700 dark:text-purple-300">Restricted Paths</h3>
                        <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Filesystem paths agents under this policy may never read or write — the Will's path-gate denylist. Entries are matched literally, so prefer short, distinctive prefixes such as <code class="font-mono text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20 px-1 rounded">.ssh</code> or <code class="font-mono text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20 px-1 rounded">.config/safi</code>.</p>
                    </div>
                </div>
                <label for="pw-forbidden-input" class="block text-[11px] font-semibold uppercase tracking-wide text-purple-600 dark:text-purple-400 mb-1.5">Path prefix</label>
                <div class="flex gap-2 mb-3">
                    <div class="relative flex-1 min-w-0">
                        <input type="text" id="pw-forbidden-input" autocomplete="off" spellcheck="false"
                            class="w-full p-2.5 rounded-lg border border-purple-200 dark:border-purple-700 bg-purple-50/40 dark:bg-neutral-800 text-sm font-mono text-gray-900 dark:text-neutral-100 placeholder-purple-400 dark:placeholder-neutral-500 focus:border-purple-400 dark:focus:border-purple-500 focus:ring-2 focus:ring-purple-500/40 outline-none transition"
                            placeholder="e.g. .ssh or .config/safi">
                    </div>
                    <button id="pw-add-forbidden-btn"
                        class="px-4 py-2 rounded-lg text-sm font-semibold shrink-0 inline-flex items-center gap-1.5 bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white shadow-sm transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                        Add
                    </button>
                </div>
                <ul id="pw-forbidden-list" class="space-y-2"></ul>
                <p id="pw-forbidden-empty" class="hidden text-xs text-gray-400 dark:text-gray-500 italic mt-2">No restricted paths yet — agents under this policy are only limited by the defaults above.</p>
            </div>

            <!-- BLOCKED COMMANDS (command-gate denylists) -->
            <div class="bg-white dark:bg-neutral-900 border border-rose-200 dark:border-rose-900/40 rounded-xl p-5 shadow-sm">
                <div class="flex items-start gap-3 mb-4">
                    <span class="shrink-0 w-9 h-9 rounded-lg bg-rose-100 dark:bg-rose-900/30 border border-rose-200 dark:border-rose-800 flex items-center justify-center">
                        <svg class="w-5 h-5 text-rose-600 dark:text-rose-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/></svg>
                    </span>
                    <div class="min-w-0">
                        <h3 class="font-bold text-rose-700 dark:text-rose-300">Blocked Commands</h3>
                        <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Two denylists the Will's command gate enforces on every shell command, in addition to the built-in defaults.</p>
                    </div>
                </div>
                <label for="pw-forbidden-exec-input" class="block text-[11px] font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400 mb-1.5">Blocked executables</label>
                <p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">Whole command names agents may never run — matched against the first token of every shell command, so <code class="font-mono text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20 px-1 rounded">sudo</code> blocks <code class="font-mono text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20 px-1 rounded">sudo rm -rf /</code> entirely.</p>
                <div class="flex gap-2 mb-3">
                    <div class="relative flex-1 min-w-0">
                        <input type="text" id="pw-forbidden-exec-input" autocomplete="off" spellcheck="false"
                            class="w-full p-2.5 rounded-lg border border-rose-200 dark:border-rose-700 bg-rose-50/40 dark:bg-neutral-800 text-sm font-mono text-gray-900 dark:text-neutral-100 placeholder-rose-400 dark:placeholder-neutral-500 focus:border-rose-400 dark:focus:border-rose-500 focus:ring-2 focus:ring-rose-500/40 outline-none transition"
                            placeholder="e.g. sudo or nmap">
                    </div>
                    <button id="pw-add-forbidden-exec-btn"
                        class="px-4 py-2 rounded-lg text-sm font-semibold shrink-0 inline-flex items-center gap-1.5 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white shadow-sm transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                        Add
                    </button>
                </div>
                <ul id="pw-forbidden-exec-list" class="space-y-2 mb-5"></ul>
                <label for="pw-forbidden-shell-input" class="block text-[11px] font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400 mb-1.5">Blocked shell patterns</label>
                <p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">Substrings that may never appear anywhere in a shell command — such as <code class="font-mono text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20 px-1 rounded">rm -rf /</code> or <code class="font-mono text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20 px-1 rounded">mkfs</code>. Use these for dangerous argument combinations rather than whole commands.</p>
                <div class="flex gap-2 mb-3">
                    <div class="relative flex-1 min-w-0">
                        <input type="text" id="pw-forbidden-shell-input" autocomplete="off" spellcheck="false"
                            class="w-full p-2.5 rounded-lg border border-rose-200 dark:border-rose-700 bg-rose-50/40 dark:bg-neutral-800 text-sm font-mono text-gray-900 dark:text-neutral-100 placeholder-rose-400 dark:placeholder-neutral-500 focus:border-rose-400 dark:focus:border-rose-500 focus:ring-2 focus:ring-rose-500/40 outline-none transition"
                            placeholder="e.g. rm -rf / or dd if=">
                    </div>
                    <button id="pw-add-forbidden-shell-btn"
                        class="px-4 py-2 rounded-lg text-sm font-semibold shrink-0 inline-flex items-center gap-1.5 bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white shadow-sm transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                        Add
                    </button>
                </div>
                <ul id="pw-forbidden-shell-list" class="space-y-2"></ul>
            </div>

            <!-- WRITTEN RULES → compiled into enforceable standards -->
            <details class="bg-gray-50 dark:bg-neutral-800/30 border border-gray-200 dark:border-neutral-700 rounded-xl p-5">
                <summary class="cursor-pointer font-semibold text-gray-700 dark:text-gray-300">Additional written rules (optional)</summary>
                <p class="text-xs text-gray-500 mt-2 mb-3">Plain-language rules for cases the options above don't cover (e.g. "The response must not promise specific outcomes."). Prefer the structured options above when they fit.</p>
                <div class="flex items-start gap-2 mb-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-900/40">
                    <svg class="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M5 19h14a2 2 0 001.84-2.75L13.74 4a2 2 0 00-3.48 0l-7.1 12.25A2 2 0 005 19z"/></svg>
                    <p class="text-xs text-amber-800 dark:text-amber-200">Written rules <strong>enforce nothing on their own</strong> &mdash; nothing in the engine reads them. Use <em>Convert to enforceable standards</em> below to turn them into non-negotiable standards the Will actually enforces; until you do, they are only notes.</p>
                </div>
                <div class="flex gap-2 mb-3">
                    <input type="text" id="pw-rule-input"
                        class="flex-1 min-w-0 p-2.5 rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-900 text-sm focus:ring-2 focus:ring-gray-400 outline-none"
                        placeholder="The response must not...">
                    <button id="pw-add-rule-btn" class="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg text-sm font-semibold transition-colors shrink-0">Add</button>
                </div>
                <ul id="pw-rules-list" class="space-y-2"></ul>
                <button id="pw-compile-rules-btn" class="mt-3 w-full px-4 py-2.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white rounded-lg text-sm font-semibold transition-colors flex items-center justify-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                    Convert to enforceable standards
                </button>
                <div id="pw-compile-result" class="mt-4 hidden"></div>
            </details>
        </div>
    `;

    loadToolCategories(policyData.id || null).then(categories => {
        const loading = document.getElementById('pw-tools-loading');
        const grid = document.getElementById('pw-tools-grid');
        if (!grid) return;
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

    const kbRestrict = document.getElementById('pw-kb-restrict');
    const kbPanel = document.getElementById('pw-kb-panel');

    kbRestrict.addEventListener('change', (e) => {
        if (e.target.checked) {
            if (!Array.isArray(policyData.allowed_knowledge_bases)) {
                policyData.allowed_knowledge_bases = [];
            }
            kbPanel.classList.remove('hidden');
            loadKnowledgeBaseChecklist(policyData);
        } else {
            delete policyData.allowed_knowledge_bases;
            kbPanel.classList.add('hidden');
        }
    });

    if (Array.isArray(policyData.allowed_knowledge_bases)) {
        loadKnowledgeBaseChecklist(policyData);
    }

    const reqEl = document.getElementById('pw-require-disclaimer');
    const subEl = document.getElementById('pw-disclaimer-substring');
    reqEl.addEventListener('change', (e) => {
        sr.require_disclaimer = !!e.target.checked;
        subEl.disabled = !sr.require_disclaimer;
        subEl.classList.toggle('opacity-60', !sr.require_disclaimer);
    });
    subEl.addEventListener('input', (e) => { sr.mandatory_disclaimer_substring = e.target.value; });

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

    renderList('pw-blacklist-list', policyData.early_prompt_blacklist, 'amber', (i) => {
        policyData.early_prompt_blacklist.splice(i, 1);
    });
    const addBlacklist = () => {
        const input = document.getElementById('pw-blacklist-input');
        const val = input.value.trim();
        if (val) {
            policyData.early_prompt_blacklist.push(val);
            input.value = '';
            renderList('pw-blacklist-list', policyData.early_prompt_blacklist, 'amber', (i) => policyData.early_prompt_blacklist.splice(i, 1));
        }
    };
    document.getElementById('pw-add-blacklist-btn').addEventListener('click', addBlacklist);
    document.getElementById('pw-blacklist-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addBlacklist(); });

    renderList('pw-forbidden-list', policyData.forbidden_paths, 'purple', (i) => {
        policyData.forbidden_paths.splice(i, 1);
    });
    const addForbidden = () => {
        const input = document.getElementById('pw-forbidden-input');
        const val = input.value.trim();
        if (val) {
            if (!policyData.forbidden_paths.includes(val)) {
                policyData.forbidden_paths.push(val);
            }
            input.value = '';
            renderList('pw-forbidden-list', policyData.forbidden_paths, 'purple', (i) => policyData.forbidden_paths.splice(i, 1));
        }
    };
    document.getElementById('pw-add-forbidden-btn').addEventListener('click', addForbidden);
    document.getElementById('pw-forbidden-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addForbidden(); });

    renderList('pw-forbidden-exec-list', policyData.forbidden_executables, 'red', (i) => {
        policyData.forbidden_executables.splice(i, 1);
    });
    const addForbiddenExec = () => {
        const input = document.getElementById('pw-forbidden-exec-input');
        const val = input.value.trim();
        if (val) {
            if (!policyData.forbidden_executables.includes(val)) {
                policyData.forbidden_executables.push(val);
            }
            input.value = '';
            renderList('pw-forbidden-exec-list', policyData.forbidden_executables, 'red', (i) => policyData.forbidden_executables.splice(i, 1));
        }
    };
    document.getElementById('pw-add-forbidden-exec-btn').addEventListener('click', addForbiddenExec);
    document.getElementById('pw-forbidden-exec-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addForbiddenExec(); });

    renderList('pw-forbidden-shell-list', policyData.forbidden_shell_patterns, 'red', (i) => {
        policyData.forbidden_shell_patterns.splice(i, 1);
    });
    const addForbiddenShell = () => {
        const input = document.getElementById('pw-forbidden-shell-input');
        const val = input.value.trim();
        if (val) {
            if (!policyData.forbidden_shell_patterns.includes(val)) {
                policyData.forbidden_shell_patterns.push(val);
            }
            input.value = '';
            renderList('pw-forbidden-shell-list', policyData.forbidden_shell_patterns, 'red', (i) => policyData.forbidden_shell_patterns.splice(i, 1));
        }
    };
    document.getElementById('pw-add-forbidden-shell-btn').addEventListener('click', addForbiddenShell);
    document.getElementById('pw-forbidden-shell-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') addForbiddenShell(); });

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

    bindRuleCompiler(policyData);
}

function bindRuleCompiler(policyData) {
    const btn = document.getElementById('pw-compile-rules-btn');
    const panel = document.getElementById('pw-compile-result');
    if (!btn || !panel) return;

    btn.addEventListener('click', async () => {
        const rules = (policyData.will_rules || []).filter(r => String(r).trim());
        if (!rules.length) {
            ui.showToast('Add at least one written rule first.', 'error');
            return;
        }

        const original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Converting...`;
        panel.classList.add('hidden');

        try {
            const ctx = `${policyData.name || 'Policy'} — ${policyData.business_unit || ''}. ${policyData.context || ''}`.trim();
            const res = await api.generatePolicyContent('compile_rules', ctx, { rules });
            if (!res.ok) throw new Error(res.error || 'Conversion failed');
            renderCompileResult(policyData, res.content || {});
        } catch (e) {
            console.error('policy wizard: rule compilation failed', e);
            ui.showToast(e.message || 'Could not convert the rules. Try again.', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = original;
        }
    });
}

function renderCompileResult(policyData, content) {
    const panel = document.getElementById('pw-compile-result');
    const gates = Array.isArray(content.gates) ? content.gates : [];
    const unconvertible = Array.isArray(content.unconvertible) ? content.unconvertible : [];

    if (!gates.length && !unconvertible.length) {
        panel.classList.remove('hidden');
        panel.innerHTML = `<p class="text-sm text-gray-500 italic">Nothing was produced. Try rewording the rules so each one describes something a response must not do.</p>`;
        return;
    }

    const gateCards = gates.map((g, i) => {
        const guide = (g.rubric && g.rubric.scoring_guide) || [];
        const pass = guide.find(s => Number(s.score) > 0);
        const fail = guide.find(s => Number(s.score) < 0);
        return `
        <label class="block p-4 rounded-xl border border-green-200 dark:border-green-900/40 bg-white dark:bg-neutral-900 cursor-pointer hover:border-green-400 transition-colors">
            <div class="flex items-start gap-3">
                <input type="checkbox" data-gate-idx="${i}" checked class="mt-1 accent-green-600 w-4 h-4 shrink-0">
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-bold text-gray-900 dark:text-white">${escapeHtml(g.name || '')}</span>
                        <span class="text-[10px] uppercase font-bold tracking-wider bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 px-2 py-0.5 rounded-full">Non-negotiable</span>
                    </div>
                    <p class="text-xs text-gray-600 dark:text-gray-300 mt-1">${escapeHtml(g.description || '')}</p>
                    ${g.source_rule ? `<p class="text-[11px] text-gray-400 mt-1.5 italic">from: &ldquo;${escapeHtml(g.source_rule)}&rdquo;</p>` : ''}
                    <div class="mt-2.5 space-y-1">
                        ${pass ? `<p class="text-xs text-green-700 dark:text-green-300"><span class="font-mono font-bold">+1.0</span> ${escapeHtml(pass.criteria || pass.descriptor || '')}</p>` : ''}
                        ${fail ? `<p class="text-xs text-red-700 dark:text-red-300"><span class="font-mono font-bold">&minus;1.0</span> ${escapeHtml(fail.criteria || fail.descriptor || '')}</p>` : ''}
                    </div>
                </div>
            </div>
        </label>`;
    }).join('');

    const skipped = unconvertible.length ? `
        <div class="mt-4 p-4 rounded-xl border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10">
            <h4 class="text-sm font-bold text-amber-800 dark:text-amber-200 mb-1">Not converted (${unconvertible.length})</h4>
            <p class="text-xs text-amber-700 dark:text-amber-300 mb-3">These describe obligations on people or processes rather than on the agent's response, so there is nothing in a response to score them against. They stay in your written rules as a record.</p>
            <ul class="space-y-2">
                ${unconvertible.map(u => `
                    <li class="text-xs">
                        <span class="text-gray-700 dark:text-gray-200">&ldquo;${escapeHtml(u.rule || '')}&rdquo;</span>
                        <span class="block text-amber-700 dark:text-amber-400 mt-0.5">${escapeHtml(u.reason || '')}</span>
                    </li>`).join('')}
            </ul>
        </div>` : '';

    panel.classList.remove('hidden');
    panel.innerHTML = `
        ${gates.length ? `
        <h4 class="text-sm font-bold text-gray-800 dark:text-gray-100 mb-1">Proposed standards (${gates.length})</h4>
        <p class="text-xs text-gray-500 mb-3">Each becomes a non-negotiable standard on the Standards step: any response scoring &minus;1.0 is blocked outright. Review the wording &mdash; a standard that is scored on every request will also be <em>checked</em> on every request.</p>
        <div class="space-y-3">${gateCards}</div>
        <button id="pw-accept-gates-btn" class="mt-3 w-full px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition-colors">Add selected to Standards</button>
        ` : ''}
        ${skipped}
    `;

    const accept = document.getElementById('pw-accept-gates-btn');
    if (!accept) return;
    accept.addEventListener('click', () => {
        const chosen = Array.from(panel.querySelectorAll('input[data-gate-idx]:checked'))
            .map(cb => gates[Number(cb.dataset.gateIdx)])
            .filter(Boolean);
        if (!chosen.length) {
            ui.showToast('Select at least one standard.', 'error');
            return;
        }

        if (!Array.isArray(policyData.values)) policyData.values = [];
        const existing = new Set(policyData.values.map(v => String(v.name || '').trim().toLowerCase()));
        let added = 0;
        chosen.forEach(g => {
            const name = String(g.name || '').trim();
            if (!name || existing.has(name.toLowerCase())) return;
            existing.add(name.toLowerCase());
            policyData.values.push({
                name,
                description: g.description || '',
                weight: 0,
                hard_gate: true,
                rubric: g.rubric || { scoring_guide: [] },
            });
            added++;
            const src = String(g.source_rule || '').trim();
            if (src) {
                const at = (policyData.will_rules || []).findIndex(r => String(r).trim() === src);
                if (at >= 0) policyData.will_rules.splice(at, 1);
            }
        });

        renderList('pw-rules-list', policyData.will_rules, 'gray', (i) => policyData.will_rules.splice(i, 1));
        panel.classList.add('hidden');
        panel.innerHTML = '';
        ui.showToast(
            added
                ? `${added} standard${added > 1 ? 's' : ''} added — review them on the Standards step.`
                : 'Those standards are already on this policy.',
            added ? 'success' : 'warning'
        );
    });
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
            amber: 'bg-amber-50 dark:bg-amber-900/10 border-amber-100 dark:border-amber-900/30 text-amber-900 dark:text-amber-200',
            gray:  'bg-gray-50 dark:bg-neutral-900 border-gray-200 dark:border-neutral-700 text-gray-800 dark:text-gray-200',
            purple: 'bg-purple-50 dark:bg-purple-900/10 border-purple-100 dark:border-purple-900/30 text-purple-900 dark:text-purple-200',
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
