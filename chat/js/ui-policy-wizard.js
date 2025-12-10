import * as ui from './ui.js';
import * as api from './api.js';

// --- CONSTANTS ---
const TOTAL_STEPS = 3;
const STORAGE_KEY = 'safi_policy_wizard_draft';

// --- WIZARD STATE ---
let currentStep = 1;
let policyData = getInitialState();
let generatedCredentials = null;

// --- UTILS ---
function getInitialState() {
    return {
        policy_id: null,
        name: "",
        context: "", // Business Description
        worldview: "",
        values: [],
        will_rules: []
    };
}

// Debounce helper for smoother inputs
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        const context = this;
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(context, args), wait);
    };
}

// --- MAIN ENTRY POINT ---
export function openPolicyWizard(existingPolicy = null) {
    currentStep = 1;
    generatedCredentials = null;

    // 1. Check for Saved Draft
    const savedDraft = localStorage.getItem(STORAGE_KEY);
    let useDraft = false;

    if (!existingPolicy && savedDraft) {
        try {
            const draft = JSON.parse(savedDraft);
            // Simple check: expire drafts older than 24 hours
            if (draft.timestamp && Date.now() - draft.timestamp < 86400000) {
                if (confirm("Found an unsaved policy draft. Would you like to restore it?")) {
                    policyData = draft.data;
                    currentStep = draft.step || 1;
                    useDraft = true;
                } else {
                    localStorage.removeItem(STORAGE_KEY);
                }
            }
        } catch (e) {
            console.error("Failed to parse draft", e);
            localStorage.removeItem(STORAGE_KEY);
        }
    }

    if (!useDraft) {
        if (existingPolicy) {
            policyData = {
                policy_id: existingPolicy.id,
                name: existingPolicy.name,
                context: existingPolicy.context || "", // Prefer direct field
                worldview: existingPolicy.worldview || "",
                values: existingPolicy.values_weights || [],
                will_rules: existingPolicy.will_rules || []
            };

            // BACKWARD COMPATIBILITY: Restore Context from Worldview hidden comment if field is missing
            if (!policyData.context) {
                const ctxMatch = policyData.worldview.match(/<!-- CONTEXT: (.*?) -->/);
                if (ctxMatch) {
                    policyData.context = ctxMatch[1];
                    // Clean the UI view
                    policyData.worldview = policyData.worldview.replace(/<!-- CONTEXT: .*? -->\n?/, "");
                }
            }
        } else {
            policyData = getInitialState();
        }
    }

    ensureWizardModalExists();

    const title = document.getElementById('policy-wizard-title');
    if (title) title.innerText = existingPolicy ? "Edit Policy" : "Create Governance Policy";

    renderStep(currentStep);

    const modal = document.getElementById('policy-wizard-modal');
    modal.classList.remove('hidden');
}

function closeWizard(skipReload = false) {
    const modal = document.getElementById('policy-wizard-modal');
    if (modal) modal.classList.add('hidden');

    // Note: We do NOT clear the draft here implicitly. 
    // We keep it in case accidental close. We clear it on SUCCESS.

    if (generatedCredentials && !skipReload) {
        window.location.reload();
    }
}

function ensureWizardModalExists() {
    if (document.getElementById('policy-wizard-modal')) return;

    const html = `
    <div id="policy-wizard-modal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity backdrop-blur-sm"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-4xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800 flex flex-col max-h-[90vh]">
                    
                    <!-- Header -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center shrink-0">
                        <div>
                            <h3 class="text-lg font-bold text-gray-900 dark:text-white" id="policy-wizard-title">Create Governance Policy</h3>
                            <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="pw-step-num">1</span> of ${TOTAL_STEPS}</p>
                        </div>
                        <button id="close-pw-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300">
                            <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1 shrink-0">
                        <div id="pw-progress" class="bg-blue-600 h-1 transition-all duration-300" style="width: 33%"></div>
                    </div>

                    <!-- Content Area (Scrollable) -->
                    <div id="pw-content" class="p-8 overflow-y-auto flex-1">
                        <!-- Dynamic Content -->
                    </div>

                    <!-- Footer -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between shrink-0">
                        <button id="pw-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50">Back</button>
                        <button id="pw-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);

    document.getElementById('close-pw-btn').addEventListener('click', () => closeWizard(false));
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
        nextBtn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.add('bg-green-600', 'hover:bg-green-700');
    } else {
        nextBtn.innerText = 'Next';
        nextBtn.classList.add('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
    }

    // Hide footer/header borders on success screen
    if (currentStep > TOTAL_STEPS) {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'none';
        document.querySelector('#policy-wizard-modal .border-b').style.display = 'none';
    } else {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'flex';
        document.querySelector('#policy-wizard-modal .border-b').style.display = 'flex';
    }
}

function saveDraft() {
    // Save to local storage
    const draft = {
        data: policyData,
        step: currentStep,
        timestamp: Date.now()
    };
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    } catch (e) {
        if (e.name === 'QuotaExceededError') {
            console.warn("LocalStorage full, cannot save draft.");
            ui.showToast("Draft not saved (Storage Full)", "warning");
        } else {
            console.error(e);
        }
    }
}

async function nextStep() {
    if (!validateCurrentStep()) return;
    saveCurrentStepData();
    saveDraft(); // Auto-save

    if (currentStep < TOTAL_STEPS) {
        currentStep++;
        renderStep(currentStep);
    } else {
        await submitPolicy();
    }
}

function prevStep() {
    // Ensure we capture current inputs before going back
    saveCurrentStepData();
    saveDraft();

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
                <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Define Context</h2>
                <p class="text-gray-500 mb-6">Tell us about your organization. This helps our AI suggest rules.</p>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Policy Name</label>
                        <input type="text" id="pw-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="e.g. Global Standard, HR Safe Mode" value="${policyData.name}">
                    </div>

                    <div>
                        <label class="block text-sm font-bold mb-2 text-gray-700 dark:text-gray-300">Organization Description</label>
                        <p class="text-xs text-gray-400 mb-2">E.g. "We are a Fintech company dealing with sensitive user data."</p>
                        <textarea id="pw-context" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="We are a...">${policyData.context}</textarea>
                    </div>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-blue-900/20 p-6 rounded-xl border border-blue-200 dark:border-blue-800 flex flex-col justify-center">
                <div class="mb-4 text-blue-600 dark:text-blue-400">
                    <svg class="w-10 h-10 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <h4 class="font-bold text-lg mb-2">Why does this matter?</h4>
                    <p class="text-sm leading-relaxed opacity-90 text-blue-800 dark:text-blue-200">
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
                            <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Global Worldview (Identity & Mission)</label>
                            <p class="text-xs text-gray-400">The AI's core persona, tone, and your organization's mission.</p>
                         </div>
                         <button id="btn-gen-worldview" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Draft with AI
                         </button>
                    </div>
                    <textarea id="pw-worldview" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm leading-relaxed text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="You are an AI assistant governed by...">${policyData.worldview}</textarea>
                </div>

                <div>
                    <div class="flex justify-between items-end mb-2">
                         <div>
                            <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Core Values & Rubrics</label>
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
                    <svg class="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    Expert Tips
                </h4>
                <ul class="space-y-4 text-xs text-gray-500 dark:text-gray-400">
                    <li>
                        <strong>Worldview:</strong> This is the AI's "Job Description". It defines the persona, tone, and mission (e.g. "You are a helpful assistant for Acme Corp").
                    </li>
                    <li>
                        <strong>Values:</strong> These act as a rubric. The "Conscience" module will grade every draft response against these keywords.
                    </li>
                    <li class="p-3 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-800 dark:text-yellow-200 rounded border border-yellow-200 dark:border-yellow-800">
                        <strong>Rubrics:</strong> Click "Edit Rubric" to see exactly how the AI grades compliance.
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
                policyData.worldview = res.content; // sync immediate for safety
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
            const ctx = policyData.context || policyData.name || "General Organization";
            const res = await api.generatePolicyContent('values', ctx);
            if (res.ok && res.content) {
                let json;
                if (typeof res.content === 'string') {
                    // Legacy/Fallback string path
                    let cleaned = res.content.trim();
                    if (cleaned.startsWith('{') && !cleaned.startsWith('[')) {
                        cleaned = `[${cleaned}]`;
                    }
                    json = JSON.parse(cleaned);
                } else {
                    // New Object path
                    json = res.content;
                }

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

    document.getElementById('btn-add-value').addEventListener('click', () => {
        policyData.values.push({ name: "New Value", description: "", weight: 0.2, rubric: { scoring_guide: [] } });
        renderValuesList();
    });
}

function renderValuesList() {
    const list = document.getElementById('pw-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.values.length === 0) {
        list.innerHTML = `<p class="text-sm text-gray-400 text-center italic py-4">No values defined yet. Click "Suggest Values" to start.</p>`;
        return;
    }

    policyData.values.forEach((v, idx) => {
        // Safe access to rubric structure
        let rubricText = "";
        let hasRubric = false;

        if (v.rubric) {
            if (v.rubric.scoring_guide && Array.isArray(v.rubric.scoring_guide)) {
                // New Format
                hasRubric = v.rubric.scoring_guide.length > 0;
                rubricText = JSON.stringify(v.rubric, null, 2);
            } else if (Array.isArray(v.rubric)) {
                // Legacy Format
                hasRubric = v.rubric.length > 0;
                rubricText = JSON.stringify(v.rubric, null, 2);
            } else {
                rubricText = JSON.stringify(v.rubric, null, 2);
            }
        }

        const rubricBadge = hasRubric
            ? `<span class="text-green-600 flex items-center gap-1 text-[10px] font-bold">✅ Rubric Active</span>`
            : `<span class="text-yellow-600 text-[10px] font-bold">⚠️ No Rubric</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-3 shadow-sm hover:border-blue-300 transition-colors group";

        // Use unique IDs for inputs to avoid reading wrong element later
        const nameId = `pw-val-name-${idx}`;
        const descId = `pw-val-desc-${idx}`;
        const rubricId = `pw-val-rubric-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2 gap-2">
                <input type="text" id="${nameId}" class="flex-1 font-bold bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 px-1 py-1 transition-all" 
                    value="${v.name}" placeholder="Value Name">
                    
                <button class="text-gray-400 hover:text-red-500 p-1 opacity-0 group-hover:opacity-100 transition-opacity" onclick="window.removePolicyValue(${idx})">
                     <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-neutral-900 border border-transparent hover:border-gray-200 focus:border-blue-500 rounded p-2 resize-none h-16 outline-none transition-all"
                placeholder="Description of this value...">${v.description || ''}</textarea>
            
            <div class="mt-2 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                </div>
                <span class="text-[10px] text-gray-400">Weight: ${v.weight || '0.2'}</span>
            </div>

            <!-- Rubric Editor (Hidden by default) -->
            <div id="rubric-container-${idx}" class="hidden mt-3 pt-3 border-t border-gray-100 dark:border-neutral-700">
                <label class="block text-[10px] uppercase text-gray-400 font-bold mb-1">Scoring Logic (JSON)</label>
                <textarea id="${rubricId}" class="w-full h-32 font-mono text-xs p-2 bg-gray-900 text-green-400 rounded border border-gray-700 focus:border-green-500 outline-none" spellcheck="false">${rubricText}</textarea>
                <p class="text-[10px] text-gray-400 mt-1">Edit the raw JSON to adjust scoring criteria.</p>
            </div>
        `;
        list.appendChild(card);

        // Add Debounced Listeners directly to elements
        const nameInput = card.querySelector(`#${nameId}`);
        const descInput = card.querySelector(`#${descId}`);
        const rubricInput = card.querySelector(`#${rubricId}`);

        // We don't save to state immediately here, we rely on readValuesFromDOM inside saveCurrentStepData for final truth.
        // But we can sync for redundancy if needed.
    });

    window.removePolicyValue = (idx) => {
        // Read current state before deleting to preserve unsaved edits in other fields
        saveCurrentStepData();
        policyData.values.splice(idx, 1);
        renderValuesList();
    };
}

// === STEP 3: WILL (Rules) ===
function renderRulesStep(container) {
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
                    let json;
                    if (typeof res.content === 'string') {
                        json = JSON.parse(res.content);
                    } else {
                        json = res.content;
                    }
                    if (Array.isArray(json)) {
                        // Transform rules to match "Action-First" style (Reject, Require, Flag)
                        const processedRules = json.map(r => {
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

                            // Capitalize first letter
                            return clean.charAt(0).toUpperCase() + clean.slice(1);
                        });

                        policyData.will_rules = [...new Set([...policyData.will_rules, ...processedRules])]; // Merge Unique
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

    if (policyData.will_rules.length === 0) {
        list.innerHTML = `<p class="text-sm text-gray-400 text-center italic py-2">No hard rules yet.</p>`;
    }

    policyData.will_rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-3 bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 rounded-lg shadow-sm group hover:border-red-300 transition-colors";

        // Editable Input
        item.innerHTML = `
            <div class="flex-1 flex items-center gap-3">
                <svg class="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
                <input type="text" 
                    class="w-full bg-transparent border-none focus:ring-0 p-1 text-sm font-medium text-red-900 dark:text-red-200 placeholder-red-300" 
                    value="${rule}" 
                    onchange="window.updatePolicyRule(${idx}, this.value)"
                    placeholder="Rule definition...">
            </div>
            <button class="text-red-300 hover:text-red-600 dark:hover:text-red-400 transition-colors" onclick="window.removePolicyRule(${idx})">
                 <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
        `;
        list.appendChild(item);
    });

    window.updatePolicyRule = (idx, val) => {
        policyData.will_rules[idx] = val;
    };

    window.removePolicyRule = (idx) => {
        policyData.will_rules.splice(idx, 1);
        renderRulesList();
    };
}

// === STEP 4: SUCCESS ===
function renderSuccessStep(container) {
    if (!generatedCredentials) return;

    const { policy_id, api_key } = generatedCredentials;
    const publicUrl = "https://safi.selfalignmentfrmework.com";
    const endpointUrl = `${publicUrl}/api/bot/process_prompt`;

    // Python code from the prompt, escaped for template string
    const pythonCode = `import os
import sys
import traceback
import aiohttp
from http import HTTPStatus

from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes
from flask import Flask, request, Response

# --- Configuration ---
APP_ID = os.environ.get("MicrosoftAppId", "")
APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
APP_TENANT_ID = os.environ.get("MicrosoftAppTenantId", None)

# Automatically generated for Policy: ${policyData.name || 'Your Policy'}
SAFI_API_URL = "${endpointUrl}"
SAFI_BOT_SECRET = "${api_key}" 
SAFI_PERSONA = "accion_admin" 

app = Flask(__name__)
settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD, channel_auth_tenant=APP_TENANT_ID)
adapter = BotFrameworkAdapter(settings)

async def on_error(context: TurnContext, error: Exception):
    print(f"\\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()
    await context.send_activity("The bot encountered an error or bug.")

adapter.on_turn_error = on_error

class SafiTeamsBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == ActivityTypes.message:
            user_text = turn_context.activity.text
            if turn_context.activity.recipient:
                user_text = user_text.replace(f"<at>{turn_context.activity.recipient.name}</at>", "").strip()

            payload = {
                "message": user_text, 
                "user_id": turn_context.activity.from_property.id,
                "conversation_id": turn_context.activity.conversation.id,
                "persona": SAFI_PERSONA 
            }

            headers = {
                "X-API-KEY": SAFI_BOT_SECRET,
                "Content-Type": "application/json"
            }

            await turn_context.send_activity(Activity(type=ActivityTypes.typing))
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(SAFI_API_URL, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            safi_data = await resp.json()
                            reply_text = safi_data.get("finalOutput", "[Error: No output]")
                            await turn_context.send_activity(reply_text)
                        else:
                            error_text = await resp.text()
                            await turn_context.send_activity(f"Error ({resp.status}): {error_text}")
            except Exception as e:
                await turn_context.send_activity(f"Connection error: {str(e)}")

        elif turn_context.activity.type == ActivityTypes.conversation_update:
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    await turn_context.send_activity("Hello! I am the Accion Compliance Assistant.")

bot = SafiTeamsBot()

@app.route("/api/messages", methods=["POST"])
def messages():
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    async def aux_func(turn_context):
        await bot.on_turn(turn_context)

    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = adapter.process_activity(activity, auth_header, aux_func)
        loop.run_until_complete(task)
        return Response(status=HTTPStatus.OK)
    except Exception as e:
        traceback.print_exc()
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

if __name__ == "__main__":
    app.run(debug=True, port=3978)`;

    container.innerHTML = `
        <div class="text-center py-8">
            <div class="w-20 h-20 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-6">
                <svg class="w-10 h-10 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-3xl font-bold mb-2 text-gray-900 dark:text-white">Policy Active!</h2>
            <p class="text-gray-500 text-lg">Your governance firewall is ready.</p>
        </div>

        <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 text-left">
            <h4 class="font-bold text-lg mb-4 text-gray-800 dark:text-gray-200">Integration Credentials</h4>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Public Endpoint</label>
                    <code class="block p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-xs truncate text-gray-600 dark:text-gray-300" title="${endpointUrl}">${endpointUrl}</code>
                </div>
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">API Key</label>
                    <div class="flex gap-2">
                        <code class="flex-1 p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm text-green-600 font-bold truncate">${api_key}</code>
                        <button class="px-3 bg-gray-200 hover:bg-gray-300 dark:bg-neutral-700 dark:hover:bg-neutral-600 rounded text-black dark:text-white font-bold transition-colors" onclick="navigator.clipboard.writeText('${api_key}'); ui.showToast('Copied!', 'success');">Copy</button>
                    </div>
                </div>
            </div>
            
            <div class="mt-6 pt-6 border-t border-gray-200 dark:border-neutral-700 space-y-6">
                
                <!-- Option 1: No Code -->
                <div>
                    <h4 class="font-bold text-md mb-2 text-gray-800 dark:text-gray-200 flex items-center gap-2">
                        <span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">Option 1</span> 
                        Use in SAFI Dashboard
                    </h4>
                    <p class="text-sm text-gray-500 mb-2">Create a Custom Agent and apply this policy immediately.</p>
                    <ol class="list-decimal list-inside text-sm text-gray-600 dark:text-gray-400 space-y-1 ml-1">
                        <li>Go to <strong>Agents</strong> tab.</li>
                        <li>Create a new <strong>Custom Agent</strong>.</li>
                        <li>In the settings dropdown, select <strong>"${policyData.name}"</strong> as the active Policy.</li>
                    </ol>
                </div>

                <!-- Option 2: API/Bots -->
                <div>
                    <h4 class="font-bold text-md mb-2 text-gray-800 dark:text-gray-200 flex items-center gap-2">
                        <span class="bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded">Option 2</span> 
                        External Integration (Teams, Slack, etc.)
                    </h4>
                    <p class="text-sm text-gray-500 mb-3">You can govern any external chat bot by routing prompts through the API above. Here is a Python example for Microsoft Teams:</p>
                    
                    <div class="relative">
                        <div class="absolute top-2 right-2">
                            <button class="text-xs bg-gray-700 hover:bg-gray-600 text-white px-2 py-1 rounded" onclick="navigator.clipboard.writeText(document.getElementById('python-snippet').innerText); ui.showToast('Code Copied!', 'success');">Copy Code</button>
                        </div>
                        <pre id="python-snippet" class="bg-gray-900 text-gray-300 text-xs p-4 rounded-lg overflow-x-auto h-48 overflow-y-auto font-mono leading-relaxed border border-gray-700 shadow-inner">${pythonCode}</pre>
                    </div>
                </div>

            </div>
        </div>
        
        <div class="mt-8 text-center">
            <button id="pw-finish-dashboard-btn" class="px-8 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 shadow-lg transition-transform hover:-translate-y-0.5">
                Go to Governance Dashboard
            </button>
        </div>
    `;

    // Attach Dynamic Navigation Listener
    setTimeout(() => {
        const finishBtn = document.getElementById('pw-finish-dashboard-btn');
        if (finishBtn) {
            finishBtn.addEventListener('click', () => {
                // 1. Close Wizard WITHOUT reloading
                closeWizard(true);

                // 2. Switch Views (Chat -> Control Panel)
                if (ui.elements.chatView && ui.elements.controlPanelView) {
                    ui.elements.chatView.classList.add('hidden');
                    ui.elements.controlPanelView.classList.remove('hidden');
                }

                // 3. Activate Governance Tab
                const governanceTab = ui.elements.cpNavGovernance || document.getElementById('cp-nav-governance');
                if (governanceTab) {
                    governanceTab.click();
                }
            });
        }
    }, 0);
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

    // Warn if Step 3 (Rules) is empty, but don't block
    if (currentStep === 3) {
        if (policyData.will_rules.length === 0) {
            if (!confirm("You have no Hard Constraints (Will) defined.\n\nThis means the AI has no hard safety stops. Are you sure you want to proceed?")) {
                return false;
            }
        }
    }

    return true;
}

function saveCurrentStepData() {
    // Read directly from DOM to ensure we capture latest keystrokes (better than onchange state)

    if (currentStep === 1) {
        const nameEl = document.getElementById('pw-name');
        const ctxEl = document.getElementById('pw-context');
        if (nameEl) policyData.name = nameEl.value.trim();
        if (ctxEl) policyData.context = ctxEl.value.trim();
    }

    if (currentStep === 2) {
        const wvEl = document.getElementById('pw-worldview');
        if (wvEl) policyData.worldview = wvEl.value.trim();

        // Sync Values from Cards
        policyData.values.forEach((v, idx) => {
            const nameEl = document.getElementById(`pw-val-name-${idx}`);
            const descEl = document.getElementById(`pw-val-desc-${idx}`);
            const rubricEl = document.getElementById(`pw-val-rubric-${idx}`);

            if (nameEl) v.name = nameEl.value;
            if (descEl) v.description = descEl.value;
            if (rubricEl) {
                try {
                    // Try to parse JSON from textarea
                    v.rubric = JSON.parse(rubricEl.value);
                } catch (e) {
                    // If invalid JSON, leave it (or maybe flag it? For now we just keep the previous valid state or partial text if we were storing text)
                    // Ideally we should warn, but for auto-save we just skip invalid JSON
                }
            }
        });
    }

    // Step 3 (Rules) updates immediately via list methods, no bulk read needed
}

async function submitPolicy() {
    const btn = document.getElementById('pw-next-btn');
    const originalText = btn.innerText;
    btn.innerText = "Creating...";
    btn.disabled = true;

    try {
        // Prepare Payload
        const payload = { ...policyData };

        // PERSISTENCE FALLBACK: 
        // If the backend does not support a dedicated 'context' column, we embed it in the worldview.
        // This ensures the "Organization Description" is not lost.
        if (payload.context) {
            // Remove any existing tag first to prevent duplicates
            const cleanView = payload.worldview.replace(/<!-- CONTEXT: .*? -->\n?/, "");
            payload.worldview = `<!-- CONTEXT: ${payload.context} -->\n${cleanView}`;
        }

        // We also send context as a distinct field for backends that DO support it
        payload.context = policyData.context;

        const res = await api.savePolicy(payload);
        if (!res.ok) throw new Error(res.error || "Failed to save policy");

        const policyId = res.policy_id || policyData.policy_id;

        // Generate credentials for display
        let apiKey = "(Hidden)";
        if (!policyData.policy_id) {
            const keyRes = await api.generateKey(policyId, "Initial Wizard Key");
            if (keyRes.ok) apiKey = keyRes.api_key;
        }

        generatedCredentials = {
            policy_id: policyId,
            api_key: apiKey
        };

        // Clear Draft on Success
        localStorage.removeItem(STORAGE_KEY);

        currentStep = TOTAL_STEPS + 1;
        renderStep(4);

    } catch (e) {
        ui.showToast(e.message, "error");
        btn.innerText = originalText;
        btn.disabled = false;
        btn.classList.remove('bg-green-600', 'hover:bg-green-700'); // Reset style if failed
        btn.classList.add('bg-blue-600', 'hover:bg-blue-700');
    }
}