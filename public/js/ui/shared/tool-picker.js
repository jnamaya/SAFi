import * as api from '../../core/api.js';

// Shared tool-checklist renderer used by both the Agent wizard (Tools step)
// and the Policy wizard (Tools & Guardrails step). The canonical tool list
// comes from the backend registry via GET /api/agents/tools.

const CHECK_SVG = '<svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>';

/**
 * Fetch the backend tool categories. Returns an array of
 * { category, tools: [{ name, label, description, icon }] }, or null on error.
 */
export async function loadToolCategories() {
    try {
        const res = await api.fetchAvailableTools();
        if (res.ok && res.tools) return res.tools;
    } catch (e) {
        console.error('tool-picker: failed to load tools', e);
    }
    return null;
}

function cardClass(checked) {
    return 'relative flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ' + (checked
        ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-1 ring-blue-500'
        : 'border-gray-200 dark:border-neutral-700 hover:border-blue-300 dark:hover:border-blue-700');
}

function boxClass(checked) {
    return 'tp-box w-5 h-5 rounded border flex items-center justify-center transition-colors ' + (checked
        ? 'bg-blue-600 border-blue-600'
        : 'border-gray-400 bg-white dark:bg-neutral-800');
}

function officeNote() {
    return `
        <div class="mb-4 flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
            <svg class="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <p class="text-xs text-amber-800 dark:text-amber-300">These tools require a connected data source. Go to <strong>App Settings</strong> to connect before using them in a conversation.</p>
        </div>`;
}

// Build a single checkbox tool card. `afterToggle` (optional) runs after the
// selection state and card styling have updated — used to refresh badges.
function buildToolCard(tool, isSelected, onToggle, afterToggle) {
    const checked = isSelected(tool.name);
    const card = document.createElement('label');
    card.className = cardClass(checked);
    card.innerHTML = `
        <input type="checkbox" class="sr-only" value="${tool.name}" ${checked ? 'checked' : ''}>
        <div class="shrink-0 mt-1">
            <div class="${boxClass(checked)}">${checked ? CHECK_SVG : ''}</div>
        </div>
        <div>
            <div class="font-bold text-sm text-gray-900 dark:text-gray-100 flex items-center gap-2">
                ${tool.label || tool.name}
                ${tool.name === 'get_stock_price' ? '<span class="text-[10px] bg-green-100 text-green-800 px-1.5 rounded">Popular</span>' : ''}
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">${tool.description || ''}</p>
        </div>
    `;
    const input = card.querySelector('input');
    input.addEventListener('change', (e) => {
        const c = e.target.checked;
        onToggle(tool.name, c);
        card.className = cardClass(c);
        const box = card.querySelector('.tp-box');
        box.className = boxClass(c);
        box.innerHTML = c ? CHECK_SVG : '';
        if (afterToggle) afterToggle();
    });
    return card;
}

/**
 * Render category cards with checkbox tool cards into `container`.
 *
 * opts:
 *   categories  - array from loadToolCategories()
 *   isSelected  - (toolName) => boolean
 *   onToggle    - (toolName, checked) => void
 *   filter      - optional Set<string> of allowed tool names. Tools not in the
 *                 set are hidden; categories that end up empty are skipped.
 *   collapsible - when true, each category is a collapsible row with a
 *                 "selected / total" badge. Categories with a selection are
 *                 expanded on first render; the rest start collapsed.
 *
 * Returns the number of tool cards actually rendered.
 */
export function renderToolGrid(container, { categories, isSelected, onToggle, filter = null, collapsible = false }) {
    container.innerHTML = '';
    let rendered = 0;

    categories.forEach(cat => {
        const tools = filter ? cat.tools.filter(t => filter.has(t.name)) : cat.tools;
        if (tools.length === 0) return;
        rendered += tools.length;

        const isOffice = cat.category === 'Office & Productivity';

        if (collapsible) {
            renderCollapsibleCategory(container, cat, tools, { isSelected, onToggle, isOffice });
        } else {
            renderStaticCategory(container, cat, tools, { isSelected, onToggle, isOffice });
        }
    });

    return rendered;
}

function renderStaticCategory(container, cat, tools, { isSelected, onToggle, isOffice }) {
    const catDiv = document.createElement('div');
    catDiv.className = 'bg-white dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700';
    catDiv.innerHTML = `
        <h3 class="text-lg font-bold text-gray-900 dark:text-white mb-4 border-b border-gray-100 dark:border-neutral-700 pb-2">
            ${cat.category}
        </h3>
        ${isOffice ? officeNote() : ''}
        <div class="tp-grid grid grid-cols-1 md:grid-cols-2 gap-4"></div>
    `;
    const grid = catDiv.querySelector('.tp-grid');
    tools.forEach(tool => grid.appendChild(buildToolCard(tool, isSelected, onToggle)));
    container.appendChild(catDiv);
}

function renderCollapsibleCategory(container, cat, tools, { isSelected, onToggle, isOffice }) {
    const selectedCount = () => tools.filter(t => isSelected(t.name)).length;

    const catDiv = document.createElement('div');
    catDiv.className = 'bg-white dark:bg-neutral-800 rounded-xl border border-gray-200 dark:border-neutral-700 overflow-hidden';

    const startOpen = selectedCount() > 0;

    catDiv.innerHTML = `
        <button type="button" class="tp-cat-header w-full flex items-center justify-between gap-3 p-4 text-left hover:bg-gray-50 dark:hover:bg-neutral-700/40 transition-colors">
            <span class="flex items-center gap-2.5 min-w-0">
                <svg class="tp-chevron w-4 h-4 text-gray-400 shrink-0 transition-transform ${startOpen ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                <span class="font-bold text-gray-900 dark:text-white truncate">${cat.category}</span>
            </span>
            <span class="tp-badge shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full"></span>
        </button>
        <div class="tp-cat-body px-4 pb-4 ${startOpen ? '' : 'hidden'}">
            ${isOffice ? officeNote() : ''}
            <div class="tp-grid grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </div>
    `;

    const header = catDiv.querySelector('.tp-cat-header');
    const chevron = catDiv.querySelector('.tp-chevron');
    const body = catDiv.querySelector('.tp-cat-body');
    const badge = catDiv.querySelector('.tp-badge');
    const grid = catDiv.querySelector('.tp-grid');

    const updateBadge = () => {
        const n = selectedCount();
        const total = tools.length;
        const active = n > 0;
        badge.className = 'tp-badge shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ' + (active
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
            : 'bg-gray-100 text-gray-500 dark:bg-neutral-700 dark:text-gray-400');
        badge.innerHTML = `${n} / ${total}${active ? '<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>' : ''}`;
    };

    tools.forEach(tool => grid.appendChild(buildToolCard(tool, isSelected, onToggle, updateBadge)));
    updateBadge();

    header.addEventListener('click', () => {
        const open = body.classList.toggle('hidden') === false;
        chevron.classList.toggle('rotate-90', open);
    });

    container.appendChild(catDiv);
}
