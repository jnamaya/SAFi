import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export function renderValuesStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <div class="md:col-span-2 space-y-8">
                 <div>
                    <div class="flex justify-between items-end mb-4">
                         <div>
                            <label class="block text-lg font-bold text-gray-700 dark:text-gray-300">Core Values & Rubrics</label>
                            <p class="text-sm text-gray-500">Define the ethical standards used to grade every response.</p>
                         </div>
                         <button id="btn-gen-values" class="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-full flex items-center gap-2 transition-colors shadow-sm">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Suggest Values
                         </button>
                    </div>
                    
                    <div id="pw-values-list" class="space-y-6 mb-6">
                        <!-- Values rendered here -->
                    </div>
                    
                    <button id="btn-add-value" class="w-full py-4 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl text-base font-medium text-gray-500 hover:border-blue-500 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/10 transition-all">
                        + Add Custom Value
                    </button>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-neutral-800 p-8 rounded-2xl border border-blue-100 dark:border-neutral-700 h-fit sticky top-6">
                <h4 class="font-bold text-xl text-gray-800 dark:text-gray-200 mb-6 flex items-center gap-2">
                    <svg class="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    How Grading Works
                </h4>
                <div class="space-y-6 text-sm text-gray-600 dark:text-gray-400">
                    <p class="leading-relaxed">
                        Every time the agent replies, it "audits" itself against these values.
                    </p>
                    <div class="p-4 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700 shadow-sm">
                        <strong class="block text-green-600 mb-1">Pass (+1.0)</strong>
                        The response actively demonstrates the value.
                    </div>
                    <div class="p-4 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700 shadow-sm">
                         <strong class="block text-red-600 mb-1">Violation (-1.0)</strong>
                        The response breaks the rule.
                    </div>
                </div>
            </div>
        </div>
    `;

    renderValuesList(policyData);

    // Bind Auto-Gen Handler
    document.getElementById('btn-gen-values')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Thinking...`;
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

    // Add Value Btn
    document.getElementById('btn-add-value').addEventListener('click', () => {
        policyData.values.push({ name: "New Value", description: "", weight: 0.2, rubric: { scoring_guide: [] } });
        renderValuesList(policyData);
    });
}

function renderValuesList(policyData) {
    const list = document.getElementById('pw-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.values.length === 0) {
        list.innerHTML = `
            <div class="text-center py-12 bg-gray-50 dark:bg-neutral-900 rounded-xl border-2 border-dashed border-gray-200 dark:border-neutral-800">
                <p class="text-gray-400 text-lg mb-2">No values yet.</p>
                <p class="text-sm text-gray-500">Click "Suggest Values" to let AI draft them for you.</p>
            </div>`;
        return;
    }

    policyData.values.forEach((v, idx) => {
        // Check for Rubric
        let hasRubric = false;
        if (v.rubric) {
            if (v.rubric.scoring_guide && Array.isArray(v.rubric.scoring_guide)) {
                hasRubric = v.rubric.scoring_guide.length > 0;
            }
        }

        const rubricBadge = hasRubric
            ? `<span class="bg-green-100 text-green-700 px-2 py-0.5 rounded text-xs font-bold border border-green-200">✅ Rubric Ready</span>`
            : `<span class="bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded text-xs font-bold border border-yellow-200">⚠️ Needs Criteria</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-6 shadow-sm hover:border-blue-300 transition-colors group";

        const nameId = `pw-val-name-${idx}`;
        const descId = `pw-val-desc-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-4 gap-4">
                <input type="text" id="${nameId}" class="flex-1 font-bold text-lg bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-900 dark:text-white placeholder-gray-400 px-1 py-1 transition-all" 
                    value="${v.name}" placeholder="Value Name (e.g. Safety)">
                    
                <button class="text-gray-400 hover:text-red-500 p-2 rounded hover:bg-red-50 dark:hover:bg-red-900/20 transition-all" onclick="window.removePolicyValue(${idx})">
                     <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 hover:border-blue-300 focus:border-blue-500 rounded-lg p-3 resize-none h-24 outline-none transition-all mb-4"
                placeholder="Brief description of this value...">${v.description || ''}</textarea>
            
            <div class="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-gray-100 dark:border-neutral-700">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-sm font-semibold text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                </div>
                
                <div class="flex items-center gap-3 bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800">
                    <label class="text-xs uppercase font-bold text-gray-500">Importance</label>
                    <input type="range" min="1" max="100" value="${(v.weight && v.weight <= 1.0) ? Math.round(v.weight * 100) : (v.weight || 20)}" 
                        class="w-24 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600">
                    <span id="pw-weight-lbl-${idx}" class="text-sm font-mono font-bold text-gray-700 dark:text-gray-300 w-8 text-right">${(v.weight && v.weight <= 1.0) ? Math.round(v.weight * 100) : (v.weight || 20)}%</span>
                </div>
            </div>

            <div id="rubric-container-${idx}" class="hidden mt-6 pt-6 border-t border-dashed border-gray-200 dark:border-neutral-700 bg-gray-50/50 dark:bg-neutral-900/30 -mx-6 -mb-6 px-6 pb-6 rounded-b-xl">
                 <div class="flex justify-between items-center mb-4">
                    <label class="block text-xs uppercase text-gray-500 font-bold tracking-wider">Scoring Criteria (Traffic Light)</label>
                    <span class="text-xs text-gray-400">Fill in the 3 states</span>
                 </div>
                 
                 <!-- Visual Builder Container -->
                 <div id="rubric-rows-${idx}" class="space-y-3"></div>
            </div>
        `;
        list.appendChild(card);

        // Bind Inputs
        card.querySelector(`#${nameId}`).addEventListener('change', (e) => policyData.values[idx].name = e.target.value);
        card.querySelector(`#${descId}`).addEventListener('change', (e) => policyData.values[idx].description = e.target.value);

        // --- RUBRIC BUILDER LOGIC (FIXED 3-POINT) ---
        const rowsContainer = document.getElementById(`rubric-rows-${idx}`);

        // Ensure rubric structure
        if (!policyData.values[idx].rubric) policyData.values[idx].rubric = { scoring_guide: [] };
        if (Array.isArray(policyData.values[idx].rubric)) {
            policyData.values[idx].rubric = { scoring_guide: policyData.values[idx].rubric };
        }
        if (!policyData.values[idx].rubric.scoring_guide) policyData.values[idx].rubric.scoring_guide = [];

        const renderFixedRows = () => {
            rowsContainer.innerHTML = '';
            const guide = policyData.values[idx].rubric.scoring_guide;

            // Helper to get text for a specific score
            const getCriteria = (targetScore) => {
                const item = guide.find(g => Math.abs(g.score - targetScore) < 0.1);
                return item ? (item.criteria || item.descriptor || '') : '';
            };

            // Helper to update the guide
            const updateCriteria = (targetScore, text) => {
                // Remove existing
                policyData.values[idx].rubric.scoring_guide = policyData.values[idx].rubric.scoring_guide.filter(g => Math.abs(g.score - targetScore) >= 0.1);
                // Add new
                if (text && text.trim()) {
                    policyData.values[idx].rubric.scoring_guide.push({ score: targetScore, criteria: text.trim() });
                }
            };

            const definitions = [
                { score: 1.0, label: "Positive (+1.0)", placeholder: "Example of excellent adherence...", color: "green", icon: "✅" },
                { score: 0.0, label: "Neutral (0.0)", placeholder: "Acceptable / Baseline behavior...", color: "gray", icon: "⚪" },
                { score: -1.0, label: "Negative (-1.0)", placeholder: "Specific violation example...", color: "red", icon: "🚫" }
            ];

            definitions.forEach(def => {
                const row = document.createElement('div');
                row.className = "flex gap-4 items-start";

                const bgClass = def.score === 1 ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900' :
                    def.score === -1 ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900' :
                        'bg-white dark:bg-neutral-800 border-gray-200 dark:border-neutral-700';

                const textClass = def.score === 1 ? 'text-green-700 dark:text-green-400' :
                    def.score === -1 ? 'text-red-700 dark:text-red-400' :
                        'text-gray-600 dark:text-gray-400';

                row.innerHTML = `
                    <div class="w-32 shrink-0 pt-3 text-right">
                        <span class="block text-xs font-bold ${textClass} mb-1">${def.label}</span>
                    </div>
                    <div class="flex-1 relative">
                        <span class="absolute top-3 left-3 text-sm select-none opacity-50">${def.icon}</span>
                        <textarea class="w-full text-sm p-3 pl-10 rounded-lg border focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-none h-20 transition-all shadow-sm ${bgClass}"
                            placeholder="${def.placeholder}">${getCriteria(def.score)}</textarea>
                    </div>
                `;

                const input = row.querySelector('textarea');
                input.addEventListener('change', (e) => {
                    updateCriteria(def.score, e.target.value);
                });

                rowsContainer.appendChild(row);
            });
        };

        renderFixedRows();

        // Slider Logic
        const slider = card.querySelector(`input[type="range"]`);
        const label = card.querySelector(`#pw-weight-lbl-${idx}`);
        if (slider) {
            slider.addEventListener('input', (e) => {
                const newWeight = parseInt(e.target.value);
                policyData.values[idx].weight = newWeight;
                if (label) label.innerText = newWeight + '%';
            });
        }
    });

    // Window global for remove (legacy pattern)
    window.removePolicyValue = (idx) => {
        policyData.values.splice(idx, 1);
        renderValuesList(policyData);
    };
}

export function validateValuesStep(policyData) {
    if (!policyData.values || policyData.values.length === 0) {
        ui.showToast("At least one Core Value is required.", "error");
        return false;
    }
    return true;
}
