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
    // We handle backward compatibility: if no 'categories' field exists, include it in both lists.
    const intellectModels = availableModels.filter(m => {
        if (typeof m === 'string') return true; // Legacy support
        return !m.categories || m.categories.includes('intellect');
    });

    const supportModels = availableModels.filter(m => {
        if (typeof m === 'string') return true; // Legacy support
        return !m.categories || m.categories.includes('support');
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

    // Generate the HTML for the model selectors
    // We pass different filtered lists to each selector
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose AI Models</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Assign a specific AI model to each of the three faculties. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'Intellect (Generation)', user.intellect_model, intellectModels)}
            ${createSelect('model-select-will', 'Will (Gatekeeping)', user.will_model, supportModels)}
            ${createSelect('model-select-conscience', 'Conscience (Auditing)', user.conscience_model, supportModels)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    // Attach event listener for the save button
    document.getElementById('save-models-btn').addEventListener('click', () => {
        const newModels = {
            intellect_model: document.getElementById('model-select-intellect').value,
            will_model: document.getElementById('model-select-will').value,
            conscience_model: document.getElementById('model-select-conscience').value,
        };
        onModelsSave(newModels);
    });
}
