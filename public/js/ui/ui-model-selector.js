import { closeComposerMenu } from './ui-composer-menu.js';
import { escapeHtml } from '../core/utils.js';

let _models = [];
let _activeModelId = null;
let _onModelChange = null;
let _publicDemoUi = false;

function _resolveModel(modelId) {
    if (!Array.isArray(_models) || _models.length === 0) return null;
    let found = _models.find(m => m.id === modelId);
    if (found) return found;
    found = _models.find(m => m.alias === modelId || (Array.isArray(m.aliases) && m.aliases.includes(modelId)));
    if (found) return found;
    found = _models.find(m => m.active);
    if (found) return found;
    return _models[0] || null;
}

export function initModelSelector(models, activeModelId, onModelChange, publicDemoUi = false) {
    _models = models || [];
    const resolved = _resolveModel(activeModelId);
    _activeModelId = resolved ? resolved.id : null;
    _onModelChange = onModelChange;
    _publicDemoUi = !!publicDemoUi;
    _renderDropdown();
    _attachDropdownListener();
}

export function isPublicDemoUi() {
    return _publicDemoUi;
}

export function getActiveModelLabel() {
    const active = _resolveModel(_activeModelId);
    return active ? _label(active) : null;
}

export function getActiveModel() {
    return _resolveModel(_activeModelId);
}

export function markModelActive(modelId) {
    let changed = false;
    for (const m of _models) {
        if (m.provider === 'local' || m.local) {
            const shouldBeActive = (m.id === modelId || m.alias === modelId);
            if (m.active !== shouldBeActive) {
                m.active = shouldBeActive;
                changed = true;
            }
        }
    }
    if (changed) _renderDropdown();
}

export function setActiveModel(modelId) {
    const resolved = _resolveModel(modelId);
    _activeModelId = resolved ? resolved.id : null;
    _renderDropdown();
}

function _label(model) {
    return model.label || model.name || model.id;
}

function _renderDropdown() {
    const dropdown = document.getElementById('model-selector-dropdown');
    if (!dropdown) return;
    const groups = [];
    const byLabel = new Map();
    for (const m of _models) {
        const label = m.provider_label || m.provider || '';
        let g = byLabel.get(label);
        if (!g) { g = { label, models: [] }; byLabel.set(label, g); groups.push(g); }
        g.models.push(m);
    }
    const showCaptions = groups.length > 1;

    dropdown.innerHTML = groups.map((g, gi) => {
        const caption = showCaptions
            ? `<div class="px-3 ${gi === 0 ? 'pt-1' : 'pt-3'} pb-1 text-[10px] font-bold uppercase tracking-wider text-neutral-400 dark:text-neutral-500 select-none">${escapeHtml(g.label)}</div>`
            : '';
        const rows = g.models.map(m => {
            const isActive = m.id === _activeModelId;
            return `<button type="button" role="menuitemradio" aria-checked="${isActive}" data-model-id="${escapeHtml(m.id)}"
                class="model-option w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors
                    ${isActive
                        ? 'bg-neutral-50 dark:bg-neutral-800 font-medium text-green-600 dark:text-green-500'
                        : 'text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'}">
                <span class="truncate">${escapeHtml(_label(m))}</span>
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
