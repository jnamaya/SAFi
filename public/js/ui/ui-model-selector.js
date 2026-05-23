let _models = [];
let _activeModelId = null;
let _onModelChange = null;

export function initModelSelector(models, activeModelId, onModelChange) {
    _models = models || [];
    _activeModelId = activeModelId || null;
    _onModelChange = onModelChange;
    _renderDropdown();
    _attachDropdownListener();
}

export function toggleModelDropdown() {
    document.getElementById('model-selector-dropdown')?.classList.toggle('hidden');
}

export function getActiveModelLabel() {
    const active = _models.find(m => m.id === _activeModelId);
    return active ? _label(active) : null;
}

export function setActiveModel(modelId) {
    _activeModelId = modelId;
    _renderDropdown();
}

function _label(model) {
    return model.label || model.name || model.id;
}

function _renderDropdown() {
    const dropdown = document.getElementById('model-selector-dropdown');
    if (!dropdown) return;
    dropdown.innerHTML = _models.map(m => {
        const isActive = m.id === _activeModelId;
        return `<button type="button" data-model-id="${m.id}"
            class="model-option w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors
                ${isActive
                    ? 'bg-neutral-100 dark:bg-neutral-800 text-neutral-900 dark:text-white font-medium'
                    : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-white'}">
            <span class="truncate">${_label(m)}</span>
            ${isActive ? `<svg class="w-4 h-4 shrink-0 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
            </svg>` : ''}
        </button>`;
    }).join('');
}

function _attachDropdownListener() {
    const dropdown = document.getElementById('model-selector-dropdown');
    if (!dropdown) return;

    dropdown.addEventListener('click', e => {
        const option = e.target.closest('.model-option');
        if (!option) return;
        const modelId = option.dataset.modelId;
        if (modelId && modelId !== _activeModelId) {
            _activeModelId = modelId;
            _renderDropdown();
            dropdown.classList.add('hidden');
            if (_onModelChange) _onModelChange(modelId);
        }
    });
}
