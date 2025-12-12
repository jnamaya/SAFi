import * as api from './../api.js';
import * as ui from './../ui.js';
import { renderModelSelector } from './ui-wizard-utils.js';

export function renderConscienceStep(container, agentData, availableModels) {
    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
            <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Core Values</h2>
                <p class="text-gray-500 text-sm mb-6">What does this agent value? The AI will score itself against these.</p>
            </div>
            <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">AI Model</label>
                <div id="conscience-model-container"></div>
            </div>
        </div>
        
        <div class="flex gap-4 mb-6">
            <input type="text" id="wiz-val-input" class="flex-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500" placeholder="Enter a value (e.g. Honesty, Frugality)">
            <button id="wiz-add-val-btn" class="px-4 py-2 bg-blue-600 text-white rounded-lg font-semibold hover:bg-blue-700 transition-colors shadow">
                Auto-Generate Rubric ✨
            </button>
        </div>

        <div id="wiz-values-list" class="space-y-4 max-h-[400px] overflow-y-auto pr-2">
            <!-- Values cards go here -->
        </div>
    `;

    // Inject Model Selector
    const modelContainer = document.getElementById('conscience-model-container');
    if (modelContainer) {
        modelContainer.innerHTML = renderModelSelector('wiz-conscience-model', agentData.conscience_model || '', 'support', availableModels);
        document.getElementById('wiz-conscience-model')?.addEventListener('change', (e) => agentData.conscience_model = e.target.value);
    }

    renderValuesList(agentData);

    // Auto-Generate Handler
    document.getElementById('wiz-add-val-btn').addEventListener('click', async () => {
        const name = document.getElementById('wiz-val-input').value.trim();
        if (!name) return ui.showToast("Please enter a value name", "error");

        const btn = document.getElementById('wiz-add-val-btn');
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Generating...`;
        btn.disabled = true;

        try {
            const context = agentData.instructions || agentData.description;
            const res = await api.generateRubric(name, context);

            if (res.ok && res.rubric) {
                const rubric = res.rubric;
                // Backend returns "definition" but ui typically uses "description". 
                // We'll use "description" if available, else "definition".
                // Ideally backend is fixed to return "description".
                agentData.values.push({
                    name: name,
                    weight: 0.2, // Default weight
                    description: rubric.description || rubric.definition,
                    rubric: rubric.scoring_guide || rubric
                });
                renderValuesList(agentData);
                document.getElementById('wiz-val-input').value = '';
                ui.showToast(`Generated rubric for ${name}`, "success");
            } else {
                throw new Error(res.error || "Unknown error");
            }
        } catch (e) {
            ui.showToast(`Generation failed: ${e.message}`, "error");
        } finally {
            btn.innerHTML = "Auto-Generate Rubric ✨";
            btn.disabled = false;
        }
    });
}

function renderValuesList(agentData) {
    const list = document.getElementById('wiz-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (agentData.values.length === 0) {
        list.innerHTML = `<div class="text-center text-gray-400 py-8 border-2 border-dashed border-gray-200 dark:border-neutral-800 rounded-lg">No values yet. Add one above!</div>`;
        return;
    }

    agentData.values.forEach((val, idx) => {
        // Prepare Rubric Status & Text
        let hasRubric = false;
        let rubricText = '{}';
        if (val.rubric) {
            if (Array.isArray(val.rubric)) {
                hasRubric = val.rubric.length > 0;
            } else if (val.rubric.scoring_guide && Array.isArray(val.rubric.scoring_guide)) {
                hasRubric = val.rubric.scoring_guide.length > 0;
            }
            rubricText = JSON.stringify(val.rubric, null, 2);
        }

        const rubricBadge = hasRubric
            ? `<span class="text-green-600 flex items-center gap-1 text-[10px] font-bold">✅ Rubric Active</span>`
            : `<span class="text-yellow-600 text-[10px] font-bold">⚠️ No Rubric</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-3 shadow-sm hover:border-blue-300 transition-colors group";

        const nameId = `ag-val-name-${idx}`;
        const descId = `ag-val-desc-${idx}`;
        const rubricId = `ag-val-rubric-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2 gap-2">
                <input type="text" id="${nameId}" class="flex-1 font-bold bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 px-1 py-1 transition-all" 
                    value="${val.name}" placeholder="Value Name">
                    
                <button class="text-gray-400 hover:text-red-500 p-1 opacity-0 group-hover:opacity-100 transition-opacity" onclick="window.removeValue(${idx})">
                     <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-neutral-900 border border-transparent hover:border-gray-200 focus:border-blue-500 rounded p-2 resize-none h-16 outline-none transition-all"
                placeholder="Description of this value...">${val.description || ''}</textarea>
            
            <div class="flex justify-between items-center mt-3 border-t border-gray-100 dark:border-neutral-700 pt-2">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('ag-rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                    
                    <div class="flex items-center gap-2 ml-4">
                        <label class="text-[10px] uppercase font-bold text-gray-400">Imp</label>
                        <input type="range" min="1" max="100" value="${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}" 
                            class="w-16 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700">
                        <span id="ag-weight-lbl-${idx}" class="text-[10px] text-gray-500 w-6">${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}%</span>
                    </div>
                </div>
            </div>

            <div id="ag-rubric-container-${idx}" class="hidden mt-3 pt-3 border-t border-gray-100 dark:border-neutral-700">
                <label class="block text-[10px] uppercase text-gray-400 font-bold mb-1">Scoring Logic (JSON)</label>
                <textarea id="${rubricId}" class="w-full h-32 font-mono text-xs p-2 bg-gray-900 text-green-400 rounded border border-gray-700 focus:border-green-500 outline-none" spellcheck="false">${rubricText}</textarea>
                <p class="text-[10px] text-gray-400 mt-1">Edit the raw JSON to adjust scoring criteria.</p>
            </div>
        `;
        list.appendChild(card);

        // Bind Change Events
        card.querySelector(`#${nameId}`).addEventListener('change', (e) => agentData.values[idx].name = e.target.value);
        card.querySelector(`#${descId}`).addEventListener('change', (e) => agentData.values[idx].description = e.target.value);
        card.querySelector(`#${rubricId}`).addEventListener('change', (e) => {
            try {
                agentData.values[idx].rubric = JSON.parse(e.target.value);
            } catch (err) { /* ignore or warn */ }
        });

        // Bind Slider
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
