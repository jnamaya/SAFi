import * as api from '../../core/api.js';
import * as ui from './../ui.js';
import { escapeHtml } from '../../core/utils.js';

export function renderIntellectStep(container, agentData) {
    container.innerHTML = `
        <div class="mb-4">
            <h2 class="text-2xl font-bold mb-2 text-gray-900 dark:text-white">Role &amp; Style</h2>
            <p class="text-gray-500 text-sm">What is this agent for, and how should it speak?</p>
        </div>
        
        <div class="space-y-6">
            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">System Instructions</label>
                        <p class="text-xs text-gray-400">Write it to the agent: "You are…". Say what it does, who it serves, and where its job ends.</p>
                    </div>
                     <button id="wiz-gen-persona-btn" class="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-instructions" class="w-full h-64 p-4 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-base text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500 resize-y" placeholder="You are an HR assistant for your company's employees. You answer questions about benefits, PTO and onboarding using the company handbook, and you refer anything legal or medical to a person.">${escapeHtml(agentData.instructions)}</textarea>
            </div>

            <div>
                <div class="flex justify-between items-end mb-2">
                    <div>
                        <label class="block text-sm font-bold text-gray-700 dark:text-gray-300">Communication Style</label>
                        <p class="text-xs text-gray-400">How should they speak? (e.g., Formal, Socratic, Concise)</p>
                    </div>
                    <button id="wiz-gen-style-btn" class="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded-full flex items-center gap-1 transition-colors shadow-sm">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Draft with AI
                    </button>
                </div>
                <textarea id="wiz-style" class="w-full h-40 p-4 rounded-xl border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 font-mono text-base text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500 resize-y" placeholder="Speak in short, punchy sentences. Use metaphors from nature. Never use emojis.">${escapeHtml(agentData.style)}</textarea>
            </div>
        </div>
    `;

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
                ui.showToast("Instructions drafted!", "success");
            } else {
                ui.showToast("Could not draft the instructions", "error");
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
