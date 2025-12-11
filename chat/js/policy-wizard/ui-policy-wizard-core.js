import * as api from '../api.js';
import * as ui from '../ui.js';

import { renderDefinitionStep, validateDefinitionStep } from './ui-policy-wizard-step1.js';
import { renderConstitutionStep, validateConstitutionStep } from './ui-policy-wizard-step2.js';
import { renderRulesStep, validateRulesStep } from './ui-policy-wizard-step3.js';
import { renderReviewStep, validateReviewStep } from './ui-policy-wizard-review.js';
import { renderSuccessStep } from './ui-policy-wizard-success.js';

// --- STATE ---
let currentStep = 1;
const TOTAL_STEPS = 4; // Steps 1-4 are input, Step 5 is Success (Virtual)
const STORAGE_KEY = 'safi_policy_wizard_draft';

let policyData = getInitialState();
let generatedCredentials = null;

function getInitialState() {
    return {
        policy_id: null,
        name: "",
        context: "",
        worldview: "",
        values: [],
        will_rules: []
    };
}

// --- MAIN API ---
export function openPolicyWizard(existingPolicy = null) {
    currentStep = 1;
    generatedCredentials = null;

    // Draft Logic
    const savedDraft = localStorage.getItem(STORAGE_KEY);
    let useDraft = false;

    if (!existingPolicy && savedDraft) {
        try {
            const draft = JSON.parse(savedDraft);
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
            localStorage.removeItem(STORAGE_KEY);
        }
    }

    if (!useDraft) {
        if (existingPolicy) {
            policyData = {
                policy_id: existingPolicy.id,
                name: existingPolicy.name,
                context: existingPolicy.context || extractContext(existingPolicy.worldview) || "",
                worldview: cleanWorldview(existingPolicy.worldview),
                values: existingPolicy.values_weights || [],
                will_rules: existingPolicy.will_rules || []
            };
        } else {
            policyData = getInitialState();
        }
    }

    ensureWizardModalExists();
    const title = document.getElementById('policy-wizard-title');
    if (title) title.innerText = existingPolicy ? "Edit Policy" : "Create Governance Policy";

    renderStep(currentStep);
    document.getElementById('policy-wizard-modal').classList.remove('hidden');
}

export function closeWizard(skipReload = false) {
    const modal = document.getElementById('policy-wizard-modal');
    if (modal) modal.classList.add('hidden');
    if (generatedCredentials && !skipReload) {
        window.location.reload();
    }
}

// --- HELPER ---
function extractContext(wv) {
    const match = wv && wv.match(/<!-- CONTEXT: (.*?) -->/);
    return match ? match[1] : "";
}

function cleanWorldview(wv) {
    return wv ? wv.replace(/<!-- CONTEXT: (.*?) -->\n?/, "") : "";
}

function saveDraft() {
    if (generatedCredentials) return; // Don't save draft if done
    const draft = { data: policyData, step: currentStep, timestamp: Date.now() };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(draft)); } catch (e) { }
}

// --- NAV ---
function renderStep(step) {
    updateProgress();
    const container = document.getElementById('pw-content');
    container.innerHTML = '';

    switch (step) {
        case 1: renderDefinitionStep(container, policyData); break;
        case 2: renderConstitutionStep(container, policyData); break;
        case 3: renderRulesStep(container, policyData); break;
        case 4: renderReviewStep(container, policyData); break;
        case 5: renderSuccessStep(container, policyData, generatedCredentials); break;
    }
}

async function nextStep() {
    if (!validateCurrentStep()) return;
    saveDraft();

    if (currentStep < TOTAL_STEPS) {
        currentStep++;
        renderStep(currentStep);
    } else {
        await submitPolicy();
    }
}

function prevStep() {
    saveDraft();
    if (currentStep > 1) {
        currentStep--;
        renderStep(currentStep);
    }
}

function validateCurrentStep() {
    switch (currentStep) {
        case 1: return validateDefinitionStep(policyData);
        case 2: return validateConstitutionStep(policyData);
        case 3: return validateRulesStep(policyData);
        case 4: return validateReviewStep(policyData);
        default: return true;
    }
}

// --- SUBMIT ---
async function submitPolicy() {
    const btn = document.getElementById('pw-next-btn');
    btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Saving...`;
    btn.disabled = true;

    try {
        // Embed context
        const finalWorldview = `<!-- CONTEXT: ${policyData.context} -->\n${policyData.worldview}`;
        const payload = { ...policyData, worldview: finalWorldview };

        const res = await api.createPolicy(payload);
        if (res.ok) {
            localStorage.removeItem(STORAGE_KEY);
            ui.showToast("Policy Saved!", "success");
            generatedCredentials = res.credentials || { policy_id: "unknown", api_key: "unknown" };
            currentStep = 5;
            renderStep(5);
        } else {
            throw new Error(res.error || "Failed to save policy");
        }
    } catch (e) {
        console.error(e);
        ui.showToast(e.message, "error");
        btn.innerHTML = policyData.policy_id ? 'Save Changes' : 'Create Policy';
        btn.disabled = false;
    }
}

// --- DOM SKELETON ---
function ensureWizardModalExists() {
    if (document.getElementById('policy-wizard-modal')) return;
    const html = `
    <div id="policy-wizard-modal" class="fixed inset-0 z-50 hidden" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity backdrop-blur-sm"></div>
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-center justify-center p-4">
                <div class="relative w-full max-w-4xl transform overflow-hidden rounded-xl bg-white dark:bg-neutral-900 shadow-2xl transition-all border border-neutral-200 dark:border-neutral-800 flex flex-col max-h-[90vh]">
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center shrink-0">
                        <div>
                            <h3 class="text-lg font-bold text-gray-900 dark:text-white" id="policy-wizard-title">Create Governance Policy</h3>
                            <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="pw-step-num">1</span> of ${TOTAL_STEPS}</p>
                        </div>
                        <button id="close-pw-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300">
                             <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                        </button>
                    </div>
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1 shrink-0 flex">
                        <div id="pw-progress" class="bg-blue-600 h-full transition-all duration-300" style="width: 20%"></div>
                    </div>
                     <div class="flex justify-between px-6 py-2 text-[10px] text-gray-400 uppercase font-bold tracking-wider border-b border-neutral-100 dark:border-neutral-800 bg-white dark:bg-neutral-950">
                        <span class="${currentStep >= 1 ? 'text-blue-600' : ''}">Context</span>
                        <span class="${currentStep >= 2 ? 'text-blue-600' : ''}">Constitution</span>
                        <span class="${currentStep >= 3 ? 'text-blue-600' : ''}">Rules</span>
                        <span class="${currentStep >= 4 ? 'text-blue-600' : ''}">Review</span>
                    </div>
                    <div id="pw-content" class="p-8 overflow-y-auto flex-1 min-h-[400px]"></div>
                    <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between shrink-0">
                        <button id="pw-back-btn" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50">Back</button>
                        <button id="pw-next-btn" class="px-6 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
                    </div>
                </div>
            </div>
        </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    document.getElementById('close-pw-btn').addEventListener('click', () => closeWizard(false));
    document.getElementById('pw-back-btn').addEventListener('click', prevStep);
    document.getElementById('pw-next-btn').addEventListener('click', nextStep);
}

function updateProgress() {
    document.getElementById('pw-step-num').innerText = currentStep <= TOTAL_STEPS ? currentStep : TOTAL_STEPS;
    document.getElementById('pw-progress').style.width = `${(Math.min(currentStep, TOTAL_STEPS) / TOTAL_STEPS) * 100}%`;

    document.getElementById('pw-back-btn').disabled = currentStep === 1 || currentStep > TOTAL_STEPS;

    const nextBtn = document.getElementById('pw-next-btn');
    if (currentStep === TOTAL_STEPS) {
        nextBtn.innerText = policyData.policy_id ? 'Save Changes' : 'Create Policy';
        nextBtn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.add('bg-green-600', 'hover:bg-green-700');
    } else {
        nextBtn.innerText = 'Next';
        nextBtn.classList.add('bg-blue-600', 'hover:bg-blue-700');
        nextBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
    }

    // Hide borders on success
    const modal = document.getElementById('policy-wizard-modal');
    if (currentStep > TOTAL_STEPS) {
        modal.querySelector('.border-t').style.display = 'none';
    } else {
        modal.querySelector('.border-t').style.display = 'flex';
    }

    // Highlight labels
    const labels = document.querySelectorAll('#policy-wizard-modal .text-\\[10px\\] span');
    labels.forEach((el, idx) => {
        if (idx + 1 <= currentStep) el.classList.add('text-blue-600');
        else el.classList.remove('text-blue-600');
    });
}
