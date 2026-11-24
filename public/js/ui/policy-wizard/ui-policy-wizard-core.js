import * as api from '../../core/api.js';
import * as ui from '../ui.js';

import { renderDefinitionStep, validateDefinitionStep }       from './ui-policy-wizard-step1.js?v=20261117.1';
import { renderConstitutionStep, validateConstitutionStep }   from './ui-policy-wizard-step2.js?v=20260928.1';
import { renderScopeStep, validateScopeStep }                 from './ui-policy-wizard-step3.js?v=20260928.1';
import { renderValuesStep, validateValuesStep }               from './ui-policy-wizard-step4.js?v=20260928.1';
import { renderWillStep, validateWillStep }                   from './ui-policy-wizard-step5.js?v=20261117.3';
import { renderGovernanceStep, validateGovernanceStep }       from './ui-policy-wizard-governance.js?v=20260928.1';
import { renderSuccessStep }                                  from './ui-policy-wizard-success.js?v=20260928.1';

let currentStep = 1;
const TOTAL_STEPS = 6;
const STORAGE_KEY = 'safi_policy_wizard_draft';

let policyData = getInitialState();
let generatedCredentials = null;

function getInitialState() {
    return {
        policy_id:        null,
        name:             "",
        business_unit:    "",
        context:          "",
        worldview:        "",
        scope_statement:  "",

        early_prompt_blacklist: [],

        values: [],

        structural_requirements: {
            require_disclaimer:            false,
            mandatory_disclaimer_substring: "",
            banned_markdown_syntaxes:      [],
        },

        allowed_tools: [],

        forbidden_paths: [],

        forbidden_executables: [],
        forbidden_shell_patterns: [],

        will_rules: [],

        alignment_threshold: 0.5,
        ethical_memory:      0.90,
    };
}

export function openPolicyWizard(existingPolicy = null) {
    currentStep = 1;
    generatedCredentials = null;

    const savedDraft = localStorage.getItem(STORAGE_KEY);
    let useDraft = false;

    if (!existingPolicy && savedDraft) {
        try {
            const draft = JSON.parse(savedDraft);
            if (draft.timestamp && Date.now() - draft.timestamp < 86400000) {
                if (confirm("Found an unsaved policy draft. Would you like to restore it?")) {
                    policyData = { ...getInitialState(), ...draft.data };
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
            policyData = hydratePolicy(existingPolicy);
        } else {
            policyData = getInitialState();
        }
    }

    ensureWizardInlineExists();

    const activeTab = document.querySelector('.tab-content:not(.hidden):not(#policy-wizard-view)');
    if (activeTab) {
        document.body.dataset.pwPreviousTab = activeTab.id;
        activeTab.classList.add('hidden');
    }

    const title = document.getElementById('policy-wizard-title');
    if (title) title.innerText = existingPolicy ? "Edit Policy" : "Create Policy";

    renderStep(currentStep);
    const view = document.getElementById('policy-wizard-view');
    view.classList.remove('hidden');
    view.classList.add('flex');
}

export function closeWizard(skipReload = false) {
    const view = document.getElementById('policy-wizard-view');
    if (view) {
        view.classList.add('hidden');
        view.classList.remove('flex');
    }

    const prevTabId = document.body.dataset.pwPreviousTab;
    if (prevTabId) {
        const prevTab = document.getElementById(prevTabId);
        if (prevTab) prevTab.classList.remove('hidden');
        document.body.removeAttribute('data-pwPreviousTab');
    } else {
        const govTab = document.getElementById('tab-governance');
        if (govTab) govTab.classList.remove('hidden');
    }

    if (generatedCredentials && !skipReload) {
        window.location.reload();
    }
}

function normalizeStandard(v) {
    if (!v || typeof v !== 'object') return v;
    const out = { ...v };
    if (out.name === undefined && out.value !== undefined) out.name = out.value;
    if (out.description === undefined && out.definition !== undefined) out.description = out.definition;
    return out;
}

function hydratePolicy(existingPolicy) {
    const init = getInitialState();
    let cfg = existingPolicy.policy_config || {};
    if (typeof cfg === 'string') {
        try { cfg = JSON.parse(cfg) || {}; } catch (e) { cfg = {}; }
    }
    const wr   = existingPolicy.will_rules;

    let structural = init.structural_requirements;
    let blacklist  = [];
    let allowed    = [];
    let legacyList = [];
    let forbiddenPaths = [];
    let forbiddenExecutables = [];
    let forbiddenShellPatterns = [];
    let allowedKnowledge;

    if (Array.isArray(wr)) {
        legacyList = wr;
    } else if (wr && typeof wr === 'object') {
        structural    = { ...structural, ...(wr.structural_requirements || {}) };
        blacklist     = wr.early_prompt_blacklist || [];
        allowed       = wr.allowed_tools || [];
        legacyList    = wr.rules || [];
        forbiddenPaths = wr.forbidden_paths || [];
        forbiddenExecutables = wr.forbidden_executables || [];
        forbiddenShellPatterns = wr.forbidden_shell_patterns || [];
        if (Array.isArray(wr.allowed_knowledge_bases)) {
            allowedKnowledge = wr.allowed_knowledge_bases;
        }
    }

    return {
        ...init,
        ...(allowedKnowledge !== undefined
            ? { allowed_knowledge_bases: allowedKnowledge } : {}),
        policy_id:       existingPolicy.id,
        name:            existingPolicy.name,
        business_unit:   cfg.business_unit  || "",
        context:         cfg.context || extractContext(existingPolicy.worldview) || "",
        worldview:       cleanWorldview(existingPolicy.worldview),
        scope_statement: cfg.scope_statement || "",

        early_prompt_blacklist: blacklist,
        values:                 (existingPolicy.values_weights || []).map(normalizeStandard),
        structural_requirements: structural,
        allowed_tools:          allowed,
        forbidden_paths:        forbiddenPaths,
        forbidden_executables:  forbiddenExecutables,
        forbidden_shell_patterns: forbiddenShellPatterns,
        will_rules:             legacyList,

        alignment_threshold: cfg.alignment_threshold ?? 0.5,
        ethical_memory:      cfg.ethical_memory      ?? 0.90,
    };
}

function extractContext(wv) {
    const match = wv && wv.match(/<!-- CONTEXT: ([\s\S]*?) -->/);
    return match ? match[1].trim() : "";
}

function cleanWorldview(wv) {
    return wv ? wv.replace(/<!-- CONTEXT: [\s\S]*? -->\n?/g, "").trim() : "";
}

function saveDraft() {
    if (generatedCredentials) return;
    const draft = { data: policyData, step: currentStep, timestamp: Date.now() };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(draft)); } catch (e) { }
}

function renderStep(step) {
    updateProgress();
    const container = document.getElementById('pw-content');
    container.innerHTML = '';

    switch (step) {
        case 1: renderDefinitionStep(container, policyData);   break;
        case 2: renderConstitutionStep(container, policyData); break;
        case 3: renderScopeStep(container, policyData);        break;
        case 4: renderValuesStep(container, policyData);       break;
        case 5: renderWillStep(container, policyData);         break;
        case 6: renderGovernanceStep(container, policyData);   break;
        case 7: renderSuccessStep(container, policyData, generatedCredentials); break;
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
        case 3: return validateScopeStep(policyData);
        case 4: return validateValuesStep(policyData);
        case 5: return validateWillStep(policyData);
        case 6: return validateGovernanceStep(policyData);
        default: return true;
    }
}

async function submitPolicy(btn = null) {
    btn = btn || document.getElementById('pw-next-btn');
    btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Saving...`;
    btn.disabled = true;

    try {
        const structuredWillRules = {
            structural_requirements: {
                ...policyData.structural_requirements,
                alignment_score_threshold: policyData.alignment_threshold,
            },
            early_prompt_blacklist: policyData.early_prompt_blacklist || [],
            allowed_tools:          policyData.allowed_tools || [],
            rules:                  policyData.will_rules || [],
            forbidden_paths:        policyData.forbidden_paths || [],
            forbidden_executables: policyData.forbidden_executables || [],
            forbidden_shell_patterns: policyData.forbidden_shell_patterns || [],
            ...(Array.isArray(policyData.allowed_knowledge_bases)
                ? { allowed_knowledge_bases: policyData.allowed_knowledge_bases }
                : {}),
        };

        const payload = {
            name:            policyData.name,
            business_unit:   policyData.business_unit,
            context:         policyData.context,
            worldview:       policyData.worldview,
            scope_statement: policyData.scope_statement,
            values:          policyData.values,
            will_rules:      structuredWillRules,

            alignment_threshold: policyData.alignment_threshold,
            ethical_memory:      policyData.ethical_memory,

            policy_id:       policyData.policy_id,
        };

        const res = await api.savePolicy(payload);
        if (res.ok) {
            localStorage.removeItem(STORAGE_KEY);
            const pendingTools = Array.isArray(res.tools_pending_approval) ? res.tools_pending_approval : [];
            if (res.pending_approval) {
                const what = (res.changed || []).join(', ') || 'changes';
                ui.showToast(`Submitted for approval: ${what}. The policy keeps its current content until a policy approver activates the change.`, 'warning', 8000);
            } else if (pendingTools.length) {
                ui.showToast(`Policy saved. ${pendingTools.length} tool${pendingTools.length === 1 ? '' : 's'} (${pendingTools.join(', ')}) awaits approval before agents can use ${pendingTools.length === 1 ? 'it' : 'them'}.`, 'warning', 7000);
            } else {
                ui.showToast("Policy Saved!", "success");
            }
            generatedCredentials = res.credentials || { policy_id: "unknown", api_key: "unknown" };
            currentStep = TOTAL_STEPS + 1;
            renderSuccessStep(document.getElementById('pw-content'), policyData, generatedCredentials);
            updateProgress();
        } else {
            throw new Error(res.error || "Failed to save policy");
        }
    } catch (e) {
        console.error(e);
        let msg = e.message || "Failed to save policy";
        try {
            const parsed = JSON.parse(msg);
            if (parsed && parsed.error) msg = parsed.error;
        } catch (_) {   }
        ui.showToast(msg, "error");
        btn.innerHTML = policyData.policy_id ? 'Save Changes' : 'Create Policy';
        btn.disabled = false;
    }
}

function ensureWizardInlineExists() {
    if (document.getElementById('pw-progress')) return;

    const container = document.getElementById('policy-wizard-view');
    if (!container) return;

    const html = `
    <div class="w-full h-full flex flex-col bg-white dark:bg-black">
        <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center shrink-0">
            <div>
                <h3 class="text-xl font-bold text-gray-900 dark:text-white" id="policy-wizard-title">Create Policy</h3>
                <p class="text-sm text-gray-500 dark:text-gray-400">Step <span id="pw-step-num">1</span> of ${TOTAL_STEPS}</p>
            </div>
            <button id="close-pw-btn" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300 p-2 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">
                    <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
        </div>

        <div class="w-full bg-gray-200 dark:bg-neutral-800 h-1 shrink-0 flex">
            <div id="pw-progress" class="bg-green-600 h-full transition-all duration-300" style="width: ${100 / TOTAL_STEPS}%"></div>
        </div>

        <div class="flex justify-between px-6 py-2 text-xs text-gray-400 uppercase font-bold tracking-wider border-b border-neutral-100 dark:border-neutral-800 bg-white dark:bg-neutral-950 overflow-x-auto gap-4">
            <span data-step="1">Basics</span>
            <span data-step="2">Purpose</span>
            <span data-step="3">Scope</span>
            <span data-step="4">Standards</span>
            <span data-step="5">Tools &amp; Controls</span>
            <span data-step="6">Review &amp; Settings</span>
        </div>

        <div id="pw-content" class="flex-1 overflow-y-auto custom-scrollbar p-6 md:p-12 max-w-7xl mx-auto w-full"></div>

        <div class="bg-gray-50 dark:bg-neutral-950 px-6 py-4 border-t border-neutral-200 dark:border-neutral-800 flex justify-between shrink-0 footer-container">
            <button id="pw-back-btn" class="px-6 py-2.5 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800 disabled:opacity-50 transition-colors">Back</button>
            <div class="flex items-center gap-3">
                <!-- Edit mode only: save from any step without walking to the
                     end. Runs the same submitPolicy path as the final step,
                     after validating the step on screen. -->
                <button id="pw-save-btn" class="hidden px-6 py-2.5 rounded-lg text-sm font-semibold text-green-700 dark:text-green-300 border border-green-300 dark:border-green-700 hover:bg-green-50 dark:hover:bg-green-900/20 disabled:opacity-50 transition-colors">Save Changes</button>
                <button id="pw-next-btn" class="px-8 py-2.5 rounded-lg text-sm font-semibold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm">Next</button>
            </div>
        </div>
    </div>`;

    container.innerHTML = html;
    document.getElementById('close-pw-btn').addEventListener('click', () => closeWizard(false));
    document.getElementById('pw-back-btn').addEventListener('click', prevStep);
    document.getElementById('pw-next-btn').addEventListener('click', nextStep);
    document.getElementById('pw-save-btn').addEventListener('click', async () => {
        if (!validateCurrentStep()) return;
        saveDraft();
        await submitPolicy(document.getElementById('pw-save-btn'));
    });

    document.querySelectorAll('#policy-wizard-view [data-step]').forEach((el) => {
        el.addEventListener('click', () => {
            const idx = parseInt(el.dataset.step, 10);
            if (idx < currentStep && currentStep <= TOTAL_STEPS) {
                saveDraft();
                currentStep = idx;
                renderStep(currentStep);
            }
        });
    });
}

function updateProgress() {
    document.getElementById('pw-step-num').innerText = currentStep <= TOTAL_STEPS ? currentStep : TOTAL_STEPS;
    document.getElementById('pw-progress').style.width = `${(Math.min(currentStep, TOTAL_STEPS) / TOTAL_STEPS) * 100}%`;

    document.getElementById('pw-back-btn').disabled = currentStep === 1 || currentStep > TOTAL_STEPS;

    const nextBtn = document.getElementById('pw-next-btn');
    nextBtn.innerText = currentStep === TOTAL_STEPS
        ? (policyData.policy_id ? 'Save Changes' : 'Create Policy')
        : 'Next';

    const saveBtn = document.getElementById('pw-save-btn');
    if (saveBtn) {
        if (policyData.policy_id && currentStep < TOTAL_STEPS) saveBtn.classList.remove('hidden');
        else saveBtn.classList.add('hidden');
    }

    const view = document.getElementById('policy-wizard-view');
    const footer = view.querySelector('.footer-container');
    if (currentStep > TOTAL_STEPS) {
        if (footer) footer.style.display = 'none';
    } else {
        if (footer) footer.style.display = 'flex';
    }

    const labels = document.querySelectorAll('#policy-wizard-view [data-step]');
    labels.forEach((el) => {
        const idx = parseInt(el.dataset.step, 10);
        if (idx <= currentStep) el.classList.add('text-green-600');
        else el.classList.remove('text-green-600');
        const clickable = idx < currentStep && currentStep <= TOTAL_STEPS;
        el.classList.toggle('cursor-pointer', clickable);
        el.classList.toggle('hover:underline', clickable);
    });
}
