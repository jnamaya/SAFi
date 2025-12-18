import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export async function renderKnowledgeStep(container, agentData) {
    container.innerHTML = `
        <h2 class="text-2xl font-bold mb-4 text-gray-900 dark:text-white">Capabilities & Tools</h2>
        <p class="text-gray-500 mb-6">Select the tools and data sources this agent can access.</p>
        
        <div id="wiz-tools-loading" class="flex items-center gap-2 text-gray-500">
            <span class="thinking-spinner w-4 h-4"></span> Loading tools...
        </div>

        <div id="wiz-tools-container" class="grid grid-cols-1 gap-6 hidden">
            <!-- Tools injected here -->
        </div>
    `;

    try {
        const res = await api.fetchAvailableTools();
        if (res.ok && res.tools) {
            renderToolsList(res.tools, agentData);
        } else {
            document.getElementById('wiz-tools-loading').innerText = "Failed to load tools.";
        }
    } catch (e) {
        console.error("Tools Fetch Error", e);
        document.getElementById('wiz-tools-loading').innerText = "Error loading tools.";
    }
}

function renderToolsList(categories, agentData) {
    const container = document.getElementById('wiz-tools-container');
    const loader = document.getElementById('wiz-tools-loading');

    if (!container) return;
    loader.classList.add('hidden');
    container.classList.remove('hidden');

    // Ensure agentData.tools is initialized
    if (!agentData.tools) agentData.tools = [];

    categories.forEach(cat => {
        const catDiv = document.createElement('div');
        catDiv.className = "bg-white dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700";

        catDiv.innerHTML = `
            <h3 class="text-lg font-bold text-gray-900 dark:text-white mb-4 border-b border-gray-100 dark:border-neutral-700 pb-2">
                ${cat.category}
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4" id="cat-grid-${cat.category.replace(/\s+/g, '-')}">
            </div>
        `;

        const grid = catDiv.querySelector('div[id^="cat-grid"]');

        cat.tools.forEach(tool => {
            const isChecked = agentData.tools.includes(tool.name);
            const toolCard = document.createElement('label');
            toolCard.className = `
                relative flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all
                ${isChecked
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-1 ring-blue-500'
                    : 'border-gray-200 dark:border-neutral-700 hover:border-blue-300 dark:hover:border-blue-700'}
            `;

            toolCard.innerHTML = `
                <input type="checkbox" class="sr-only" value="${tool.name}" ${isChecked ? 'checked' : ''}>
                <div class="shrink-0 mt-1">
                    <div class="w-5 h-5 rounded border ${isChecked ? 'bg-blue-600 border-blue-600' : 'border-gray-400 bg-white dark:bg-neutral-800'} flex items-center justify-center transition-colors">
                        ${isChecked ? '<svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>' : ''}
                    </div>
                </div>
                <div>
                    <div class="font-bold text-sm text-gray-900 dark:text-gray-100 flex items-center gap-2">
                        ${tool.label || tool.name}
                        ${tool.name === 'get_stock_price' ? '<span class="text-[10px] bg-green-100 text-green-800 px-1.5 rounded">Popular</span>' : ''}
                    </div>
                    <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">${tool.description}</p>
                </div>
            `;

            // Bind Event
            const input = toolCard.querySelector('input');
            input.addEventListener('change', (e) => {
                const checked = e.target.checked;
                if (checked) {
                    if (!agentData.tools.includes(tool.name)) agentData.tools.push(tool.name);
                } else {
                    agentData.tools = agentData.tools.filter(t => t !== tool.name);
                }
                // Re-render card style
                // Simplest way is to just toggle classes manually or re-render. 
                // Let's toggle classes for performance.
                if (checked) {
                    toolCard.className = 'relative flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-1 ring-blue-500';
                    toolCard.querySelector('.w-5').className = 'w-5 h-5 rounded border bg-blue-600 border-blue-600 flex items-center justify-center transition-colors';
                    toolCard.querySelector('.w-5').innerHTML = '<svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>';
                } else {
                    toolCard.className = 'relative flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all border-gray-200 dark:border-neutral-700 hover:border-blue-300 dark:hover:border-blue-700';
                    toolCard.querySelector('.w-5').className = 'w-5 h-5 rounded border border-gray-400 bg-white dark:bg-neutral-800 flex items-center justify-center transition-colors';
                    toolCard.querySelector('.w-5').innerHTML = '';
                }
                console.log("Agent Tools:", agentData.tools);
            });

            grid.appendChild(toolCard);
        });

        container.appendChild(catDiv);
    });
}

export function validateKnowledgeStep(agentData) {
    // Tools are optional
    return true;
}
