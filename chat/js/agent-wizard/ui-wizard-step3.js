import * as api from './../api.js';
import * as ui from './../ui.js';
import { renderModelSelector } from './ui-wizard-utils.js';

export function renderIntellectStep(container, agentData, availableModels) {
    // Model Selector Helper is now imported/passed or we can redefine it/helper it.
    // If I move renderModelSelector to Core, I need to make sure Core exports it.
    // OR I can implement it here.
    // Let's rely on Core exporting it, or just pass it in.
    // Actually, `ui-wizard-core.js` isn't created yet so I can't import from it easily without creating it first if using browser modules?
    // But since I'm writing files, I can assume Core exists.

    container.innerHTML = `
        <div class="flex justify-between items-start mb-4">
             <div>
                <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Intellect & Style</h2>
                <p class="text-gray-500 text-sm mb-4">How does this agent think and speak?</p>
             </div>
             <div>
                <label class="block text-xs font-bold text-gray-500 uppercase mb-1">AI Model</label>
                <!-- Placeholder for Model Selector, populated via JS helper or direct HTML if passed -->
                <div id="intellect-model-container"></div>
            </div>
        </div>
        
        <div class="space-y-6">
            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">System Instructions / Persona</label>
                        <p class="text-xs text-gray-400">TIPS: Use "You are..." statements. Describe their core philosophy.</p>
                    </div>
                     <button id="wiz-gen-persona-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-instructions" class="w-full h-40 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="You are a Stoic philosopher. You view the world through the dichotomy of control...">${agentData.instructions}</textarea>
            </div>

            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Communication Style</label>
                        <p class="text-xs text-gray-400">How should they speak? (e.g., Formal, Socratic, Concise)</p>
                    </div>
                    <button id="wiz-gen-style-btn" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-style" class="w-full h-24 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500" placeholder="Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.">${agentData.style}</textarea>
            </div>
        </div>
    `;

    // Inject Model Selector
    const modelContainer = document.getElementById('intellect-model-container');
    if (modelContainer) {
        modelContainer.innerHTML = renderModelSelector('wiz-intellect-model', agentData.intellect_model || '', 'intellect', availableModels);
        // Bind change event manually since it's injected
        document.getElementById('wiz-intellect-model')?.addEventListener('change', (e) => agentData.intellect_model = e.target.value);
    }

    // Attach Text Listeners
    document.getElementById('wiz-instructions')?.addEventListener('input', (e) => agentData.instructions = e.target.value);
    document.getElementById('wiz-style')?.addEventListener('input', (e) => agentData.style = e.target.value);

    // AI Handlers
    attachAiHandlers(agentData);
}

function attachAiHandlers(agentData) {
    // AI PERSONA HANDLER
    document.getElementById('wiz-gen-persona-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Drafting...`;
        btn.disabled = true;

        try {
            const context = agentData.description || "A helpful AI assistant";
            const res = await api.generatePolicyContent('persona', context, { name: agentData.name });

            if (res.ok && res.content) {
                const instructions = res.content;
                document.getElementById('wiz-instructions').value = instructions;
                agentData.instructions = instructions;
                ui.showToast("Persona generated!", "success");
            } else {
                ui.showToast("Failed to generate persona", "error");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("Generation error", "error");
        } finally {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    });

    // AI STYLE HANDLER
    document.getElementById('wiz-gen-style-btn').addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block mr-1"></span> Drafting...`;
        btn.disabled = true;

        try {
            const context = agentData.instructions || agentData.description || "A helpful AI assistant";
            const res = await api.generatePolicyContent('style', context, { name: agentData.name });

            if (res.ok && res.content) {
                document.getElementById('wiz-style').value = res.content;
                agentData.style = res.content;
                ui.showToast("Style generated!", "success");
            } else {
                ui.showToast("Failed to generate style", "error");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("Generation error", "error");
        } finally {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    });
}

export function validateIntellectStep(agentData) {
    if (!agentData.instructions || !agentData.instructions.trim()) {
        alert("System instructions are required.");
        return false;
    }
    return true;
}
