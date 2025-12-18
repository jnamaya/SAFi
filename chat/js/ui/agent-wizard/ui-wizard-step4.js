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
                     <div class="flex justify-between items-end mb-2">
                        <div>
                             <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Defining Values</label>
                        </div>
                        <button id="wiz-suggest-val-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Suggest Values
                        </button>
                     </div>
                     
                     <!-- Suggestion Zone (Hidden by default) -->
                     <div id="wiz-val-suggestions" class="hidden mb-4 p-4 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-xl relative">
                        <button onclick="document.getElementById('wiz-val-suggestions').classList.add('hidden')" class="absolute top-2 right-2 text-xs text-purple-400 hover:text-purple-600">✕ Close</button>
                        <h3 class="font-bold text-purple-900 dark:text-purple-100 mb-3 text-xs uppercase tracking-wide">AI Suggestions</h3>
                        <div id="wiz-val-suggestions-list" class="grid grid-cols-1 gap-2 max-h-60 overflow-y-auto pr-1">
                            <div class="text-center w-full py-4 text-purple-400">Loading suggestions...</div>
                        </div>
                     </div>

                     <div id="wiz-values-list" class="space-y-3 mb-3">
                         <!-- Values rendered here -->
                     </div>
                     
                     <button id="wiz-manual-val-btn" class="w-full py-3 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-lg text-sm font-bold text-gray-500 hover:border-blue-500 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/10 transition-colors flex justify-center items-center gap-2">
                         <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
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

    // 1. Suggest Values
    document.getElementById('wiz-suggest-val-btn').addEventListener('click', async () => {
        const btn = document.getElementById('wiz-suggest-val-btn');
        const container = document.getElementById('wiz-val-suggestions');
        const list = document.getElementById('wiz-val-suggestions-list');

        // Reset/Show
        container.classList.remove('hidden');
        list.innerHTML = `<div class="text-center py-4 text-purple-500 text-sm"><span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Analyzing agent profile...</div>`;
        btn.disabled = true;

        try {
            const context = `Name: ${agentData.name}\nDescription: ${agentData.description}\nInstructions: ${agentData.instructions}`;
            const res = await api.suggestValues(context);

            if (res.ok && res.values) {
                list.innerHTML = '';
                res.values.forEach(val => {
                    const item = document.createElement('div');
                    item.className = "flex items-start gap-3 p-3 bg-white dark:bg-neutral-800 rounded border border-purple-100 dark:border-purple-900/50 hover:border-purple-300 transition-colors cursor-pointer";
                    item.innerHTML = `
                        <div class="mt-1">
                            <input type="checkbox" class="w-4 h-4 text-purple-600 rounded focus:ring-purple-500" data-name="${val.name}">
                        </div>
                        <div>
                            <div class="font-bold text-gray-900 dark:text-gray-100 text-sm">${val.name}</div>
                            <div class="text-xs text-gray-500 dark:text-gray-400 leading-snug">${val.description}</div>
                        </div>
                    `;
                    // Click entire card to toggle
                    item.addEventListener('click', (e) => {
                        if (e.target.type !== 'checkbox') {
                            const cb = item.querySelector('input');
                            cb.checked = !cb.checked;
                        }
                    });
                    list.appendChild(item);
                });

                // Add "Add Selected" button at bottom of suggestions
                const actions = document.createElement('div');
                actions.className = "mt-2 pt-2 border-t border-purple-200 dark:border-purple-800 flex justify-end";
                actions.innerHTML = `<button id="wiz-add-selected-btn" class="px-3 py-1 bg-purple-600 text-white text-xs font-bold rounded shadow hover:bg-purple-700">Add Selected</button>`;
                list.appendChild(actions);

                document.getElementById('wiz-add-selected-btn').addEventListener('click', () => {
                    const checked = list.querySelectorAll('input:checked');
                    if (checked.length === 0) return ui.showToast("No values selected", "warning");

                    checked.forEach(cb => {
                        const name = cb.dataset.name;
                        const vObj = res.values.find(v => v.name === name);
                        if (vObj) {
                            if (!agentData.values.find(ex => ex.name === name)) {
                                agentData.values.push({
                                    name: vObj.name,
                                    weight: 0.2,
                                    description: vObj.description,
                                    rubric: null
                                });
                            }
                        }
                    });
                    renderValuesList(agentData);
                    container.classList.add('hidden');
                    ui.showToast(`Added ${checked.length} values`, "success");
                });

            } else {
                list.innerHTML = `<div class="text-red-500 text-xs">Failed to generate suggestions.</div>`;
            }
        } catch (e) {
            console.error(e);
            list.innerHTML = `<div class="text-red-500 text-xs">Error: ${e.message}</div>`;
        } finally {
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

function renderValuesList(agentData) {
    const list = document.getElementById('wiz-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (agentData.values.length === 0) {
        list.innerHTML = `<div class="text-center text-gray-400 py-8 border-2 border-dashed border-gray-200 dark:border-neutral-800 rounded-lg">No values yet. Suggest or Add one above!</div>`;
        return;
    }

    agentData.values.forEach((val, idx) => {
        // Rubric State Check
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
            ? `<span class="text-green-600 flex items-center gap-1 text-[10px] font-bold bg-green-50 dark:bg-green-900/20 px-2 py-0.5 rounded">✅ Rubric Active</span>`
            : `<span class="text-yellow-600 text-[10px] font-bold bg-yellow-50 dark:bg-yellow-900/20 px-2 py-0.5 rounded">⚠️ No Rubric</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-4 shadow-sm hover:border-blue-300 transition-colors group";

        const nameId = `ag-val-name-${idx}`;
        const descId = `ag-val-desc-${idx}`;
        const rubricId = `ag-val-rubric-${idx}`;
        const genBtnId = `ag-gen-rubric-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2 gap-2">
                <input type="text" id="${nameId}" class="flex-1 text-base font-bold bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 px-1 py-0.5 transition-all" 
                    value="${val.name}" placeholder="Value Name">
                    
                <button class="text-gray-400 hover:text-red-500 p-1 opacity-60 hover:opacity-100 transition-opacity" onclick="window.removeValue(${idx})" title="Remove Value">
                     <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-neutral-900 border border-transparent hover:border-gray-200 focus:border-blue-500 rounded p-2 resize-none h-14 outline-none transition-all mb-3"
                placeholder="Description of this value...">${val.description || ''}</textarea>
            
            <div class="flex flex-wrap justify-between items-center border-t border-gray-100 dark:border-neutral-700 pt-3 gap-y-2">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    
                    <div class="flex items-center gap-2 ml-2 border-l border-gray-200 dark:border-neutral-700 pl-3">
                        <label class="text-[10px] uppercase font-bold text-gray-400">Importance</label>
                        <input type="range" min="1" max="100" value="${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}" 
                            class="w-16 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700">
                        <span id="ag-weight-lbl-${idx}" class="text-[10px] text-gray-500 w-6 font-mono">${(val.weight && val.weight <= 1.0) ? Math.round(val.weight * 100) : (val.weight || 20)}%</span>
                    </div>
                </div>

                <div class="flex gap-2">
                     ${!hasRubric ? `
                        <button id="${genBtnId}" class="px-3 py-1 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-xs font-bold rounded hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors">
                            ⚡ Generate Rubric
                        </button>
                     ` : ''}
                     <button class="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300" onclick="document.getElementById('ag-rubric-container-${idx}').classList.toggle('hidden')">
                        ${hasRubric ? 'Edit JSON' : 'Manual JSON'}
                    </button>
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
            } catch (err) { /* ignore */ }
        });

        // Bind Slider
        const slider = card.querySelector(`input[type="range"]`);
        const blabel = card.querySelector(`#ag-weight-lbl-${idx}`);
        if (slider) {
            slider.addEventListener('input', (e) => {
                const newWeight = parseInt(e.target.value);
                agentData.values[idx].weight = newWeight;
                if (blabel) blabel.innerText = newWeight + '%';
            });
        }

        // Bind Auto-Generate Rubric Button
        const genBtn = document.getElementById(genBtnId);
        if (genBtn) {
            genBtn.addEventListener('click', async () => {
                genBtn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Working...`;
                genBtn.disabled = true;

                try {
                    // Use description as context, fallback to agent instructions
                    const context = val.description || agentData.instructions || agentData.description;
                    const res = await api.generateRubric(val.name, context);

                    if (res.ok && res.rubric) {
                        agentData.values[idx].rubric = res.rubric.scoring_guide || res.rubric;
                        // Determine default description if user left it blank
                        if (!val.description && (res.rubric.description || res.rubric.definition)) {
                            agentData.values[idx].description = res.rubric.description || res.rubric.definition;
                        }

                        renderValuesList(agentData); // Re-render to show "Active" badge
                        ui.showToast("Rubric generated!", "success");
                    } else {
                        ui.showToast("Failed to generate rubric", "error");
                        genBtn.innerHTML = `⚡ Generate Rubric`;
                        genBtn.disabled = false;
                    }
                } catch (e) {
                    ui.showToast("Error: " + e.message, "error");
                    genBtn.innerHTML = `⚡ Generate Rubric`;
                    genBtn.disabled = false;
                }
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
