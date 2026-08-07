import * as api from '../../core/api.js';
import { loadToolCategories, renderToolGrid } from '../shared/tool-picker.js';
import { escapeHtml } from '../../core/utils.js';

export async function renderToolsStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Tools &amp; Knowledge</h2>
        <p class="text-gray-500 mb-6">Select the tools and data sources this agent can access.</p>

        <div id="wiz-policy-note" class="hidden mb-6 flex items-start gap-2 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
            <svg class="w-4 h-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
            <p class="text-xs text-blue-800 dark:text-blue-300" id="wiz-policy-note-text"></p>
        </div>

        <div id="wiz-tools-loading" class="flex items-center gap-2 text-gray-500">
            <span class="thinking-spinner w-4 h-4"></span> Loading tools...
        </div>

        <div id="wiz-tools-container" class="grid grid-cols-1 gap-6 hidden">
            <!-- Tools injected here -->
        </div>

        <div class="mt-8 pt-6 border-t border-gray-200 dark:border-neutral-700">
            <h3 class="text-lg font-bold text-gray-900 dark:text-white mb-1">Knowledge Base</h3>
            <p class="text-xs text-gray-400 mb-3">
                Ground this agent in a document repository. It retrieves from the
                knowledge base on every turn and cites the documents it used.
            </p>
            <div id="wiz-kb-container">
                <div class="flex items-center gap-2 text-sm text-gray-500">
                    <span class="thinking-spinner w-4 h-4"></span> Loading knowledge bases…
                </div>
            </div>
        </div>
    `;

    if (!agentData.tools) agentData.tools = [];

    // Resolve the governing policy ONCE — both the tool grid and the knowledge
    // base picker are filtered by it.
    const governance = await resolvePolicyGovernance(agentData);

    // Two independent awaits, not one block. They used to share a function
    // whose early returns ("policy authorizes no tools", "failed to load
    // tools") skipped everything after them — including the knowledge base
    // picker, which then sat on its loading spinner forever. Any future
    // section added here gets its own call for the same reason.
    await renderTools(agentData, governance);
    await renderKnowledgeBasePicker(agentData, governance);
}

async function renderTools(agentData, governance) {
    const loader = document.getElementById('wiz-tools-loading');
    const containerEl = document.getElementById('wiz-tools-container');
    if (!loader || !containerEl) return;

    try {
        const categories = await loadToolCategories();
        if (!categories) {
            loader.innerText = "Failed to load tools.";
            return;
        }

        // The policy's authorized-tool universe.
        //   null  -> no governing policy (or legacy policy) -> full catalog
        //   []    -> policy authorizes no tools
        //   [...] -> policy authorizes exactly these tools
        const allow = governance.tools;

        let filter = null;
        if (allow !== null) {
            filter = new Set(allow);
            // Drop any previously-selected tools the policy no longer authorizes.
            agentData.tools = agentData.tools.filter(t => filter.has(t));

            const note = document.getElementById('wiz-policy-note');
            const noteText = document.getElementById('wiz-policy-note-text');
            note.classList.remove('hidden');

            if (allow.length === 0) {
                noteText.innerHTML = "This agent's governing policy authorizes <strong>no tools</strong>. It will run without tool access. Edit the policy's Tools &amp; Guardrails step to authorize tools.";
                loader.classList.add('hidden');
                return;
            }
            noteText.innerHTML = "Only tools authorized by this agent's governing policy are shown. Edit the policy to change what's available here.";
        }

        loader.classList.add('hidden');
        containerEl.classList.remove('hidden');

        renderToolGrid(containerEl, {
            categories,
            filter,
            isSelected: (name) => agentData.tools.includes(name),
            onToggle: (name, checked) => {
                if (checked) {
                    if (!agentData.tools.includes(name)) agentData.tools.push(name);
                } else {
                    agentData.tools = agentData.tools.filter(t => t !== name);
                }
            },
        });
    } catch (e) {
        console.error("Tools Fetch Error", e);
        loader.innerText = "Error loading tools.";
    }
}

/**
 * Offers only knowledge bases that have a built index.
 *
 * A KB with no vectors would look configured on the agent and answer nothing —
 * the "allowed is not the same as useful" failure the connector settings tab
 * already had to fix. /knowledge-bases/available applies that filter server
 * side, so the picker cannot drift from what the retriever can actually load.
 *
 * A built-in agent's knowledge base (the Steward's `safi`, the Bible Scholar's
 * `bible_bsb_v1`) is not a row in that table, so it is preserved as an
 * explicit option rather than silently cleared when such an agent is edited.
 */
async function renderKnowledgeBasePicker(agentData, governance) {
    const el = document.getElementById('wiz-kb-container');
    if (!el) return;

    let bases = [];
    try {
        const res = await api.listAvailableKnowledgeBases();
        bases = (res && res.knowledge_bases) || [];
    } catch (e) {
        console.error("Knowledge base fetch error", e);
        el.innerHTML = `<p class="text-sm text-red-600 dark:text-red-400">Could not load knowledge bases.</p>`;
        return;
    }

    // Narrow to what the governing policy authorizes — the same contract the
    // tool grid follows. This filter is presentation; the enforcement is
    // synderesis._stamp_knowledge_authorization, which strips an unauthorized
    // knowledge base out of the compiled profile at runtime.
    const allowed = governance ? governance.knowledgeBases : null;
    if (Array.isArray(allowed)) {
        const permitted = new Set(allowed);
        bases = bases.filter(kb => permitted.has(kb.id));
        // Drop a previously-chosen knowledge base the policy no longer allows,
        // so saving the agent does not silently re-assert it.
        if (agentData.rag_knowledge_base &&
            !permitted.has(agentData.rag_knowledge_base)) {
            agentData.rag_knowledge_base = "";
        }
    }

    const current = agentData.rag_knowledge_base || '';
    const isBuiltIn = current && !bases.some(kb => kb.id === current);

    if (Array.isArray(allowed) && allowed.length === 0) {
        el.innerHTML = `
            <div class="p-4 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/10 text-sm text-blue-800 dark:text-blue-300">
                This agent's governing policy authorizes <strong>no knowledge
                bases</strong>. It will answer without retrieval. Edit the
                policy's Tools &amp; Guardrails step to authorize one.
            </div>`;
        return;
    }

    if (!bases.length && !isBuiltIn) {
        el.innerHTML = `
            <div class="p-4 rounded-lg border border-gray-200 dark:border-neutral-700 text-sm text-gray-500 dark:text-gray-400">
                ${Array.isArray(allowed)
                    ? `None of the knowledge bases authorized by this agent's
                       policy are ready yet. They appear here once they have
                       documents and have finished indexing.`
                    : `No knowledge bases are ready yet. Create one under
                       <strong class="text-gray-700 dark:text-gray-300">Knowledge</strong>,
                       upload documents, and it will appear here once it has
                       finished indexing.`}
            </div>`;
        return;
    }

    const policyNote = Array.isArray(allowed)
        ? `<p class="text-xs text-blue-600 dark:text-blue-400 mb-2">Only knowledge bases authorized by this agent's governing policy are shown.</p>`
        : '';

    el.innerHTML = `
        ${policyNote}
        <select id="wiz-kb-select"
            class="w-full px-3 py-2 text-sm bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-600 rounded-lg focus:ring-2 focus:ring-purple-500 outline-none text-gray-900 dark:text-white">
            <option value="">None — this agent answers without retrieval</option>
            ${isBuiltIn ? `<option value="${escapeHtml(current)}" selected>${escapeHtml(current)} (built-in)</option>` : ''}
            ${bases.map(kb => `
                <option value="${escapeHtml(kb.id)}" ${kb.id === current ? 'selected' : ''}>
                    ${escapeHtml(kb.name)} — ${kb.chunk_count} chunk${kb.chunk_count === 1 ? '' : 's'}
                </option>`).join('')}
        </select>`;

    document.getElementById('wiz-kb-select').addEventListener('change', (e) => {
        agentData.rag_knowledge_base = e.target.value;
    });
}

/**
 * What the governing policy authorizes for the agent being edited.
 *
 * Returns { tools, knowledgeBases }, each either null ("this policy does not
 * narrow — offer everything") or an array ("exactly these, and [] means
 * none"). One lookup serves both pickers.
 */
async function resolvePolicyGovernance(agentData) {
    const wr = await resolvePolicyWillRules(agentData);
    if (!wr) return { tools: null, knowledgeBases: null };
    return {
        tools: Array.isArray(wr.allowed_tools) ? wr.allowed_tools : [],
        // Absent is NOT the same as empty here: a policy written before
        // knowledge authorization existed must keep working (null), while a
        // policy that explicitly authorizes none must mean none ([]).
        knowledgeBases: Array.isArray(wr.allowed_knowledge_bases)
            ? wr.allowed_knowledge_bases : null,
    };
}

// Resolve the governing policy's structured will_rules for the agent being
// edited. Returns null when there is no governing policy, or when the policy
// predates the structured shape (legacy list-form will_rules never declared
// tools or knowledge bases, so they should not narrow anything).
async function resolvePolicyWillRules(agentData) {
    const pid = agentData.policy_id;
    if (!pid || pid === 'standalone') return null;

    // Step 1 stores the selected policy object here; fall back to a lookup.
    let policy = (agentData._policyData && agentData._policyData.id === pid)
        ? agentData._policyData
        : null;

    if (!policy) {
        try {
            const res = await api.fetchPolicies();
            if (res.ok && res.policies) policy = res.policies.find(p => p.id === pid);
        } catch (e) {
            console.error("Could not resolve policy for tool filtering", e);
        }
    }
    if (!policy) return null;

    const wr = policy.will_rules;
    // Only structured (dict) will_rules carry an allowlist. Legacy list-shaped
    // policies never declared tools, so leave them unrestricted.
    if (wr && typeof wr === 'object' && !Array.isArray(wr)) {
        return Array.isArray(wr.allowed_tools) ? wr.allowed_tools : [];
    }
    return null;
}

export function validateToolsStep(agentData) {
    // Tools are optional
    return true;
}
