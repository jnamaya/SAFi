import * as ui from './ui.js';
import * as api from './api.js';

// --- WIZARD STATE ---
let currentStep = 1;
const TOTAL_STEPS = 3;
let policyData = {
    policy_id: null,
    name: "",
    context: "", // Business Description
    worldview: "",
    values: [],
    will_rules: []
};

let generatedCredentials = null;

// --- MAIN ENTRY POINT ---
export function openPolicyWizard(existingPolicy = null) {
    currentStep = 1;
    generatedCredentials = null;

    if (existingPolicy) {
        policyData = {
            policy_id: existingPolicy.id,
            name: existingPolicy.name,
            context: "",
            worldview: existingPolicy.worldview || "",
            values: existingPolicy.values_weights || [],
            will_rules: existingPolicy.will_rules || []
        };

        // HACK: Restore Context from Worldview hidden comment
        const ctxMatch = policyData.worldview.match(/<!-- CONTEXT: (.*?) -->/);
        if (ctxMatch) {
            policyData.context = ctxMatch[1];
            // Remove the hack tag from the UI display so user doesn't see it (clean worldview)
            policyData.worldview = policyData.worldview.replace(/<!-- CONTEXT: .*? -->\n?/, "");
        }
    } else {
        policyData = {
            policy_id: null,
            name: "",
            context: "",
            worldview: "",
            values: [],
            will_rules: []
        };
    }

    ensureWizardModalExists();

    const title = document.getElementById('policy-wizard-title');
    if (title) title.innerText = existingPolicy ? "Edit Policy" : "Create Governance Policy";

    renderStep(1);

    const modal = document.getElementById('policy-wizard-modal');
    modal.classList.remove('hidden');
}

function closeWizard() {
    const modal = document.getElementById('policy-wizard-modal');
    modal.classList.add('hidden');
    if (generatedCredentials) {
        window.location.reload();
    }
}

function ensureWizardModalExists() {
    if (document.getElementById('policy-wizard-modal')) return;

    const html = `
    <div id="policy-wizard-modal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-4xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800">
                    
                    <!-- Header -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-bold text-gray-900 dark:text-white" id="policy-wizard-title">Create Governance Policy</h3>
                            <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="pw-step-num">1</span> of ${TOTAL_STEPS}</p>
                        </div>
                        <button id="close-pw-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300">
                            <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1">
                        <div id="pw-progress" class="bg-blue-600 h-1 transition-all duration-300" style="width: 33%"></div>
                    </div>

                    <!-- Content Area -->
                    <div id="pw-content" class="p-8 min-h-[450px]">
                        <!-- Dynamic Content -->
                    </div>

                    <!-- Footer -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between">
                        <button id="pw-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50">Back</button>
                        <button id="pw-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);

    document.getElementById('close-pw-btn').addEventListener('click', closeWizard);
    document.getElementById('pw-back-btn').addEventListener('click', prevStep);
    document.getElementById('pw-next-btn').addEventListener('click', nextStep);
}

function updateProgress() {
    document.getElementById('pw-step-num').innerText = currentStep;
    document.getElementById('pw-progress').style.width = `${(currentStep / TOTAL_STEPS) * 100}%`;

    const backBtn = document.getElementById('pw-back-btn');
    const nextBtn = document.getElementById('pw-next-btn');

    backBtn.disabled = currentStep === 1;

    if (currentStep === TOTAL_STEPS) {
        nextBtn.innerText = policyData.policy_id ? 'Save Changes' : 'Create Policy';
    } else {
        nextBtn.innerText = 'Next';
    }

    if (currentStep > TOTAL_STEPS) {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'none';
        document.querySelector('#policy-wizard-modal .border-b').style.display = 'none';
    } else {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'flex';
        document.querySelector('#policy-wizard-modal .border-b').style.display = 'flex';
    }
}

async function nextStep() {
    if (!validateCurrentStep()) return;
    saveCurrentStepData();

    if (currentStep < TOTAL_STEPS) {
        currentStep++;
        renderStep(currentStep);
    } else {
        await submitPolicy();
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
    const container = document.getElementById('pw-content');
    container.innerHTML = '';

    switch (step) {
        case 1: renderDefinitionStep(container); break;
        case 2: renderConstitutionStep(container); break;
        case 3: renderRulesStep(container); break;
        case 4: renderSuccessStep(container); break;
    }
}

// === STEP 1: DEFINITION ===
function renderDefinitionStep(container) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h2 class="text-2xl font-bold mb-4">Define Context</h2>
                <p class="text-gray-500 mb-6">Tell us about your organization. This helps our AI suggest rules.</p>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-bold mb-2">Policy Name</label>
                        <input type="text" id="pw-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. Global Standard, HR Safe Mode" value="${policyData.name}">
                    </div>

                    <div>
                        <label class="block text-sm font-bold mb-2">Organization Description</label>
                        <p class="text-xs text-gray-400 mb-2">E.g. "We are a Fintech company dealing with sensitive user data."</p>
                        <textarea id="pw-context" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm" placeholder="We are a...">${policyData.context}</textarea>
                    </div>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-blue-900/20 p-6 rounded-xl border border-blue-200 dark:border-blue-800 flex flex-col justify-center">
                <div class="mb-4 text-blue-600 dark:text-blue-300">
                    <svg class="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <h4 class="font-bold text-lg mb-2">Why does this matter?</h4>
                    <p class="text-sm leading-relaxed opacity-90">
                        Unlike traditional chatbots that just "answer questions", SAFi uses a 
                        <strong>Governance Layer</strong>. 
                        By defining your organization's context here, we can auto-generate a "Constitution" 
                        that ensures every AI agent speaks with your brand's voice and obeys your safety rules.
                    </p>
                </div>
            </div>
        </div>
    `;
}

// === STEP 2: CONSTITUTION ===
function renderConstitutionStep(container) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <div class="md:col-span-2 space-y-6">
                 <div>
                    <div class="flex justify-between items-end mb-2">
                         <div>
                            <label class="block text-sm font-bold">Global Worldview ("The Mission")</label>
                            <p class="text-xs text-gray-400">The core mission and identity of the organization.</p>
                         </div>
                         <button id="btn-gen-worldview" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Draft with AI
                         </button>
                    </div>
                    <textarea id="pw-worldview" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm leading-relaxed" placeholder="You are an AI assistant governed by...">${policyData.worldview}</textarea>
                </div>

                <div>
                    <div class="flex justify-between items-end mb-2">
                         <div>
                            <label class="block text-sm font-bold">Core Values & Rubrics</label>
                            <p class="text-xs text-gray-400">The ethical standards used to grade responses.</p>
                         </div>
                         <button id="btn-gen-values" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Suggest Values
                         </button>
                    </div>
                    
                    <div id="pw-values-list" class="space-y-3 mb-3">
                        <!-- Values rendered here -->
                    </div>
                    
                    <button id="btn-add-value" class="w-full py-2 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-lg text-sm text-gray-500 hover:border-blue-500 hover:text-blue-500 transition-colors">
                        + Add Custom Value
                    </button>
                </div>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700">
                <h4 class="font-bold text-gray-700 dark:text-gray-200 mb-4 flex items-center gap-2">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    Expert Tips
                </h4>
                <ul class="space-y-4 text-xs text-gray-500 dark:text-gray-400">
                    <li>
                        <strong>Worldview:</strong> This is the AI's "Job Description". Be explicit about who it represents (e.g. "You represent Acme Corp").
                    </li>
                    <li>
                        <strong>Values:</strong> These act as a rubric. The "Conscience" module will grade every draft response against these keywords.
                    </li>
                    <li class="p-3 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-800 dark:text-yellow-200 rounded border border-yellow-200 dark:border-yellow-800">
                        <strong>New:</strong> AI now generates detailed scoring rubrics for each value!
                    </li>
                </ul>
            </div>
        </div>
    `;

    // Initial Render
    renderValuesList();

    // AI HANDLERS
    document.getElementById('btn-gen-worldview').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerText = "Generating...";
        btn.disabled = true;

        try {
            const res = await api.generatePolicyContent('worldview', policyData.context || "General Organization");
            if (res.ok && res.content) {
                document.getElementById('pw-worldview').value = res.content;
            } else {
                ui.showToast("Failed to generate worldview", "error");
            }
        } catch (err) { console.error(err); }

        btn.innerHTML = original;
        btn.disabled = false;
    });

    document.getElementById('btn-gen-values').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerText = "Thinking...";
        btn.disabled = true;

        try {
            // Context is empty? Use name or generic
            const ctx = policyData.context || policyData.name || "General Organization";
            const res = await api.generatePolicyContent('values', ctx);
            if (res.ok && res.content) {
                let cleaned = res.content.trim();
                // Safety Fix: If AI returns raw objects like {"name":...}, {"name":...} wrap in []
                if (cleaned.startsWith('{') && !cleaned.startsWith('[')) {
                    cleaned = `[${cleaned}]`;
                }
                const json = JSON.parse(cleaned);

                // Assign DIRECTLY. JSON contains {name, description, rubric}
                // Ensure weight is present (default 0.2) to prevent backend crashes
                policyData.values = json.map(v => ({ ...v, weight: v.weight || 0.2 }));
                renderValuesList();
                ui.showToast("Values & Rubrics Generated!", "success");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("AI returned invalid format", "error");
        }

        btn.innerHTML = original;
        btn.disabled = false;
    });

    // Add Value Button
    document.getElementById('btn-add-value').addEventListener('click', () => {
        policyData.values.push({ name: "New Value", description: "", weight: 0.2 });
        renderValuesList();
    });
}

function renderValuesList() {
    const list = document.getElementById('pw-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.values.length === 0) {
        list.innerHTML = `<p class="text-sm text-gray-400 text-center italic">No values defined yet. Click "Suggest Values" to start.</p>`;
        return;
    }

    policyData.values.forEach((v, idx) => {
        let hasRubric = false;
        let rubricCount = 0;
        let rubricBadge = '<span class="text-yellow-600">⚠️ No Rubric</span>';

        if (v.rubric) {
            if (Array.isArray(v.rubric)) {
                // Legacy: Array logic
                hasRubric = v.rubric.length > 0;
                rubricCount = v.rubric.length;
            } else if (v.rubric.scoring_guide && Array.isArray(v.rubric.scoring_guide)) {
                // New: Object logic
                hasRubric = v.rubric.scoring_guide.length > 0;
                rubricCount = v.rubric.scoring_guide.length;
            }
        }

        if (hasRubric) {
            rubricBadge = `<span class="text-green-600 flex items-center gap-1">✅ Rubric (${rubricCount} levels)</span>`;
        }

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-3 shadow-sm hover:border-blue-300 transition-colors";

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2 gap-2">
                <input type="text" class="flex-1 font-bold bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 px-1" 
                    value="${v.name}" placeholder="Value Name" onchange="window.updatePolicyValueName(${idx}, this.value)">
                    
                <button class="text-gray-400 hover:text-red-500 p-1" onclick="window.removePolicyValue(${idx})">
                     <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea class="w-full text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-neutral-900 border border-transparent hover:border-gray-200 focus:border-blue-500 rounded p-2 resize-none h-16 outline-none"
                placeholder="Description of this value..." onchange="window.updatePolicyValueDesc(${idx}, this.value)">${v.description || ''}</textarea>
            
            <div class="mt-2 flex items-center justify-between">
                <span class="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                     ${rubricBadge}
                </span>
                <span class="text-[10px] text-gray-400">Weight: ${v.weight || 'Auto'}</span>
            </div>
        `;
        list.appendChild(card);
    });

    // Global Helpers for inline editing
    window.removePolicyValue = (idx) => {
        policyData.values.splice(idx, 1);
        renderValuesList();
    };
    window.updatePolicyValueName = (idx, val) => {
        if (policyData.values[idx]) policyData.values[idx].name = val;
    };
    window.updatePolicyValueDesc = (idx, val) => {
        if (policyData.values[idx]) policyData.values[idx].description = val;
    };
}

// === STEP 3: WILL (Rules) ===
function renderRulesStep(container) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div class="md:col-span-2">
                <div class="flex justify-between items-center mb-4">
                     <div>
                        <h2 class="text-2xl font-bold">The Will (Constraints)</h2>
                        <p class="text-gray-500 text-sm">Hard block rules. Interactions violating these are rejected.</p>
                     </div>
                     <button id="btn-gen-rules" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded-full flex items-center gap-1 transition-colors shadow">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Suggest Rules
                     </button>
                </div>
                
                <div class="flex gap-4 mb-6">
                    <input type="text" id="pw-rule-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. Never give financial advice.">
                    <button id="pw-add-rule-btn" class="px-6 py-2 bg-neutral-800 dark:bg-neutral-700 text-white rounded-lg font-semibold hover:bg-black transition-colors">
                        Add
                    </button>
                </div>

                <ul id="pw-rules-list" class="space-y-2"></ul>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 h-fit">
                <h4 class="font-bold text-gray-700 dark:text-gray-200 mb-4">Hard vs Soft?</h4>
                <p class="text-xs text-gray-500 dark:text-gray-400 mb-4 leading-relaxed">
                    <strong>Values (Step 2)</strong> are soft. The AI tries to align with them but can be flexible.
                </p>
                <p class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    <strong>Will (Step 3)</strong> are HARD stops. If a user asks the AI to break a Will rule, the "Will Faculty" intercepts and blocks the request entirely. Use this for legal or safety boundaries.
                </p>
            </div>
        </div>
    `;

    renderRulesList();

    // HANDLERS
    const addRule = () => {
        const input = document.getElementById('pw-rule-input');
        const rule = input.value.trim();
        if (rule) {
            policyData.will_rules.push(rule);
            input.value = '';
            renderRulesList();
        }
    };

    document.getElementById('pw-add-rule-btn').addEventListener('click', addRule);
    document.getElementById('pw-rule-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') addRule();
    });

    document.getElementById('btn-gen-rules').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerText = "Analyzing...";
        btn.disabled = true;

        try {
            const res = await api.generatePolicyContent('rules', policyData.context || "General Organization");
            if (res.ok && res.content) {
                try {
                    const json = JSON.parse(res.content);
                    if (Array.isArray(json)) {
                        policyData.will_rules = [...new Set([...policyData.will_rules, ...json])]; // Merge Unique
                        renderRulesList();
                    }
                } catch {
                    ui.showToast("AI returned invalid format", "error");
                }
            }
        } catch (err) { console.error(err); }

        btn.innerHTML = original;
        btn.disabled = false;
    });
}

function renderRulesList() {
    const list = document.getElementById('pw-rules-list');
    if (!list) return;
    list.innerHTML = '';

    policyData.will_rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-3 bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg shadow-sm";
        item.innerHTML = `
            <span class="text-sm font-medium">⛔ ${rule}</span>
            <button class="text-gray-400 hover:text-red-500" onclick="window.removePolicyRule(${idx})">
                 <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
        `;
        list.appendChild(item);
    });

    window.removePolicyRule = (idx) => {
        policyData.will_rules.splice(idx, 1);
        renderRulesList();
    };
}

// === STEP 4: SUCCESS ===
function renderSuccessStep(container) {
    if (!generatedCredentials) return;

    const { policy_id, api_key } = generatedCredentials;

    container.innerHTML = `
        <div class="text-center py-8">
            <div class="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
                <svg class="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-3xl font-bold mb-2">Policy Active!</h2>
            <p class="text-gray-500 text-lg">Your governance firewall is ready.</p>
        </div>

        <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 text-left">
            <h4 class="font-bold text-lg mb-4">Integration Credentials</h4>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Headless Endpoint</label>
                    <code class="block p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm truncate">.../api/bot/process_prompt</code>
                </div>
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">API Key</label>
                    <div class="flex gap-2">
                        <code class="flex-1 p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm text-green-600 font-bold truncate">${api_key}</code>
                        <button class="px-3 bg-gray-200 hover:bg-gray-300 rounded text-black font-bold" onclick="navigator.clipboard.writeText('${api_key}')">Copy</button>
                    </div>
                </div>
            </div>
            
            <div class="mt-6 pt-6 border-t border-gray-200 dark:border-neutral-700">
                <h4 class="font-bold text-lg mb-2">🚀 Next Steps</h4>
                <p class="text-sm text-gray-500">Go to your Microsoft Teams Bot code and update the <code>SAFI_BOT_SECRET</code>.</p>
            </div>
        </div>
        
        <div class="mt-8 text-center">
            <button onclick="window.location.reload()" class="px-8 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 shadow-lg transition-transform hover:-translate-y-0.5">
                Go to Dashboard
            </button>
        </div>
    `;
}

// === LOGIC ===
function validateCurrentStep() {
    if (currentStep === 1) {
        const name = document.getElementById('pw-name').value.trim();
        if (!name) {
            ui.showToast("Policy Name is required", "error");
            return false;
        }
    }
    return true;
}

function saveCurrentStepData() {
    if (currentStep === 1) {
        policyData.name = document.getElementById('pw-name').value.trim();
        policyData.context = document.getElementById('pw-context').value.trim();
    }
    if (currentStep === 2) {
        policyData.worldview = document.getElementById('pw-worldview').value.trim();
        // Values are updated in real-time by the list inputs, so we don't need to parse them here.
    }
}

async function submitPolicy() {
    const btn = document.getElementById('pw-next-btn');
    const originalText = btn.innerText;
    btn.innerText = "Creating...";
    btn.disabled = true;

    try {
        // HACK: Resave Context into Worldview so it persists
        const payload = { ...policyData };
        if (payload.context) {
            // Ensure we don't duplicate it
            const cleanView = payload.worldview.replace(/<!-- CONTEXT: .*? -->\n?/, "");
            payload.worldview = `<!-- CONTEXT: ${payload.context} -->\n${cleanView}`;
        }

        const res = await api.savePolicy(payload);
        if (!res.ok) throw new Error(res.error || "Failed to save policy");

        const policyId = res.policy_id || policyData.policy_id;

        // Always generate a key for display in the wizard success screen
        let apiKey = "(Hidden)";
        if (!policyData.policy_id) {
            const keyRes = await api.generateKey(policyId, "Initial Wizard Key");
            if (keyRes.ok) apiKey = keyRes.api_key;
        }

        generatedCredentials = {
            policy_id: policyId,
            api_key: apiKey
        };

        currentStep = TOTAL_STEPS + 1;
        renderStep(4);

    } catch (e) {
        ui.showToast(e.message, "error");
        btn.innerText = originalText;
        btn.disabled = false;
    }
}
