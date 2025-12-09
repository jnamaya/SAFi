import * as ui from './ui.js';
import * as api from './api.js';

// --- WIZARD STATE ---
let currentStep = 1;
const TOTAL_STEPS = 3; // Reduced steps (removed Identity)
let policyData = {
    policy_id: null,
    name: "",
    worldview: "", // The "Constitution"
    values: [],
    will_rules: []
};

let generatedCredentials = null; // Store credentials locally at the end

// --- MAIN ENTRY POINT ---
export function openPolicyWizard(existingPolicy = null) {
    // Reset State
    currentStep = 1;
    generatedCredentials = null;

    if (existingPolicy) {
        policyData = {
            policy_id: existingPolicy.id,
            name: existingPolicy.name,
            worldview: existingPolicy.worldview || "",
            values: existingPolicy.values_weights || [], // DB uses values_weights
            will_rules: existingPolicy.will_rules || []
        };
    } else {
        policyData = {
            policy_id: null,
            name: "",
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
    // Reload if we created/saved something
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
                <div class="relative w-full max-w-3xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800">
                    
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
                    <div id="pw-content" class="p-8 min-h-[400px]">
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

    // Hide Footer on Success Screen
    if (currentStep > TOTAL_STEPS) {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'none';
    } else {
        document.querySelector('#policy-wizard-modal .border-t').style.display = 'flex';
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
        case 4: renderSuccessStep(container); break; // Integration & API Key
    }
}

// === STEP 1: DEFINITION ===
function renderDefinitionStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4">Define Policy</h2>
        <p class="text-gray-500 mb-6">Create a governance container for your organization.</p>
        
        <div class="space-y-4">
            <div>
                <label class="block text-sm font-bold mb-2">Policy Name</label>
                <input type="text" id="pw-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. Global Standard, HR Safe Mode" value="${policyData.name}">
            </div>
            
            <div class="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg border border-blue-200 dark:border-blue-800 mt-6">
                <h4 class="font-bold text-blue-800 dark:text-blue-200 mb-2">What is a Policy?</h4>
                <p class="text-sm text-blue-600 dark:text-blue-300">
                    A Policy is a set of "Constitution" rules (Worldview, Values, Constraints) that can be applied to thousands of agents.
                </p>
            </div>
        </div>
    `;
}

// === STEP 2: CONSTITUTION (Worldview + Values) ===
function renderConstitutionStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4">The Constitution</h2>
        <p class="text-gray-500 mb-6">Define the core worldview and ethical values.</p>
        
        <div class="space-y-6">
            <div>
                <label class="block text-sm font-bold mb-2">Global Worldview</label>
                <p class="text-xs text-gray-400 mb-2">System instructions applied to EVERY agent using this policy.</p>
                <textarea id="pw-worldview" class="w-full h-32 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm" placeholder="You are an AI assistant governed by [Organization Name]. You must prioritize safety...">${policyData.worldview}</textarea>
            </div>

            <!-- Simplified Values Input for MVP -->
            <div>
                <label class="block text-sm font-bold mb-2">Core Values</label>
                <p class="text-xs text-gray-400 mb-2">Comma separated values (e.g. Safety, Privacy, Truthfulness)</p>
                <input type="text" id="pw-values-simple" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" 
                    value="${policyData.values.map(v => v.name).join(', ')}"
                    placeholder="Safety, Privacy, Truthfulness">
            </div>
        </div>
    `;
}

// === STEP 3: WILL (Hard Rules) ===
function renderRulesStep(container) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-2">The Will (Constraints)</h2>
        <p class="text-gray-500 mb-6">Hard block rules. Interactions violating these are rejected.</p>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="pw-rule-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" placeholder="e.g. Never give financial advice.">
            <button id="pw-add-rule-btn" class="px-6 py-2 bg-neutral-800 dark:bg-neutral-700 text-white rounded-lg font-semibold hover:bg-black transition-colors">
                Add Rule
            </button>
        </div>

        <ul id="pw-rules-list" class="space-y-2"></ul>
    `;

    renderRulesList();

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
}

function renderRulesList() {
    const list = document.getElementById('pw-rules-list');
    if (!list) return;
    list.innerHTML = '';

    policyData.will_rules.forEach((rule, idx) => {
        const item = document.createElement('li');
        item.className = "flex justify-between items-center p-3 bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg";
        item.innerHTML = `
            <span class="text-sm font-medium">⛔ ${rule}</span>
            <button class="text-gray-400 hover:text-red-500" onclick="window.removePolicyRule(${idx})">
                 x
            </button>
        `;
        list.appendChild(item);
    });

    window.removePolicyRule = (idx) => {
        policyData.will_rules.splice(idx, 1);
        renderRulesList();
    };
}

// === STEP 4: SUCCESS (API KEYS) ===
function renderSuccessStep(container) {
    if (!generatedCredentials) return; // Should not happen

    const { policy_id, api_key } = generatedCredentials;

    container.innerHTML = `
        <div class="text-center">
            <div class="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-2xl font-bold mb-2">Policy Created!</h2>
            <p class="text-gray-500 mb-8">Your Organization Policy is now active.</p>
        </div>

        <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 text-left">
            <h4 class="font-bold text-lg mb-4">Integration Credentials</h4>
            
            <div class="mb-4">
                <label class="block text-xs uppercase text-gray-400 font-bold mb-1">API Endpoint</label>
                <div class="flex gap-2">
                    <code class="flex-1 p-2 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm">https://api.safi.ai/v1</code>
                </div>
            </div>

            <div class="mb-4">
                <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Secret API Key (Copy Now!)</label>
                <div class="flex gap-2">
                    <code class="flex-1 p-2 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm text-green-600 font-bold break-all">${api_key}</code>
                    <button class="px-3 py-1 bg-gray-200 hover:bg-gray-300 rounded text-sm text-black font-semibold" onclick="navigator.clipboard.writeText('${api_key}')">Copy</button>
                </div>
                <p class="text-xs text-red-500 mt-2">⚠️ This key will not be shown again.</p>
            </div>
        </div>
        
        <div class="mt-8 text-center">
            <button onclick="window.location.reload()" class="px-8 py-3 bg-blue-600 text-white font-bold rounded-lg hover:bg-blue-700 shadow-lg transition-transform hover:-translate-y-0.5">
                Go to Dashboard
            </button>
        </div>
    `;
}

// --- LOGIC ---
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
    }
    if (currentStep === 2) {
        policyData.worldview = document.getElementById('pw-worldview').value.trim();
        const rawVals = document.getElementById('pw-values-simple').value;
        // Convert simple string to existing value structure
        policyData.values = rawVals.split(',').map(s => s.trim()).filter(s => s).map(s => ({
            name: s,
            weight: 0.2 // Default
        }));
    }
}

async function submitPolicy() {
    const btn = document.getElementById('pw-next-btn');
    const originalText = btn.innerText;
    btn.innerText = "Creating...";
    btn.disabled = true;

    try {
        // 1. Save Policy
        const res = await api.savePolicy(policyData);
        if (!res.ok) throw new Error(res.error || "Failed to save policy");

        const policyId = res.policy_id || policyData.policy_id;

        // 2. Generate Initial API Key
        // Only generate key if creating NEW. If editing, assume they have keys or can generic new ones in dashboard.
        // Actually, for this wizard flow, we always offer a key on creation.
        let apiKey = "(Hidden)";
        if (!policyData.policy_id) {
            const keyRes = await api.generateKey(policyId, "Initial Wizard Key");
            if (keyRes.ok) apiKey = keyRes.api_key;
        }

        generatedCredentials = {
            policy_id: policyId,
            api_key: apiKey
        };

        // 3. Move to Success Screen
        currentStep = TOTAL_STEPS + 1; // 4
        renderStep(4);

    } catch (e) {
        ui.showToast(e.message, "error");
        btn.innerText = originalText;
        btn.disabled = false;
    }
}
