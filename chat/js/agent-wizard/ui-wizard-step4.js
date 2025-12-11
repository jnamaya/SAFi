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
                agentData.values.push({
                    name: name,
                    weight: 0.2, // Default weight
                    description: rubric.description,
                    rubric: rubric.scoring_guide
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
        const card = document.createElement('div');
        card.className = "bg-gray-50 dark:bg-neutral-800 p-4 rounded-lg border border-gray-200 dark:border-neutral-700 relative group";

        // Prepare JSON for the textarea
        const rubricJson = JSON.stringify(val.rubric, null, 2);

        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <div class="flex-1">
                    <input type="text" class="font-bold text-lg text-gray-900 dark:text-white bg-transparent border-none focus:ring-0 p-0 w-full" value="${val.name}" onchange="window.updateValueName(${idx}, this.value)">
                    <p class="text-xs text-gray-500">${val.description}</p>
                </div>
                <div class="flex gap-2">
                    <button class="text-blue-500 hover:text-blue-700 text-xs" onclick="toggleEdit(${idx})">Edit</button>
                    <button class="text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity" onclick="window.removeValue(${idx})">
                    <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </div>
            </div>
            
             <!-- Edit Mode (Hidden) -->
            <div id="wiz-val-edit-${idx}" class="hidden mt-4 space-y-3 border-t border-gray-200 dark:border-neutral-700 pt-3">
                <div>
                    <label class="block text-xs font-bold text-gray-500 mb-1">Description</label>
                    <textarea class="w-full text-xs p-2 rounded border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-gray-900 dark:text-white" rows="2" onchange="window.updateValueDesc(${idx}, this.value)">${val.description}</textarea>
                </div>
                <div>
                    <label class="block text-xs font-bold text-gray-500 mb-1">Rubric Criteria (JSON)</label>
                    <textarea class="w-full font-mono text-xs p-2 rounded border border-gray-300 dark:border-neutral-700 bg-gray-900 text-green-400" rows="6" onchange="window.updateValueRubric(${idx}, this.value)">${rubricJson}</textarea>
                </div>
            </div>

            <!-- Mini Rubric Preview -->
            <div id="wiz-val-preview-${idx}" class="grid grid-cols-3 gap-2 text-xs mt-3">
               <div class="p-2 bg-red-100 dark:bg-red-900/30 rounded text-red-800 dark:text-red-200">
                   <strong>-1.0:</strong> ${(val.rubric && val.rubric.find(r => r.score < 0)?.criteria) || 'Violation'}
               </div>
               <div class="p-2 bg-gray-100 dark:bg-gray-700/50 rounded text-gray-800 dark:text-gray-200">
                   <strong>0.0:</strong> ${(val.rubric && val.rubric.find(r => r.score === 0)?.criteria) || 'Neutral'}
               </div>
               <div class="p-2 bg-green-100 dark:bg-green-900/30 rounded text-green-800 dark:text-green-200">
                   <strong>1.0:</strong> ${(val.rubric && val.rubric.find(r => r.score > 0)?.criteria) || 'Perfect'}
               </div>
            </div>
        `;
        list.appendChild(card);
    });

    // Helpers attached to window for inline onclicks (scoped for safety?)
    // In modules, window globals are messy. Ideally we attach event listeners to buttons.
    // But since I'm regenerating HTML string, I'll stick to window helpers for now OR delegate.
    // Event delegation is cleaner. Let's try to clean this up later.
    // For now, I'll attach them to window in `ui-wizard-core.js` or here.
    // Since these need access to `agentData` which is local scope here...
    // I MUST re-attach definitions to window every time render is called with new agentData closure?
    // or use a closure-safe way.

    window.toggleEdit = (idx) => {
        const editDiv = document.getElementById(`wiz-val-edit-${idx}`);
        if (editDiv) editDiv.classList.toggle('hidden');
    };

    window.updateValueName = (idx, val) => { agentData.values[idx].name = val; };
    window.updateValueDesc = (idx, val) => { agentData.values[idx].description = val; };

    window.updateValueRubric = (idx, val) => {
        try {
            const parsed = JSON.parse(val);
            agentData.values[idx].rubric = parsed;
        } catch (e) {
            alert("Invalid JSON");
        }
    };

    window.removeValue = (idx) => {
        agentData.values.splice(idx, 1);
        renderValuesList(agentData);
    };
}

export function validateConscienceStep(agentData) {
    if (agentData.values.length === 0) {
        // Warning OK, but maybe optional? Let's require at least one for a good agent?
        // User might rely on Policy.
        // Let's allow empty if policy is set.
        // But for "Custom" agent usually you want values.
        // We'll trust the user.
    }
    return true;
}
