import * as api from './../api.js';
import * as ui from './../ui.js';

export function renderConstitutionStep(container, policyData) {
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

            <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 h-fit">
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

    renderValuesList(policyData);

    // Bind Handlers
    document.getElementById('pw-worldview')?.addEventListener('input', (e) => policyData.worldview = e.target.value);

    bindAiHandlers(policyData);

    // Add Value Btn
    document.getElementById('btn-add-value').addEventListener('click', () => {
        policyData.values.push({ name: "New Value", description: "", weight: 0.2, rubric: { scoring_guide: [] } });
        renderValuesList(policyData);
    });
}

function bindAiHandlers(policyData) {
    // GEN WORLDVIEW
    document.getElementById('btn-gen-worldview')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Generating...`;
        btn.disabled = true;

        try {
            const res = await api.generatePolicyContent('worldview', policyData.context || "General Organization");
            if (res.ok && res.content) {
                document.getElementById('pw-worldview').value = res.content;
                policyData.worldview = res.content;
                ui.showToast("Worldview generated!", "success");
            } else {
                ui.showToast("Failed to generate worldview", "error");
            }
        } catch (err) { console.error(err); }
        btn.innerHTML = original;
        btn.disabled = false;
    });

    // GEN VALUES
    document.getElementById('btn-gen-values')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Thinking...`;
        btn.disabled = true;

        try {
            const ctx = policyData.context || policyData.name || "General Organization";
            const res = await api.generatePolicyContent('values', ctx);
            if (res.ok && res.content) {
                let json;
                if (typeof res.content === 'string') {
                    let cleaned = res.content.trim();
                    if (cleaned.startsWith('{') && !cleaned.startsWith('[')) cleaned = `[${cleaned}]`;
                    json = JSON.parse(cleaned);
                } else {
                    json = res.content;
                }
                policyData.values = json.map(v => ({ ...v, weight: v.weight || 0.2 }));
                renderValuesList(policyData);
                ui.showToast("Values & Rubrics Generated!", "success");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("AI returned invalid format", "error");
        }
        btn.innerHTML = original;
        btn.disabled = false;
    });
}

function renderValuesList(policyData) {
    const list = document.getElementById('pw-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.values.length === 0) {
        list.innerHTML = `<p class="text-sm text-gray-400 text-center italic py-4">No values defined yet. Click "Suggest Values" to start.</p>`;
        return;
    }

    policyData.values.forEach((v, idx) => {
        let rubricText = "";
        let hasRubric = false;

        if (v.rubric) {
            if (v.rubric.scoring_guide && Array.isArray(v.rubric.scoring_guide)) {
                hasRubric = v.rubric.scoring_guide.length > 0;
            } else if (Array.isArray(v.rubric)) {
                hasRubric = v.rubric.length > 0;
            }
            rubricText = JSON.stringify(v.rubric, null, 2);
        }

        const rubricBadge = hasRubric
            ? `<span class="text-green-600 flex items-center gap-1 text-[10px] font-bold">✅ Rubric Active</span>`
            : `<span class="text-yellow-600 text-[10px] font-bold">⚠️ No Rubric</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-3 shadow-sm hover:border-blue-300 transition-colors group";

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
            
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                    
                    <div class="flex items-center gap-2 ml-4">
                        <label class="text-[10px] uppercase font-bold text-gray-400">Imp</label>
                        <input type="range" min="1" max="100" value="${(v.weight && v.weight <= 1.0) ? Math.round(v.weight * 100) : (v.weight || 20)}" 
                            class="w-16 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700">
                        <span id="pw-weight-lbl-${idx}" class="text-[10px] text-gray-500 w-6">${(v.weight && v.weight <= 1.0) ? Math.round(v.weight * 100) : (v.weight || 20)}%</span>
                    </div>
                </div>
            </div>

            <div id="rubric-container-${idx}" class="hidden mt-3 pt-3 border-t border-gray-100 dark:border-neutral-700">
                <label class="block text-[10px] uppercase text-gray-400 font-bold mb-1">Scoring Logic (JSON)</label>
                <textarea id="${rubricId}" class="w-full h-32 font-mono text-xs p-2 bg-gray-900 text-green-400 rounded border border-gray-700 focus:border-green-500 outline-none" spellcheck="false">${rubricText}</textarea>
                <p class="text-[10px] text-gray-400 mt-1">Edit the raw JSON to adjust scoring criteria.</p>
            </div>
        `;
        list.appendChild(card);

        // Bind Change Events
        card.querySelector(`#${nameId}`).addEventListener('change', (e) => policyData.values[idx].name = e.target.value);
        card.querySelector(`#${descId}`).addEventListener('change', (e) => policyData.values[idx].description = e.target.value);
        card.querySelector(`#${rubricId}`).addEventListener('change', (e) => {
            try {
                policyData.values[idx].rubric = JSON.parse(e.target.value);
            } catch (err) { /* ignore or warn */ }
        });

        // Fix: Bind Slider Event properly with closure
        const slider = card.querySelector(`input[type="range"]`);
        const label = card.querySelector(`#pw-weight-lbl-${idx}`);
        if (slider) {
            slider.addEventListener('input', (e) => {
                const newWeight = parseInt(e.target.value);
                policyData.values[idx].weight = newWeight; // Update Data Model
                // Update Label immediately
                if (label) label.innerText = newWeight + '%';
            });
        }
    });

    // Delegated Remove Handler (Needs scope access, so must re-define on window or use cleaner delegation in core)
    // For consistency with Agent Wizard, I'll use window with a localized name.
    window.removePolicyValue = (idx) => {
        policyData.values.splice(idx, 1);
        renderValuesList(policyData);
    };
}

export function validateConstitutionStep(policyData) {
    if (!policyData.values || policyData.values.length === 0) {
        ui.showToast("At least one Core Value is required to proceed.", "error");
        return false;
    }
    return true;
}
