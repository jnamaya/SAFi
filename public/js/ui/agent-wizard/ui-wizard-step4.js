import * as api from '../../core/api.js';
import * as ui from './../ui.js';
import { renderModelSelector } from './ui-wizard-utils.js';

export function renderConscienceStep(container, agentData, availableModels) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-5">
             <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Core Values</h2>
                <p class="text-gray-500 text-sm">Define the ethical framework. The AI will score itself against these values.</p>
             </div>
             <div class="w-64">
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1 text-right">Ethical Reasoning Model</label>
                <div id="conscience-model-container"></div>
             </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <!-- Left Column: Values List -->
            <div class="md:col-span-2 space-y-6">
                <div>
                     <div class="flex justify-between items-end mb-4">
                        <div>
                             <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Defining Values</label>
                        </div>
                        <button id="wiz-suggest-val-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Suggest Values
                        </button>
                     </div>
                     
                     <div id="wiz-values-list" class="space-y-6 mb-8">
                         <!-- Values rendered here -->
                     </div>
                     
                     <button id="wiz-manual-val-btn" class="w-full py-4 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl text-base font-medium text-gray-500 hover:border-blue-500 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/10 transition-colors flex justify-center items-center gap-2">
                         <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                         Add Custom Value
                     </button>
                </div>
            </div>

            <!-- Right Column: Expert Tips -->
            <div class="bg-blue-50 dark:bg-neutral-800 p-6 rounded-xl border border-blue-100 dark:border-neutral-700 h-fit">
                <h4 class="font-bold text-gray-700 dark:text-gray-200 mb-4 flex items-center gap-2">
                    <svg class="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    Value Engineering
                </h4>
                <ul class="space-y-4 text-xs text-gray-600 dark:text-gray-400">
                    <li>
                        <strong>Identity vs Values:</strong> Use System Instructions for who the agent is. Use Core Values for the agent to grade itself (ethically).
                    </li>
                    <li>
                        <strong>Rubrics:</strong> Each value has a scoring rubric. The AI uses this to "grade" its own alignment with company values.
                    </li>
                    <li class="p-3 bg-white dark:bg-neutral-900 rounded border border-blue-200 dark:border-neutral-600 shadow-sm">
                        <strong>Tip:</strong> Click <span class="font-bold text-blue-600">⚡ Generate Rubric</span> on a card to have the AI write the detailed grading logic for you.
                    </li>
                </ul>
            </div>
        </div>
    `;

    // Inject Model Selector
    const modelContainer = document.getElementById('conscience-model-container');
    if (modelContainer) {
        // Use 'minimal' or 'small' if supported, else 'support' is fine
        modelContainer.innerHTML = renderModelSelector('wiz-conscience-model', agentData.conscience_model || '', 'support', availableModels);
        document.getElementById('wiz-conscience-model')?.addEventListener('change', (e) => agentData.conscience_model = e.target.value);
    }

    renderValuesList(agentData);

    // --- EVENT LISTENERS ---

    // 1. Suggest Values (Auto-Generate)
    document.getElementById('wiz-suggest-val-btn').addEventListener('click', async () => {
        const btn = document.getElementById('wiz-suggest-val-btn');
        const originalHtml = btn.innerHTML;

        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Thinking...`;
        btn.disabled = true;

        try {
            const context = `Name: ${agentData.name}\nDescription: ${agentData.description}\nInstructions: ${agentData.instructions}`;
            const res = await api.suggestValues(context);

            if (res.ok && res.values) {
                // Auto-populate directly
                agentData.values = res.values.map(v => ({
                    name: v.name,
                    weight: 0.2, // Default weight
                    description: v.description,
                    rubric: null
                }));

                renderValuesList(agentData);
                ui.showToast("Values generated!", "success");
            } else {
                ui.showToast("Failed to generate suggestions.", "error");
            }
        } catch (e) {
            console.error(e);
            ui.showToast(`Error: ${e.message}`, "error");
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    });

    // 2. Manual Add (Inline)
    document.getElementById('wiz-manual-val-btn').addEventListener('click', () => {
        agentData.values.push({
            name: "New Value",
            weight: 0.2,
            description: "",
            rubric: null
        });
        renderValuesList(agentData);
        // Scroll to bottom
        setTimeout(() => document.getElementById('wiz-values-list').lastElementChild?.scrollIntoView({ behavior: 'smooth' }), 50);
    });
}


// --- LIST RENDERER (Updated with Generate Rubric Logic) ---

// --- LIST RENDERER (Updated with TRAFFIC LIGHT Rubric Builder) ---

function renderValuesList(agentData) {
    const list = document.getElementById('wiz-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (agentData.values.length === 0) {
        list.innerHTML = `<div class="text-center text-gray-400 py-12 border-2 border-dashed border-gray-200 dark:border-neutral-800 rounded-xl">
            <p class="text-lg mb-2">No values defined yet.</p>
            <p class="text-sm">Suggest or Add one above!</p>
        </div>`;
        return;
    }

    agentData.values.forEach((val, idx) => {
        let hasRubric = false;
        if (val.rubric) {
            if (val.rubric.scoring_guide && Array.isArray(val.rubric.scoring_guide)) {
                hasRubric = val.rubric.scoring_guide.length > 0;
            } else if (Array.isArray(val.rubric)) {
                hasRubric = val.rubric.length > 0;
            }
        }

        const rubricBadge = hasRubric
            ? `<span class="bg-green-100 text-green-700 px-2 py-0.5 rounded text-xs font-bold border border-green-200">✅ Rubric Ready</span>`
            : `<span class="bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded text-xs font-bold border border-yellow-200">⚠️ Needs Criteria</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-6 shadow-sm hover:border-blue-300 transition-colors group";

        const nameId = `ag-val-name-${idx}`;
        const descId = `ag-val-desc-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-4 gap-4">
                <input type="text" id="${nameId}" class="flex-1 font-bold text-lg bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-900 dark:text-white placeholder-gray-400 px-1 py-1 transition-all" 
                    value="${val.name}" placeholder="Value Name">
                    
                <button class="text-gray-400 hover:text-red-500 p-2 rounded hover:bg-red-50 dark:hover:bg-red-900/20 transition-all" onclick="window.removeValue(${idx})">
                     <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 hover:border-blue-300 focus:border-blue-500 rounded-lg p-3 resize-none h-20 outline-none transition-all mb-4"
                placeholder="Description of this value...">${val.description || ''}</textarea>
            
            <div class="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-gray-100 dark:border-neutral-700">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-sm font-semibold text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('ag-rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                </div>
                
                <div class="flex items-center gap-3 bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800">
                    <label class="text-xs uppercase font-bold text-gray-500">Importance</label>
                    <input type="range" min="1" max="100" value="${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}" 
                        class="w-24 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600">
                    <span id="ag-weight-lbl-${idx}" class="text-sm font-mono font-bold text-gray-700 dark:text-gray-300 w-8 text-right">${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}%</span>
                </div>
            </div>

            <div id="ag-rubric-container-${idx}" class="hidden mt-6 pt-6 border-t border-dashed border-gray-200 dark:border-neutral-700 bg-gray-50/50 dark:bg-neutral-900/30 -mx-6 -mb-6 px-6 pb-6 rounded-b-xl">
                 <div class="flex justify-between items-center mb-4">
                    <label class="block text-xs uppercase text-gray-500 font-bold tracking-wider">Scoring Criteria (Traffic Light)</label>
                    <span class="text-xs text-gray-400">Fill in the 3 states</span>
                 </div>
                 
                 <div id="ag-rubric-rows-${idx}" class="space-y-3"></div>
            </div>
        `;
        list.appendChild(card);

        // Bind Inputs
        card.querySelector(`#${nameId}`).addEventListener('change', (e) => agentData.values[idx].name = e.target.value);
        card.querySelector(`#${descId}`).addEventListener('change', (e) => agentData.values[idx].description = e.target.value);

        // --- RUBRIC BUILDER LOGIC (FIXED 3-POINT) ---
        const rowsContainer = document.getElementById(`ag-rubric-rows-${idx}`);

        // Ensure rubric structure
        if (!agentData.values[idx].rubric) agentData.values[idx].rubric = { scoring_guide: [] };
        // Normalize array vs object
        if (Array.isArray(agentData.values[idx].rubric)) {
            agentData.values[idx].rubric = { scoring_guide: agentData.values[idx].rubric };
        } else if (!agentData.values[idx].rubric.scoring_guide) {
            agentData.values[idx].rubric.scoring_guide = [];
        }

        const renderFixedRows = () => {
            rowsContainer.innerHTML = '';
            const guide = agentData.values[idx].rubric.scoring_guide;

            const getCriteria = (targetScore) => {
                const item = guide.find(g => Math.abs(g.score - targetScore) < 0.1);
                return item ? (item.criteria || item.descriptor || '') : '';
            };

            const updateCriteria = (targetScore, text) => {
                agentData.values[idx].rubric.scoring_guide = agentData.values[idx].rubric.scoring_guide.filter(g => Math.abs(g.score - targetScore) >= 0.1);
                if (text && text.trim()) {
                    agentData.values[idx].rubric.scoring_guide.push({ score: targetScore, criteria: text.trim() });
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
        const label = card.querySelector(`#ag-weight-lbl-${idx}`);
        if (slider) {
            slider.addEventListener('input', (e) => {
                const newWeight = parseInt(e.target.value);
                agentData.values[idx].weight = newWeight;
                if (label) label.innerText = newWeight + '%';
            });
        }
    });

    // Delegated Remove
    window.removeValue = (idx) => {
        agentData.values.splice(idx, 1);
        renderValuesList(agentData);
    };
}

export function validateConscienceStep(agentData) {
    if (agentData.values.length === 0) {
        ui.showToast("Please add at least one value to define the agent's ethical framework.", "error");
        return false;
    }
    return true;
}
