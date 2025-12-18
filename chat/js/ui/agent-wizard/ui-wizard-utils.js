export let availableModelsCache = [];

export function setAvailableModels(models) {
    availableModelsCache = models || [];
}

export function renderModelSelector(id, currentValue, category, passedModels = null) {
    const models = passedModels || availableModelsCache;
    // console.log(`[Wizard] Rendering selector ${id} cat ${category}. Available:`, models.length);

    const filteredModels = models.filter(m => {
        if (typeof m === 'string') return true;
        return !m.categories || m.categories.includes(category);
    });

    if (filteredModels.length === 0) {
        // Fallback
        return `<input type="text" id="${id}" class="p-1 text-sm border-b border-gray-300 dark:border-neutral-700 bg-transparent focus:ring-0 w-32" placeholder="Default" value="${currentValue}">`;
    }

    return `
        <select id="${id}" class="p-1 text-xs border border-gray-300 dark:border-neutral-700 rounded bg-white dark:bg-neutral-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 w-40">
            <option value="">Default (System)</option>
            ${filteredModels.map(m => {
        const val = m.id || m;
        const label = m.label || m;
        return `<option value="${val}" ${val === currentValue ? 'selected' : ''}>${label}</option>`;
    }).join('')}
        </select>
    `;
}
