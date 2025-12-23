import * as api from '../../core/api.js';
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
                <textarea id="wiz-instructions" class="w-full h-64 p-4 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-base text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500 resize-y" placeholder="You are a Stoic philosopher. You view the world through the dichotomy of control...">${agentData.instructions}</textarea>
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
                <textarea id="wiz-style" class="w-full h-40 p-4 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-base text-gray-900 dark:text-white focus:ring-2 focus:ring-purple-500 resize-y" placeholder="Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.">${agentData.style}</textarea>
            </div>
            
            <!-- Capabilities removed as requested -->
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

    // Capabilities / Tools
    _renderToolSelector(agentData);
}

async function _renderToolSelector(agentData) {
    const container = document.getElementById('intellect-tools-container');
    if (!container) return; // Should exist if HTML updated

    try {
        const res = await api.fetchAvailableTools();
        // mcp_manager returns list of categories, containing tools
        // We want to find "Office & Productivity" or just flatten

        let tools = [];
        if (res && Array.isArray(res)) {
            // Flatten categories
            res.forEach(cat => {
                if (cat.tools) tools.push(...cat.tools);
            });
        }

        // Use defined capabilities "google_drive" and "sharepoint"
        // Filter for specific ones we support toggling
        const supported = ['google_drive', 'sharepoint'];
        const displayTools = tools.filter(t => supported.includes(t.name));

        if (displayTools.length === 0) {
            container.innerHTML = `<p class="text-xs text-gray-500">No external tools available.</p>`;
            return;
        }

        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                ${displayTools.map(t => {
            const isChecked = agentData.tools && agentData.tools.includes(t.name);

            // --- CUSTOM: GitHub Connect Button ---
            let extraAction = '';
            if (t.name === 'github') {
                extraAction = `
                    <div class="mt-2 pt-2 border-t border-gray-100 dark:border-neutral-700">
                        <a href="/api/auth/github/login" target="_blank" class="inline-flex items-center gap-1 text-[10px] font-semibold text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200 uppercase tracking-wider transition-colors">
                            <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
                            Connect Account
                        </a>
                    </div>
                `;
            }

            return `
                    <label class="flex items-start gap-3 p-3 bg-white dark:bg-neutral-800 border ${isChecked ? 'border-purple-500 bg-purple-50 dark:bg-purple-900/10' : 'border-gray-200 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-purple-400 transition-colors group relative">
                        <div class="mt-0.5">
                            <input type="checkbox" value="${t.name}" class="w-4 h-4 text-purple-600 rounded focus:ring-purple-500" ${isChecked ? 'checked' : ''}>
                        </div>
                        <div class="flex-1">
                            <div class="font-bold text-sm text-gray-900 dark:text-gray-100 flex items-center gap-2">
                                ${t.label || t.name}
                                ${t.icon === 'cloud' ? '<svg class="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" /></svg>' : ''}
                                ${t.icon === 'office-building' ? '<svg class="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>' : ''}
                                ${t.icon === 'code' ? '<svg class="w-4 h-4 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" /></svg>' : ''}
                            </div>
                            <div class="text-xs text-gray-500 dark:text-gray-400 leading-snug mt-0.5">${t.description}</div>
                            ${extraAction}
                        </div>
                    </label>
                    `;
        }).join('')}
            </div>
            <p class="text-xs text-gray-400 mt-2">
                <span class="font-bold">Note:</span> Enabling a tool grants the agent access to data from that connected account.
            </p>
        `;

        // Bind events
        container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const val = e.target.value;
                if (!agentData.tools) agentData.tools = [];

                if (e.target.checked) {
                    if (!agentData.tools.includes(val)) agentData.tools.push(val);
                    e.target.closest('label').classList.add('border-purple-500', 'bg-purple-50', 'dark:bg-purple-900/10');
                    e.target.closest('label').classList.remove('border-gray-200', 'dark:border-neutral-700');
                } else {
                    agentData.tools = agentData.tools.filter(t => t !== val);
                    e.target.closest('label').classList.remove('border-purple-500', 'bg-purple-50', 'dark:bg-purple-900/10');
                    e.target.closest('label').classList.add('border-gray-200', 'dark:border-neutral-700');
                }
            });
        });

    } catch (e) {
        console.error("Error loading tools", e);
        container.innerHTML = `<div class="text-red-500 text-xs">Failed to load capabilities.</div>`;
    }
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
