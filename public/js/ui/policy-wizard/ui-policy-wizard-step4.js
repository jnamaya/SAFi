import * as api from '../../core/api.js';
import * as ui from './../ui.js';

export function renderValuesStep(container, policyData) {
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 h-full">
            <div class="md:col-span-2 space-y-8">
                 <div>
                    <div class="flex justify-between items-end mb-4">
                         <div>
                            <label class="block text-lg font-bold text-gray-700 dark:text-gray-300">Standards</label>
                            <p class="text-sm text-gray-500">The standards this business unit holds its agents to. Every response from agents using this policy is scored against these.</p>
                         </div>
                         <button id="btn-gen-values" class="shrink-0 text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded-full flex items-center gap-1.5 transition-colors shadow-sm font-medium">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                            Suggest Standards
                         </button>
                    </div>
                    
                    <div id="pw-values-list" class="space-y-6 mb-6">
                        <!-- Values rendered here -->
                    </div>
                    
                    <button id="btn-add-value" class="w-full py-4 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl text-base font-medium text-gray-500 hover:border-blue-500 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/10 transition-all">
                        + Add Custom Standard
                    </button>
                </div>
            </div>

            <div class="bg-blue-50 dark:bg-neutral-800 p-8 rounded-2xl border border-blue-100 dark:border-neutral-700 h-fit sticky top-6">
                <h4 class="font-bold text-xl text-gray-800 dark:text-gray-200 mb-6 flex items-center gap-2">
                    <svg class="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                    How Standards Work
                </h4>
                <div class="space-y-5 text-sm text-gray-600 dark:text-gray-400">
                    <p class="leading-relaxed">
                        Every response is scored against each standard on a scale from <span class="font-mono">-1.0</span> (violated) to <span class="font-mono">+1.0</span> (upheld). The three states below tell the system how to judge each one.
                    </p>
                    <div id="pw-charter-note" class="hidden p-4 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg border border-indigo-200 dark:border-indigo-800/40 text-xs leading-relaxed"></div>
                    <div class="p-4 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700 shadow-sm">
                        <strong class="block text-green-600 mb-1">Upheld (+1.0)</strong>
                        The response actively demonstrates the standard.
                    </div>
                    <div class="p-4 bg-white dark:bg-black rounded-lg border border-gray-200 dark:border-neutral-700 shadow-sm">
                         <strong class="block text-red-600 mb-1">Violated (-1.0)</strong>
                        The response acts against this standard.
                    </div>
                    <div class="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-900/30 text-xs">
                        <strong class="block text-amber-800 dark:text-amber-300 mb-1">Non-negotiable</strong>
                        Mark a standard as non-negotiable so that any violation blocks the response outright, no matter how well it scores elsewhere. Reserve for must-nevers like privacy or staying in scope.
                    </div>
                    <div class="p-4 bg-gray-100 dark:bg-neutral-700/40 rounded-lg border border-gray-200 dark:border-neutral-600 text-xs">
                        <strong class="block text-gray-700 dark:text-gray-300 mb-1">Importance</strong>
                        Sets how much each standard counts toward the overall score. Only the relative importance matters — the numbers are balanced automatically.
                    </div>
                </div>
            </div>
        </div>
    `;

    renderValuesList(policyData);
    loadCharterNote();

    // Bind Auto-Gen Handler
    document.getElementById('btn-gen-values')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const original = btn.innerHTML;
        btn.innerHTML = `<span class="thinking-spinner w-4 h-4 inline-block mr-2"></span> Thinking...`;
        btn.disabled = true;

        try {
            const ctx = policyData.context || policyData.business_unit || policyData.name || "General business unit";
            const res = await api.generatePolicyContent('values', ctx);
            if (res.ok && res.content) {
                let json;
                if (typeof res.content === 'string') {
                    let cleaned = res.content.trim();
                    if (cleaned.startsWith('{') && !cleaned.startsWith('[')) cleaned = `[${cleaned}]`;
                    json = JSON.parse(cleaned);
                } else {
                    json = res.content;
                }
                policyData.values = json.map(v => ({ ...v, weight: v.weight || 0.2 }));
                renderValuesList(policyData);
                ui.showToast("Standards generated!", "success");
            }
        } catch (err) {
            console.error(err);
            ui.showToast("AI returned invalid format", "error");
        }
        btn.innerHTML = original;
        btn.disabled = false;
    });

    // Add Value Btn
    document.getElementById('btn-add-value').addEventListener('click', () => {
        policyData.values.push({ name: "New Value", description: "", weight: 0.2, hard_gate: false, rubric: { scoring_guide: [] } });
        renderValuesList(policyData);
    });
}

// If the org has a Charter, its core values take a fixed share of every score
// (settings.governance_split, default 40%) and the standards on this policy
// share the rest. Without this note, authors read "every response is scored
// against these" and assume 100%.
async function loadCharterNote() {
    try {
        const orgRes = await api.getMyOrganization();
        const org = orgRes && orgRes.organization;
        if (!org || !org.id) return;

        const cRes = await api.getCharter(org.id).catch(() => null);
        const charter = cRes && cRes.charter;
        if (!charter) return;

        let coreValues = charter.core_values || [];
        if (typeof coreValues === 'string') {
            try { coreValues = JSON.parse(coreValues); } catch (_) { coreValues = []; }
        }
        const scoredCount = coreValues.filter(v => !v.hard_gate).length;
        if (scoredCount === 0) return; // gate-only charter: no share of the score

        let settings = org.settings || {};
        if (typeof settings === 'string') {
            try { settings = JSON.parse(settings); } catch (_) { settings = {}; }
        }
        const split = Number(settings.governance_split);
        const charterPct = Math.round((isFinite(split) && split > 0 ? split : 0.40) * 100);

        const note = document.getElementById('pw-charter-note');
        if (!note) return; // user navigated away
        note.innerHTML = `
            <strong class="block text-indigo-800 dark:text-indigo-300 mb-1">Your organization has a Charter</strong>
            Its ${scoredCount} core value${scoredCount === 1 ? '' : 's'} automatically take <strong>${charterPct}%</strong> of every score for agents under this policy. The standards you define here share the remaining <strong>${100 - charterPct}%</strong>.`;
        note.classList.remove('hidden');
    } catch (_) { /* note is informational — never block the step on it */ }
}

// Weight is stored as a 0..1 float (legacy rows may hold a 0..100 percent).
// A stored 0 MUST render as 0 — the old `(v.weight && ...) : (v.weight || 20)`
// fallback displayed zero-weight standards as a healthy-looking 20%, hiding
// values that in fact never affect scoring.
function weightToPct(weight) {
    if (typeof weight !== 'number' || !isFinite(weight)) return 20;
    if (weight <= 1.0) return Math.round(weight * 100);
    return Math.min(100, Math.round(weight));
}

function renderValuesList(policyData) {
    const list = document.getElementById('pw-values-list');
    if (!list) return;
    list.innerHTML = '';

    if (policyData.values.length === 0) {
        list.innerHTML = `
            <div class="text-center py-12 bg-gray-50 dark:bg-neutral-900 rounded-xl border-2 border-dashed border-gray-200 dark:border-neutral-800">
                <p class="text-gray-400 text-lg mb-2">No standards defined yet.</p>
                <p class="text-sm text-gray-500">Click "Suggest Standards" to generate them from your description, or add your own.</p>
            </div>`;
        return;
    }

    policyData.values.forEach((v, idx) => {
        // Check for Rubric
        let hasRubric = false;
        if (v.rubric) {
            if (v.rubric.scoring_guide && Array.isArray(v.rubric.scoring_guide)) {
                hasRubric = v.rubric.scoring_guide.length > 0;
            }
        }

        const rubricBadge = hasRubric
            ? `<span class="bg-green-100 text-green-700 px-2 py-0.5 rounded text-xs font-bold border border-green-200">✅ Criteria Set</span>`
            : `<span class="bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded text-xs font-bold border border-yellow-200">⚠️ Needs Criteria</span>`;

        const card = document.createElement('div');
        card.className = "bg-white dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-6 shadow-sm hover:border-blue-300 transition-colors group";

        const nameId = `pw-val-name-${idx}`;
        const descId = `pw-val-desc-${idx}`;

        card.innerHTML = `
            <div class="flex justify-between items-start mb-4 gap-4">
                <input type="text" id="${nameId}" class="flex-1 font-bold text-lg bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none text-gray-900 dark:text-white placeholder-gray-400 px-1 py-1 transition-all" 
                    value="${v.name}" placeholder="e.g. Data Privacy, Accuracy, Regulatory Compliance">
                    
                <button class="text-gray-400 hover:text-red-500 p-2 rounded hover:bg-red-50 dark:hover:bg-red-900/20 transition-all" onclick="window.removePolicyValue(${idx})">
                     <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <textarea id="${descId}" class="w-full text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 hover:border-blue-300 focus:border-blue-500 rounded-lg p-3 resize-none h-24 outline-none transition-all mb-4"
                placeholder="Brief description of this standard...">${v.description || ''}</textarea>
            
            <div class="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-gray-100 dark:border-neutral-700">
                <div class="flex items-center gap-3">
                    ${rubricBadge}
                    <button class="text-sm font-semibold text-blue-600 dark:text-blue-400 hover:underline" onclick="document.getElementById('rubric-container-${idx}').classList.toggle('hidden')">
                        View/Edit Rubric
                    </button>
                </div>

                <div class="flex items-center gap-4 flex-wrap">
                    <label class="flex items-center gap-2 cursor-pointer select-none bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800" title="If checked, any violation of this standard blocks the response outright, regardless of other scores.">
                        <input type="checkbox" id="pw-hardgate-${idx}" ${v.hard_gate ? 'checked' : ''} class="accent-red-600 w-4 h-4">
                        <span class="text-xs uppercase font-bold text-gray-500">Non-negotiable</span>
                    </label>

                    <div id="pw-weight-wrap-${idx}" class="flex items-center gap-3 bg-gray-50 dark:bg-neutral-900 px-3 py-1.5 rounded-lg border border-gray-100 dark:border-neutral-800 ${v.hard_gate ? 'opacity-40' : ''}"
                        title="${v.hard_gate ? 'Not used: a non-negotiable standard blocks on violation instead of contributing to the score.' : 'How much this standard counts toward the overall score.'}">
                        <label class="text-xs uppercase font-bold text-gray-500">Importance</label>
                        <input type="range" min="0" max="100" value="${weightToPct(v.weight)}" ${v.hard_gate ? 'disabled' : ''}
                            class="w-24 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-blue-600 disabled:cursor-not-allowed">
                        <span id="pw-weight-lbl-${idx}" class="text-sm font-mono font-bold ${!v.hard_gate && weightToPct(v.weight) === 0 ? 'text-red-600' : 'text-gray-700 dark:text-gray-300'} w-8 text-right">${weightToPct(v.weight)}%</span>
                    </div>
                </div>
            </div>

            <div id="rubric-container-${idx}" class="hidden mt-6 pt-6 border-t border-dashed border-gray-200 dark:border-neutral-700 bg-gray-50/50 dark:bg-neutral-900/30 -mx-6 -mb-6 px-6 pb-6 rounded-b-xl">
                 <div class="flex justify-between items-center mb-4">
                    <label class="block text-xs uppercase text-gray-500 font-bold tracking-wider">How to evaluate it</label>
                    <span class="text-xs text-gray-400">Fill in the 3 states</span>
                 </div>
                 
                 <!-- Visual Builder Container -->
                 <div id="rubric-rows-${idx}" class="space-y-3"></div>
            </div>
        `;
        list.appendChild(card);

        // Bind Inputs
        card.querySelector(`#${nameId}`).addEventListener('change', (e) => policyData.values[idx].name = e.target.value);
        card.querySelector(`#${descId}`).addEventListener('change', (e) => policyData.values[idx].description = e.target.value);

        // --- RUBRIC BUILDER LOGIC (FIXED 3-POINT) ---
        const rowsContainer = document.getElementById(`rubric-rows-${idx}`);

        // Ensure rubric structure
        if (!policyData.values[idx].rubric) policyData.values[idx].rubric = { scoring_guide: [] };
        if (Array.isArray(policyData.values[idx].rubric)) {
            policyData.values[idx].rubric = { scoring_guide: policyData.values[idx].rubric };
        }
        if (!policyData.values[idx].rubric.scoring_guide) policyData.values[idx].rubric.scoring_guide = [];

        const renderFixedRows = () => {
            rowsContainer.innerHTML = '';
            const guide = policyData.values[idx].rubric.scoring_guide;

            // Helper to get text for a specific score
            const getCriteria = (targetScore) => {
                const item = guide.find(g => Math.abs(g.score - targetScore) < 0.1);
                return item ? (item.criteria || item.descriptor || '') : '';
            };

            // Helper to update the guide
            const updateCriteria = (targetScore, text) => {
                // Remove existing
                policyData.values[idx].rubric.scoring_guide = policyData.values[idx].rubric.scoring_guide.filter(g => Math.abs(g.score - targetScore) >= 0.1);
                // Add new
                if (text && text.trim()) {
                    policyData.values[idx].rubric.scoring_guide.push({ score: targetScore, criteria: text.trim() });
                }
            };

            const definitions = [
                { score: 1.0, label: "Positive (+1.0)", placeholder: "Example of excellent adherence...", color: "green", icon: "✅" },
                { score: 0.0, label: "Neutral (0.0)", placeholder: "Acceptable / Baseline behavior...", color: "gray", icon: "⚪" },
                { score: -1.0, label: "Negative (-1.0)", placeholder: "Something the response actively DOES that violates this (e.g. reveals confidential data) — not something it merely fails to mention...", color: "red", icon: "🚫" }
            ];

            definitions.forEach(def => {
                const row = document.createElement('div');
                row.className = "flex gap-4 items-start";

                const bgClass = def.score === 1 ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900' :
                    def.score === -1 ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900' :
                        'bg-white dark:bg-neutral-800 border-gray-200 dark:border-neutral-700';

                const textClass = def.score === 1 ? 'text-green-700 dark:text-green-400' :
                    def.score === -1 ? 'text-red-700 dark:text-red-400' :
                        'text-gray-600 dark:text-gray-400';

                row.innerHTML = `
                    <div class="w-32 shrink-0 pt-3 text-right">
                        <span class="block text-xs font-bold ${textClass} mb-1">${def.label}</span>
                    </div>
                    <div class="flex-1 relative">
                        <span class="absolute top-3 left-3 text-sm select-none opacity-50">${def.icon}</span>
                        <textarea class="w-full text-sm p-3 pl-10 rounded-lg border focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-none h-20 transition-all shadow-sm ${bgClass}"
                            placeholder="${def.placeholder}">${getCriteria(def.score)}</textarea>
                    </div>
                `;

                const input = row.querySelector('textarea');
                input.addEventListener('change', (e) => {
                    updateCriteria(def.score, e.target.value);
                });

                rowsContainer.appendChild(row);
            });
        };

        renderFixedRows();

        // Slider Logic — normalize back to 0..1 float so the engine sees consistent shape
        const slider = card.querySelector(`input[type="range"]`);
        const label = card.querySelector(`#pw-weight-lbl-${idx}`);
        if (slider) {
            slider.addEventListener('input', (e) => {
                const pct = parseInt(e.target.value);
                policyData.values[idx].weight = pct / 100;
                if (label) {
                    label.innerText = pct + '%';
                    label.classList.toggle('text-red-600', pct === 0);
                    label.classList.toggle('text-gray-700', pct !== 0);
                }
            });
        }

        // Hard gate toggle — the engine ignores weight for non-negotiables
        // (they block on violation instead of contributing to the score), so
        // disable the Importance control rather than let it suggest otherwise.
        const hg = card.querySelector(`#pw-hardgate-${idx}`);
        const weightWrap = card.querySelector(`#pw-weight-wrap-${idx}`);
        if (hg) {
            hg.addEventListener('change', (e) => {
                const gated = !!e.target.checked;
                policyData.values[idx].hard_gate = gated;
                if (slider) slider.disabled = gated;
                if (weightWrap) {
                    weightWrap.classList.toggle('opacity-40', gated);
                    weightWrap.title = gated
                        ? 'Not used: a non-negotiable standard blocks on violation instead of contributing to the score.'
                        : 'How much this standard counts toward the overall score.';
                }
            });
        }
    });

    // Window global for remove (legacy pattern)
    window.removePolicyValue = (idx) => {
        policyData.values.splice(idx, 1);
        renderValuesList(policyData);
    };
}

// Mirrors the engine's compile-time contract (synderesis._validate_value_rubrics
// and the save-time checks in policy_api_routes.validate_policy_data): a
// rubric-less non-negotiable blocks every response; a rubric-less ordinary
// standard is silently stripped; a zero-weight ordinary standard never counts.
// Catch all three here, on the step where the fix is, instead of at save or —
// worse — at a user's first chat.
function hasUsableCriteria(v) {
    const rub = v.rubric;
    if (Array.isArray(rub)) return rub.length > 0;
    if (rub && typeof rub === 'object') {
        if (Array.isArray(rub.scoring_guide) && rub.scoring_guide.length > 0) return true;
        return !!(rub.description && String(rub.description).trim());
    }
    return false;
}

export function validateValuesStep(policyData) {
    if (!policyData.values || policyData.values.length === 0) {
        ui.showToast("At least one Standard is required.", "error");
        return false;
    }
    for (const v of policyData.values) {
        const name = v.name || 'Unnamed standard';
        if (!hasUsableCriteria(v)) {
            ui.showToast(
                v.hard_gate
                    ? `"${name}" is non-negotiable but has no scoring criteria — agents would block every response. Open "View/Edit Rubric" and fill in the states.`
                    : `"${name}" has no scoring criteria, so it can never be scored. Open "View/Edit Rubric" and fill in the states.`,
                "error"
            );
            return false;
        }
        if (!v.hard_gate && (!v.weight || v.weight <= 0)) {
            ui.showToast(
                `"${name}" has an importance of 0%, so it never affects scoring. Raise its importance or mark it non-negotiable.`,
                "error"
            );
            return false;
        }
    }
    return true;
}
