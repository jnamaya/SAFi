/**
 * Import an existing governance document.
 *
 * Serves both tiers, because they take different documents. An organization has
 * ONE AI policy, and it belongs on the Charter where it binds every agent;
 * business units have their own procedures and compliance manuals, and those
 * belong on a policy. Uploading the org-wide AI policy into a business-unit
 * policy is the mistake this card exists to make hard — hence the pointer in
 * each card to where the other kind of document goes.
 *
 * Two passes, deliberately separate. The first classifies every clause; the
 * second compiles only the ones needing judgment into rubrics. Combining them
 * is what makes a model write a scoring rubric for "the committee meets
 * monthly" — measured against a real 15-page corporate AI policy, roughly
 * three-quarters of it governs people and processes, not responses.
 *
 * Nothing is applied without the author ticking it. What the classifier
 * produces is a proposal about how their organization will be governed, and the
 * choice between a literal check and a model-judged standard has consequences
 * they should see before it is live.
 *
 * The "not converted" list is shown at the same weight as the rest. It is not
 * an apology — it tells the author exactly which obligations from their policy
 * SAFi does not cover and still need a human process.
 *
 * The caller owns where accepted material lands: this module produces the
 * selection and the compiled gates, then hands them to `onApply`. Keeping the
 * target out of here is what lets the Charter and the wizard share one flow
 * without either inheriting the other's field names.
 */
import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';

// Matches Config.ALLOWED_UPLOAD_EXTENSIONS. Advisory only — the server
// re-validates, since a file picker filter is trivially bypassed.
const ACCEPTED = '.pdf,.docx,.txt,.md,.csv,.xlsx';

let result = null;      // last classification
let sourceName = '';    // filename, kept for provenance in the review panel
let config = null;      // { context, onApply, onApplied }

/**
 * @param {object} opts
 * @param {string} opts.title     card heading
 * @param {string} opts.subtitle  one line under it
 * @param {string} [opts.hint]    where the OTHER kind of document belongs
 */
export function renderImportCard({ title, subtitle, hint }) {
    return `
    <div class="bg-white dark:bg-neutral-900 border border-purple-200 dark:border-purple-900/40 rounded-xl p-5">
        <div class="flex items-start gap-3">
            <svg class="w-6 h-6 text-purple-600 dark:text-purple-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
            <div class="min-w-0">
                <h4 class="font-bold text-gray-900 dark:text-white">${escapeHtml(title)}</h4>
                <p class="text-xs text-gray-500 mt-0.5">${subtitle}</p>
            </div>
        </div>
        <input type="file" id="pw-import-file" accept="${ACCEPTED}" class="hidden">
        <button id="pw-import-btn" class="mt-4 w-full px-4 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-400 text-white rounded-lg text-sm font-semibold transition-colors">
            Choose a document
        </button>
        ${hint ? `<p class="text-xs text-gray-400 mt-2">${hint}</p>` : ''}
        <div id="pw-import-result" class="mt-4 hidden"></div>
    </div>`;
}

/**
 * @param {object} opts
 * @param {() => string} opts.context   description of what is being governed
 * @param {(payload) => string[]} opts.onApply
 *        Receives { structural, blacklist, gates, suggested, definitions } and
 *        writes them wherever they belong. Returns human-readable descriptions
 *        of what it applied, for the summary. Runs only after every step that
 *        could fail has already succeeded.
 * @param {() => void} [opts.onApplied] called after a successful apply
 */
export function bindImportCard(opts) {
    config = opts;
    bindPicker();
}

function bindPicker() {
    const btn = document.getElementById('pw-import-btn');
    const input = document.getElementById('pw-import-file');
    if (!btn || !input) return;

    btn.addEventListener('click', () => input.click());
    input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        input.value = '';                     // let the same file be retried

        const original = btn.innerHTML;
        btn.disabled = true;
        try {
            btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Reading ${escapeHtml(file.name)}...`;
            const extracted = await api.extractDocumentText(file);
            const text = (extracted && extracted.text || '').trim();
            if (!text) throw new Error('No readable text found in that file.');

            btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Reading the policy...`;
            const res = await api.generatePolicyContent(
                'classify_document', config.context() || 'General organization',
                { document_text: text });
            if (!res.ok) throw new Error(res.error || 'Could not read that policy.');

            result = res.content || {};
            sourceName = file.name;
            renderReview();
        } catch (e) {
            console.error('policy wizard: document import failed', e);
            ui.showToast(e.message || 'Could not import that document.', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = original;
        }
    });
}

// Full class strings, never interpolated fragments: Tailwind's JIT scans the
// source for complete class names, so `text-${colour}-800` would compile to
// nothing and the heading would render unstyled.
const HEADING_CLASS = {
    blue:  'text-blue-800 dark:text-blue-200',
    amber: 'text-amber-800 dark:text-amber-200',
    gray:  'text-gray-800 dark:text-gray-100',
};

function section(title, subtitle, colour, bodyHtml, count) {
    return `
    <div class="mt-4">
        <div class="flex items-baseline gap-2">
            <h5 class="text-sm font-bold ${HEADING_CLASS[colour] || HEADING_CLASS.gray}">${title}</h5>
            <span class="text-xs text-gray-400">${count}</span>
        </div>
        <p class="text-xs text-gray-500 mt-0.5 mb-2">${subtitle}</p>
        ${bodyHtml}
    </div>`;
}

function clauseLine(text) {
    return `<p class="text-[11px] text-gray-400 italic mt-1 break-words">&ldquo;${escapeHtml(text)}&rdquo;</p>`;
}

function renderReview() {
    const panel = document.getElementById('pw-import-result');
    if (!panel) return;

    const structural = result.structural || [];
    const blacklist = result.blacklist || [];
    const values = result.values || [];
    const unconvertible = result.unconvertible || [];
    const notes = result.notes || [];
    const definitions = result.definitions || [];

    if (!structural.length && !blacklist.length && !values.length) {
        panel.classList.remove('hidden');
        panel.innerHTML = `
            <div class="p-4 rounded-xl border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10">
                <p class="text-sm text-amber-800 dark:text-amber-200 font-semibold">Nothing in this document constrains an agent's answers.</p>
                <p class="text-xs text-amber-700 dark:text-amber-300 mt-1">
                    ${unconvertible.length} clause${unconvertible.length === 1 ? '' : 's'} were read and all govern people or processes &mdash;
                    approvals, training, committees. That is normal for an AI use policy: they govern how staff use AI tools,
                    while SAFi governs what an agent says. You'll need to write the standards yourself in the next steps.
                </p>
            </div>`;
        return;
    }

    const structuralHtml = structural.map((s, i) => `
        <label class="flex items-start gap-3 p-3 rounded-lg border border-blue-200 dark:border-blue-900/40 bg-blue-50/50 dark:bg-blue-900/10 cursor-pointer">
            <input type="checkbox" data-imp-struct="${i}" checked class="mt-1 accent-blue-600 w-4 h-4 shrink-0">
            <div class="min-w-0">
                <p class="text-sm font-medium text-gray-900 dark:text-white">Require this on every response</p>
                <p class="text-sm text-blue-800 dark:text-blue-200 mt-1 font-mono break-words">${escapeHtml(s.disclaimer_text)}</p>
                ${clauseLine(s.text)}
            </div>
        </label>`).join('');

    const blacklistHtml = blacklist.map((b, i) => `
        <label class="flex items-start gap-3 p-3 rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10 cursor-pointer">
            <input type="checkbox" data-imp-black="${i}" checked class="mt-1 accent-amber-600 w-4 h-4 shrink-0">
            <div class="min-w-0">
                <p class="text-sm font-mono text-gray-900 dark:text-white break-words">${escapeHtml(b.phrase)}</p>
                ${clauseLine(b.text)}
            </div>
        </label>`).join('');

    const valuesHtml = values.map((v, i) => `
        <label class="flex items-start gap-3 p-3 rounded-lg border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 cursor-pointer">
            <input type="checkbox" data-imp-value="${i}" checked class="mt-1 accent-green-600 w-4 h-4 shrink-0">
            <div class="min-w-0">
                <p class="text-sm text-gray-900 dark:text-white break-words">${escapeHtml(v.text)}</p>
                <p class="text-xs text-gray-500 mt-1">${escapeHtml(v.reason)}</p>
            </div>
        </label>`).join('');

    const unconvertibleHtml = unconvertible.length ? `
        <details class="mt-4 p-4 rounded-xl border border-gray-200 dark:border-neutral-700">
            <summary class="cursor-pointer text-sm font-bold text-gray-700 dark:text-gray-200">
                Not converted (${unconvertible.length})
            </summary>
            <p class="text-xs text-gray-500 mt-2 mb-3">
                These govern people or processes rather than what an agent says, so there is nothing in a response to check them against.
                <strong>They still apply to your organization</strong> &mdash; SAFi just isn't the thing that enforces them.
            </p>
            <ul class="space-y-2">
                ${unconvertible.map(u => `
                    <li class="text-xs">
                        <span class="text-gray-700 dark:text-gray-200 break-words">&ldquo;${escapeHtml(u.text)}&rdquo;</span>
                        <span class="block text-gray-500 mt-0.5">${escapeHtml(u.reason)}</span>
                    </li>`).join('')}
            </ul>
        </details>` : '';

    const notesHtml = notes.length ? `
        <div class="mt-4 p-4 rounded-xl border border-indigo-200 dark:border-indigo-900/40 bg-indigo-50 dark:bg-indigo-900/10">
            <h5 class="text-sm font-bold text-indigo-800 dark:text-indigo-200 mb-1">Worth knowing</h5>
            <ul class="text-xs text-indigo-700 dark:text-indigo-300 space-y-1 list-disc pl-4">
                ${notes.map(n => `<li>${escapeHtml(n)}</li>`).join('')}
            </ul>
        </div>` : '';

    panel.classList.remove('hidden');
    panel.innerHTML = `
        <div class="border-t border-gray-200 dark:border-neutral-700 pt-4">
            <p class="text-xs text-gray-500 mb-1">From <strong>${escapeHtml(sourceName)}</strong>${definitions.length ? ` &middot; ${definitions.length} definition${definitions.length === 1 ? '' : 's'} found and used to sharpen the standards` : ''}</p>
            ${structural.length ? section('Checked literally', 'Enforced by matching the text itself. No AI judgement involved.', 'blue', structuralHtml, structural.length) : ''}
            ${blacklist.length ? section('Blocked phrases', 'Checked against every message before the agent runs.', 'amber', blacklistHtml, blacklist.length) : ''}
            ${values.length ? section('Scored standards', 'These need judgement, so the auditor model scores each response against them. Rubrics are written when you apply.', 'gray', valuesHtml, values.length) : ''}
            ${notesHtml}
            ${unconvertibleHtml}
            <button id="pw-import-apply" class="mt-4 w-full px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition-colors">
                Apply selected
            </button>
        </div>`;

    document.getElementById('pw-import-apply')?.addEventListener('click', () => applySelected());
}

async function applySelected() {
    const panel = document.getElementById('pw-import-result');
    const btn = document.getElementById('pw-import-apply');
    if (!panel || !btn) return;

    // Read the index off the attribute directly. Deriving the dataset key from
    // the attribute name works but breaks silently the moment an attribute is
    // renamed, and a silent break here applies the wrong clauses.
    const picked = (attr, arr) => Array.from(panel.querySelectorAll(`input[${attr}]:checked`))
        .map(cb => arr[Number(cb.getAttribute(attr))])
        .filter(Boolean);

    const structural = picked('data-imp-struct', result.structural || []);
    const blacklist = picked('data-imp-black', result.blacklist || []);
    const values = picked('data-imp-value', result.values || []);

    if (!structural.length && !blacklist.length && !values.length) {
        ui.showToast('Nothing selected.', 'error');
        return;
    }

    btn.disabled = true;
    const original = btn.innerHTML;
    showApplyError('');

    // Everything that can fail runs BEFORE anything is written to the target.
    // The first version applied the disclaimer, then called the model, and left
    // the disclaimer applied when that call failed — the author was told it had
    // failed while a setting had in fact changed underneath them.
    let gates = [];
    let rejected = [];
    try {
        if (values.length) {
            btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block"></span> Writing rubrics for ${values.length} standard${values.length === 1 ? '' : 's'}...`;
            // Definitions from the source document ride along: a rubric naming
            // the actual categories of personal data is a check, while one
            // saying "Personal Information" is an interpretation the auditor has
            // to make afresh on every turn.
            const res = await api.generatePolicyContent('compile_rules', config.context() || 'General organization', {
                rules: values.map(v => v.text),
                definitions: result.definitions || [],
            });
            if (!res.ok) throw new Error(res.error || 'Could not write the rubrics.');
            gates = (res.content && res.content.gates) || [];
            rejected = (res.content && res.content.unconvertible) || [];
        }
    } catch (e) {
        console.error('policy wizard: rubric compilation failed', e);
        // Inline, not a toast: this step can take the better part of a minute,
        // and a 3-second toast fired at the end of that is one the author has
        // usually looked away from. Nothing was applied, so say so plainly.
        showApplyError(`${e.message || 'Could not write the rubrics.'} Nothing was applied.`);
        btn.disabled = false;
        btn.innerHTML = original;
        return;
    }

    // Past this point nothing can fail. The caller writes to its own tier's
    // fields and reports back what it applied.
    const applied = config.onApply({
        structural,
        blacklist,
        gates,
        suggested: result.suggested || {},
        definitions: result.definitions || [],
    }) || [];

    panel.classList.add('hidden');
    panel.innerHTML = '';
    result = null;

    let msg = applied.length
        ? `Applied: ${applied.join(', ')}.`
        : 'Nothing new to apply — these were already set.';
    if (rejected.length) {
        msg += ` ${rejected.length} could not be written as a standard and were skipped.`;
    }
    ui.showToast(msg, applied.length ? 'success' : 'warning', 6000);
    if (typeof config.onApplied === 'function') config.onApplied();
}

/**
 * Shared writer for the parts both tiers store identically: a mandated
 * disclaimer, blocked phrases, and compiled hard gates. Only the field names
 * differ between a policy and a charter, so the caller passes the target object
 * and the key its value list lives under.
 */
export function applyCommon(target, { structural, blacklist, gates }, valuesKey) {
    const applied = [];

    if (structural.length) {
        // evaluate_draft_structure checks exactly one substring, so only the
        // first can be enforced. Said in the summary rather than as a toast that
        // competes with the result.
        target.structural_requirements = target.structural_requirements || {};
        target.structural_requirements.require_disclaimer = true;
        target.structural_requirements.mandatory_disclaimer_substring = structural[0].disclaimer_text;
        applied.push(structural.length > 1
            ? 'the first required disclaimer (only one can be enforced)'
            : 'required disclaimer');
    }

    if (blacklist.length) {
        if (!Array.isArray(target.early_prompt_blacklist)) target.early_prompt_blacklist = [];
        let added = 0;
        blacklist.forEach(b => {
            if (b.phrase && !target.early_prompt_blacklist.includes(b.phrase)) {
                target.early_prompt_blacklist.push(b.phrase);
                added++;
            }
        });
        if (added) applied.push(`${added} blocked phrase${added === 1 ? '' : 's'}`);
    }

    if (gates.length) {
        if (!Array.isArray(target[valuesKey])) target[valuesKey] = [];
        const existing = new Set(target[valuesKey].map(v => String(v.name || '').trim().toLowerCase()));
        let added = 0;
        gates.forEach(g => {
            const name = String(g.name || '').trim();
            if (!name || existing.has(name.toLowerCase())) return;
            existing.add(name.toLowerCase());
            // weight 0 + hard_gate: blocked by the Will, excluded from the
            // Spirit average — the same shape Scope Compliance already uses.
            target[valuesKey].push({
                name,
                description: g.description || '',
                weight: 0,
                hard_gate: true,
                rubric: g.rubric || { scoring_guide: [] },
            });
            added++;
        });
        if (added) applied.push(`${added} non-negotiable standard${added === 1 ? '' : 's'}`);
    }

    return applied;
}

/** Persistent in-panel error. Empty string clears it. */
function showApplyError(message) {
    const panel = document.getElementById('pw-import-result');
    if (!panel) return;
    let box = document.getElementById('pw-import-error');
    if (!message) {
        box?.remove();
        return;
    }
    if (!box) {
        box = document.createElement('div');
        box.id = 'pw-import-error';
        box.className = 'mt-3 p-3 rounded-lg border border-red-300 dark:border-red-900/50 bg-red-50 dark:bg-red-900/10 text-sm text-red-800 dark:text-red-200';
        const applyBtn = document.getElementById('pw-import-apply');
        applyBtn ? applyBtn.insertAdjacentElement('beforebegin', box) : panel.appendChild(box);
    }
    box.textContent = message;
}
