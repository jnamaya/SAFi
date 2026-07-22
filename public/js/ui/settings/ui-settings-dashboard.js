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
    'confidence, then combined into a 1–10 grade for the turn. Higher is better.';
const CONSISTENCY_HELP =
    'How closely this turn’s value expression matches the agent’s own historical ' +
    'pattern. 100% means the agent behaved as it usually does; a low value flags an ' +
    'out-of-character turn, even if that turn scored well on its own. N/A on an ' +
    'agent’s first turns, before a history exists.';

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
    return WILL_REASON_EXPLANATIONS[code] || `Unrecognized gate code: ${code}`;
}

const BADGE = 'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap';

function decisionBadge(decision) {
    const map = {
        approve: ['Approved', 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200'],
        redirected: ['Redirected', 'bg-purple-100 text-purple-800 dark:bg-purple-900/60 dark:text-purple-200'],
        violation: ['Violation', 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200'],
    };
    const [label, cls] = map[decision] || [decision || 'Unknown', 'bg-gray-100 text-gray-700 dark:bg-neutral-800 dark:text-gray-300'];
    return `<span class="${BADGE} ${cls}">${esc(label)}</span>`;
}

function chainBadge(chain) {
    if (!chain) return '';
    return chain.valid
        ? `<span class="${BADGE} bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200" title="${chain.entries} audit-trail entries recomputed and verified">Chain verified ✓</span>`
        : `<span class="${BADGE} bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200" title="First bad entry: ${esc(chain.first_bad_id)}">CHAIN INVALID</span>`;
}

function flaggedBadge(ev) {
    const flagged = (ev.spirit_score !== null && ev.spirit_score < 6) ||
        (ev.drift !== null && ev.drift > 0.4);
    return flagged ? `<span class="${BADGE} bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200">Flagged</span>` : '';
}

function rangeDates() {
    if (state.range === 'all') return {};
    const days = state.range === '7d' ? 7 : 30;
    return { from: new Date(Date.now() - days * 86400000).toISOString() };
}

function entityParams() {
    const p = rangeDates();
    if (state.mode === 'policy' && state.entity) p.policy_id = state.entity;
    if (state.mode === 'agent' && state.entity) p.profile = state.entity;
    return p;
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
    state = { mode: 'agent', entity: '', range: '30d', filter: '', q: '', offset: 0,
              maDays: 7, view: 'deviation', showPoints: false, filters: { profiles: [], policies: [] } };

    try {
        state.filters = await api.getAuditFilters(orgId);
    } catch (e) { /* pickers stay empty; data may simply not exist yet */ }

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
            <div id="ah-trend" class="settings-card"></div>
            <div id="ah-explorer" class="settings-card"></div>
        </div>`;

    renderControls();
    refreshData();
}

function renderControls() {
    const el = document.getElementById('ah-controls');
    if (!el) return;
    const opts = state.mode === 'policy' ? state.filters.policies : state.filters.profiles;
    const sel = (id, entries, cur) => `
        <select id="${id}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
            ${entries.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(l)}</option>`).join('')}
        </select>`;
    el.innerHTML = `
        ${sel('ah-mode', [['agent', 'By agent'], ['policy', 'By policy']], state.mode)}
        ${sel('ah-entity', [['', state.mode === 'policy' ? 'All policies' : 'All agents'],
            ...opts.map(o => [o, String(o).replace(/_/g, ' ')])], state.entity)}
        ${sel('ah-range', [['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['all', 'All time']], state.range)}
        <button id="ah-export" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg whitespace-nowrap" title="Downloads the decrypted records matching the current filters. The export is recorded in the compliance evidence log.">Export JSON</button>
    `;
    el.querySelector('#ah-mode')?.addEventListener('change', e => {
        state.mode = e.target.value; state.entity = ''; state.offset = 0;
        renderControls(); refreshData();
    });
    el.querySelector('#ah-entity')?.addEventListener('change', e => {
        state.entity = e.target.value; state.offset = 0; refreshData();
    });
    el.querySelector('#ah-range')?.addEventListener('change', e => {
        state.range = e.target.value; state.offset = 0; refreshData();
    });
    el.querySelector('#ah-export')?.addEventListener('click', () => {
        window.open(api.auditExportUrl(orgId, { ...entityParams(), filter: state.filter || undefined }), '_blank');
    });
}

function refreshData() {
    loadKpis();
    loadTrend();
    renderExplorer();
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
                    <linearGradient id="ahg-green" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#10b981"/><stop offset="100%" stop-color="#34d399"/></linearGradient>
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
            <div class="text-2xl font-bold mt-0.5">${value}</div>
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
                           'all scored turns', CONSISTENCY_HELP)}
                    ${tile('Interventions', s.interventions,
                           `${s.intervention_rate !== null && s.intervention_rate !== undefined ? s.intervention_rate.toFixed(1) : '0.0'}% of responses redirected${redirectSub ? ' · ' + redirectSub : ''}${s.violations ? ` · ${s.violations} gateway violation${s.violations === 1 ? '' : 's'}` : ''}`)}
                    ${tile('Total Audits', s.total_audits, `${s.flagged} flagged in period`)}
                </div>
            </div>
        </div>`;
}

// --- Consistency trend ---------------------------------------------------------

async function loadTrend() {
    const el = document.getElementById('ah-trend');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let buckets;
    try {
        buckets = (await api.getAuditTrend(orgId, entityParams())).buckets || [];
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load the trend: ${esc(e.message || e)}</p>`;
        return;
    }
    const scored = buckets.filter(b => b.avg_drift !== null && b.avg_drift !== undefined);

    const sel = (id, entries, cur) => `
        <select id="${id}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
            ${entries.map(([v, l]) => `<option value="${v}" ${String(v) === String(cur) ? 'selected' : ''}>${l}</option>`).join('')}
        </select>`;

    el.innerHTML = `
        <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div>
                <h4 class="text-lg font-semibold">Agent Consistency Trend</h4>
                <p class="text-xs text-gray-500 mt-0.5" title="${esc(CONSISTENCY_HELP)}">Daily consistency of value expression against the agent's own history.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                ${sel('ah-ma', [[3, 'MA: 3 days'], [7, 'MA: 7 days'], [14, 'MA: 14 days'], [30, 'MA: 30 days']], state.maDays)}
                ${sel('ah-view', [['consistency', 'Consistency (%)'], ['drift', 'Drift (0=best)'], ['deviation', 'Drift vs. average']], state.view)}
                <label class="flex items-center gap-1.5 text-xs text-gray-500"><input type="checkbox" id="ah-points" ${state.showPoints ? 'checked' : ''}> Raw points</label>
            </div>
        </div>
        <div id="ah-trend-chart">${scored.length < 2
            ? `<p class="text-sm text-gray-400 py-8 text-center">Not enough drift data in this period to draw a trend line.</p>`
            : buildTrendChart(scored)}</div>`;

    el.querySelector('#ah-ma')?.addEventListener('change', e => { state.maDays = parseInt(e.target.value, 10); loadTrend(); });
    el.querySelector('#ah-view')?.addEventListener('change', e => { state.view = e.target.value; loadTrend(); });
    el.querySelector('#ah-points')?.addEventListener('change', e => { state.showPoints = e.target.checked; loadTrend(); });
}

// Reusable SVG line chart over daily buckets. Moving average is turn-weighted
// over a trailing window of state.maDays days — the smoothing (like the view
// mode) is a display choice, mirroring the Streamlit selectors.
function buildTrendChart(scored) {
    const days = scored.map(b => ({
        t: new Date(b.bucket + 'T00:00:00Z').getTime(),
        drift: b.avg_drift,
        n: b.scored_turns || 1,
    }));
    const avgDrift = days.reduce((a, d) => a + d.drift * d.n, 0) / days.reduce((a, d) => a + d.n, 0);
    const windowMs = state.maDays * 86400000;
    const ma = days.map((d, i) => {
        let num = 0, den = 0;
        for (let k = i; k >= 0 && d.t - days[k].t < windowMs; k--) {
            num += days[k].drift * days[k].n;
            den += days[k].n;
        }
        return num / den;
    });

    let raw, smooth, yMin, yMax, yLabel, zeroLine = false;
    if (state.view === 'consistency') {
        raw = days.map(d => (1 - d.drift) * 100);
        smooth = ma.map(v => (1 - v) * 100);
        yMin = 0; yMax = 100; yLabel = 'Consistency (%)';
    } else if (state.view === 'deviation') {
        raw = days.map(d => d.drift - avgDrift);
        smooth = ma.map(v => v - avgDrift);
        const amp = Math.max(...raw.map(Math.abs), 0.01) * 1.15;
        yMin = -amp; yMax = amp; yLabel = 'Drift vs. period average'; zeroLine = true;
    } else {
        raw = days.map(d => d.drift);
        smooth = ma;
        yMin = 0; yMax = 1; yLabel = 'Drift (lower is better)';
    }

    const W = 800, H = 260, PL = 46, PR = 12, PT = 12, PB = 28;
    const tMin = days[0].t, tMax = days[days.length - 1].t || tMin + 1;
    const x = t => PL + ((t - tMin) / Math.max(1, tMax - tMin)) * (W - PL - PR);
    const y = v => PT + (1 - (v - yMin) / (yMax - yMin)) * (H - PT - PB);
    const fmt = v => state.view === 'consistency' ? `${Math.round(v)}%` : v.toFixed(2);
    const dateLabel = t => new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

    const ticks = [yMin, (yMin + yMax) / 2, yMax];
    const xticks = days.length > 1
        ? [days[0].t, days[Math.floor(days.length / 2)].t, days[days.length - 1].t]
        : [days[0].t];

    const line = pts => pts.map((v, i) => `${x(days[i].t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');

    return `
        <div class="overflow-x-auto">
        <svg viewBox="0 0 ${W} ${H}" class="w-full h-auto min-w-[480px]" role="img" aria-label="${esc(yLabel)} over time">
            ${ticks.map(v => `
                <line x1="${PL}" y1="${y(v)}" x2="${W - PR}" y2="${y(v)}" class="stroke-neutral-300/40 dark:stroke-neutral-700/40" stroke-width="1" stroke-dasharray="2 2"/>
                <text x="${PL - 6}" y="${y(v) + 3}" text-anchor="end" class="fill-gray-400 text-[10px]">${fmt(v)}</text>`).join('')}
            ${zeroLine ? `<line x1="${PL}" y1="${y(0)}" x2="${W - PR}" y2="${y(0)}" class="stroke-gray-400/70" stroke-width="1" stroke-dasharray="3 3"/>` : ''}
            ${xticks.map(t => `<text x="${x(t)}" y="${H - 8}" text-anchor="middle" class="fill-gray-400 text-[10px]">${dateLabel(t)}</text>`).join('')}
            ${state.showPoints ? raw.map((v, i) =>
                `<circle cx="${x(days[i].t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" class="fill-emerald-500/25"><title>${dateLabel(days[i].t)}: ${fmt(v)} (${days[i].n} turns)</title></circle>`).join('') : ''}
            <polyline fill="none" class="stroke-emerald-500 dark:stroke-emerald-400" stroke-width="2" points="${line(smooth)}"/>
        </svg>
        </div>
        <p class="text-xs text-gray-400 mt-1">${esc(yLabel)} · ${state.maDays}-day moving average over ${days.length} day${days.length === 1 ? '' : 's'}.</p>`;
}

// --- Log Explorer ----------------------------------------------------------------

async function renderExplorer() {
    const el = document.getElementById('ah-explorer');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let res;
    try {
        res = await api.listAuditEvents(orgId, {
            ...entityParams(),
            filter: state.filter || undefined,
            q: state.q || undefined,
            limit: PAGE_SIZE,
            offset: state.q ? undefined : state.offset,
        });
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load events: ${esc(e.message || e)}</p>`;
        return;
    }
    const items = res.items || [];
    const total = res.total || 0;

    const rows = items.map(i => `
        <tr class="border-b border-gray-100 dark:border-neutral-800 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer" data-audit-event="${i.message_pk}">
            <td class="px-4 py-3 text-sm whitespace-nowrap">${fmtDate(i.created_at)}</td>
            <td class="px-4 py-3 text-sm">${esc((i.profile_key || '—').replace(/_/g, ' '))}
                ${i.prompt_preview ? `<div class="text-xs text-gray-400 truncate max-w-[26rem]">${esc(i.prompt_preview)}</div>` : ''}</td>
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
            ? `<p class="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">${state.q || state.filter ? 'Nothing matches these filters.' : 'No governance records in this period yet. New turns are recorded from the moment this feature shipped; older history stays in the legacy dashboard until its sunset.'}</p>`
            : `<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-neutral-700">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 dark:bg-neutral-800 text-xs uppercase text-gray-500 dark:text-gray-400">
                        <tr><th class="px-4 py-3">Time</th><th class="px-4 py-3">Agent</th><th class="px-4 py-3">Model</th><th class="px-4 py-3">Alignment</th><th class="px-4 py-3">Consistency</th><th class="px-4 py-3">Decision</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
               </div>`}
        ${state.q
            ? `<p class="text-xs text-gray-400 mt-2">Showing the ${items.length} newest match${items.length === 1 ? '' : 'es'} across ${res.window} record${res.window === 1 ? '' : 's'} in the window.</p>`
            : total > PAGE_SIZE ? `
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
    const reviewNote = doc.review
        ? `<span class="${BADGE} bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-200 capitalize" title="This turn was sampled into the supervisory review queue">In review queue · ${esc(doc.review.status)}</span>`
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

    const sections = [
        ['draft', 'AI Draft'],
        ['decision', 'Decision'],
        ['audit', 'Policy Audit'],
        ['alignment', 'Alignment'],
        ['output', 'Final Output'],
    ];

    const failingRows = (Array.isArray(r.originalLedger) ? r.originalLedger : [])
        .filter(row => row && typeof row === 'object' && Number(row.score || 0) <= -1);

    const sectionHtml = {
        draft: `
            <div class="space-y-4">
                ${textCard('Generated response', esc(r.intellectDraft || r.externalOutput || '—'))}
                ${r.intellectReflection ? textCard('AI reasoning', esc(r.intellectReflection)) : ''}
                ${r.memorySummary ? textCard('Context — memory summary', esc(r.memorySummary)) : ''}
                ${r.recentTurns ? textCard('Context — recent turns', esc(r.recentTurns)) : ''}
                ${r.retrievedContext ? textCard('Context — retrieved documents', esc(r.retrievedContext)) : ''}
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
        audit: (Array.isArray(r.conscienceLedger) && r.conscienceLedger.length)
            ? renderConscienceReport({
                ledger: r.conscienceLedger,
                spirit_score: r.spiritScore,
                profile: r.agentName || ev.profile_key,
                policy_id: r.policyId || ev.policy_id,
                policy_version: r.policyVersion ?? ev.policy_version,
            }, 'ah-')
            : `<p class="text-sm text-gray-400">No value-by-value evaluation was recorded for this turn${ev.will_stage === 'phase_zero' ? ' — it was blocked before the audit stage' : ''}.</p>`,
        alignment: `
            <div class="space-y-4">
                <div class="grid grid-cols-2 gap-3">
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3" title="${esc(ALIGNMENT_HELP)}">
                        <div class="text-xs uppercase text-gray-400">Alignment</div>
                        <div class="text-2xl font-bold mt-0.5">${alignmentLabel(ev.spirit_score)}</div>
                    </div>
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3" title="${esc(CONSISTENCY_HELP)}">
                        <div class="text-xs uppercase text-gray-400">Consistency</div>
                        <div class="text-2xl font-bold mt-0.5">${consistencyLabel(ev.drift)}</div>
                    </div>
                </div>
                ${r.spiritNote ? textCard('Consistency note', esc(r.spiritNote)) : ''}
            </div>`,
        output: `
            <div class="space-y-4">
                ${textCard('User prompt', esc(r.userPrompt || '—'))}
                ${textCard('Final output to user', esc(r.finalOutput || '—'))}
            </div>`,
    };

    el.innerHTML = `
        <button id="ah-back" class="text-sm text-blue-600 hover:underline mb-4">&larr; Back to explorer</button>
        <div class="flex flex-wrap items-center gap-2 mb-1">
            ${decisionBadge(ev.will_decision)} ${chainBadge(doc.trail)} ${reviewNote} ${deletedNote}
        </div>
        <div class="text-xs text-gray-400 mb-4">
            ${fmtDate(ev.created_at)} · ${esc((ev.profile_key || '—').replace(/_/g, ' '))}
            ${ev.policy_id ? ` · policy ${esc(String(ev.policy_id).replace(/_/g, ' '))}${ev.policy_version ? ` (v${esc(ev.policy_version)})` : ''}` : ''}
            ${ev.intellect_model ? ` · <span class="font-mono">${esc(ev.intellect_model)}</span>` : ''}
            ${auditModel ? ` · <span title="Model that performed the per-value policy audit for this turn">audited by <span class="font-mono">${esc(auditModel)}</span></span>` : ''}
        </div>
        ${!doc.record ? `<p class="text-sm text-amber-600 dark:text-amber-400 mb-4">The encrypted record for this turn could not be decoded — provenance columns and the chain verification above remain valid.</p>` : ''}
        <div class="border-b border-gray-200 dark:border-gray-700 mb-4">
            <nav class="flex flex-wrap -mb-px" aria-label="Sections">
                ${sections.map(([key, label], idx) => `
                    <button data-ah-section="${key}" class="ah-section-btn px-4 py-2 text-sm font-medium border-b-2 ${idx === 0 ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}">${label}</button>`).join('')}
            </nav>
        </div>
        ${sections.map(([key], idx) => `<div id="ah-panel-${key}" class="${idx === 0 ? '' : 'hidden'}">${sectionHtml[key]}</div>`).join('')}
        <div class="mt-6 flex justify-end">
            <button id="ah-dl-entry" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg">Download this record (JSON)</button>
        </div>`;

    attachTabSwitching(el); // for the conscience report inside Policy Audit
    el.querySelector('#ah-back')?.addEventListener('click', () => renderExplorer());
    el.querySelectorAll('.ah-section-btn').forEach(btn => btn.addEventListener('click', () => {
        el.querySelectorAll('.ah-section-btn').forEach(b => {
            const active = b === btn;
            b.classList.toggle('border-emerald-500', active);
            b.classList.toggle('text-emerald-600', active);
            b.classList.toggle('dark:text-emerald-400', active);
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
