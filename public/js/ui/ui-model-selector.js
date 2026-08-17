import { closeComposerMenu } from './ui-composer-menu.js';

let _models = [];
let _activeModelId = null;
let _onModelChange = null;
// True only on the public demo. It used to gate a paragraph of showcase copy
// inside this dropdown (removed 2026-08-11 — the menu explains itself); its
// remaining consumer is ui-messages.js, which stamps the model name onto demo
// messages. Inside a customer deployment both are noise.
let _publicDemoUi = false;

export function initModelSelector(models, activeModelId, onModelChange, publicDemoUi = false) {
    _models = models || [];
    _activeModelId = activeModelId || null;
    _onModelChange = onModelChange;
    _publicDemoUi = !!publicDemoUi;
    _renderDropdown();
    _attachDropdownListener();
}

export function isPublicDemoUi() {
    return _publicDemoUi;
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
    // No header: this list is a section of the + panel, which prints
    // "AI Models" above it. Rows are grouped under small provider captions
    // (the /models endpoint ships provider_label), because a flat list of
    // eleven ids from seven vendors reads as soup. With a single provider
    // configured the caption is skipped — one group needs no label.
    const groups = [];
    for (const m of _models) {
        const label = m.provider_label || m.provider || '';
        const last = groups[groups.length - 1];
        if (last && last.label === label) last.models.push(m);
        else groups.push({ label, models: [m] });
    }
    const showCaptions = groups.length > 1;

    dropdown.innerHTML = groups.map((g, gi) => {
        const caption = showCaptions
            ? `<div class="px-3 ${gi === 0 ? 'pt-1' : 'pt-3'} pb-1 text-[10px] font-bold uppercase tracking-wider text-neutral-400 dark:text-neutral-500 select-none">${g.label}</div>`
            : '';
        const rows = g.models.map(m => {
            const isActive = m.id === _activeModelId;
            return `<button type="button" role="menuitemradio" aria-checked="${isActive}" data-model-id="${m.id}"
                class="model-option w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors
                    ${isActive
                        ? 'bg-neutral-50 dark:bg-neutral-800 font-medium text-green-600 dark:text-green-500'
                        : 'text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'}">
                <span class="truncate">${_label(m)}</span>
                ${isActive ? `<svg class="w-4 h-4 shrink-0 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>` : ''}
            </button>`;
        }).join('');
        return caption + rows;
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
            closeComposerMenu();
            if (_onModelChange) _onModelChange(modelId);
        }
    });
}
