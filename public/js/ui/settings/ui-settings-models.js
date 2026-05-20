import * as ui from '../ui.js';

/**
 * Renders the AI Model selection tab in the Control Panel.
 * @param {Array} availableModels - List of model name strings OR objects {id, label, categories}
 * @param {object} user - The current user object (to get selections)
 * @param {Function} onModelsSave - Callback function when save is clicked
 */
export function renderSettingsModelsTab(availableModels, user, onModelsSave) {
    ui._ensureElements();
    const container = ui.elements.cpTabModels;
    if (!container) return;

    // Filter the available models based on categories
    // We handle backward compatibility: if no 'categories' field exists, include it.
    const intellectModels = availableModels.filter(m => {
        if (typeof m === 'string') return true; // Legacy support
        return !m.categories || m.categories.includes('intellect');
    });

    // Helper function to create a single <select> dropdown with a custom list of options
    const createSelect = (id, label, selectedValue, modelsList) => `
        <div>
            <label for="${id}" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">${label}</label>
            <select id="${id}" class="settings-modal-select">
                ${modelsList.map(model => {
        // Handle both old format (string) and new format (object)
        const modelId = model.id || model;
        const modelLabel = model.label || model;

        return `
                    <option value="${modelId}" ${modelId === selectedValue ? 'selected' : ''}>
                        ${modelLabel}
                    </option>
                    `;
    }).join('')}
            </select>
        </div>
    `;

    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose an AI Model</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Select the AI model used to generate responses. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'AI Model', user.intellect_model, intellectModels)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-black text-white hover:bg-gray-800 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    // Attach event listener for the save button
    document.getElementById('save-models-btn').addEventListener('click', () => {
        const newModels = {
            intellect_model: document.getElementById('model-select-intellect').value,
        };
        onModelsSave(newModels);
    });
}
