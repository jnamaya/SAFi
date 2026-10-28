// Audit Hub (native): the org's observe surface over governance records.
// Replaces the embedded Streamlit dashboard — same tab, same sidebar entry,
// but session-authenticated (no dashboard JWT, no iframe) and DB-backed
// (encrypted governance_records via audit_api.py, never disk logs).
// Observe stays observe: dispositions live in the Review tab; the one write
// this surface causes is the server-side audit_export custody log.
// Vocabulary: Alignment (/10) and Consistency (%) — null renders N/A, never
// a default.
import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { renderConscienceReport, attachTabSwitching } from './ui-modal-conscience.js';

let orgId = null;
let state = null;

const PAGE_SIZE = 50;

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtDate(v) {
    if (!v) return '—';
    const d = new Date(v);
    return isNaN(d) ? esc(v) : d.toLocaleString();
}

// Alignment is spirit_score /10; null renders N/A, never a default.
function alignmentLabel(score) {
    return (score === null || score === undefined) ? 'N/A' : `${Number(score).toFixed(1)} / 10`;
}

// Consistency = (1 − drift) × 100%; null renders N/A.
function consistencyLabel(drift) {
    return (drift === null || drift === undefined) ? 'N/A' : `${Math.round((1 - drift) * 100)}%`;
}

const ALIGNMENT_HELP =
    'How well this response expressed the agent’s declared values, as assessed by ' +
    'the governance audit. Each value’s score is weighted by importance and audit ' +
    'confidence, then combined into a 1–10 grade for the turn. Higher is better. ' +
    'Expect both this and Consistency to look unstable while a policy is still being ' +
    'tested — scores settle down once enough turns accumulate against a finished ' +
    'policy, so it’s best to test a policy through to stability before relying on it in production.';
const CONSISTENCY_HELP =
    'How closely this turn’s value expression matches the agent’s own historical ' +
    'pattern. 100% means the agent behaved as it usually does; a low value flags an ' +
    'out-of-character turn, even if that turn scored well on its own. N/A on an ' +
    'agent’s first turns, before a history exists. Expect both this and Alignment to ' +
    'look unstable while a policy is still being tested — scores settle down once enough ' +
    'turns accumulate against a finished policy, so it’s best to test a policy through to ' +
    'stability before relying on it in production.';

// The WillGate is pure code with a finite set of exit paths, so its reason
// codes are enumerable and translated deterministically — ported verbatim
// from the Streamlit Audit Hub.
const WILL_REASON_EXPLANATIONS = {
    alignment_within_threshold: 'The draft passed structural checks and all hard gates, and its alignment score met the approval threshold.',
    hard_gates_passed: 'All non-negotiable (hard-gate) values passed the governance audit.',
    no_hard_gates_defined: 'This agent defines no hard-gate values, so no bright-line checks applied.',
    pass: 'The draft passed the enforcement gate’s structural checks.',
    missing_disclaimer: 'The draft omitted the mandatory disclaimer required by this agent’s structural rules.',
    ethical_violation: 'The draft contained a disallowed content structure (such as a non-whitelisted code block) or was flagged as a critical values violation.',
    scope_violation: 'The Scope Compliance hard gate scored −1: the request or draft fell outside this agent’s permitted scope.',
    scope_validation: 'The request fell outside this agent’s permitted scope.',
    grounding_violation: 'The Grounding Fidelity hard gate scored −1: the draft asserted claims not supported by the retrieved sources.',
    hard_gate_violation: 'A non-negotiable (hard-gate) value scored −1 in the governance audit.',
    hard_gate_unscored: 'The governance audit failed to score one of this agent’s hard-gate values, so the gate failed closed rather than ship an unaudited draft.',
    audit_unavailable: 'The governance audit was unavailable or covered none of this agent’s values, so the draft could not ship unaudited (fail-closed).',
};

function explainWillReason(code, decision) {
    code = typeof code === 'string' ? code.trim() : '';
    const approved = String(decision || '').toLowerCase().startsWith('approv');
    if (!code) {
        return approved
            ? 'The draft passed the enforcement gate’s deterministic checks (structure, hard gates, alignment threshold).'
            : 'No reason was recorded for this decision.';
    }
    if (code === 'low_alignment_score') {
        return approved
            ? 'Neither the draft nor its retry met the alignment threshold cleanly, so the better draft shipped with its honest low score recorded instead of redirecting an in-scope request.'
            : 'The weighted alignment score fell below this agent’s approval threshold, and the corrected retry did not pass either, so the response was redirected.';
    }
    if (code.startsWith('injection:')) {
        const category = code.split(':', 2)[1].replace(/_/g, ' ');
        return `Blocked before generation: the prompt matched an injection-attack pattern (${category}).`;
    }
    if (code.startsWith("Tool '")) return code; // already a human-readable sentence
    // Tool-risk gate exits (will.py approve_tool_call, batch intent gate) also
    // return full human-readable sentences rather than snake_case codes — show
    // them verbatim instead of mislabeling them "unrecognized". A snake_case
    // code never contains spaces or uppercase letters, so anything that does
    // is treated as pre-written prose.
    if (code.includes(' ') && (/[.!?]$/.test(code) || /[A-Z]/.test(code) || code.includes(':'))) {
        return code;
    }
    return WILL_REASON_EXPLANATIONS[code] || `Gate decision recorded: ${code}`;
}

const BADGE = 'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap';

function decisionBadge(decision) {
    const map = {
        approve: ['Approved', 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200'],
        redirected: ['Redirected', 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200'],
        violation: ['Violation', 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200'],
    };
    const [label, cls] = map[decision] || [decision || 'Unknown', 'bg-gray-100 text-gray-700 dark:bg-neutral-800 dark:text-gray-300'];
    return `<span class="${BADGE} ${cls}">${esc(label)}</span>`;
}

// The digest is rendered beside the verdict so a reader can copy it, compare it
// against an earlier export, and re-walk the chain — a badge alone is our
// assertion, not evidence.
function chainHash(chain) {
    if (!chain?.entry_hash) return '';
    const h = String(chain.entry_hash);
    return ` <code class="chain-hash" data-hash="${esc(h)}" role="button" tabindex="0"
        title="Chain head digest (SHA-256): ${esc(h)}\nprev: ${esc(chain.prev_hash ?? 'none (first entry)')}\nClick to copy.">${esc(h.slice(0, 12))}…</code>`;
}

function chainBadge(chain) {
    if (!chain) return '';
    // valid === null means there are no trail entries at all. That is an absence
    // of evidence, not a pass: this used to fall through to the green tick and
    // claim "verified" over zero entries, which is what a purged trail looks like.
    if (chain.valid === null || chain.valid === undefined || !chain.entries) {
        return `<span class="${BADGE} bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200" title="No chat_audit_trail entries exist for this turn, so there is nothing to verify. Expected if the trail was purged under the retention policy.">No trail entries</span>`;
    }
    return chain.valid
        ? `<span class="${BADGE} bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200" title="${chain.entries} audit-trail entries recomputed and verified">Chain verified ✓</span>${chainHash(chain)}`
        : `<span class="${BADGE} bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200" title="First bad entry: ${esc(chain.first_bad_id)}">CHAIN INVALID</span>${chainHash(chain)}`;
}

function flaggedBadge(ev) {
    const flagged = (ev.spirit_score !== null && ev.spirit_score < 6) ||
        (ev.drift !== null && ev.drift > 0.4);
    return flagged ? `<span class="${BADGE} bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200">Flagged</span>` : '';
}

function rangeDates() {
    if (state.range === 'custom') {
        const p = {};
        if (state.dateFrom) p.from = state.dateFrom;
        if (state.dateTo) p.to = state.dateTo;
        return p;
    }
    if (state.range === 'all') return {};
    const days = state.range === '7d' ? 7 : 30;
    return { from: new Date(Date.now() - days * 86400000).toISOString() };
}

// Local date (YYYY-MM-DD) for the native <input type="date"> value.
function todayLocalISO() {
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function daysAgoLocalISO(n) {
    const d = new Date(Date.now() - n * 86400000);
    const p = x => String(x).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function entityParams() {
    const p = rangeDates();
    if (state.mode === 'policy' && state.entity) p.policy_id = state.entity;
    if (state.mode === 'agent' && state.entity) p.profile = state.entity;
    if (state.user_id) p.user_id = state.user_id;
    return p;
}

// D1 URL-synced filter state: the hub's shareable query (mode, entity, user,
// range, dates) lives in the tab's hash-free query string so a filtered view
// can be bookmarked, linked, or restored after a reload. replaceState keeps
// the history clean — navigating back does not replay filter states.
function syncUrl() {
    const p = new URLSearchParams();
    p.set('mode', state.mode);
    if (state.entity) p.set('entity', state.entity);
    if (state.user_id) p.set('user', state.user_id);
    p.set('range', state.range);
    if (state.range === 'custom') {
        p.set('from', state.dateFrom);
        p.set('to', state.dateTo);
    }
    history.replaceState(null, '', `${location.pathname}?${p}`);
}

function restoreFromUrl() {
    const p = new URLSearchParams(location.search);
    const mode = p.get('mode');
    if (mode === 'policy' || mode === 'agent') state.mode = mode;
    if (p.get('entity') !== null) state.entity = p.get('entity') || '';
    if (p.get('user') !== null) state.user_id = p.get('user') || '';
    const range = p.get('range');
    if (['7d', '30d', 'all', 'custom'].includes(range)) state.range = range;
    if (state.range === 'custom') {
        const from = p.get('from'), to = p.get('to');
        if (/^\d{4}-\d{2}-\d{2}$/.test(from || '')) state.dateFrom = from;
        if (/^\d{4}-\d{2}-\d{2}$/.test(to || '')) state.dateTo = to;
    }
}

// ---------------------------------------------------------------------------

export async function renderSettingsDashboardTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabDashboard;
    if (!container) return;

    container.innerHTML = `<div class="flex items-center justify-center w-full py-16"><div class="thinking-spinner"></div></div>`;

    let org = null;
    try {
        const orgRes = await api.getMyOrganization();
        org = orgRes ? orgRes.organization : null;
    } catch (e) { /* fall through */ }
    if (!org) {
        container.innerHTML = `<p class="text-sm text-gray-500">You need an organization (and the admin, editor, or auditor role) to use the Audit Hub.</p>`;
        return;
    }
    orgId = org.id;
    // view defaults to 'consistency' so the card's heading and its y-axis agree
    // on load; it used to open on 'deviation' under a "Consistency Trend" title.
    state = { mode: 'agent', entity: '', user_id: '', range: '30d',
              scope: 'prompt',
              dateFrom: daysAgoLocalISO(30), dateTo: todayLocalISO(),
              filter: '', q: '', offset: 0, sort: '', sortDir: 'desc',
              maDays: 7, view: 'consistency', showPoints: false, filters: { profiles: [], policies: [], users: [] } };

    try {
        state.filters = await api.getAuditFilters(orgId);
    } catch (e) { /* pickers stay empty; data may simply not exist yet */ }
    restoreFromUrl();

    container.innerHTML = `
        <div class="space-y-6">
            <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 class="text-2xl font-bold">Audit Hub</h1>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Governance analytics over the encrypted audit record: alignment, consistency, interventions, and the per-turn evidence behind each decision.</p>
                </div>
                <div id="ah-controls" class="flex flex-wrap items-center gap-2"></div>
            </div>
            <div id="ah-kpis"></div>
            <div id="ah-policy"></div>
            <div id="ah-trend" class="settings-card"></div>
            <div id="ah-explorer" class="settings-card"></div>
        </div>`;

    renderControls();
    refreshData();
}

// 2.2 Multi-select filters: the backend already accepts comma-joined filter
// values via _as_id_list (database.py), so the UI stores selections as a
// comma-joined string and renders native multi-selects.
const csv = s => String(s || '').split(',').map(v => v.trim()).filter(Boolean);
const joined = sel => csv([...sel.selectedOptions].map(o => o.value)).join(',');

const MULTI_SEL_CLS = 'rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1 text-xs text-gray-800 dark:text-neutral-200 max-h-24 overflow-y-auto';
function multiSel(id, entries, cur) {
    const curSet = new Set(csv(cur));
    return `<select id="${id}" multiple size="1" class="${MULTI_SEL_CLS}" title="Ctrl/Cmd-click to select several">
        ${entries.map(([v, l]) => `<option value="${esc(v)}" ${curSet.has(String(v)) ? 'selected' : ''}>${esc(l)}</option>`).join('')}
    </select>`;
}

function renderControls() {
    const el = document.getElementById('ah-controls');
    if (!el) return;
    const opts = state.mode === 'policy' ? state.filters.policies : state.filters.profiles;
    const userOpts = state.filters.users || [];
    const sel = (id, entries, cur) => `
        <select id="${id}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs text-gray-800 dark:text-neutral-200">
            ${entries.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(l)}</option>`).join('')}
        </select>`;
    el.innerHTML = `
        ${sel('ah-mode', [['agent', 'By agent'], ['policy', 'By policy']], state.mode)}
        ${multiSel('ah-entity', opts.map(o => [o, String(o).replace(/_/g, ' ')]), state.entity)}
        ${userOpts.length > 0 ? multiSel('ah-user',
            // C3: the __none__ sentinel (UNATTRIBUTED_USER in database.py)
            // makes NULL-user_id records selectable instead of unreachable.
            userOpts.map(u => [u.user_id, u.name || u.user_id])
                .concat([['__none__', '(no user — unattributed)']]), state.user_id) : ''}
        ${sel('ah-range', [['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['all', 'All time'], ['custom', 'Custom']], state.range)}
        <input type="date" id="ah-from" value="${state.dateFrom}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs text-gray-800 dark:text-neutral-200">
        <input type="date" id="ah-to" value="${state.dateTo}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs text-gray-800 dark:text-neutral-200">
        <button id="ah-csv" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg whitespace-nowrap text-gray-800 dark:text-neutral-200 hover:bg-gray-50 dark:hover:bg-neutral-700" title="D3: downloads the currently visible explorer rows as CSV — plaintext columns only, no decryption, so no evidence-log entry is needed.">Export CSV</button>
        <button id="ah-export" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg whitespace-nowrap text-gray-800 dark:text-neutral-200 hover:bg-gray-50 dark:hover:bg-neutral-700" title="Downloads the decrypted records matching the current filters. The export is recorded in the compliance evidence log.">Export JSON</button>
    `;
    const syncDates = () => {
        const f = el.querySelector('#ah-from'), t = el.querySelector('#ah-to');
        f.style.display = t.style.display = state.range === 'custom' ? '' : 'none';
    };
    syncDates();
    el.querySelector('#ah-mode')?.addEventListener('change', e => {
        state.mode = e.target.value; state.entity = ''; state.offset = 0;
        renderControls(); refreshData();
    });
    el.querySelector('#ah-entity')?.addEventListener('change', e => {
        state.entity = joined(e.target); state.offset = 0; refreshData();
    });
    el.querySelector('#ah-user')?.addEventListener('change', e => {
        state.user_id = joined(e.target); state.offset = 0; refreshData();
    });
    el.querySelector('#ah-range')?.addEventListener('change', e => {
        state.range = e.target.value; state.offset = 0; syncDates(); refreshData();
    });
    el.querySelector('#ah-from')?.addEventListener('change', e => {
        state.dateFrom = e.target.value; state.range = 'custom'; state.offset = 0; syncDates(); refreshData();
    });
    el.querySelector('#ah-to')?.addEventListener('change', e => {
        state.dateTo = e.target.value; state.range = 'custom'; state.offset = 0; syncDates(); refreshData();
    });
    el.querySelector('#ah-export')?.addEventListener('click', () => {
        window.open(api.auditExportUrl(orgId, { ...entityParams(), filter: state.filter || undefined }), '_blank');
    });
    // D3: plaintext CSV of the visible explorer rows — no decryption, so no
    // evidence-log entry (compare the JSON export, which is logged).
    el.querySelector('#ah-csv')?.addEventListener('click', () => {
        const cols = ['created_at', 'profile_key', 'user_name', 'user_id',
                      'intellect_model', 'spirit_score', 'drift',
                      'will_decision', 'will_stage', 'flagged'];
        const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
        const csv = [cols.join(','),
            ...lastExplorerItems.map(i => cols.map(c => cell(
                c === 'flagged' ? (i.spirit_score !== null && i.spirit_score !== undefined && i.spirit_score < 6) || (i.drift !== null && i.drift !== undefined && i.drift > 0.4)
                    : i[c])).join(','))].join('\n');
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        const a = Object.assign(document.createElement('a'),
            { href: url, download: `audit-explorer-${new Date().toISOString().slice(0, 10)}.csv` });
        a.click();
        URL.revokeObjectURL(url);
    });
}

function refreshData() {
    syncUrl();
    loadKpis();
    loadPolicyBreakdown();
    loadTrend();
    renderExplorer();
}

// --- C2: per-policy breakdown --------------------------------------------------

// One aggregate row per policy so a weak policy is visible at a glance
// instead of requiring a hand-built filter per policy. Plaintext aggregates
// only — the endpoint never decrypts anything.
async function loadPolicyBreakdown() {
    const el = document.getElementById('ah-policy');
    if (!el) return;
    // In By-policy mode the entity picker already scopes a single policy —
    // a breakdown across policies would just echo that filter back.
    if (state.mode === 'policy' && state.entity && !state.entity.includes(',')) {
        el.innerHTML = '';
        return;
    }
    let items;
    try {
        items = (await api.getAuditByPolicy(orgId, entityParams())).items || [];
    } catch (e) {
        el.innerHTML = '';   // non-critical card; never block the page
        return;
    }
    if (items.length === 0) { el.innerHTML = ''; return; }
    const label = id => id ? esc(String(id).replace(/_/g, ' ')) : '<span class="text-gray-400">unassigned</span>';
    el.innerHTML = `
        <div class="settings-card">
            <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div>
                    <h4 class="text-lg font-semibold">By Policy</h4>
                    <p class="text-xs text-gray-500 mt-0.5">Turns, alignment and interventions grouped by policy version for the period. Click a row to pin the explorer to that policy.</p>
                </div>
            </div>
            <div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-neutral-700">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 dark:bg-neutral-800 text-xs uppercase text-gray-500 dark:text-gray-400">
                        <tr><th class="px-4 py-3">Policy</th><th class="px-4 py-3">Turns</th><th class="px-4 py-3">Avg. Alignment</th><th class="px-4 py-3">Avg. Consistency</th><th class="px-4 py-3">Redirected</th><th class="px-4 py-3">Violations</th><th class="px-4 py-3">Flagged</th></tr>
                    </thead>
                    <tbody>
                        ${items.map(r => `
                            <tr class="border-b border-gray-100 dark:border-neutral-800 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer" data-policy-row="${esc(r.policy_id)}">
                                <td class="px-4 py-3 text-sm font-medium">${label(r.policy_id)}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.turns}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.avg_alignment !== null && r.avg_alignment !== undefined ? Number(r.avg_alignment).toFixed(1) : '—'}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.avg_drift !== null && r.avg_drift !== undefined ? ((1 - r.avg_drift) * 100).toFixed(0) + '%' : '—'}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.redirected}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.violations}</td>
                                <td class="px-4 py-3 text-sm tabular-nums">${r.flagged}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>
        </div>`;
    // Clicking a row pins the explorer to that policy — same affordance as
    // the trend-chart cross-filter (2.6).
    el.querySelectorAll('[data-policy-row]').forEach(tr =>
        tr.addEventListener('click', () => {
            state.mode = 'policy';
            state.entity = tr.getAttribute('data-policy-row') || '';
            state.offset = 0;
            renderControls();
            refreshData();
        }));
}

// --- KPI row -----------------------------------------------------------------

// Same thresholds as the per-message gauge (ui-modal-conscience.js).
function gaugeSvg(score) {
    const hasScore = score !== null && score !== undefined;
    const s = hasScore ? Math.max(0, Math.min(10, score)) : 0;
    const circumference = 50 * 2 * Math.PI;
    const offset = hasScore ? circumference - (s / 10) * circumference : circumference;
    const grad = s > 7 ? 'ahg-green' : s > 4 ? 'ahg-yellow' : 'ahg-red';
    const colorClass = !hasScore ? 'text-gray-400 dark:text-gray-500'
        : s > 7 ? 'text-green-500' : s > 4 ? 'text-yellow-500' : 'text-red-500';
    return `
        <div class="relative w-32 h-32">
            <svg class="w-full h-full transform -rotate-90" viewBox="0 0 120 120">
                <defs>
                    <linearGradient id="ahg-green" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#22c55e"/><stop offset="100%" stop-color="#4ade80"/></linearGradient>
                    <linearGradient id="ahg-yellow" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#f59e0b"/><stop offset="100%" stop-color="#fbbf24"/></linearGradient>
                    <linearGradient id="ahg-red" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#ef4444"/><stop offset="100%" stop-color="#f87171"/></linearGradient>
                </defs>
                <circle class="text-gray-200 dark:text-neutral-800" stroke-width="8" stroke="currentColor" fill="transparent" r="50" cx="60" cy="60"/>
                ${hasScore ? `<circle stroke="url(#${grad})" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" fill="transparent" r="50" cx="60" cy="60"/>` : ''}
            </svg>
            <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center">
                <span class="text-4xl font-bold ${colorClass}">${hasScore ? s.toFixed(1) : 'N/A'}</span>
                <span class="text-xs text-gray-500 dark:text-gray-400">${hasScore ? '/ 10' : 'no data'}</span>
            </div>
        </div>`;
}

async function loadKpis() {
    const el = document.getElementById('ah-kpis');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let s;
    try {
        s = await api.getAuditSummary(orgId, entityParams());
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load KPIs: ${esc(e.message || e)}</p>`;
        return;
    }
    const tile = (label, value, sub = '', help = '') => `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3" ${help ? `title="${esc(help)}"` : ''}>
            <div class="text-xs uppercase text-gray-400">${label}</div>
            <div class="text-2xl font-bold mt-0.5 tabular-nums">${value}</div>
            ${sub ? `<div class="text-xs text-gray-400 mt-0.5">${sub}</div>` : ''}
        </div>`;
    const redirectSub = s.avg_redirect_quality !== null && s.avg_redirect_quality !== undefined
        ? `avg. redirect quality ${Number(s.avg_redirect_quality).toFixed(1)} / 10` : '';
    el.innerHTML = `
        <div class="settings-card">
            <div class="flex flex-col md:flex-row items-center gap-6">
                <div class="flex flex-col items-center shrink-0" title="Overall governance score for the period: average Alignment (approved turns) reduced by average drift. Bounded 1–10.">
                    ${gaugeSvg(s.overall_score)}
                    <h4 class="font-semibold mt-2 text-sm text-gray-800 dark:text-gray-200">Overall Score</h4>
                </div>
                <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 flex-1 w-full">
                    ${tile('Avg. Alignment', s.avg_alignment !== null && s.avg_alignment !== undefined ? `${Number(s.avg_alignment).toFixed(1)} <span class="text-sm font-normal text-gray-400">/ 10</span>` : 'N/A',
                           'approved turns only', ALIGNMENT_HELP + ' Redirected turns are scored on a separate redirect-quality rubric and shown in the Interventions card.')}
                    ${tile('Avg. Consistency', s.avg_consistency !== null && s.avg_consistency !== undefined ? `${Number(s.avg_consistency).toFixed(1)}%` : 'N/A',
                           (s.drift_p95 !== null && s.drift_p95 !== undefined ? `p95 drift ${Number(s.drift_p95).toFixed(2)}` : 'all scored turns'),
                           CONSISTENCY_HELP + (s.drift_p50 !== null && s.drift_p50 !== undefined ? ` Drift percentiles for the period: p50 ${Number(s.drift_p50).toFixed(2)}, p95 ${Number(s.drift_p95).toFixed(2)}, max ${Number(s.drift_max).toFixed(2)}.` : ''))}
                    ${tile('Interventions', s.interventions,
                           `${s.intervention_rate !== null && s.intervention_rate !== undefined ? s.intervention_rate.toFixed(1) : '0.0'}% of responses redirected${redirectSub ? ' · ' + redirectSub : ''}${s.violations ? ` · ${s.violations} gateway violation${s.violations === 1 ? '' : 's'}` : ''}`)}
                    ${tile('Total Audits', s.total_audits, `${s.flagged} flagged in period`)}
                </div>
            </div>
        </div>`;
}

// --- Consistency trend ---------------------------------------------------------

// Fixed categorical order (see --ah-series-N in styles.css). Slots are handed
// out by position in the org's agent roster, NOT by position in the filtered
// result — narrowing the range must never repaint the lines that survive.
const AH_SERIES_SLOTS = 8;

function seriesColor(profileKey) {
    const roster = [...(state.filters.profiles || [])].map(String).sort();
    const i = roster.indexOf(String(profileKey));
    // An agent absent from the roster (deleted, or a NULL profile_key row) gets
    // the last slot rather than colliding with slot 1.
    const slot = i < 0 ? AH_SERIES_SLOTS : (i % AH_SERIES_SLOTS) + 1;
    return `var(--ah-series-${slot})`;
}

const humanAgent = k => String(k || '').replace(/_/g, ' ') || 'unattributed';

// What the y-axis is actually showing, so the heading can never contradict it.
const VIEW_METRIC = {
    consistency: 'Consistency Trend',
    drift: 'Drift Trend',
    deviation: 'Drift vs. Period Average',
    flagged: 'Flagged Turns',
};

// The heading names the real scope. Previously it read "Agent Consistency
// Trend" in every state — including "All agents", and including policy mode.
function trendHeading() {
    const metric = VIEW_METRIC[state.view] || 'Consistency Trend';
    const scope = state.entity
        ? humanAgent(state.entity)
        : (state.mode === 'policy' ? 'All policies' : 'All agents');
    return `${scope} · ${metric}`;
}

async function loadTrend() {
    const el = document.getElementById('ah-trend');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let buckets, rawSeries;
    try {
        const res = await api.getAuditTrend(orgId, entityParams());
        buckets = res.buckets || [];
        rawSeries = res.series || [];
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load the trend: ${esc(e.message || e)}</p>`;
        return;
    }
    // The flagged view counts events, so it doesn't need a drift score on the
    // bucket — only the drift views do.
    const bucketUsable = b => state.view === 'flagged'
        ? (b.turns || 0) > 0
        : b.avg_drift !== null && b.avg_drift !== undefined;
    const scored = buckets.filter(bucketUsable);

    // One line per agent. Drift is per-agent by construction (spirit_memory is
    // keyed on profile_name), so pooling it across agents is turn-weighted and
    // describes no agent in particular — splitting is what makes the label true.
    const split = rawSeries
        .map(s => ({ key: s.profile_key, label: humanAgent(s.profile_key),
                     color: seriesColor(s.profile_key), days: toDays(s.buckets.filter(bucketUsable)) }))
        .filter(s => s.days.length > 0);

    // Past the palette's fixed slots, N lines stop being readable. Fall back to
    // the pooled line and say so, rather than cycling hues into spaghetti.
    const tooMany = split.length > AH_SERIES_SLOTS;
    const perAgent = split.length > 1 && !tooMany;
    const series = perAgent
        ? split
        : [{ key: '', label: 'All turns (pooled)', color: 'var(--ah-series-1)', days: toDays(scored) }];

    let subtitle;
    if (state.entity && state.mode === 'agent') {
        subtitle = `Daily consistency of value expression against this agent's own history.`;
    } else if (perAgent) {
        subtitle = `One line per agent — ${split.length} with data in this period. Each turn is measured against its own agent's history, so the lines are not comparable as levels, only as stability.`;
    } else if (tooMany) {
        subtitle = `${split.length} agents in this period — too many to plot separately, so this is the turn-weighted mean across all of them and it may describe no single agent. Pick an agent above to see its own line.`;
    } else {
        subtitle = `Turn-weighted mean across all turns in scope. Each turn is measured against its own agent's history.`;
    }

    const sel = (id, entries, cur) => `
        <select id="${id}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
            ${entries.map(([v, l]) => `<option value="${v}" ${String(v) === String(cur) ? 'selected' : ''}>${l}</option>`).join('')}
        </select>`;

    const plottable = series.filter(s => s.days.length > 0);
    const enoughData = perAgent ? plottable.length > 0 : scored.length >= 2;

    el.innerHTML = `
        <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div>
                <h4 class="text-lg font-semibold">${esc(trendHeading())}</h4>
                <p class="text-xs text-gray-500 mt-0.5 max-w-2xl" title="${esc(CONSISTENCY_HELP)}">${esc(subtitle)}</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                ${sel('ah-ma', [[3, 'MA: 3 days'], [7, 'MA: 7 days'], [14, 'MA: 14 days'], [30, 'MA: 30 days']], state.maDays)}
                ${sel('ah-view', [['consistency', 'Consistency (%)'], ['drift', 'Drift (0=best)'], ['deviation', 'Drift vs. average'], ['flagged', 'Flagged count']], state.view)}
                <label class="flex items-center gap-1.5 text-xs text-gray-500"><input type="checkbox" id="ah-points" ${state.showPoints ? 'checked' : ''}> Raw points</label>
            </div>
        </div>
        <div id="ah-trend-chart">${enoughData
            ? buildTrendChart(plottable)
            : `<p class="text-sm text-gray-400 py-8 text-center">Not enough drift data in this period to draw a trend line.</p>`}</div>`;

    el.querySelector('#ah-ma')?.addEventListener('change', e => { state.maDays = parseInt(e.target.value, 10); loadTrend(); });
    el.querySelector('#ah-view')?.addEventListener('change', e => { state.view = e.target.value; loadTrend(); });
    el.querySelector('#ah-points')?.addEventListener('change', e => { state.showPoints = e.target.checked; loadTrend(); });

    // 2.6 Trend → Explorer cross-filtering: click a point/bucket to pin the
    // Explorer (and KPIs) to that day. The backend treats date_to as
    // exclusive (created_at<date_to), so the "to" bound is the next day.
    el.querySelector('#ah-trend-chart svg')?.addEventListener('click', e => {
        const svg = e.currentTarget;
        const W = +svg.getAttribute('data-w') || 800;
        const PL = +svg.getAttribute('data-pl') || 46;
        const PR = +svg.getAttribute('data-pr') || 12;
        const rect = svg.getBoundingClientRect();
        const vx = (e.clientX - rect.left) / rect.width * W;   // viewBox coords
        const ts = plottable.flatMap(s => s.days.map(d => d.t));
        if (!ts.length) return;
        const tMin = Math.min(...ts), tMax = Math.max(...ts);
        const span = tMax - tMin || 86400000;
        const clicked = tMin + ((vx - PL) / (W - PL - PR)) * span;
        let nearest = ts[0];
        for (const t of ts) if (Math.abs(t - clicked) < Math.abs(nearest - clicked)) nearest = t;
        state.range = 'custom';
        state.dateFrom = new Date(nearest).toISOString().slice(0, 10);
        state.dateTo = new Date(nearest + 86400000).toISOString().slice(0, 10);
        state.offset = 0;
        renderControls();
        refreshData();
        ui.showToast(`Explorer filtered to ${new Date(nearest).toLocaleDateString()}. Change the date range to reset.`, 'info');
    });
}

function toDays(bkts) {
    return bkts.map(b => ({
        t: new Date(b.bucket + 'T00:00:00Z').getTime(),
        drift: b.avg_drift,
        n: b.scored_turns || 1,
        flagged: b.flagged || 0,
    })).sort((a, b) => a.t - b.t);
}

// SVG line chart over daily buckets, one line per series. Moving average is
// turn-weighted over a trailing window of state.maDays days — the smoothing
// (like the view mode) is a display choice, mirroring the Streamlit selectors.
//
// `series` is [{key, label, color, days:[{t, drift, n}]}]. A single pooled
// series renders exactly as this chart always did.
function buildTrendChart(series) {
    const windowMs = state.maDays * 86400000;

    // Turn-weighted trailing mean, computed within a series — never across
    // them, which is the whole point of the split.
    const movingAvg = days => days.map((d, i) => {
        let num = 0, den = 0;
        for (let k = i; k >= 0 && d.t - days[k].t < windowMs; k--) {
            num += days[k].drift * days[k].n;
            den += days[k].n;
        }
        return num / den;
    });

    const prepared = series.map(s => {
        const days = s.days;
        const totalN = days.reduce((a, d) => a + d.n, 0) || 1;
        // Each series deviates from its OWN period average: "is this agent off
        // its own norm" is the only question the deviation view can answer once
        // the lines are per-agent. For one pooled series this is unchanged.
        const ownAvg = days.reduce((a, d) => a + d.drift * d.n, 0) / totalN;
        const ma = movingAvg(days);
        let raw, smooth;
        if (state.view === 'consistency') {
            raw = days.map(d => (1 - d.drift) * 100);
            smooth = ma.map(v => (1 - v) * 100);
        } else if (state.view === 'deviation') {
            raw = days.map(d => d.drift - ownAvg);
            smooth = ma.map(v => v - ownAvg);
        } else if (state.view === 'flagged') {
            // Counts, not smoothed scores: the spike IS the signal. Keep the
            // MA so long windows stay readable, but always draw raw too.
            raw = days.map(d => d.flagged);
            smooth = [...raw];
        } else {
            raw = days.map(d => d.drift);
            smooth = ma;
        }
        return { ...s, days, raw, smooth };
    });

    let yMin, yMax, yLabel, zeroLine = false;
    if (state.view === 'consistency') {
        yMin = 0; yMax = 100; yLabel = 'Consistency (%)';
    } else if (state.view === 'deviation') {
        const amp = Math.max(...prepared.flatMap(s => s.raw.map(Math.abs)), 0.01) * 1.15;
        yMin = -amp; yMax = amp; yLabel = 'Drift vs. each series’ period average'; zeroLine = true;
    } else if (state.view === 'flagged') {
        yMin = 0; yMax = Math.max(1, ...prepared.flatMap(s => s.raw)) * 1.15; yLabel = 'Flagged turns per day';
    } else {
        yMin = 0; yMax = 1; yLabel = 'Drift (lower is better)';
    }

    const allT = prepared.flatMap(s => s.days.map(d => d.t));
    const tMin = Math.min(...allT), tMaxRaw = Math.max(...allT);
    const tMax = tMaxRaw === tMin ? tMin + 1 : tMaxRaw;

    // ≤4 series are direct-labeled as well as legended, so identity never rests
    // on hue alone — this is also the relief the palette's light-mode contrast
    // warning requires. More than that and the labels would collide.
    const labelled = prepared.length > 1 && prepared.length <= 4;
    const W = 800, H = 260, PL = 46, PT = 12, PB = 28;
    const PR = labelled ? 116 : 12;
    const x = t => PL + ((t - tMin) / (tMax - tMin)) * (W - PL - PR);
    const y = v => PT + (1 - (v - yMin) / (yMax - yMin)) * (H - PT - PB);
    const fmt = v => state.view === 'consistency' ? `${Math.round(v)}%`
        : state.view === 'flagged' ? String(Math.round(v)) : v.toFixed(2);
    const dateLabel = t => new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

    const ticks = [yMin, (yMin + yMax) / 2, yMax];
    const dayCount = new Set(allT).size;
    const sortedT = [...new Set(allT)].sort((a, b) => a - b);
    const xticks = sortedT.length > 1
        ? [sortedT[0], sortedT[Math.floor(sortedT.length / 2)], sortedT[sortedT.length - 1]]
        : [sortedT[0]];

    const path = s => s.smooth.map((v, i) => `${x(s.days[i].t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');

    // Direct labels: nudge apart vertically so two series ending at a similar
    // value stay legible. Text stays in muted ink with a colored dot carrying
    // identity, rather than coloring the text itself.
    const endLabels = [];
    if (labelled) {
        const ends = prepared.map(s => ({
            label: s.label, color: s.color,
            yv: y(s.smooth[s.smooth.length - 1]),
            xv: x(s.days[s.days.length - 1].t),
        })).sort((a, b) => a.yv - b.yv);
        let prev = -Infinity;
        for (const e of ends) {
            const yy = Math.max(e.yv, prev + 12);
            endLabels.push({ ...e, yy: Math.min(yy, H - PB) });
            prev = yy;
        }
    }

    return `
        <div class="overflow-x-auto">
        <svg viewBox="0 0 ${W} ${H}" class="w-full h-auto min-w-[480px] cursor-crosshair" role="img"
             data-w="${W}" data-pl="${PL}" data-pr="${PR}"
             aria-label="${esc(yLabel)} over time${prepared.length > 1 ? `, ${prepared.length} series: ${esc(prepared.map(s => s.label).join(', '))}` : ''}">
            ${ticks.map(v => `
                <line x1="${PL}" y1="${y(v)}" x2="${W - PR}" y2="${y(v)}" class="stroke-neutral-300/40 dark:stroke-neutral-700/40" stroke-width="1" stroke-dasharray="2 2"/>
                <text x="${PL - 6}" y="${y(v) + 3}" text-anchor="end" class="fill-gray-400 text-[10px]">${fmt(v)}</text>`).join('')}
            ${zeroLine ? `<line x1="${PL}" y1="${y(0)}" x2="${W - PR}" y2="${y(0)}" class="stroke-gray-400/70" stroke-width="1" stroke-dasharray="3 3"/>` : ''}
            ${xticks.map(t => `<text x="${x(t)}" y="${H - 8}" text-anchor="middle" class="fill-gray-400 text-[10px]">${dateLabel(t)}</text>`).join('')}
            ${prepared.map(s => `
                ${state.showPoints ? s.raw.map((v, i) =>
                    `<circle cx="${x(s.days[i].t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="${s.color}" fill-opacity="0.3"><title>${esc(s.label)} · ${dateLabel(s.days[i].t)}: ${fmt(v)} (${s.days[i].n} turns)</title></circle>`).join('') : ''}
                ${s.days.length === 1
                    // A one-day series draws nothing as a polyline; show the point
                    // so the agent isn't silently missing from the chart.
                    ? `<circle cx="${x(s.days[0].t).toFixed(1)}" cy="${y(s.smooth[0]).toFixed(1)}" r="3.5" fill="${s.color}"><title>${esc(s.label)} · ${dateLabel(s.days[0].t)}: ${fmt(s.smooth[0])}</title></circle>`
                    : `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${path(s)}"><title>${esc(s.label)}</title></polyline>`}
            `).join('')}
            ${endLabels.map(e => `
                <circle cx="${(W - PR + 8).toFixed(1)}" cy="${e.yy.toFixed(1)}" r="3.5" fill="${e.color}"/>
                <text x="${(W - PR + 16).toFixed(1)}" y="${(e.yy + 3.5).toFixed(1)}" class="fill-gray-500 dark:fill-gray-400 text-[10px]">${esc(e.label.length > 18 ? e.label.slice(0, 17) + '…' : e.label)}</text>`).join('')}
        </svg>
        </div>
        ${prepared.length > 1 ? `<div class="ah-legend">${prepared.map(s => `
            <span class="ah-legend-item"><span class="ah-legend-swatch" style="background:${s.color}"></span>${esc(s.label)}</span>`).join('')}</div>` : ''}
        <p class="text-xs text-gray-400 mt-1">${esc(yLabel)} · ${state.view === 'flagged' ? 'daily counts, unsmoothed' : `${state.maDays}-day moving average`} over ${dayCount} day${dayCount === 1 ? '' : 's'}.</p>`;
}

// --- Log Explorer ----------------------------------------------------------------

// In-flight guard (2.10d): each render bumps a token; a stale response is
// discarded so fast typing never paints an older result over a newer one.
let explorerToken = 0;
let lastExplorerItems = [];   // D3: last rendered explorer rows (CSV export source)

async function renderExplorer() {
    const el = document.getElementById('ah-explorer');
    if (!el) return;
    const token = ++explorerToken;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let res;
    try {
        res = await api.listAuditEvents(orgId, {
            ...entityParams(),
            filter: state.filter || undefined,
            q: state.q || undefined,
            scope: state.scope || undefined,
            limit: PAGE_SIZE,
            offset: state.offset,
        });
    } catch (e) {
        if (token !== explorerToken) return;   // superseded by a newer query
        // Auto-fallback: the decrypt cap only applies to the prompt scope.
        // Rather than dead-ending the user with a "narrow the date range"
        // error, transparently retry the identical query as a plaintext
        // scan (pure SQL LIKE, no decryption, no cap) and say so once.
        if (state.q && state.scope !== 'plaintext' && /cap \d+\)/.test(String(e.message || e))) {
            state.scope = 'plaintext';
            const sel = document.getElementById('ah-scope');
            if (sel) sel.value = 'plaintext';
            const notice = document.getElementById('ah-cap-notice');
            if (notice) { notice.textContent =
                `Window exceeded the 5,000-record decrypt cap — automatically re-run as a plaintext scan (no decryption, no cap). Switch the scope back manually to re-enable prompt search on a narrower range.`;
                notice.classList.remove('hidden'); }
            return renderExplorer();
        }
        const hint = /cap \d+\)/.test(String(e.message || e))
            ? '<p class="text-xs text-gray-500 mt-1">Tip: switch the scope dropdown to “In user message (plaintext)” — it searches the same window without decryption and has no cap.</p>'
            : '';
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load events: ${esc(e.message || e)}</p>${hint}`;
        return;
    }
    if (token !== explorerToken) return;       // stale response, drop it
    const items = res.items || [];
    const total = res.total || 0;
    lastExplorerItems = items;   // D3: CSV export downloads the visible rows

    const rows = items.map(i => `
        <tr class="border-b border-gray-100 dark:border-neutral-800 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer" data-audit-event="${i.message_pk}">
            <td class="px-4 py-3 text-sm whitespace-nowrap">${fmtDate(i.created_at)}</td>
            <td class="px-4 py-3 text-sm">${esc((i.profile_key || '—').replace(/_/g, ' '))}
                ${i.prompt_preview ? `<div class="text-xs text-gray-400 truncate max-w-[26rem]">${esc(i.prompt_preview)}</div>` : ''}</td>
            <td class="px-4 py-3 text-sm whitespace-nowrap">
                <span class="font-medium text-gray-900 dark:text-neutral-100">${esc(i.user_name || i.user_id || '—')}</span>
                ${i.user_name && i.user_id && i.user_name !== i.user_id ? `<div class="text-xs text-gray-400 font-mono">${esc(i.user_id)}</div>` : ''}
            </td>
            <td class="px-4 py-3 text-xs font-mono whitespace-nowrap">${esc(i.intellect_model || '—')}</td>
            <td class="px-4 py-3 text-sm whitespace-nowrap" title="${esc(ALIGNMENT_HELP)}">${alignmentLabel(i.spirit_score)}</td>
            <td class="px-4 py-3 text-sm whitespace-nowrap" title="${esc(CONSISTENCY_HELP)}">${consistencyLabel(i.drift)}</td>
            <td class="px-4 py-3">${decisionBadge(i.will_decision)} ${flaggedBadge(i)}</td>
        </tr>`).join('');

    el.innerHTML = `
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
                <h4 class="text-lg font-semibold">Log Explorer</h4>
                <p class="text-xs text-gray-500 mt-0.5">Every governed turn in the period. Click a row for the full per-turn evidence.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                <input type="search" id="ah-search" value="${esc(state.q)}" placeholder="Search prompts…"
                    class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-1.5 text-xs w-52">
                <select id="ah-scope" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs" title="Where to search">
                    <option value="prompt" ${state.scope === 'prompt' ? 'selected' : ''}>In prompt (decrypt)</option>
                    <option value="plaintext" ${state.scope === 'plaintext' ? 'selected' : ''}>In user message (plaintext)</option>
                </select>
                <span id="ah-cap-notice" class="text-xs text-amber-600 hidden" aria-live="polite"></span>
                <select id="ah-filter" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
                    <option value="">All decisions</option>
                    <option value="flagged" ${state.filter === 'flagged' ? 'selected' : ''}>Flagged (Alignment &lt; 6 or Consistency &lt; 60%)</option>
                    <option value="approved" ${state.filter === 'approved' ? 'selected' : ''}>Approved</option>
                    <option value="redirected" ${state.filter === 'redirected' ? 'selected' : ''}>Redirected</option>
                    <option value="violation" ${state.filter === 'violation' ? 'selected' : ''}>Violations</option>
                </select>
            </div>
        </div>
        ${items.length === 0
            ? `<p class="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">${state.q || state.filter ? 'Nothing matches these filters.' : 'No governance records in this period yet. Turns are recorded from the moment governance shipped; widen the date range or clear filters to see more.'}</p>`
            : `<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-neutral-700">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 dark:bg-neutral-800 text-xs uppercase text-gray-500 dark:text-gray-400">
                        <tr><th class="px-4 py-3">Time</th><th class="px-4 py-3">Agent</th><th class="px-4 py-3">User</th><th class="px-4 py-3">Model</th><th class="px-4 py-3">Alignment</th><th class="px-4 py-3">Consistency</th><th class="px-4 py-3">Decision</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
               </div>`}
        ${state.q ? `<p class="text-xs text-gray-400 mt-2">${total} match${total === 1 ? '' : 'es'} across ${res.window} record${res.window === 1 ? '' : 's'} in the window · ${state.scope === 'plaintext' ? 'plaintext scan (no decryption)' : 'prompt scan (window decrypted once)'}.</p>` : ''}
        ${res.cap && state.scope !== 'plaintext' && res.window >= res.cap * 0.8 ? `<p class="text-xs text-amber-600 mt-1">Window is near the ${res.cap}-record decrypt cap — narrow the date range, or switch the scope to “In user message (plaintext)” which has no cap.</p>` : ''}
        ${total > PAGE_SIZE ? `
            <div class="flex items-center justify-between mt-3 text-xs text-gray-500">
                <span>Showing ${state.offset + 1}–${Math.min(state.offset + PAGE_SIZE, total)} of ${total}</span>
                <div class="flex gap-2">
                    <button id="ah-prev" class="px-3 py-1 border border-gray-300 dark:border-neutral-600 rounded-lg ${state.offset === 0 ? 'opacity-40' : ''}" ${state.offset === 0 ? 'disabled' : ''}>Prev</button>
                    <button id="ah-next" class="px-3 py-1 border border-gray-300 dark:border-neutral-600 rounded-lg ${state.offset + PAGE_SIZE >= total ? 'opacity-40' : ''}" ${state.offset + PAGE_SIZE >= total ? 'disabled' : ''}>Next</button>
                </div>
            </div>` : ''}`;

    let searchTimer = null;
    el.querySelector('#ah-search')?.addEventListener('input', e => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.offset = 0; renderExplorer(); }, 400);
    });
    el.querySelector('#ah-scope')?.addEventListener('change', e => {
        state.scope = e.target.value; state.offset = 0; renderExplorer();
    });
    el.querySelector('#ah-filter')?.addEventListener('change', e => {
        state.filter = e.target.value; state.offset = 0; renderExplorer();
    });
    el.querySelector('#ah-prev')?.addEventListener('click', () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); renderExplorer(); });
    el.querySelector('#ah-next')?.addEventListener('click', () => { state.offset += PAGE_SIZE; renderExplorer(); });
    el.querySelectorAll('[data-audit-event]').forEach(tr =>
        tr.addEventListener('click', () => renderDetail(tr.getAttribute('data-audit-event'))));
}

// --- Drill-down --------------------------------------------------------------------

function textCard(title, body, help = '') {
    return `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700">
            <div class="px-4 py-2 border-b border-gray-100 dark:border-neutral-800 text-xs uppercase text-gray-400">${title}</div>
            ${help ? `<div class="px-4 pt-2 text-xs text-gray-400">${help}</div>` : ''}
            <div class="px-4 py-3 text-sm whitespace-pre-wrap break-words">${body}</div>
        </div>`;
}

// 2.5 Per-value audit breakdown: the aggregate spirit_score is opaque on its
// own. `profile_values` (already fetched for the conscience modal) carries each
// value's name, weight and importance; the ledger carries its per-turn score.
// Rendered as compact bars so a reviewer sees WHY a turn scored as it did.
function valuesBreakdownCard(values, ledger) {
    if (!Array.isArray(values) || values.length === 0) return '';
    const ledgerRows = Array.isArray(ledger) ? ledger : [];
    const scoreFor = name => {
        const n = String(name || '').trim().toLowerCase();
        const row = ledgerRows.find(r => String(r?.value || r?.name || '').trim().toLowerCase() === n);
        return row ? Number(row.score || 0) : null;
    };
    const bars = values.map(v => {
        const name = v.name || v.Value || v.value || 'Unknown value';
        const weight = Number(v.weight);
        const importance = Number(v.importance);
        const score = scoreFor(name);
        // score runs -3..+3 in the two-tier model; map to 0..100% bar width.
        const pct = score === null ? null : Math.max(0, Math.min(100, ((score + 3) / 6) * 100));
        const scoreCls = score === null ? 'text-gray-400'
            : score <= -1 ? 'text-red-500' : score < 1 ? 'text-gray-500' : 'text-green-600';
        return `
        <div class="flex items-center gap-3 text-sm">
            <div class="w-40 truncate font-medium text-gray-700 dark:text-gray-300" title="${esc(name)}">${esc(name)}</div>
            <div class="flex-1 h-2 rounded-full bg-gray-100 dark:bg-neutral-800 overflow-hidden">
                ${pct === null ? '' : `<div class="h-full rounded-full ${score <= -1 ? 'bg-red-400' : score < 1 ? 'bg-gray-400' : 'bg-green-500'}" style="width:${pct.toFixed(0)}%"></div>`}
            </div>
            <div class="w-28 text-right tabular-nums ${scoreCls} whitespace-nowrap">
                ${score === null ? 'not scored' : `score ${score > 0 ? '+' : ''}${score.toFixed(1)}`}
                ${Number.isFinite(weight) ? ` · w${weight}` : ''}
                ${Number.isFinite(importance) ? ` · imp ${importance}` : ''}
            </div>
        </div>`;
    }).join('');
    return `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700">
            <div class="px-4 py-2 border-b border-gray-100 dark:border-neutral-800 text-xs uppercase text-gray-400">Why this alignment score</div>
            <div class="px-4 py-3 space-y-2">${bars}</div>
        </div>`;
}

// Renders the agent's tool loop — what it DID, not just what it said.
//
// The governance capture had no tool field at all until 2026-07-31: each tool
// call was journaled into the hash-chained trail, but the Audit Hub and the
// examiner export both read the capture, so the record was tamper-evident and
// unreadable by the people it exists for. `params` values are clipped
// server-side, so this never renders a payload.
function toolCallsCard(calls) {
    if (!Array.isArray(calls) || calls.length === 0) return '';
    const rows = calls.map(c => {
        // Orchestrator records use tool/params; agentic tool proposals use
        // tool_name/parameters, and returned client (e.g. safi-cli) results use
        // tool_name/arguments. Read all three shapes so older and newer turns
        // remain legible in the same audit timeline.
        const tool = c.tool || c.tool_name || 'unknown tool';
        const rawParams = c.params ?? c.parameters ?? c.arguments ?? {};
        const paramsObject = rawParams && typeof rawParams === 'object' && !Array.isArray(rawParams)
            ? rawParams : {};
        const hasResult = Object.prototype.hasOwnProperty.call(c, 'result');
        const status = c.decision === 'approve' ? 'approved'
            : (c.decision === 'violation' || c.decision === 'blocked') ? 'blocked'
            : c.decision || (hasResult ? 'executed' : 'proposed');
        const statusColor = status === 'approved' || status === 'executed' ? '#15803d'
            : status === 'blocked' ? '#b91c1c' : '#6b7280';
        const badge = `<span class="text-xs font-semibold" style="color:${statusColor}">${esc(status)}</span>`;
        const params = Object.keys(paramsObject).length
            ? Object.entries(paramsObject).map(([k, v]) => `${esc(k)}=${esc(String(v))}`).join(', ')
            : '—';
        return `
            <div class="px-4 py-3 border-b border-gray-100 dark:border-neutral-800 last:border-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <code class="text-sm font-semibold">${esc(tool)}</code>
                    ${badge}
                    ${c.agent_turn ? `<span class="text-xs text-gray-400">step ${esc(String(c.agent_turn))}</span>` : ''}
                </div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mt-1 break-words">${params}</div>
                ${c.reason ? `<div class="text-xs text-gray-400 mt-1 break-words">${esc(c.reason)}</div>` : ''}
            </div>`;
    }).join('');
    return `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700">
            <div class="px-4 py-2 border-b border-gray-100 dark:border-neutral-800 text-xs uppercase text-gray-400">Tools used</div>
            <div class="px-4 pt-2 text-xs text-gray-400">Tool proposals and the Will's verdicts, plus calls returned by the agentic client.</div>
            ${rows}
        </div>`;
}

async function renderDetail(messagePk) {
    const el = document.getElementById('ah-explorer');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let doc;
    try {
        doc = await api.getAuditEvent(orgId, messagePk);
    } catch (e) {
        ui.showToast(e.message || 'Failed to load the event', 'error');
        renderExplorer();
        return;
    }
    const ev = doc.event || {};
    const r = doc.record || {};
    // D2 cross-surface deep link: the drill-down already joins review_queue, so
    // the badge is now a link — it switches to the Review tab and opens the
    // sampled item there instead of forcing the reviewer to hunt for it.
    const reviewNote = doc.review
        ? `<button type="button" data-open-review="${esc(String(doc.review.queue_id ?? doc.review.id ?? ''))}" class="${BADGE} bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200 capitalize hover:ring-2 hover:ring-green-400" title="This turn was sampled into the supervisory review queue. Click to open it in the Review tab.">In review queue · ${esc(doc.review.status)} &rarr;</button>`
        : '';
    // Org governance records deliberately survive member deletion — flag it.
    const deletedNote = !doc.chat
        ? `<span class="${BADGE} bg-gray-100 text-gray-700 dark:bg-neutral-800 dark:text-gray-300" title="The member deleted this conversation. The organization's governance record is retained and will be destroyed by the retention policy.">Conversation deleted by member</span>`
        : '';

    // Which model performed the policy audit. New records carry it in the
    // encrypted capture; older ones fall back to chat_history.model_attribution
    // ("provider/model"), which is lost if the member deleted the conversation.
    let auditModel = r.conscienceModel || null;
    if (!auditModel && doc.chat && doc.chat.model_attribution) {
        try {
            const attr = JSON.parse(doc.chat.model_attribution).conscience || '';
            auditModel = attr.split('/').slice(1).join('/') || attr;
        } catch { /* unparseable legacy value — omit */ }
    }

    let auditValues = r.profileValues ?? doc.chat?.profile_values ?? [];
    if (typeof auditValues === 'string') {
        try { auditValues = JSON.parse(auditValues); } catch { auditValues = []; }
    }
    if (!Array.isArray(auditValues)) auditValues = [];

    const sections = [
        ['draft', 'AI Draft'],
        ['decision', 'Decision'],
        ['audit', 'Policy Audit'],
        ['alignment', 'Alignment'],
        ['output', 'Final Output'],
    ];

    const failingRows = (Array.isArray(r.originalLedger) ? r.originalLedger : [])
        .filter(row => row && typeof row === 'object' && Number(row.score || 0) <= -1);
    const hasPolicyAudit = Array.isArray(r.conscienceLedger) && r.conscienceLedger.length > 0
        && !r.clientToolProposal && r.turnKind !== 'tool_proposal';
    const toolOnlyTurn = r.toolOnlyTurn === true || r.clientToolProposal === true
        || r.turnKind === 'tool_proposal'
        || (ev.will_stage === 'tool_intent' && !hasPolicyAudit);
    const hasToolProposalLedger = Array.isArray(r.toolProposalLedger) && r.toolProposalLedger.length > 0;
    const auditFailureReason = r.auditFailureReason || r.willReason || null;
    const policyAuditState = hasPolicyAudit && !toolOnlyTurn
        ? null
        : toolOnlyTurn && !hasToolProposalLedger
            ? 'This is a tool handoff, not a response draft. SAFi checked the proposed tool against the agent and policy allow-lists; the coding client executes it and sends the result back for the response audit.'
            : toolOnlyTurn
                ? 'This is a tool handoff, not a response draft. SAFi checked the tool authorization and evaluated these tool-proposal safeguards; the final response is audited when the coding client returns the result.'
                : ev.will_stage === 'phase_zero'
                    ? 'No policy audit was run: the request was blocked by the pre-generation safety gate.'
                : ev.will_stage === 'structure'
                    ? 'No policy audit was run: the draft failed the response-structure check before Conscience.'
                    : ev.will_stage === 'audit'
                        ? `The policy audit could not be completed successfully. See the Decision tab and reasoning log for the failure.${auditFailureReason ? ` Detail: ${auditFailureReason}` : ''}`
                        : !r.conscienceLedger
                            ? 'No policy audit record is available for this turn. It may be a legacy record from before value-by-value ledgers were stored.'
                            : 'No value-by-value evaluation was recorded for this turn.';

    const sectionHtml = {
        draft: `
            <div class="space-y-4">
                ${textCard('Generated response', esc(r.intellectDraft || r.externalOutput || '—'))}
                ${r.intellectReflection ? textCard('AI reasoning', esc(r.intellectReflection)) : ''}
                ${toolCallsCard(r.toolCalls)}
                ${r.memorySummary ? textCard('Context — memory summary', esc(r.memorySummary)) : ''}
                ${r.recentTurns ? textCard('Context — recent turns', esc(r.recentTurns)) : ''}
                ${r.retrievedContext ? textCard('Context — retrieved documents', esc(r.retrievedContext)) : ''}
                ${r.agentWorkContext ? textCard('Context — work memory', esc(r.agentWorkContext),
                    'The agent’s accumulated work-context memory as injected this turn (budgeted copy). Entries carry updated/src stamps; src is the message id of the governed turn that stated the fact.') : ''}
                ${r.spiritFeedback ? textCard('Context — self-correction nudge', esc(r.spiritFeedback),
                    'Injected into the agent’s prompt for this turn because recent consistency had slipped. Deliberately blind: it names at most one value and never contains scoring criteria, so the agent cannot optimize toward the audit.') : ''}
            </div>`,
        decision: `
            <div class="space-y-4">
                <div class="flex items-center gap-2">${decisionBadge(ev.will_decision)}${ev.will_stage ? `<span class="text-xs text-gray-400">at ${esc(String(ev.will_stage).replace(/_/g, ' '))}</span>` : ''}</div>
                ${textCard('Reason', `${esc(explainWillReason(r.willReason, r.willDecision || ev.will_decision))}${r.willReason ? `<div class="text-xs text-gray-400 font-mono mt-2">Gate code: ${esc(r.willReason)}</div>` : ''}`)}
                ${failingRows.length ? `
                    <div class="rounded-lg border border-red-200 dark:border-red-900">
                        <div class="px-4 py-2 border-b border-red-100 dark:border-red-900/60 text-xs uppercase text-red-500">Audit justification for the block</div>
                        <div class="px-4 py-3 space-y-2">
                            ${failingRows.map(row => `<div class="text-sm"><span class="font-semibold">${esc(row.value || 'Unknown value')}</span> <span class="text-red-500">(score ${Number(row.score || 0) > 0 ? '+' : ''}${Number(row.score || 0).toFixed(1)})</span>: ${esc(row.reason || row.reflection || 'No justification recorded.')}</div>`).join('')}
                        </div>
                    </div>` : ''}
                ${r.blockedDraft ? textCard('Blocked draft', esc(r.blockedDraft)) : ''}
            </div>`,
        audit: hasPolicyAudit && !toolOnlyTurn
            ? renderConscienceReport({
                ledger: r.conscienceLedger,
                spirit_score: r.spiritScore,
                profile: r.agentName || ev.profile_key,
                policy_id: r.policyId || ev.policy_id,
                policy_version: r.policyVersion ?? ev.policy_version,
                will_reason: r.willReason || null,
                is_redirect: r.isRedirect === true,
                final_output: r.finalOutput || null,
                values: auditValues,
            }, 'ah-')
            : `<div class="space-y-3"><p class="text-sm text-gray-400">${esc(policyAuditState)}</p>${toolOnlyTurn && hasToolProposalLedger ? `<div class="space-y-2">${r.toolProposalLedger.map(row => `<div class="text-sm"><span class="font-medium">${esc(row.value || 'safeguard')}</span> — ${esc(row.score > 0 ? 'passed' : row.score < 0 ? 'failed' : 'neutral')}<span class="text-gray-500">: ${esc(row.reason || '')}</span></div>`).join('')}</div>` : ''}</div>`,
        alignment: `
            <div class="space-y-4">
                <div class="grid grid-cols-2 gap-3">
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3" title="${esc(ALIGNMENT_HELP)}">
                        <div class="text-xs uppercase text-gray-400">Alignment</div>
                        <div class="text-2xl font-bold mt-0.5 tabular-nums">${alignmentLabel(ev.spirit_score)}</div>
                    </div>
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3" title="${esc(CONSISTENCY_HELP)}">
                        <div class="text-xs uppercase text-gray-400">Consistency</div>
                        <div class="text-2xl font-bold mt-0.5 tabular-nums">${consistencyLabel(ev.drift)}</div>
                    </div>
                </div>
                ${valuesBreakdownCard(auditValues, r.conscienceLedger)}
                ${r.spiritNote ? textCard('Consistency note', esc(r.spiritNote)) : ''}
            </div>`,
        output: `
            <div class="space-y-4">
                ${textCard('User prompt', esc(r.userPrompt || '—'))}
                ${textCard('Final output to user', esc(r.finalOutput || '—'))}
            </div>`,
    };

    el.innerHTML = `
        <button id="ah-back" class="text-sm text-green-600 hover:underline mb-4">&larr; Back to explorer</button>
        <div class="flex flex-wrap items-center gap-2 mb-1">
            ${decisionBadge(ev.will_decision)} ${chainBadge(doc.trail)} ${reviewNote} ${deletedNote}
        </div>
        <div class="text-xs text-gray-400 mb-4">
            ${fmtDate(ev.created_at)} · ${esc((ev.profile_key || '—').replace(/_/g, ' '))}
            ${(ev.user_name || ev.user_id) ? ` · user <strong class="text-gray-700 dark:text-neutral-200 font-medium">${esc(ev.user_name || ev.user_id)}${ev.user_name && ev.user_id && ev.user_name !== ev.user_id ? ` (${esc(ev.user_id)})` : ''}</strong>` : ''}
            ${ev.policy_id ? ` · policy ${esc(String(ev.policy_id).replace(/_/g, ' '))}${ev.policy_version ? ` (v${esc(ev.policy_version)})` : ''}` : ''}
            ${ev.intellect_model ? ` · <span class="font-mono">${esc(ev.intellect_model)}</span>` : ''}
            ${auditModel ? ` · <span title="Model that performed the per-value policy audit for this turn">audited by <span class="font-mono">${esc(auditModel)}</span></span>` : ''}
        </div>
        ${!doc.record ? `<p class="text-sm text-amber-600 dark:text-amber-400 mb-4">The encrypted record for this turn could not be decoded — provenance columns and the chain verification above remain valid.</p>` : ''}
        <div class="border-b border-gray-200 dark:border-gray-700 mb-4">
            <nav class="flex flex-wrap -mb-px" aria-label="Sections">
                ${sections.map(([key, label], idx) => `
                    <button data-ah-section="${key}" class="ah-section-btn px-4 py-2 text-sm font-medium border-b-2 ${idx === 0 ? 'border-green-500 text-green-600 dark:text-green-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}">${label}</button>`).join('')}
            </nav>
        </div>
        ${sections.map(([key], idx) => `<div id="ah-panel-${key}" class="${idx === 0 ? '' : 'hidden'}">${sectionHtml[key]}</div>`).join('')}
        <div class="mt-6 flex justify-end">
            <button id="ah-dl-entry" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg">Download this record (JSON)</button>
        </div>`;

    attachTabSwitching(el); // for the conscience report inside Policy Audit
    el.querySelector('#ah-back')?.addEventListener('click', () => renderExplorer());
    // D2: badge click → switch to the Review tab and open the sampled item.
    el.querySelector('[data-open-review]')?.addEventListener('click', e => {
        const id = e.currentTarget.getAttribute('data-open-review');
        if (!id) return;
        import('./ui-settings-review.js').then(m => m.openReviewItemDeep(id));
    });
    el.querySelectorAll('.ah-section-btn').forEach(btn => btn.addEventListener('click', () => {
        el.querySelectorAll('.ah-section-btn').forEach(b => {
            const active = b === btn;
            b.classList.toggle('border-green-500', active);
            b.classList.toggle('text-green-600', active);
            b.classList.toggle('dark:text-green-400', active);
            b.classList.toggle('border-transparent', !active);
            b.classList.toggle('text-gray-500', !active);
        });
        sections.forEach(([key]) => {
            el.querySelector(`#ah-panel-${key}`)?.classList.toggle('hidden', key !== btn.getAttribute('data-ah-section'));
        });
    }));
    el.querySelector('#ah-dl-entry')?.addEventListener('click', () => {
        const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `safi-audit-event-${messagePk}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    });
}
