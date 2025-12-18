import * as ui from './ui.js';
import * as api from './api.js';

// Reuse logic from agent wizard where possible, but simplify.
let currentStep = 1;
const TOTAL_STEPS = 3; // Identity, Intellect, Conscience
let orgData = {
    name: "",
    description: "",
    instructions: "", // Global Worldview
    values: []        // Global Values
};

export function openOrgWizard() {
    currentStep = 1;
    orgData = {
        name: "",
        description: "",
        instructions: "",
        values: []
    };

    ensureWizardModalExists();
    renderStep(1);
    document.getElementById('org-wizard-modal').classList.remove('hidden');
}

function closeWizard() {
    document.getElementById('org-wizard-modal').classList.add('hidden');
}

function ensureWizardModalExists() {
    if (document.getElementById('org-wizard-modal')) return;

    const html = `
    <div id="org-wizard-modal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-900 opacity-75 transition-opacity"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-3xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border-2 border-blue-500">
                    
                    <div class="bg-blue-50 dark:bg-blue-900 px-6 py-4 border-b border-blue-100 dark:border-blue-800 flex justify-between items-center">
                        <div>
                            <h3 class="text-lg font-bold text-blue-900 dark:text-blue-100">Create Global Policy</h3>
                            <p class="text-sm text-blue-500 dark:text-blue-300">Define the backbone of your organization.</p>
                        </div>
                        <button id="close-org-wizard-btn" class="text-gray-400 hover:text-gray-500">✕</button>
                    </div>

                    <div id="org-wizard-content" class="p-8 min-h-[400px]"></div>

                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between">
                        <button id="org-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800">Back</button>
                        <button id="org-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);

    document.getElementById('close-org-wizard-btn').addEventListener('click', closeWizard);
    document.getElementById('org-back-btn').addEventListener('click', prevStep);
    document.getElementById('org-next-btn').addEventListener('click', nextStep);
}

function updateButtons() {
    const backBtn = document.getElementById('org-back-btn');
    const nextBtn = document.getElementById('org-next-btn');

    backBtn.disabled = currentStep === 1;
    nextBtn.innerText = currentStep === TOTAL_STEPS ? 'Create Policy' : 'Next';
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
    updateButtons();
    const container = document.getElementById('org-wizard-content');
    container.innerHTML = '';

    if (step === 1) {
        container.innerHTML = `
            <div class="space-y-4">
                <h2 class="text-2xl font-bold">Organization Identity</h2>
                <div>
                    <label class="block text-sm font-bold mb-2">Organization Name</label>
                    <input type="text" id="org-name" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" value="${orgData.name}" placeholder="e.g. Acme Corp">
                </div>
                <div>
                    <label class="block text-sm font-bold mb-2">Description</label>
                    <input type="text" id="org-desc" class="w-full p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800" value="${orgData.description}" placeholder="A brief summary of your governance goal.">
                </div>
            </div>
        `;
    } else if (step === 2) {
        container.innerHTML = `
            <div class="space-y-4">
                <h2 class="text-2xl font-bold">Global Worldview</h2>
                <p class="text-gray-500">These instructions will be prepended to EVERY agent in this organization.</p>
                <textarea id="org-instructions" class="w-full h-60 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm" placeholder="You are governed by the Acme Corp Policy. Your mission is to...">${orgData.instructions}</textarea>
            </div>
        `;
    } else if (step === 3) {
        container.innerHTML = `
            <div class="space-y-4">
                <h2 class="text-2xl font-bold">Global Values</h2>
                <p class="text-gray-500">Every agent will inherit these constraints.</p>
                
                <div class="flex gap-4">
                    <input type="text" id="org-val-input" class="flex-1 p-3 rounded-lg border" placeholder="Value Name">
                    <button id="org-add-val-btn" class="bg-blue-600 text-white px-4 rounded-lg">Add Value</button>
                </div>
                <div id="org-values-list" class="space-y-2 max-h-[300px] overflow-y-auto"></div>
            </div>
        `;
        renderValues();
        document.getElementById('org-add-val-btn').addEventListener('click', addValue);
    }
}

function renderValues() {
    const list = document.getElementById('org-values-list');
    list.innerHTML = '';
    orgData.values.forEach((v, idx) => {
        const div = document.createElement('div');
        div.className = "p-3 bg-gray-50 dark:bg-neutral-800 border rounded flex justify-between";
        div.innerHTML = `<span>${v.name}</span> <button onclick="window.removeOrgValue(${idx})" class="text-red-500">Remove</button>`;
        list.appendChild(div);
    });

    window.removeOrgValue = (idx) => {
        orgData.values.splice(idx, 1);
        renderValues();
    };
}

async function addValue() {
    const name = document.getElementById('org-val-input').value.trim();
    if (!name) return;

    // Auto-generate stub rubric or call API? For simplicity, we create a stub for now 
    // or we could reuse the rubic generator. Let's do a stub.
    orgData.values.push({
        name: name,
        weight: 0.1,
        rubric: { description: "Global value", scoring_guide: [] }
    });
    document.getElementById('org-val-input').value = '';
    renderValues();
}

function validateCurrentStep() {
    if (currentStep === 1) {
        const name = document.getElementById('org-name').value.trim();
        if (!name) { ui.showToast("Name required", "error"); return false; }
    }
    return true;
}

function saveCurrentStepData() {
    if (currentStep === 1) {
        orgData.name = document.getElementById('org-name').value.trim();
        orgData.description = document.getElementById('org-desc').value.trim();
    }
    if (currentStep === 2) {
        orgData.instructions = document.getElementById('org-instructions').value;
    }
}

async function finishWizard() {
    const btn = document.getElementById('org-next-btn');
    btn.disabled = true;
    btn.innerText = "Saving...";

    try {
        const payload = {
            name: orgData.name,
            description: orgData.description,
            global_worldview: orgData.instructions,
            global_values: orgData.values
        };
        await api.saveOrganization(payload);
        ui.showToast("Organization Created!", "success");
        closeWizard();
        window.location.reload(); // Refresh to update dropdowns
    } catch (e) {
        ui.showToast(e.message, "error");
        btn.disabled = false;
        btn.innerText = "Create Policy";
    }
}
