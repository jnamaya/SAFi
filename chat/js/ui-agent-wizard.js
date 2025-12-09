import * as ui from './ui.js';
import * as api from './api.js';

// --- WIZARD STATE ---
let currentStep = 1;
const TOTAL_STEPS = 4;
let agentData = {
    key: "",
    name: "",
    description: "",
    avatar: "", // NEW: Custom Avatar URL
    instructions: "", // Worldview
    style: "", // NEW: Communication Style
    values: [],
    rules: [],
    policy_id: "standalone" // NEW: Governance Policy
};

// --- MAIN ENTRY POINT ---
export function openAgentWizard(existingAgent = null) {
    // Reset State
    currentStep = 1;

    if (existingAgent) {
        // PRE-FILL for Edit Mode
        // Map backend fields to frontend state
        agentData = {
            key: existingAgent.key,
            name: existingAgent.name,
            description: existingAgent.description || "",
            avatar: existingAgent.avatar || "", // Load existing avatar
            instructions: (existingAgent.worldview || "").replace("--- Organizational Policy ---\n", "").split("--- SPECIFIC ROLE ---\n").pop() || "",
            style: existingAgent.style || "", // Load existing style
            values: existingAgent.values || [],
            rules: existingAgent.will_rules || [],
            policy_id: existingAgent.policy_id || "standalone"
        };
        // Clean up instructions if they are just the raw worldview
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
            rules: []
        };
    }

    // Inject Modal if needed (lazy load)
    ensureWizardModalExists();

    // Update Header 
    const title = document.getElementById('wizard-title');
    if (title) title.innerText = existingAgent ? "Edit Agent" : "Create New Agent";

    // Render Step 1
    renderStep(1);

    // Show Modal
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
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-3xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800">
                    
                    <!-- Header -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-bold text-gray-900 dark:text-white" id="wizard-title">Create New Agent</h3>
                            <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="wizard-step-num">1</span> of ${TOTAL_STEPS}</p>
                        </div>
                        <button id="close-wizard-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300">
                            <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1">
                        <div id="wizard-progress" class="bg-green-600 h-1 transition-all duration-300" style="width: 25%"></div>
                    </div>

                    <!-- Content Area -->
                    <div id="wizard-content" class="p-8 min-h-[400px]">
                        <!-- Dynamic Content loads here -->
                    </div>

                    <!-- Footer -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between">
                        <button id="wizard-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50">Back</button>
                        <button id="wizard-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);

    // Attach Global Listeners
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
    } else {
        nextBtn.innerText = 'Next';
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

// --- STEP RENDERING ---

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

// === STEP 1: IDENTITY ===
function renderIdentityStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4">Identity & Style</h2>
        <p class="text-gray-500 mb-6">Who is this agent? Give them a name and a personality.</p>
        
        <div class="space-y-4">
            <div>
                <label class="block text-sm font-bold mb-2">Agent Name</label>
                <input type="text" id="wiz-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. The Stoic Coach" value="${agentData.name}">
                ${agentData.key ? `<p class="text-xs text-gray-400 mt-1">Key: ${agentData.key} (Cannot be changed)</p>` : ''}
            </div>
            <div>
                <label class="block text-sm font-bold mb-2">Short Description</label>
                <input type="text" id="wiz-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. A wise mentor based on Marcus Aurelius" value="${agentData.description}">
            </div>
            <div>
                <label class="block text-sm font-bold mb-2">Avatar URL (Optional)</label>
                <input type="text" id="wiz-avatar" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="https://example.com/image.png" value="${agentData.avatar}">
                <p class="text-xs text-gray-400 mt-1">Provide a direct link to an image to use as the avatar.</p>
            </div>
        </div>
    `;
}

// === STEP 2: INTELLECT (Worldview & Style) ===
async function renderIntellectStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4">Worldview (The Intellect)</h2>
        <p class="text-gray-500 mb-6">How does this agent think? Define their philosophy and tone.</p>
        
        <div class="space-y-4">
            <!-- GOVERNANCE DROPDOWN -->
            <div class="bg-blue-50 dark:bg-blue-900/10 p-4 rounded-lg border border-blue-200 dark:border-blue-800">
                <label class="block text-sm font-bold mb-2 text-blue-900 dark:text-blue-100">Governing Policy</label>
                <div class="flex gap-4">
                    <select id="wiz-policy" class="flex-1 p-2 rounded border border-blue-300 dark:border-blue-700 bg-white dark:bg-neutral-800">
                        <option value="standalone">Loading Policies...</option>
                    </select>
                </div>
                <p class="text-xs text-blue-600 dark:text-blue-300 mt-2" id="wiz-policy-desc">
                    Policies define base values and hard rules that cannot be overridden.
                </p>
                <div id="wiz-policy-preview" class="hidden mt-3 text-xs p-2 bg-white dark:bg-neutral-900 rounded border border-blue-100 dark:border-neutral-700 text-gray-600 dark:text-gray-400">
                    <!-- Preview -->
                </div>
            </div>

            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold">System Instructions / Persona</label>
                        <p class="text-xs text-gray-400">TIPS: Use "You are..." statements. Describe their core philosophy.</p>
                    </div>
                     <button id="wiz-gen-persona-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-instructions" class="w-full h-40 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm" placeholder="You are a Stoic philosopher. You view the world through the dichotomy of control...">${agentData.instructions}</textarea>
            </div>
            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold">Communication Style</label>
                        <p class="text-xs text-gray-400">How should they speak? (e.g., Formal, Socratic, Concise)</p>
                    </div>
                    <button id="wiz-gen-style-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-style" class="w-full h-24 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm" placeholder="Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.">${agentData.style}</textarea>
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

    // Fetch and Populate Policies
    try {
        const res = await api.fetchPolicies();
        const policies = (res.ok && res.policies) ? res.policies : [];
        const select = document.getElementById('wiz-policy');
        if (!select) return;

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
                    <strong class="block mb-1">Inherited Rules:</strong>
                    <ul class="list-disc list-inside">
                        ${(policy.will_rules || []).slice(0, 3).map(r => `<li>${r}</li>`).join('')}
                        ${(policy.will_rules || []).length > 3 ? `<li>...and ${(policy.will_rules.length - 3)} more</li>` : ''}
                    </ul>
                `;
                preview.classList.remove('hidden');
            }
        });

        // Trigger once
        select.dispatchEvent(new Event('change'));

    } catch (e) {
        console.error("Failed to load policies", e);
    }
}

// === STEP 3: CONSCIENCE (Values) ===
function renderConscienceStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-2">Ethical Values (The Conscience)</h2>
        <p class="text-gray-500 mb-6">What does this agent value? The AI will score itself against these.</p>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="wiz-val-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="Enter a value (e.g. Honesty, Frugality)">
            <button id="wiz-add-val-btn" class="px-4 py-2 bg-blue-600 text-white rounded-lg font-semibold hover:bg-blue-700 transition-colors">
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
        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <div>
                    <h4 class="font-bold text-lg">${val.name}</h4>
                    <p class="text-xs text-gray-500">${val.description}</p>
                </div>
                <button class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity" onclick="window.removeValue(${idx})">
                   <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                </button>
            </div>
            
            <!-- Mini Rubric Preview -->
            <div class="grid grid-cols-3 gap-2 text-xs mt-3">
               <div class="p-2 bg-red-100 dark:bg-red-900/30 rounded text-red-800 dark:text-red-200">
                   <strong>-1.0:</strong> ${val.rubric.find(r => r.score < 0)?.criteria || 'Violation'}
               </div>
               <div class="p-2 bg-gray-100 dark:bg-gray-700/50 rounded text-gray-800 dark:text-gray-200">
                   <strong>0.0:</strong> ${val.rubric.find(r => r.score === 0)?.criteria || 'Neutral'}
               </div>
               <div class="p-2 bg-green-100 dark:bg-green-900/30 rounded text-green-800 dark:text-green-200">
                   <strong>1.0:</strong> ${val.rubric.find(r => r.score > 0)?.criteria || 'Perfect'}
               </div>
            </div>
        `;
        list.appendChild(card);
    });

    // Global helper for the onclick
    window.removeValue = (idx) => {
        agentData.values.splice(idx, 1);
        renderValuesList();
    };
}


// === STEP 4: WILL (Rules) ===
function renderWillStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-2">The Will (Gatekeeper)</h2>
        <p class="text-gray-500 mb-6">Hard rules. If the Intellect violates these, the Will forces a rewrite.</p>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="wiz-rule-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. Do not create Python scripts.">
            <button id="wiz-add-rule-btn" class="px-6 py-2 bg-neutral-800 dark:bg-neutral-700 text-white rounded-lg font-semibold hover:bg-black transition-colors">
                Add Rule
            </button>
        </div>

        <ul id="wiz-rules-list" class="space-y-2">
            <!-- Rules go here -->
        </ul>
    `;

    renderRulesList();

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
}

function renderRulesList() {
    const list = document.getElementById('wiz-rules-list');
    if (!list) return;
    list.innerHTML = '';

    agentData.rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-3 bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg";
        item.innerHTML = `
            <span class="text-sm font-medium">⛔ ${rule}</span>
            <button class="text-gray-400 hover:text-red-500" onclick="window.removeRule(${idx})">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        `;
        list.appendChild(item);
    });

    window.removeRule = (idx) => {
        agentData.rules.splice(idx, 1);
        renderRulesList();
    };
}


// --- VALIDATION & SAVING ---

function validateCurrentStep() {
    if (currentStep === 1) {
        const name = document.getElementById('wiz-name').value.trim();
        if (!name) {
            ui.showToast("Please name your agent.", "error");
            return false;
        }
    }
    return true;
}

function saveCurrentStepData() {
    if (currentStep === 1) {
        agentData.name = document.getElementById('wiz-name').value.trim();
        agentData.description = document.getElementById('wiz-desc').value.trim();
        agentData.avatar = document.getElementById('wiz-avatar').value.trim(); // Save Avatar
        // Generate key ONLY if it doesn't exist (Create Mode)
        if (!agentData.key) {
            agentData.key = agentData.name.toLowerCase().replace(/[^a-z0-9]/g, '_');
        }
    }
    if (currentStep === 2) {
        agentData.instructions = document.getElementById('wiz-instructions').value;
        agentData.style = document.getElementById('wiz-style').value; // Save Style
        agentData.policy_id = document.getElementById('wiz-policy').value; // Save Policy
    }
}

async function finishWizard() {
    const btn = document.getElementById('wizard-next-btn');
    const isEdit = !!agentData.key;
    btn.innerHTML = isEdit ? "Saving..." : "Creating Agent...";
    btn.disabled = true;

    try {
        const payload = {
            key: agentData.key,
            name: agentData.name,
            description: agentData.description,
            avatar: agentData.avatar, // Include Avatar
            worldview: agentData.instructions,
            style: agentData.style, // Include Style
            values: agentData.values,
            will_rules: agentData.rules,
            policy_id: agentData.policy_id, // Include Policy
            is_custom: true
        };

        await api.saveAgent(payload);

        ui.showToast(isEdit ? "Agent Updated!" : "Agent Created Successfully!", "success");
        closeWizard();

        // Trigger a refresh of the profiles list
        setTimeout(() => window.location.reload(), 1000);

    } catch (e) {
        ui.showToast(`Error saving agent: ${e.message}`, "error");
        btn.innerHTML = "Try Again";
        btn.disabled = false;
    }
}