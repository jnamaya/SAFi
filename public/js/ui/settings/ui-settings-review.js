// Review tab: the org's human-oversight act surface (FINRA 3110/3120
// supervisory review; EU AI Act Art. 14). Sampled turns land in the queue
// via the server-side hook; reviewers (admin|auditor — editors are content
// authors and don't supervise themselves) approve or override each item.
// Review is post-hoc supervision, never a delivery gate: an override does
// NOT retract a delivered message — it records the firm's documented
// supervisory determination about it, hash-chained into the audit trail.
// The Audit Hub stays observe-only; this tab is where governance data gets
// acted on. Vocabulary: Alignment (/10) and Consistency (%) — never faculty
// names as UI labels (glossary bridge lives in exports only).
import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { renderConscienceReport, attachTabSwitching } from './ui-modal-conscience.js';

let orgId = null;
let currentUser = null;
// Multi-select filter state: arrays (rows match ANY selected value).
let filters = { status: ['pending'], trigger: [], from: '', to: '' };
let sort = { key: 'created_at', desc: true }; // server-side sort (see _parse_sort)
let offset = 0;
let pageSize = 50;                            // T3c: page-size control (10–200)
let selected = new Set();                     // queue ids checked for bulk Approve
let lastItems = [];                           // last rendered page, for j/k nav
let cursor = 0;                               // keyboard cursor into lastItems
let loadSeq = 0;                              // guards stale queue responses
let keysBound = false;

// --- URL-synced filter state (Tier 1) ----------------------------------------
// The queue view is linkable: filters, sort, page size and offset live in the
// URL so a filtered view can be shared/bookmarked (and the Audit Hub drill-down
// stays stable). replaceState only — no history spam on every keystroke.

function syncUrl() {
    const p = new URLSearchParams();
    const defaultStatus = filters.status.length === 1 && filters.status[0] === 'pending';
    if (filters.status.length && !defaultStatus) p.set('status', filters.status.join(','));
    if (filters.trigger.length) p.set('trigger', filters.trigger.join(','));
    if (filters.from) p.set('from', filters.from);
    if (filters.to) p.set('to', filters.to);
    if (sort.key !== 'created_at' || !sort.desc) p.set('sort', `${sort.key}:${sort.desc ? 'desc' : 'asc'}`);
    if (pageSize !== 50) p.set('ps', String(pageSize));
    if (offset) p.set('off', String(offset));
    const qs = p.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : '') + (window.location.hash || ''));
}

function readUrl() {
    const p = new URLSearchParams(window.location.search);
    const s = p.get('status');
    if (s !== null) filters.status = s ? s.split(',').filter(Boolean) : [];
    const t = p.get('trigger');
    if (t !== null) filters.trigger = t.split(',').filter(Boolean);
    if (p.get('from')) filters.from = p.get('from');
    if (p.get('to')) filters.to = p.get('to');
    const so = p.get('sort');
    if (so) { const [k, d] = so.split(':'); sort = { key: k, desc: d !== 'asc' }; }
    const ps = parseInt(p.get('ps'), 10);
    if (ps) pageSize = Math.min(Math.max(ps, 10), 200);
    const off = parseInt(p.get('off'), 10);
    if (off > 0) offset = off;
}

// D2 cross-surface deep link: the Audit Hub drill-down links into the Review
// queue. Switches to the Review tab (clicking the sidebar nav so the core
// module's own tab logic runs), waits for the async tab render, then opens the
// queue item directly instead of leaving the reviewer to hunt for it.
export async function openReviewItemDeep(queueId) {
    if (!document.getElementById('review-queue')) {
        const nav = document.querySelector('[data-tab="review"]');
        if (nav) nav.click();
        // renderSettingsReviewTab fetches the org before it builds the DOM.
        for (let i = 0; i < 50 && !document.getElementById('review-queue'); i++) {
            await new Promise(r => setTimeout(r, 100));
        }
    }
    await renderDetail(queueId);
}

export function setReviewCurrentUser(u) {
    currentUser = u;
}

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtDate(v) {
    if (!v) return '—';
    const d = new Date(v);
    return isNaN(d) ? esc(v) : d.toLocaleString();
}

function age(v) {
    if (!v) return '—';
    const d = new Date(v);
    if (isNaN(d)) return esc(v);
    const mins = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    if (mins < 60 * 24) return `${Math.floor(mins / 60)}h ago`;
    return `${Math.floor(mins / (60 * 24))}d ago`;
}

// Alignment is spirit_score /10; null renders N/A, never a default.
function alignmentLabel(score) {
    return (score === null || score === undefined) ? 'N/A' : `${Number(score).toFixed(1)} / 10`;
}

// Consistency = (1 − drift) × 100%; null renders N/A.
function consistencyLabel(drift) {
    return (drift === null || drift === undefined) ? 'N/A' : `${Math.round((1 - drift) * 100)}%`;
}

const BADGE = 'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap';

const TRIGGER_META = {
    hard_gate_block: { label: 'Hard-gate block', cls: 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200' },
    gateway_violation: { label: 'Gateway violation', cls: 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200' },
    agent_redirect: { label: 'Agent redirect', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200' },
    low_alignment: { label: 'Low alignment', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200' },
    drift_spike: { label: 'Consistency drop', cls: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200' },
    random_sample: { label: 'Random sample', cls: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200' },
};

function triggerBadges(triggers) {
    return (triggers || []).map(t => {
        const m = TRIGGER_META[t] || { label: t, cls: 'bg-gray-100 text-gray-700 dark:bg-neutral-800 dark:text-gray-300' };
        return `<span class="${BADGE} ${m.cls}">${esc(m.label)}</span>`;
    }).join(' ');
}

function statusBadge(status) {
    const map = {
        pending: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200',
        approved: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200',
        overridden: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200',
    };
    return `<span class="${BADGE} ${map[status] || map.pending} capitalize">${esc(status)}</span>`;
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

const isAdmin = () => currentUser?.role === 'admin';

// ---------------------------------------------------------------------------

export async function renderSettingsReviewTab() {
    const root = document.getElementById('review-content');
    if (!root) return;
    root.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;

    let org = null;
    try {
        const orgRes = await api.getMyOrganization();
        org = orgRes ? orgRes.organization : null;
    } catch (e) { /* fall through */ }
    if (!org) {
        root.innerHTML = `<p class="text-sm text-gray-500">You need an organization (and the admin or auditor role) to run supervisory review.</p>`;
        return;
    }
    orgId = org.id;
    selected = new Set();
    readUrl(); // URL-synced state: a shared/bookmarked link reproduces the view

    root.innerHTML = `
        <div id="review-alerts"></div>
        <div id="review-stats" class="mb-6"></div>
        <div id="review-queue" class="settings-card"></div>
        <div id="review-config" class="settings-card mt-6"></div>
    `;

    // Long ledger reasons render with an .expand-btn — same delegated
    // listener the conscience modal gets in ui-settings-core.js.
    root.addEventListener('click', (event) => {
        if (event.target.classList.contains('expand-btn')) {
            const reasonText = event.target.previousElementSibling;
            if (reasonText && reasonText.classList.contains('reason-text')) {
                const isTruncated = reasonText.classList.contains('truncated');
                reasonText.classList.toggle('truncated');
                event.target.textContent = isTruncated ? 'Show Less' : 'Show More';
            }
        }
    });

    bindKeys(); // j/k/Enter/A — one-shot global binding, guarded by keysBound
    loadAlerts();
    loadStats();
    renderQueueList();
    renderConfigCard();
}

// --- Alerts strip (Art. 72 monitoring journal, in-app surface) -------------

async function loadAlerts() {
    const el = document.getElementById('review-alerts');
    if (!el) return;
    try {
        const res = await api.listReviewAlerts(orgId, 5);
        const alerts = res.alerts || [];
        if (!alerts.length) { el.innerHTML = ''; return; }
        const ALERT_LABELS = {
            alignment_degradation: 'Alignment degradation',
            drift_spike: 'Consistency drop',
            queue_backlog: 'Review backlog',
        };
        el.innerHTML = `
            <div class="mb-6 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 px-4 py-3">
                <h4 class="text-sm font-semibold text-amber-800 dark:text-amber-200 mb-2">Monitoring alerts</h4>
                ${alerts.map(a => {
                    const delivered = a.delivered?.webhook
                        ? ` · webhook: ${esc(a.delivered.webhook)}` : '';
                    return `<div class="text-sm text-amber-800 dark:text-amber-200/90 py-0.5">
                        <span class="font-mono text-xs opacity-70">${fmtDate(a.created_at)}</span>
                        <span class="font-medium ml-2">${esc(ALERT_LABELS[a.alert_type] || a.alert_type)}</span>
                        <span class="opacity-80 ml-1">${esc(summariseAlert(a))}${delivered}</span>
                    </div>`;
                }).join('')}
            </div>`;
    } catch (e) {
        el.innerHTML = '';
    }
}

function summariseAlert(a) {
    const d = a.detail || {};
    if (a.alert_type === 'alignment_degradation' && d.observed !== undefined)
        return `— rolling Alignment ${Number(d.observed).toFixed(1)} / 10 (threshold ${d.threshold})`;
    if (a.alert_type === 'drift_spike' && d.drift !== undefined)
        return `— Consistency ${Math.round((1 - d.drift) * 100)}% (floor ${Math.round((1 - d.threshold) * 100)}%)`;
    if (a.alert_type === 'queue_backlog' && d.oldest_days !== undefined)
        return `— oldest pending item is ${d.oldest_days}d old (max ${d.max_age_days}d)`;
    return '';
}

// --- Coverage stats strip ---------------------------------------------------
// Custom date range (Tier 1): the API already accepted from/to; the UI now
// exposes it, and both CSV exports inherit the same window.
let statsFrom = '';
let statsTo = '';

async function loadStats() {
    const el = document.getElementById('review-stats');
    if (!el) return;
    try {
        const rep = await api.getReviewReport(orgId, statsFrom || undefined, statsTo || undefined);
        const tile = (label, value, sub = '') => `
            <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3">
                <div class="text-xs uppercase text-gray-400">${label}</div>
                <div class="text-xl font-bold mt-0.5">${value}</div>
                ${sub ? `<div class="text-xs text-gray-400 mt-0.5">${sub}</div>` : ''}
            </div>`;
        const latency = rep.median_review_latency_seconds;
        const fmtDur = (s) => s === null || s === undefined ? '—'
            : s < 3600 ? `${Math.round(s / 60)}m`
            : s < 86400 ? `${(s / 3600).toFixed(1)}h`
            : `${(s / 86400).toFixed(1)}d`;
        const b = rep.pending_age_buckets || {};
        const bucketTotal = Object.values(b).reduce((a, n) => a + n, 0);
        const bucketPct = (n) => bucketTotal ? Math.round(n * 100 / bucketTotal) : 0;
        const cell = (n, label) => `
            <div class="rounded-md bg-gray-50 dark:bg-neutral-800 px-2 py-1.5">
                <div class="text-xs text-gray-400">${label}</div>
                <div class="text-sm font-semibold">${n}</div>
                ${bucketTotal ? `<div class="h-1 mt-1 rounded bg-green-500/70" style="width:${Math.max(bucketPct(n), 2)}%"></div>` : ''}
            </div>`;
        const reviewers = Object.entries(rep.per_reviewer || {}).sort((a, c) => c[1] - a[1]).slice(0, 6);
        const trend = Object.entries(rep.override_trend || {}).slice(-14);
        const trendMax = Math.max(1, ...trend.map(([, v]) => v.total));
        el.innerHTML = `
            <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
                <p class="text-xs text-gray-400 max-w-xl">Coverage, ${statsFrom && statsTo ? `${statsFrom} → ${statsTo}` : 'last 30 days'}. Both exports are logged to the compliance evidence log as chain of custody.</p>
                <div class="flex flex-wrap items-center gap-2">
                    <input type="date" id="review-stats-from" value="${esc(statsFrom)}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
                    <span class="text-xs text-gray-400">→</span>
                    <input type="date" id="review-stats-to" value="${esc(statsTo)}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
                    ${statsFrom || statsTo ? '<button id="review-stats-clear" class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline">Last 30d</button>' : ''}
                    <button id="review-report-csv" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg whitespace-nowrap"
                            title="The coverage summary above, as aggregate fields.">Export summary CSV</button>
                    <button id="review-items-csv" class="px-3 py-1.5 text-xs border border-gray-300 dark:border-neutral-600 rounded-lg whitespace-nowrap"
                            title="One row per reviewed turn: agent, policy version, triggers, disposition, reviewer, latency, hash-chain verdict and the reviewer's written rationale. Use this for an examiner.">Export items CSV</button>
                </div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
                ${tile('Governed turns', rep.total_turns)}
                ${tile('Sampled', rep.sampled, rep.sampled_pct_of_turns !== null && rep.sampled_pct_of_turns !== undefined ? `${rep.sampled_pct_of_turns}% of turns` : '')}
                ${tile('Pending', rep.dispositions?.pending ?? 0, rep.oldest_pending_age_days !== null && rep.oldest_pending_age_days !== undefined ? `oldest ${rep.oldest_pending_age_days}d` : '')}
                ${tile('Reviewed', rep.reviewed, `${rep.dispositions?.approved ?? 0} approved · ${rep.dispositions?.overridden ?? 0} overridden`)}
                ${tile('Review time', fmtDur(latency), `p90 ${fmtDur(rep.p90_review_latency_seconds)} · max ${fmtDur(rep.max_review_latency_seconds)}`)}
            </div>
            ${bucketTotal ? `
            <div class="mt-3">
                <p class="text-xs uppercase text-gray-400 mb-1.5">Pending aging (SLA) <span class="normal-case font-normal">— ${bucketTotal} pending item${bucketTotal > 1 ? 's' : ''}</span></p>
                <div class="grid grid-cols-2 md:grid-cols-5 gap-2">
                    ${cell(b.under_1d, '< 1 day')}${cell(b['1_7d'], '1–7 days')}${cell(b['7_14d'], '7–14 days')}${cell(b['14_30d'], '14–30 days')}${cell(b.over_30d, 'over 30 days')}
                </div>
            </div>` : ''}
            <div class="grid md:grid-cols-2 gap-3 mt-3">
                ${reviewers.length ? `
                <div>
                    <p class="text-xs uppercase text-gray-400 mb-1.5">Reviewer workload</p>
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 divide-y divide-gray-100 dark:divide-neutral-800">
                        ${reviewers.map(([name, n]) => `
                        <div class="flex items-center gap-3 px-3 py-1.5 text-sm">
                            <span class="truncate flex-1">${esc(name)}</span>
                            <div class="w-24 h-1.5 rounded bg-green-500/60" style="min-width:${Math.max(n * 8, 4)}px"></div>
                            <span class="text-xs text-gray-400 w-8 text-right">${n}</span>
                        </div>`).join('')}
                    </div>
                </div>` : ''}
                ${trend.length ? `
                <div>
                    <p class="text-xs uppercase text-gray-400 mb-1.5">Overrides per day <span class="normal-case font-normal">— newest ${trend.length} days with activity</span></p>
                    <div class="flex items-end gap-1 h-20 rounded-lg border border-gray-200 dark:border-neutral-700 px-2 py-1">
                        ${trend.map(([day, v]) => `
                        <div class="flex-1 bg-red-400/70 dark:bg-red-500/60 rounded-t relative group" style="height:${Math.max(v.total * 100 / trendMax, 8)}%"
                             title="${day}: ${v.total} override${v.total > 1 ? 's' : ''}${Object.entries(v.by_trigger).map(([t, n]) => `\n${t}: ${n}`).join('')}">
                        </div>`).join('')}
                    </div>
                </div>` : ''}
            </div>`;
        el.querySelector('#review-stats-from')?.addEventListener('change', e => { statsFrom = e.target.value; loadStats(); });
        el.querySelector('#review-stats-to')?.addEventListener('change', e => { statsTo = e.target.value; loadStats(); });
        el.querySelector('#review-stats-clear')?.addEventListener('click', () => { statsFrom = ''; statsTo = ''; loadStats(); });
        el.querySelector('#review-report-csv')?.addEventListener('click', () =>
            window.open(api.reviewReportCsvUrl(orgId, statsFrom || undefined, statsTo || undefined), '_blank'));
        el.querySelector('#review-items-csv')?.addEventListener('click', () =>
            window.open(api.reviewItemsCsvUrl(orgId, statsFrom || undefined, statsTo || undefined), '_blank'));
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load coverage stats: ${esc(e.message || e)}</p>`;
    }
}

// --- Queue list --------------------------------------------------------------

// Multi-select popover: <details> keeps it dependency-free; checkboxes toggle
// array membership and re-fetch. Rows match ANY selected value.
function multiSel(id, label, opts, selectedArr) {
    const on = (v) => selectedArr.includes(v) ? 'checked' : '';
    return `<details id="${id}" class="relative">
        <summary class="cursor-pointer list-none rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs inline-flex items-center gap-1 select-none">
            ${label}${selectedArr.length ? ` <span class="font-bold">(${selectedArr.length})</span>` : ''} ▾
        </summary>
        <div class="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 shadow-lg p-2 text-sm">
            ${opts.map(([v, l]) => `<label class="flex items-center gap-2 px-1 py-1 cursor-pointer rounded hover:bg-gray-50 dark:hover:bg-neutral-700">
                <input type="checkbox" class="rms-chk accent-green-600" value="${esc(v)}" ${on(v)}><span>${esc(l)}</span>
            </label>`).join('')}
            <button class="w-full mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-1 py-1" data-clear>Clear</button>
        </div>
    </details>`;
}

const SORT_COLS = [
    ['created_at', 'Sampled'], ['profile_name', 'Agent'], ['status', 'Status'], ['reviewed_at', 'Reviewed'],
];

function sortHeader(colKey, label) {
    const active = sort.key === colKey;
    const arrow = active ? (sort.desc ? ' ↓' : ' ↑') : '';
    const next = active && sort.desc ? 'asc' : 'desc';
    return `<th class="px-4 py-3"><button class="uppercase tracking-wide hover:text-gray-700 dark:hover:text-gray-200 ${active ? 'text-gray-700 dark:text-gray-200' : ''}"
        data-sort="${colKey}" data-dir="${next}" title="Sort by ${label}">${label}${arrow}</button></th>`;
}

async function renderQueueList() {
    const el = document.getElementById('review-queue');
    if (!el) return;
    // Skeleton rows, not a spinner: the table shape stays put while loading.
    el.innerHTML = `<div class="animate-pulse space-y-2 py-6">${'<div class="h-9 bg-gray-100 dark:bg-neutral-800 rounded-lg"></div>'.repeat(6)}</div>`;
    const seq = ++loadSeq;
    let res;
    try {
        res = await api.listReviewQueue(orgId, {
            status: filters.status, trigger: filters.trigger,
            from: filters.from || undefined, to: filters.to || undefined,
            sort: `${sort.key}:${sort.desc ? 'desc' : 'asc'}`,
            limit: pageSize, offset,
        });
    } catch (e) {
        if (seq !== loadSeq) return; // a newer request superseded this failure
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load the review queue: ${esc(e.message || e)}</p>`;
        return;
    }
    if (seq !== loadSeq) return; // stale response — a newer filter already re-rendered
    const items = res.items || [];
    const total = res.total || 0;
    lastItems = items;
    cursor = 0;
    selected = new Set([...selected].filter(id => items.some(i => i.id === Number(id))));
    const hasFilters = filters.status.length || filters.trigger.length || filters.from || filters.to;

    const rows = items.map((i, idx) => `
        <tr class="border-b border-gray-100 dark:border-neutral-800 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer ${idx === cursor ? 'ring-1 ring-inset ring-green-500/50' : ''}" data-review-item="${i.id}" data-idx="${idx}">
            <td class="px-2 py-3" data-stop><input type="checkbox" class="bulk-chk accent-green-600" data-bulk="${i.id}" ${i.status !== 'pending' ? 'disabled' : ''} ${selected.has(i.id) ? 'checked' : ''}></td>
            <td class="px-4 py-3 text-sm whitespace-nowrap" title="${fmtDate(i.created_at)}">${age(i.created_at)}</td>
            <td class="px-4 py-3 text-sm">${esc((i.profile_name || '—').replace(/_/g, ' '))}</td>
            <td class="px-4 py-3"><div class="flex flex-wrap gap-1">${triggerBadges(i.triggers)}</div></td>
            <td class="px-4 py-3 text-sm whitespace-nowrap">${alignmentLabel(i.trigger_detail?.spirit_score)}</td>
            <td class="px-4 py-3 text-sm whitespace-nowrap">${consistencyLabel(i.trigger_detail?.drift)}</td>
            <td class="px-4 py-3">${statusBadge(i.status)}</td>
            <td class="px-4 py-3 text-xs text-gray-400">${i.status === 'pending' ? '' : esc(i.reviewer_email || i.reviewed_by || '')}</td>
        </tr>`).join('');

    el.innerHTML = `
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
                <h4 class="text-lg font-semibold">Review queue</h4>
                <p class="text-xs text-gray-500 mt-0.5">Turns sampled by your supervision rules. Review is post-hoc: items are already delivered; your disposition becomes hash-chained audit evidence.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                ${multiSel('review-filter-status', 'Status', [['pending', 'Pending'], ['approved', 'Approved'], ['overridden', 'Overridden']], filters.status)}
                ${multiSel('review-filter-trigger', 'Triggers', Object.entries(TRIGGER_META).map(([k, m]) => [k, m.label]), filters.trigger)}
                <input type="date" id="review-filter-from" value="${esc(filters.from)}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
                <span class="text-xs text-gray-400">→</span>
                <input type="date" id="review-filter-to" value="${esc(filters.to)}" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs">
                ${hasFilters ? `<button id="review-filter-reset" class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline">Reset</button>` : ''}
                <select id="review-page-size" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1.5 text-xs" title="Rows per page">
                    ${[10, 25, 50, 100, 200].map(n => `<option value="${n}" ${n === pageSize ? 'selected' : ''}>${n} / page</option>`).join('')}
                </select>
            </div>
        </div>
        ${selected.size ? `
        <div class="flex items-center gap-3 mb-3 text-sm">
            <span class="text-xs text-gray-500">${selected.size} pending item${selected.size > 1 ? 's' : ''} selected</span>
            <button id="review-bulk-approve" class="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-bold">Approve selected</button>
            <span class="text-xs text-gray-400">Bulk applies approve only — overrides stay per-item so each keeps its own rationale.</span>
        </div>` : ''}
        ${items.length === 0
            ? `<p class="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">${hasFilters ? 'Nothing matches these filters.' : 'The queue is empty.'}</p>`
            : `<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-neutral-700">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 dark:bg-neutral-800 text-xs uppercase text-gray-500 dark:text-gray-400">
                        <tr><th class="px-2 py-3"></th>${SORT_COLS.map(([k, l]) => sortHeader(k, l)).join('')}<th class="px-4 py-3">Triggers</th><th class="px-4 py-3">Alignment</th><th class="px-4 py-3">Consistency</th><th class="px-4 py-3">Reviewer</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
               </div>`}
        <div class="flex items-center justify-between mt-3 text-xs text-gray-500">
            <span>${total ? `Showing ${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}` : ''}</span>
            <div class="flex items-center gap-2">
                <span class="hidden md:inline">j/k move · Enter opens · A approves the cursor row</span>
                <button id="review-prev" class="px-3 py-1 border border-gray-300 dark:border-neutral-600 rounded-lg ${offset === 0 ? 'opacity-40' : ''}" ${offset === 0 ? 'disabled' : ''}>Prev</button>
                <button id="review-next" class="px-3 py-1 border border-gray-300 dark:border-neutral-600 rounded-lg ${offset + pageSize >= total ? 'opacity-40' : ''}" ${offset + pageSize >= total ? 'disabled' : ''}>Next</button>
            </div>
        </div>`;

    const refetch = () => { syncUrl(); renderQueueList(); };
    el.querySelectorAll('.rms-chk').forEach(chk => chk.addEventListener('change', () => {
        const arr = chk.closest('details').id === 'review-filter-status' ? filters.status : filters.trigger;
        const i = arr.indexOf(chk.value);
        if (chk.checked && i < 0) arr.push(chk.value);
        if (!chk.checked && i >= 0) arr.splice(i, 1);
        offset = 0; refetch();
    }));
    el.querySelectorAll('details').forEach(d => d.querySelector('[data-clear]')?.addEventListener('click', () => {
        if (d.id === 'review-filter-status') filters.status = []; else filters.trigger = [];
        d.removeAttribute('open'); offset = 0; refetch();
    }));
    el.querySelector('#review-filter-from')?.addEventListener('change', e => { filters.from = e.target.value; offset = 0; refetch(); });
    el.querySelector('#review-filter-to')?.addEventListener('change', e => { filters.to = e.target.value; offset = 0; refetch(); });
    el.querySelector('#review-filter-reset')?.addEventListener('click', () => {
        filters = { status: ['pending'], trigger: [], from: '', to: '' }; offset = 0; refetch();
    });
    el.querySelector('#review-page-size')?.addEventListener('change', e => { pageSize = Number(e.target.value); offset = 0; refetch(); });
    el.querySelectorAll('[data-sort]').forEach(b => b.addEventListener('click', () => {
        sort = { key: b.dataset.sort, desc: b.dataset.dir === 'desc' }; offset = 0; refetch();
    }));
    el.querySelector('#review-prev')?.addEventListener('click', () => { offset = Math.max(0, offset - pageSize); refetch(); });
    el.querySelector('#review-next')?.addEventListener('click', () => { offset += pageSize; refetch(); });
    el.querySelectorAll('.bulk-chk').forEach(chk => chk.addEventListener('click', e => {
        e.stopPropagation();
        const id = Number(chk.dataset.bulk);
        chk.checked ? selected.add(id) : selected.delete(id);
        // Restripe the bulk bar in place — cheaper than a refetch round-trip
        // for a pure selection change.
        const bar = document.getElementById('review-bulk-approve');
        if (selected.size && !bar) refetch();
        else if (!selected.size && bar) refetch();
    }));
    el.querySelector('#review-bulk-approve')?.addEventListener('click', bulkApprove);
    el.querySelectorAll('[data-review-item]').forEach(tr => {
        tr.addEventListener('click', e => {
            if (e.target.closest('[data-stop]')) return;
            cursor = Number(tr.dataset.idx);
            renderDetail(tr.getAttribute('data-review-item'));
        });
    });
    syncUrl();
}

// Bulk Approve: per-item results, because each disposition is one-shot and
// races (someone else reviewed it, or self-review) must not abort the batch.
async function bulkApprove() {
    const ids = [...selected];
    if (!ids.length) return;
    if (!confirm(`Approve ${ids.length} pending item${ids.length > 1 ? 's' : ''}? Each disposition is hash-chained and one-shot.`)) return;
    let ok = 0; const failures = [];
    for (const id of ids) {
        try {
            await api.actOnReviewItem(orgId, id, 'approve', null);
            ok++;
        } catch (e) {
            failures.push(`#${id}: ${e.message || e}`);
        }
    }
    selected.clear();
    ui.showToast(`Approved ${ok}/${ids.length}${failures.length ? ` — ${failures.length} failed (see console)` : ''}`, failures.length ? 'info' : 'success');
    if (failures.length) console.warn('Bulk approve failures:', failures);
    renderQueueList();
}

// --- Keyboard navigation (Tier 2): j/k move the cursor, Enter opens the
// detail pane, A approves the cursor row (one-shot, no bulk shortcut for
// override — rationale discipline). Bound once; ignores typing in inputs.
function bindKeys() {
    if (keysBound) return;
    keysBound = true;
    document.addEventListener('keydown', (e) => {
        if (!document.getElementById('review-queue')) return;
        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'select' || tag === 'textarea' || e.target.isContentEditable) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.key === 'j' || e.key === 'k') {
            e.preventDefault();
            if (!lastItems.length) return;
            cursor = e.key === 'j'
                ? Math.min(cursor + 1, lastItems.length - 1)
                : Math.max(cursor - 1, 0);
            document.querySelectorAll('[data-review-item]').forEach(tr =>
                tr.classList.toggle('ring-1', Number(tr.dataset.idx) === cursor));
            document.querySelector(`[data-review-item][data-idx="${cursor}"]`)?.scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter') {
            const item = lastItems[cursor];
            if (item) { e.preventDefault(); renderDetail(String(item.id)); }
        } else if (e.key === 'A' || e.key === 'a') {
            const item = lastItems[cursor];
            if (item && item.status === 'pending') {
                e.preventDefault();
                api.actOnReviewItem(orgId, item.id, 'approve', null)
                    .then(() => { ui.showToast('Approved', 'success'); renderQueueList(); })
                    .catch(err => ui.showToast(err.message || 'Approve failed', 'error'));
            }
        }
    });
}

// --- Detail pane --------------------------------------------------------------

async function renderDetail(queueId) {
    const el = document.getElementById('review-queue');
    if (!el) return;
    el.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    let doc;
    try {
        doc = await api.getReviewItem(orgId, queueId);
    } catch (e) {
        ui.showToast(e.message || 'Failed to load the review item', 'error');
        renderQueueList();
        return;
    }
    const q = doc.queue;
    const turn = doc.turn;

    // Parse persisted JSON strings (ledger, attribution) defensively.
    let ledger = [];
    try { ledger = JSON.parse(turn?.conscience_ledger || '[]') || []; } catch (e) { /* leave empty */ }
    let profileValues = [];
    try {
        profileValues = Array.isArray(turn?.profile_values)
            ? turn.profile_values
            : JSON.parse(turn?.profile_values || '[]');
        if (!Array.isArray(profileValues)) profileValues = [];
    } catch (e) { /* legacy/malformed row — omit rubric descriptions */ }
    let attribution = null;
    try { attribution = turn?.model_attribution ? JSON.parse(turn.model_attribution) : null; } catch (e) { /* opaque */ }

    const detail = q.trigger_detail || {};
    const willDecision = turn?.will_decision ?? detail.will_decision;
    const willStage = turn?.will_stage ?? detail.will_stage;

    const metaRows = [
        ['Sampled', `${fmtDate(q.created_at)} <span class="text-gray-400">(${age(q.created_at)})</span>`],
        ['Agent', esc((q.profile_name || '—').replace(/_/g, ' '))],
        ['Governing policy', q.policy_id ? `${esc(String(q.policy_id).replace(/_/g, ' '))}${q.policy_version ? ` (v${esc(q.policy_version)})` : ''}` : '—'],
        ['Enforcement decision', willDecision ? `<span class="capitalize">${esc(willDecision)}</span>${willStage ? ` <span class="text-gray-400">at ${esc(String(willStage).replace(/_/g, ' '))}</span>` : ''}` : 'recorded before decision provenance shipped'],
        ['Alignment', alignmentLabel(turn ? turn.spirit_score : detail.spirit_score)],
        ['Consistency', consistencyLabel(turn ? turn.drift : detail.drift)],
    ];
    if (attribution && typeof attribution === 'object') {
        metaRows.push(['Models used', Object.entries(attribution).map(([k, v]) => `<span class="font-mono text-xs">${esc(v)}</span>`).join('<br>')]);
    }

    const historyHtml = (doc.review_history || []).map(h => `
        <li class="border-l-2 border-gray-200 dark:border-neutral-700 pl-4 pb-3">
            <div class="text-xs text-gray-400">${fmtDate(h.event_at)} · ${esc(h.actor || '')}</div>
            <div class="text-sm font-medium capitalize">${esc(h.disposition || '')}</div>
            ${h.reason ? `<div class="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap">${esc(h.reason)}</div>` : ''}
        </li>`).join('');

    const textCard = (title, body, extraCls = '') => `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700 ${extraCls}">
            <div class="px-4 py-2 border-b border-gray-100 dark:border-neutral-800 text-xs uppercase text-gray-400">${title}</div>
            <div class="px-4 py-3 text-sm whitespace-pre-wrap break-words">${body}</div>
        </div>`;

    el.innerHTML = `
        <button id="review-back" class="text-sm text-green-600 hover:underline mb-4">&larr; Back to queue</button>
        <div class="flex flex-wrap items-center gap-2 mb-4">
            ${statusBadge(q.status)} ${triggerBadges(q.triggers)} ${chainBadge(doc.chain)}
        </div>
        <div class="grid lg:grid-cols-2 gap-6">
            <div class="space-y-4">
                <div class="rounded-lg border border-gray-200 dark:border-neutral-700 divide-y divide-gray-100 dark:divide-neutral-800">
                    ${metaRows.map(([k, v]) => `<div class="px-4 py-2 grid grid-cols-3 gap-2"><span class="text-xs uppercase text-gray-400 pt-0.5">${k}</span><span class="col-span-2 text-sm">${v}</span></div>`).join('')}
                </div>
                ${turn ? `
                    ${doc.user_prompt ? textCard('User prompt', esc(doc.user_prompt)) : ''}
                    ${textCard('Delivered response', esc(turn.content || ''))}
                    ${turn.spirit_note ? textCard('Alignment note', esc(turn.spirit_note)) : ''}
                ` : `
                    <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3 text-sm text-gray-500">
                        The underlying message has been destroyed by the org's retention policy.
                        The queue row and any dispositions recorded before the purge remain as evidence.
                    </div>
                `}
                ${q.status === 'pending' ? renderActionBar() : `
                    <div>
                        <h4 class="text-sm font-semibold mb-2">Review history</h4>
                        <ul>${historyHtml || '<li class="text-sm text-gray-400">No review entries.</li>'}</ul>
                    </div>
                `}
            </div>
            <div>
                <h4 class="text-sm font-semibold mb-2">Governance record</h4>
                ${turn && ledger.length
                    ? renderConscienceReport({
                        ledger,
                        spirit_score: turn.spirit_score,
                        profile: turn.profile_name,
                        policy_id: turn.policy_id,
                        policy_version: turn.policy_version,
                        will_reason: ledger.find(item => item?.recorded_violation)?.recorded_violation || null,
                        is_redirect: ledger.some(item => Boolean(item?.recorded_violation)),
                        final_output: turn.content || null,
                        values: profileValues,
                    }, 'rq-')
                    : `<p class="text-sm text-gray-400">No value-by-value evaluation was recorded for this turn${willStage === 'hard_gate' ? ' — it was stopped at a hard gate before the audit stage' : ''}.</p>`}
            </div>
        </div>`;

    attachTabSwitching(el);
    el.querySelector('#review-back')?.addEventListener('click', () => renderQueueList());

    if (q.status === 'pending') {
        const reasonEl = el.querySelector('#review-reason');
        const act = async (action) => {
            const reason = (reasonEl?.value || '').trim();
            if (action === 'override' && !reason) {
                ui.showToast('An override requires a reason — it becomes part of the audit evidence', 'error');
                reasonEl?.focus();
                return;
            }
            try {
                await api.actOnReviewItem(orgId, q.id, action, reason || undefined);
                ui.showToast(action === 'approve' ? 'Approved — recorded in the audit trail' : 'Override recorded in the audit trail', 'success');
                loadStats();
                renderDetail(q.id);
            } catch (e) {
                ui.showToast(e.message || 'Action failed', 'error');
            }
        };
        el.querySelector('#review-approve')?.addEventListener('click', () => act('approve'));
        el.querySelector('#review-override')?.addEventListener('click', () => act('override'));
    }
}

function renderActionBar() {
    return `
        <div class="rounded-lg border border-gray-200 dark:border-neutral-700 px-4 py-3 space-y-3">
            <h4 class="text-sm font-semibold">Supervisory disposition</h4>
            <p class="text-xs text-gray-500">This message has already been delivered. An override does not retract it — it records your determination that the response should not have gone out as-is. Both dispositions are appended to the message's tamper-evident audit trail under your identity.</p>
            <textarea id="review-reason" rows="2" placeholder="Reviewer note — required for an override, optional for an approval"
                class="w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm"></textarea>
            <div class="flex gap-3">
                <button id="review-approve" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg">Approve</button>
                <button id="review-override" class="px-4 py-2 bg-green-700 hover:bg-green-800 text-white text-sm font-medium rounded-lg">Override</button>
            </div>
        </div>`;
}

// --- Config card ---------------------------------------------------------------

async function renderConfigCard() {
    const el = document.getElementById('review-config');
    if (!el) return;
    let cfg;
    try {
        cfg = await api.getReviewConfig(orgId);
    } catch (e) {
        el.innerHTML = `<p class="text-sm text-red-500">Failed to load review settings: ${esc(e.message || e)}</p>`;
        return;
    }
    const admin = isAdmin();
    const dis = admin ? '' : 'disabled';
    const t = cfg.triggers || {};
    const a = cfg.alerts || {};
    const consistencyFloor = Math.round((1 - (t.drift_threshold ?? 0.4)) * 100);

    const numInput = (id, value, attrs) =>
        `<input type="number" id="${id}" value="${value}" ${attrs} ${dis}
            class="w-20 rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-2 py-1 text-sm text-right">`;

    el.innerHTML = `
        <h4 class="text-lg font-semibold mb-1">Supervisory review settings</h4>
        <p class="text-xs text-gray-500 mb-4">Which turns are sampled into the queue, and when monitoring alerts fire. Sampling is deterministic — an examiner can recompute exactly which turns were due. Every change here is recorded in the compliance evidence log.${admin ? '' : ' <span class="font-semibold">Read-only for auditors — ask an org admin to change these.</span>'}</p>
        <div class="space-y-5">
            <label class="flex items-center gap-2 text-sm">
                <input type="checkbox" id="rvc-enabled" ${cfg.enabled ? 'checked' : ''} ${dis}>
                <span class="font-bold text-gray-700 dark:text-gray-300">Enable supervisory review</span>
                <span class="text-xs text-gray-400">(off = nothing is sampled)</span>
            </label>

            <div class="grid md:grid-cols-2 gap-x-8 gap-y-3">
                <div class="space-y-3">
                    <div class="text-xs uppercase text-gray-400 font-semibold">Sampling triggers</div>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span class="flex items-center gap-2"><input type="checkbox" id="rvc-random" ${(cfg.random_sample_pct || 0) > 0 ? 'checked' : ''} ${dis}> Random sample</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-random-pct', cfg.random_sample_pct ?? 5, 'min="0" max="100" step="0.5"')} % of turns</span>
                    </label>
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" id="rvc-hard-gate" ${t.hard_gate_block ? 'checked' : ''} ${dis}> Every hard-gate block
                    </label>
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" id="rvc-gateway" ${t.gateway_violation ? 'checked' : ''} ${dis}> Every gateway violation
                    </label>
                    <label class="flex items-center gap-2 text-sm" title="Turns where the agent redirected instead of answering, other than hard-gate blocks — those have their own checkbox above.">
                        <input type="checkbox" id="rvc-redirect" ${t.agent_redirect ? 'checked' : ''} ${dis}> Every agent redirect
                    </label>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span class="flex items-center gap-2"><input type="checkbox" id="rvc-low-align" ${t.low_alignment ? 'checked' : ''} ${dis}> Alignment below</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-align-thr', t.alignment_threshold ?? 6, 'min="0" max="10" step="0.5"')} / 10</span>
                    </label>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span class="flex items-center gap-2"><input type="checkbox" id="rvc-drift" ${t.drift_spike ? 'checked' : ''} ${dis}> Consistency below</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-consistency-floor', consistencyFloor, 'min="0" max="100" step="1"')} %</span>
                    </label>
                </div>
                <div class="space-y-3">
                    <div class="text-xs uppercase text-gray-400 font-semibold">Monitoring alerts</div>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span>Alert when rolling Alignment falls below</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-avg-thr', a.alignment_avg_threshold ?? 6, 'min="0" max="10" step="0.5"')} / 10</span>
                    </label>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span>…measured over the last</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-window', a.alignment_window_turns ?? 20, 'min="1" max="500" step="1"')} turns</span>
                    </label>
                    <label class="flex items-center justify-between gap-2 text-sm">
                        <span>Alert when a pending item is older than</span>
                        <span class="flex items-center gap-1 text-xs text-gray-500">${numInput('rvc-backlog', a.backlog_max_age_days ?? 14, 'min="1" max="365" step="1"')} days</span>
                    </label>
                    <label class="block text-sm">
                        <span class="block mb-1">Alert webhook URL <span class="text-xs text-gray-400">(optional — alerts always show here in-app)</span></span>
                        <input type="url" id="rvc-webhook" value="${esc(a.webhook_url || '')}" placeholder="https://…" ${dis}
                            class="w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                    </label>
                </div>
            </div>
            ${admin ? `
            <div class="flex justify-end">
                <button id="rvc-save" class="px-5 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">Save Review Settings</button>
            </div>` : ''}
        </div>`;

    if (!admin) return;
    el.querySelector('#rvc-save')?.addEventListener('click', async () => {
        const num = (id) => parseFloat(el.querySelector(id).value);
        const floor = num('#rvc-consistency-floor');
        const changes = {
            enabled: el.querySelector('#rvc-enabled').checked,
            random_sample_pct: el.querySelector('#rvc-random').checked ? num('#rvc-random-pct') : 0,
            triggers: {
                hard_gate_block: el.querySelector('#rvc-hard-gate').checked,
                gateway_violation: el.querySelector('#rvc-gateway').checked,
                agent_redirect: el.querySelector('#rvc-redirect').checked,
                low_alignment: el.querySelector('#rvc-low-align').checked,
                alignment_threshold: num('#rvc-align-thr'),
                drift_spike: el.querySelector('#rvc-drift').checked,
                // Consistency floor X% ⇔ drift threshold 1 − X/100
                drift_threshold: Math.round((1 - floor / 100) * 100) / 100,
            },
            alerts: {
                webhook_url: el.querySelector('#rvc-webhook').value.trim() || null,
                alignment_avg_threshold: num('#rvc-avg-thr'),
                alignment_window_turns: parseInt(el.querySelector('#rvc-window').value, 10),
                backlog_max_age_days: parseInt(el.querySelector('#rvc-backlog').value, 10),
            },
        };
        for (const [field, v] of [['sample %', changes.random_sample_pct], ['Alignment threshold', changes.triggers.alignment_threshold], ['Consistency floor', floor]]) {
            if (Number.isNaN(v)) { ui.showToast(`Enter a valid ${field}`, 'error'); return; }
        }
        try {
            await api.updateReviewConfig(orgId, changes);
            ui.showToast('Review settings saved', 'success');
            renderConfigCard();
        } catch (e) {
            ui.showToast(e.message || 'Save failed', 'error');
        }
    });
}
