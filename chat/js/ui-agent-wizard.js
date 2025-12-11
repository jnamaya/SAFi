import * as ui from './ui.js';
import * as api from './api.js';

// --- WIZARD STATE ---
let currentStep = 1;
const TOTAL_STEPS = 4;
let agentData = {
    key: "",
    name: "",
    description: "",
    avatar: "", // Custom Avatar URL
    instructions: "", // Worldview
    style: "", // Communication Style
    values: [],
    rules: [],
    policy_id: "standalone", // Governance Policy
    is_update_mode: false, // Flag for Create vs Update
    // NEW: Model & RAG Configuration
    intellect_model: "",
    will_model: "",
    conscience_model: "",
    rag_knowledge_base: "",
    rag_format_string: ""
};

let availableModelsCache = []; // Store passed models

// --- MAIN ENTRY POINT ---
export function openAgentWizard(existingAgent = null, availableModels = []) {
    // Reset State
    currentStep = 1;

    availableModelsCache = availableModels || [];

    if (existingAgent) {
        // PRE-FILL for Edit Mode
        agentData = {
            key: existingAgent.key,
            name: existingAgent.name,
            description: existingAgent.description || "",
            avatar: existingAgent.avatar || "",
            // Clean up instructions if they are just the raw worldview
            instructions: (existingAgent.worldview || "").replace("--- Organizational Policy ---\n", "").split("--- SPECIFIC ROLE ---\n").pop() || "",
            style: existingAgent.style || "",
            values: existingAgent.values || [],
            rules: existingAgent.will_rules || [],
            policy_id: existingAgent.policy_id || "standalone",
            visibility: existingAgent.visibility || "private",
            is_update_mode: true, // Explicitly set update mode

            // Populate New Fields
            intellect_model: existingAgent.intellect_model || "",
            will_model: existingAgent.will_model || "",
            conscience_model: existingAgent.conscience_model || "",
            rag_knowledge_base: existingAgent.rag_knowledge_base || "",
            rag_format_string: existingAgent.rag_format_string || ""
        };
        if (existingAgent.worldview && !agentData.instructions) {
            agentData.instructions = existingAgent.worldview;
        }
    } else {
        // Reset for Create Mode
        agentData = {
            key: "",
            name: "",
            description: "",
            avatar: "",
            instructions: "",
            style: "",
            values: [],
            rules: [],
            policy_id: "standalone",
            visibility: "private",
            is_update_mode: false, // Explicitly set create mode

            // Reset New Fields
            intellect_model: "",
            will_model: "",
            conscience_model: "",
            rag_knowledge_base: "",
            rag_format_string: ""
        };
    }

    ensureWizardModalExists();

    const title = document.getElementById('wizard-title');
    if (title) title.innerText = existingAgent ? "Edit Agent" : "Create New Agent";

    renderStep(1);

    const modal = document.getElementById('agent-wizard-modal');
    modal.classList.remove('hidden');
}

function closeWizard() {
    const modal = document.getElementById('agent-wizard-modal');
    modal.classList.add('hidden');
}

function ensureWizardModalExists() {
    if (document.getElementById('agent-wizard-modal')) return;

    const html = `
    <div id="agent-wizard-modal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity backdrop-blur-sm"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-3xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800 flex flex-col max-h-[90vh]">
                    
                    <!-- Header -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center shrink-0">
                        <div>
                            <h3 class="text-lg font-bold text-gray-900 dark:text-white" id="wizard-title">Create New Agent</h3>
                            <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="wizard-step-num">1</span> of ${TOTAL_STEPS}</p>
                        </div>
                        <button id="close-wizard-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300">
                            <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1 shrink-0">
                        <div id="wizard-progress" class="bg-blue-600 h-1 transition-all duration-300" style="width: 25%"></div>
                    </div>

                    <!-- Content Area (Scrollable) -->
                    <div id="wizard-content" class="p-8 overflow-y-auto flex-1 min-h-[400px]">
                        <!-- Dynamic Content loads here -->
                    </div>

                    <!-- Footer -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between shrink-0">
                        <button id="wizard-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50">Back</button>
                        <button id="wizard-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);

    document.getElementById('close-wizard-btn').addEventListener('click', closeWizard);
    document.getElementById('wizard-back-btn').addEventListener('click', prevStep);
    document.getElementById('wizard-next-btn').addEventListener('click', nextStep);
}

// --- NAVIGATION LOGIC ---

function updateProgress() {
    document.getElementById('wizard-step-num').innerText = currentStep;
    document.getElementById('wizard-progress').style.width = `${(currentStep / TOTAL_STEPS) * 100}%`;

    const backBtn = document.getElementById('wizard-back-btn');
    const nextBtn = document.getElementById('wizard-next-btn');

    backBtn.disabled = currentStep === 1;
    const isEdit = !!agentData.key;
    if (currentStep === TOTAL_STEPS) {
        nextBtn.innerText = isEdit ? 'Save Changes' : 'Create Agent';
        nextBtn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.add('bg-green-600', 'hover:bg-green-700');
    } else {
        nextBtn.innerText = 'Next';
        nextBtn.classList.add('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
    }
}

function nextStep() {
    if (!validateCurrentStep()) return;
    saveCurrentStepData();

    if (currentStep < TOTAL_STEPS) {
        currentStep++;
        renderStep(currentStep);
    } else {
        finishWizard();
    }
}

function prevStep() {
    if (currentStep > 1) {
        currentStep--;
        renderStep(currentStep);
    }
}

function renderStep(step) {
    updateProgress();
    const container = document.getElementById('wizard-content');
    container.innerHTML = ''; // Clear

    switch (step) {
        case 1: renderIdentityStep(container); break;
        case 2: renderIntellectStep(container); break;
        case 3: renderConscienceStep(container); break;
        case 4: renderWillStep(container); break;
    }
}

// === STEP 1: PROFILE & GOVERNANCE ===
async function renderIdentityStep(container) {
    // CORRECTED TITLE & CONTENT
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Profile & Governance</h2>
        <p class="text-gray-500 mb-6">Define the agent's identity and attach it to a compliance policy.</p>
        
        <div class="grid grid-cols-1 gap-6">
            <!-- Basic Info -->
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Agent Name</label>
                    <input type="text" id="wiz-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. The Stoic Coach" value="${agentData.name}">
                    ${agentData.key ? `<p class="text-xs text-gray-400 mt-1">Key: ${agentData.key} (Cannot be changed)</p>` : ''}
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Short Description</label>
                    <input type="text" id="wiz-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. A wise mentor based on Marcus Aurelius" value="${agentData.description}">
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Avatar URL (Optional)</label>
                    <input type="text" id="wiz-avatar" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="https://example.com/image.png" value="${agentData.avatar}">
                </div>
            </div>

            <!-- GOVERNANCE & VISIBILITY SELECTION -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- VISIBILITY -->
                <div>
                    <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Visibility</label>
                    <div class="relative">
                        <select id="wiz-visibility" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 appearance-none">
                            <option value="private" ${agentData.visibility === 'private' ? 'selected' : ''}>Private (Testing only)</option>
                            <option value="member" ${agentData.visibility === 'member' ? 'selected' : ''}>Organization (Everyone)</option>
                            <option value="auditor" ${agentData.visibility === 'auditor' ? 'selected' : ''}>Auditors & Admins Only</option>
                            <option value="admin" ${agentData.visibility === 'admin' ? 'selected' : ''}>Admins Only</option>
                        </select>
                        <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700 dark:text-gray-300">
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                        </div>
                    </div>
                </div>

                <!-- RAG Configuration -->
                <div class="pt-4 border-t border-gray-200 dark:border-neutral-800 mt-2">
                    <h3 class="text-sm font-bold text-gray-900 dark:text-white mb-4 uppercase tracking-wider">RAG / Knowledge Base</h3>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Knowledge Base ID</label>
                            <input type="text" id="wiz-rag-kb" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. bible_bsb_v1" value="${agentData.rag_knowledge_base || ''}">
                            <p class="text-xs text-gray-500 mt-1">Foundational text for retrieval</p>
                        </div>
                        <div>
                             <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Format String</label>
                             <textarea id="wiz-rag-fmt" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono text-xs h-[100px]" placeholder="REFERENCE: {reference}\nCONTENT:\n{text_chunk}\n---">${agentData.rag_format_string || 'REFERENCE: {reference}\nCONTENT:\n{text_chunk}\n---'}</textarea>
                             <p class="text-xs text-gray-500 mt-1">Result formatting template</p>
                        </div>
                    </div>
                </div>

            </div>
                <div class="bg-blue-50 dark:bg-blue-900/10 p-5 rounded-xl border border-blue-200 dark:border-blue-800">
                    <div class="flex items-center gap-2 mb-2">
                        <svg class="w-5 h-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                        <label class="block text-sm font-bold text-blue-900 dark:text-blue-100">Governing Policy</label>
                    </div>
                    
                    <div class="flex gap-4">
                        <select id="wiz-policy" class="flex-1 p-2 rounded border border-blue-300 dark:border-blue-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500">
                            <option value="standalone">Loading Policies...</option>
                        </select>
                    </div>
                    <p class="text-xs text-blue-600 dark:text-blue-300 mt-2">
                        Policies define the "Constitution" (Values & Rules) that this agent must obey.
                    </p>
                    <div id="wiz-policy-preview" class="hidden mt-3 text-xs p-3 bg-white dark:bg-neutral-900 rounded border border-blue-100 dark:border-neutral-700 text-gray-600 dark:text-gray-400">
                        <!-- Preview populated by JS -->
                    </div>
                </div>
            </div>
        </div>
    `;

    // Fetch and Populate Policies
    try {
        const res = await api.fetchPolicies();
        const policies = (res.ok && res.policies) ? res.policies : [];
        const select = document.getElementById('wiz-policy');

        if (select) {
            select.innerHTML = `<option value="standalone">No Governance (Standalone)</option>`;
            policies.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name} ${p.is_demo ? '(Official)' : ''}`;
                select.appendChild(opt);
            });

            // Set current value
            select.value = agentData.policy_id || "standalone";

            // Change Listener for Preview
            select.addEventListener('change', () => {
                const pid = select.value;
                const preview = document.getElementById('wiz-policy-preview');

                if (pid === 'standalone') {
                    preview.classList.add('hidden');
                    return;
                }

                const policy = policies.find(p => p.id === pid);
                if (policy) {
                    preview.innerHTML = `
                        <strong class="block mb-1 text-blue-800 dark:text-blue-200">Policy: ${policy.name}</strong>
                        <div class="grid grid-cols-2 gap-4 mt-2">
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400">Values</span>
                                <ul class="list-disc list-inside mt-1">
                                    ${(policy.values_weights || []).slice(0, 2).map(v => `<li>${v.name}</li>`).join('')}
                                </ul>
                            </div>
                            <div>
                                <span class="uppercase text-[10px] font-bold text-gray-400">Rules</span>
                                <ul class="list-disc list-inside mt-1 text-red-600 dark:text-red-400">
                                    ${(policy.will_rules || []).slice(0, 2).map(r => `<li>${r.substring(0, 30)}...</li>`).join('')}
                                </ul>
                            </div>
                        </div>
                    `;
                    preview.classList.remove('hidden');
                }
            });

            // Trigger once to load initial state
            select.dispatchEvent(new Event('change'));
        }

    } catch (e) {
        console.error("Failed to load policies", e);
    }
}

// Helper to render model dropdown
function renderModelSelector(id, currentValue, category) {
    console.log(`[Wizard] Rendering selector ${id} forcat ${category}. Available:`, availableModelsCache.length);

    const filteredModels = availableModelsCache.filter(m => {
        if (typeof m === 'string') return true;
        return !m.categories || m.categories.includes(category);
    });
    console.log(`[Wizard] Filtered models for ${category}:`, filteredModels);

    if (filteredModels.length === 0) {
        // Fallback to text input if no models loaded
        return `<input type="text" id="${id}" class="p-1 text-sm border-b border-gray-300 dark:border-neutral-700 bg-transparent focus:ring-0 w-32" placeholder="Default" value="${currentValue}">`;
    }

    return `
        <select id="${id}" class="p-1 text-xs border border-gray-300 dark:border-neutral-700 rounded bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 w-40">
            <option value="">Default (System)</option>
            ${filteredModels.map(m => {
        const val = m.id || m;
        const label = m.label || m;
        return `<option value="${val}" ${val === currentValue ? 'selected' : ''}>${label}</option>`;
    }).join('')}
        </select>
    `;
}

// === STEP 2: INTELLECT (Worldview & Style) ===
function renderIntellectStep(container) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
             <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Intellect & Style</h2>
                <p class="text-gray-500 text-sm mb-4">How does this agent think and speak?</p>
             </div>
             <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">AI Model</label>
                ${renderModelSelector('wiz-intellect-model', agentData.intellect_model || '', 'intellect')}
            </div>
        </div>
        
        <div class="space-y-6">
            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">System Instructions / Persona</label>
                        <p class="text-xs text-gray-400">TIPS: Use "You are..." statements. Describe their core philosophy.</p>
                    </div>
                     <button id="wiz-gen-persona-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-instructions" class="w-full h-40 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="You are a Stoic philosopher. You view the world through the dichotomy of control...">${agentData.instructions}</textarea>
            </div>

            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Communication Style</label>
                        <p class="text-xs text-gray-400">How should they speak? (e.g., Formal, Socratic, Concise)</p>
                    </div>
                    <button id="wiz-gen-style-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-style" class="w-full h-24 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.">${agentData.style}</textarea>
            </div>
        </div>
    `;

    // AI PERSONA HANDLER
    document.getElementById('wiz-gen-persona-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Drafting...`;
        btn.disabled = true;

        try {
            const context = agentData.description || "A helpful AI assistant";
            const res = await api.generatePolicyContent('persona', context, { name: agentData.name });

            if (res.ok && res.content) {
                document.getElementById('wiz-instructions').value = res.content;
                agentData.instructions = res.content;
                ui.showToast("Persona generated!", "success");
            } else {
                ui.showToast("Failed to generate persona", "error");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("Generation error", "error");
        } finally {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    });

    // AI STYLE HANDLER
    document.getElementById('wiz-gen-style-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Drafting...`;
        btn.disabled = true;

        try {
            const context = agentData.instructions || agentData.description || "A helpful AI assistant";
            const res = await api.generatePolicyContent('style', context, { name: agentData.name });

            if (res.ok && res.content) {
                document.getElementById('wiz-style').value = res.content;
                agentData.style = res.content;
                ui.showToast("Style generated!", "success");
            } else {
                ui.showToast("Failed to generate style", "error");
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

// === STEP 3: CONSCIENCE (Values) ===
function renderConscienceStep(container) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
            <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Core Values</h2>
                <p class="text-gray-500 text-sm mb-6">What does this agent value? The AI will score itself against these.</p>
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">AI Model</label>
                ${renderModelSelector('wiz-conscience-model', agentData.conscience_model || '', 'support')}
            </div>
        </div>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="wiz-val-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="Enter a value (e.g. Honesty, Frugality)">
            <button id="wiz-add-val-btn" class="px-4 py-2 bg-blue-600 text-white rounded-lg font-semibold hover:bg-blue-700 transition-colors shadow">
                Auto-Generate Rubric ✨
            </button>
        </div>

        <div id="wiz-values-list" class="space-y-4 max-h-[400px] overflow-y-auto pr-2">
            <!-- Values cards go here -->
        </div>
    `;

    renderValuesList();

    // Auto-Generate Handler
    document.getElementById('wiz-add-val-btn').addEventListener('click', async () => {
        const name = document.getElementById('wiz-val-input').value.trim();
        if (!name) return ui.showToast("Please enter a value name", "error");

        const btn = document.getElementById('wiz-add-val-btn');
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Generating...`;
        btn.disabled = true;

        try {
            const context = agentData.instructions || agentData.description;
            const res = await api.generateRubric(name, context);

            if (res.ok && res.rubric) {
                const rubric = res.rubric;
                agentData.values.push({
                    name: name,
                    weight: 0.2, // Default weight
                    description: rubric.description,
                    rubric: rubric.scoring_guide
                });
                renderValuesList();
                document.getElementById('wiz-val-input').value = '';
                ui.showToast(`Generated rubric for ${name}`, "success");
            } else {
                throw new Error(res.error || "Unknown error");
            }
        } catch (e) {
            ui.showToast(`Generation failed: ${e.message}`, "error");
        } finally {
            btn.innerHTML = "Auto-Generate Rubric ✨";
            btn.disabled = false;
        }
    });
}

function renderValuesList() {
    const list = document.getElementById('wiz-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (agentData.values.length === 0) {
        list.innerHTML = `<div class="text-center text-gray-400 py-8 border-2 border-dashed border-gray-200 dark:border-neutral-800 rounded-lg">No values yet. Add one above!</div>`;
        return;
    }

    agentData.values.forEach((val, idx) => {
        const card = document.createElement('div');
        card.className = "bg-gray-50 dark:bg-neutral-800 p-4 rounded-lg border border-gray-200 dark:border-neutral-700 relative group";

        // Prepare JSON for the textarea
        const rubricJson = JSON.stringify(val.rubric, null, 2);

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <div class="flex-1">
                    <input type="text" class="font-bold text-lg text-gray-900 dark:text-white bg-transparent border-none focus:ring-0 p-0 w-full" value="${val.name}" onchange="updateValueName(${idx}, this.value)">
                    <p class="text-xs text-gray-500">${val.description}</p>
                </div>
                <div class="flex gap-2">
                    <button class="text-blue-500 hover:text-blue-700 text-xs" onclick="toggleEdit(${idx})">Edit</button>
                    <button class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity" onclick="window.removeValue(${idx})">
                    <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </div>
            </div>
            
             <!-- Edit Mode (Hidden) -->
            <div id="wiz-val-edit-${idx}" class="hidden mt-4 space-y-3 border-t border-gray-200 dark:border-neutral-700 pt-3">
                <div>
                    <label class="block text-xs font-bold text-gray-500 mb-1">Description</label>
                    <textarea class="w-full text-xs p-2 rounded border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-gray-900 dark:text-white" rows="2" onchange="updateValueDesc(${idx}, this.value)">${val.description}</textarea>
                </div>
                <div>
                    <label class="block text-xs font-bold text-gray-500 mb-1">Rubric Criteria (JSON)</label>
                    <textarea class="w-full font-mono text-xs p-2 rounded border border-gray-300 dark:border-neutral-700 bg-gray-900 text-green-400" rows="6" onchange="updateValueRubric(${idx}, this.value)">${rubricJson}</textarea>
                </div>
            </div>

            <!-- Mini Rubric Preview -->
            <div id="wiz-val-preview-${idx}" class="grid grid-cols-3 gap-2 text-xs mt-3">
               <div class="p-2 bg-red-100 dark:bg-red-900/30 rounded text-red-800 dark:text-red-200">
                   <strong>-1.0:</strong> ${(val.rubric && val.rubric.find(r => r.score < 0)?.criteria) || 'Violation'}
               </div>
               <div class="p-2 bg-gray-100 dark:bg-gray-700/50 rounded text-gray-800 dark:text-gray-200">
                   <strong>0.0:</strong> ${(val.rubric && val.rubric.find(r => r.score === 0)?.criteria) || 'Neutral'}
               </div>
               <div class="p-2 bg-green-100 dark:bg-green-900/30 rounded text-green-800 dark:text-green-200">
                   <strong>1.0:</strong> ${(val.rubric && val.rubric.find(r => r.score > 0)?.criteria) || 'Perfect'}
               </div>
            </div>
        `;
        list.appendChild(card);
    });

    // Helpers attached to window for inline onclicks
    window.toggleEdit = (idx) => {
        const editDiv = document.getElementById(`wiz-val-edit-${idx}`);
        if (editDiv) {
            editDiv.classList.toggle('hidden');
        }
    };

    window.updateValueName = (idx, val) => {
        agentData.values[idx].name = val;
    };

    window.updateValueDesc = (idx, val) => {
        agentData.values[idx].description = val;
    };

    window.updateValueRubric = (idx, val) => {
        try {
            const parsed = JSON.parse(val);
            agentData.values[idx].rubric = parsed;
        } catch (e) {
            alert("Invalid JSON");
        }
    };

    window.removeValue = (idx) => {
        agentData.values.splice(idx, 1);
        renderValuesList();
    };
}


// === STEP 4: WILL (Rules) ===
function renderWillStep(container) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
            <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Rules (Non-Negotiable)</h2>
                <p class="text-gray-500 text-sm">Hard rules. If the Intellect violates these, the Will forces a rewrite.</p>
            </div>
             <div class="flex flex-col items-end gap-2">
                <div>
                     <label class="block text-xs font-bold text-gray-500 uppercase text-right mb-1">AI Model</label>
                     ${renderModelSelector('wiz-will-model', agentData.will_model || '', 'support')}
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

    renderRulesList();

    // Add Manual Rule
    const addRule = () => {
        const input = document.getElementById('wiz-rule-input');
        const rule = input.value.trim();
        if (rule) {
            agentData.rules.push(rule);
            input.value = '';
            renderRulesList();
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
            // Use instructions (Step 2) as context, fallback to description (Step 1)
            const context = agentData.instructions || agentData.description || "General Assistant";
            const res = await api.generatePolicyContent('rules', context);

            if (res.ok && res.content) {
                let newRules = [];
                try {
                    // Case 1: Already an Array (Backend sent JSON list)
                    if (Array.isArray(res.content)) {
                        newRules = res.content;
                    }
                    // Case 2: String that needs parsing
                    else if (typeof res.content === 'string') {
                        // Try JSON parse first
                        try {
                            const json = JSON.parse(res.content);
                            if (Array.isArray(json)) newRules = json;
                        } catch (e) {
                            // Fallback to newline splitting
                            newRules = res.content.split('\n').filter(l => l.trim().length > 0);
                        }
                    }

                    if (newRules.length > 0) {
                        // Standardize format (Action-First)
                        const processedRules = newRules.map(r => {
                            let clean = r.trim();

                            // 1. Remove common fluff prefixes
                            clean = clean.replace(/^(The AI should|The AI must|The agent should|The agent must|Must|Will|Always)\s+/i, "");

                            // 2. Normalize "Refuse/Decline" to "Reject requests to " (Clean English grammar)
                            if (clean.match(/^(Refuse|Decline|Deny)\s+to\s+/i)) {
                                clean = clean.replace(/^(Refuse|Decline|Deny)\s+to\s+/i, "Reject requests to ");
                            }
                            else if (clean.match(/^Never\s+/i)) {
                                clean = clean.replace(/^Never\s+/i, "Reject requests to ");
                            }

                            // 3. Fallback: If it doesn't start with a strong action verb, assume it's a negative constraint
                            if (!clean.match(/^(Reject|Require|Flag|Do not)/i)) {
                                return "Reject " + clean;
                            }

                            return clean.charAt(0).toUpperCase() + clean.slice(1);
                        });

                        // Merge unique
                        agentData.rules = [...new Set([...agentData.rules, ...processedRules])];
                        renderRulesList();
                        ui.showToast(`Added ${processedRules.length} rules`, "success");
                    }
                } catch (e) {
                    console.error("Rules processing error", e);
                    ui.showToast("Failed to process rules", "error");
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

function renderRulesList() {
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
        renderRulesList();
    };
}


// --- VALIDATION & SAVING ---

function validateCurrentStep() {
    if (currentStep === 1) {
        const name = document.getElementById('wiz-name').value;
        if (!name || !name.trim()) {
            alert("Agent Name is required");
            return false;
        }
    }
    return true;
}

function saveCurrentStepData() {
    if (currentStep === 1) {
        agentData.name = document.getElementById('wiz-name').value.trim();
        agentData.description = document.getElementById('wiz-desc').value.trim();
        agentData.avatar = document.getElementById('wiz-avatar').value.trim();
        agentData.visibility = document.getElementById('wiz-visibility').value;
        // Save Policy ID if available
        const policySelect = document.getElementById('wiz-policy');
        if (policySelect) {
            agentData.policy_id = policySelect.value;
        }

        // Generate key ONLY if it doesn't exist (Create Mode)
        if (!agentData.key && agentData.name) {
            agentData.key = agentData.name.toLowerCase().replace(/[^a-z0-9]/g, '_');
            agentData.is_update_mode = false;
        }

        // New RAG Fields
        agentData.rag_knowledge_base = document.getElementById('wiz-rag-kb').value;
        agentData.rag_format_string = document.getElementById('wiz-rag-fmt').value;
    } else if (currentStep === 2) {
        agentData.instructions = document.getElementById('wiz-instructions').value;
        agentData.style = document.getElementById('wiz-style').value;
        agentData.intellect_model = document.getElementById('wiz-intellect-model')?.value || "";
    } else if (currentStep === 3) {
        // Values updated in real-time
        agentData.conscience_model = document.getElementById('wiz-conscience-model')?.value || "";
    } else if (currentStep === 4) {
        // Rules updated in real-time
        agentData.will_model = document.getElementById('wiz-will-model')?.value || "";
    }
}

// === API CALLS ===
async function finishWizard() {
    const btn = document.getElementById('wizard-next-btn');
    const originalText = btn.innerText;
    btn.innerText = "Saving...";
    btn.disabled = true;

    try {
        const payload = {
            ...agentData,
            // MAP Frontend 'instructions' (Persona) to Backend 'worldview'
            worldview: agentData.instructions,
            // Ensure we send the correct key for update, or allow backend to generate for create
            key: agentData.key || undefined
        };

        const res = await api.saveAgent(payload, agentData.is_update_mode);

        if (res.ok) {
            const isNew = !agentData.is_update_mode;
            if (isNew) {
                ui.showToast(`Agent "${agentData.name}" created!`, "success");
            } else {
                ui.showToast(`Agent "${agentData.name}" updated!`, "success");
            }
            closeWizard();

            setTimeout(() => window.location.reload(), 1000);

        } else {
            // Handle specific API errors
            if (res.status === 409 || (res.error && res.error.includes("exists"))) {
                ui.showToast("Agent name already taken. Please Edit existing agent.", "error");
            } else {
                ui.showToast(res.error || "Failed to save agent", "error");
            }
        }
    } catch (e) {
        console.error("Save Wizard Error", e);
        if (e.message && e.message.includes("409")) {
            ui.showToast("Agent name already taken. Please Edit existing agent.", "error");
        } else {
            ui.showToast("Error saving agent: " + e.message, "error");
        }
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
}