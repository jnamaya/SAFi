import * as api from '../api.js';
import * as ui from '../ui.js';

import {
    renderIdentityStep, validateIdentityStep
} from './ui-wizard-step1.js';
import {
    renderKnowledgeStep, validateKnowledgeStep
} from './ui-wizard-step2.js';
import {
    renderIntellectStep, validateIntellectStep
} from './ui-wizard-step3.js';
import {
    renderConscienceStep, validateConscienceStep
} from './ui-wizard-step4.js';
import {
    renderWillStep, validateWillStep
} from './ui-wizard-step5.js';
import {
    renderReviewStep
} from './ui-wizard-review.js';

import { setAvailableModels, availableModelsCache } from './ui-wizard-utils.js';

// --- WIZARD STATE ---
let currentStep = 1;
const TOTAL_STEPS = 6;
export let agentData = {
    key: "",
    name: "",
    description: "",
    avatar: "",
    instructions: "", // Worldview
    style: "",
    values: [],
    rules: [],
    policy_id: "standalone",
    is_update_mode: false,
    visibility: "private",
    intellect_model: "",
    will_model: "",
    conscience_model: "",
    rag_knowledge_base: "",
    rag_format_string: "",
    tools: []
};

// --- MAIN ENTRANCE ---
export function openAgentWizard(existingAgent = null, availableModels = []) {
    currentStep = 1;
    setAvailableModels(availableModels);

    if (existingAgent) {
        // Edit Mode Pre-fill
        agentData = {
            key: existingAgent.key,
            name: existingAgent.name,
            description: existingAgent.description || "",
            avatar: existingAgent.avatar || "",
            instructions: (existingAgent.worldview || "").replace("--- Organizational Policy ---\n", "").split("--- SPECIFIC ROLE ---\n").pop() || "",
            style: existingAgent.style || "",
            values: existingAgent.values || [],
            rules: existingAgent.will_rules || [],
            policy_id: existingAgent.policy_id || "standalone",
            visibility: existingAgent.visibility || "private",
            is_update_mode: true,

            intellect_model: existingAgent.intellect_model || "",
            will_model: existingAgent.will_model || "",
            conscience_model: existingAgent.conscience_model || "",
            rag_knowledge_base: existingAgent.rag_knowledge_base || "",
            rag_knowledge_base: existingAgent.rag_knowledge_base || "",
            rag_format_string: existingAgent.rag_format_string || "",
            tools: existingAgent.tools || []
        };
        // Fallback checks
        if (existingAgent.worldview && !agentData.instructions) {
            agentData.instructions = existingAgent.worldview;
        }
    } else {
        // Create Mode Reset
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
            is_update_mode: false,
            intellect_model: "",
            will_model: "",
            conscience_model: "",
            rag_knowledge_base: "",
            rag_knowledge_base: "",
            rag_format_string: "",
            tools: []
        };
    }

    ensureWizardModalExists();

    const title = document.getElementById('wizard-title');
    if (title) title.innerText = existingAgent ? "Edit Agent" : "Create New Agent";

    renderStep(1);

    document.getElementById('agent-wizard-modal').classList.remove('hidden');
}

export function closeWizard() {
    document.getElementById('agent-wizard-modal').classList.add('hidden');
}

// --- DOM & NAV ---

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
                    <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1 shrink-0 flex">
                        <div id="wizard-progress-track" class="h-full bg-blue-600 transition-all duration-300" style="width: 0%"></div>
                    </div>
                    <!-- Step Labels (Optional enhancement) -->
                    <div class="flex justify-between px-6 py-2 text-[10px] text-gray-400 uppercase font-bold tracking-wider border-b border-neutral-100 dark:border-neutral-800 bg-white dark:bg-neutral-950">
                        <span class="${currentStep >= 1 ? 'text-blue-600' : ''}">Profile</span>
                        <span class="${currentStep >= 2 ? 'text-blue-600' : ''}">Capabilities</span>
                        <span class="${currentStep >= 3 ? 'text-blue-600' : ''}">Intellect</span>
                        <span class="${currentStep >= 4 ? 'text-blue-600' : ''}">Values</span>
                        <span class="${currentStep >= 5 ? 'text-blue-600' : ''}">Rules</span>
                        <span class="${currentStep >= 6 ? 'text-blue-600' : ''}">Review</span>
                    </div>

                    <!-- Content Area -->
                    <div id="wizard-content" class="p-8 overflow-y-auto flex-1 min-h-[400px]"></div>

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

function updateProgress() {
    document.getElementById('wizard-step-num').innerText = currentStep;
    document.getElementById('wizard-progress-track').style.width = `${(currentStep / TOTAL_STEPS) * 100}%`;

    const backBtn = document.getElementById('wizard-back-btn');
    const nextBtn = document.getElementById('wizard-next-btn');
    const labels = document.querySelectorAll('.text-\\[10px\\] span');

    backBtn.disabled = currentStep === 1;

    // Update labels highlight (hacky index match)
    labels.forEach((el, idx) => {
        if (idx + 1 <= currentStep) el.classList.add('text-blue-600', 'dark:text-blue-400');
        else el.classList.remove('text-blue-600', 'dark:text-blue-400');
    });

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

async function renderStep(step) {
    updateProgress();
    const container = document.getElementById('wizard-content');
    container.innerHTML = '';

    try {
        switch (step) {
            case 1: renderIdentityStep(container, agentData); break;
            case 2: renderKnowledgeStep(container, agentData); break;
            case 3: renderIntellectStep(container, agentData, availableModelsCache); break;
            case 4: renderConscienceStep(container, agentData, availableModelsCache); break;
            case 5: renderWillStep(container, agentData, availableModelsCache); break;
            case 6:
                // Auto-generate key for review visualization
                // Naming Convention: [org_prefix]_[agent_name]
                if (!agentData.key && agentData.name) {
                    let prefix = "org";
                    try {
                        const res = await api.getMyOrganization();
                        const org = res ? res.organization : null;

                        if (org) {
                            if (org.domain_verified && org.domain_to_verify) {
                                prefix = org.domain_to_verify.replace(/\./g, '_').toLowerCase();
                            } else if (org.id) {
                                prefix = `org_${org.id.substring(0, 4)}`;
                            }
                        }
                    } catch (e) { console.warn("Naming fetch failed", e); }

                    const nameSlug = agentData.name.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
                    agentData.key = `${prefix}_${nameSlug}`;
                }
                renderReviewStep(container, agentData);
                break;
        }
    } catch (e) {
        console.error("Render Step Failed", e);
        container.innerHTML = `<div class="text-red-500">Error rendering step ${step}: ${e.message}</div>`;
    }
}

function nextStep() {
    if (!validateCurrentStep()) return;

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

function validateCurrentStep() {
    switch (currentStep) {
        case 1: return validateIdentityStep(agentData);
        case 2: return validateKnowledgeStep(agentData);
        case 3: return validateIntellectStep(agentData);
        case 4: return validateConscienceStep(agentData);
        case 5: return validateWillStep(agentData);
        case 6: return true; // Review always valid
        default: return true;
    }
}

async function finishWizard() {
    const btn = document.getElementById('wizard-next-btn');
    const originalText = btn.innerText;
    btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Saving...`;
    btn.disabled = true;

    try {
        // Fix: Auto-generate key if missing (Robust Fallback)
        if (!agentData.key && agentData.name) {
            let prefix = "org";
            try {
                const res = await api.getMyOrganization();
                const org = res ? res.organization : null;

                if (org) {
                    if (org.domain_verified && org.domain_to_verify) {
                        prefix = org.domain_to_verify.replace(/\./g, '_').toLowerCase();
                    } else if (org.id) {
                        prefix = `org_${org.id.substring(0, 4)}`;
                    }
                }
            } catch (e) { console.warn("Naming fetch failed in finishWizard", e); }

            const nameSlug = agentData.name.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
            agentData.key = `${prefix}_${nameSlug}`;
        }

        const payload = {
            ...agentData,
            worldview: agentData.instructions // Map back to backend expectation
        };

        const res = await api.saveAgent(payload);

        if (res.ok) {
            ui.showToast(agentData.is_update_mode ? "Agent Updated!" : "Agent Created!", "success");
            closeWizard();
            // Force reload to update UI lists (User Request)
            setTimeout(() => {
                window.location.reload();
            }, 500); // Small delay to let toast show
        } else {
            throw new Error(res.error || "Save failed");
        }
    } catch (e) {
        console.error(e);
        ui.showToast(`Error: ${e.message}`, "error");
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}
