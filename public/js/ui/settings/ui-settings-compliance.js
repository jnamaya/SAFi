// Compliance tab: the org's examiner-facing controls in one place.
// Order is deliberate — the evidence log leads (every other card on this tab
// writes to it), then provider governance, records retention, examiner
// export, and the security-incidents registry (ui-settings-incidents.js).
// Moved out of the Organization tab 2026-07-16 so Organization stays
// identity-only and roadmap phases D/E have an obvious home here.
import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { renderIncidentsSection } from './ui-settings-incidents.js';

export async function renderSettingsComplianceTab() {
    logLimit = 20; // fresh visit starts with the compact window
    const cards = document.getElementById('compliance-cards');
    const incidents = document.getElementById('compliance-incidents');
    if (!cards) return;
    cards.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;

    let org = null;
    try {
        const orgRes = await api.getMyOrganization();
        org = orgRes ? orgRes.organization : null;
    } catch (e) { /* fall through to the no-org notice */ }

    if (!org) {
        cards.innerHTML = `<p class="text-sm text-gray-500">You need an organization (and the admin role) to manage compliance settings.</p>`;
        if (incidents) incidents.innerHTML = '';
        return;
    }

    cards.innerHTML = `
        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">Compliance Evidence Log</h4>
             <p class="text-xs text-gray-500 mb-4">Append-only record of governance actions: retention changes, legal holds, purges, examiner exports, provider policy changes. This is the artifact you show an examiner.</p>
             <div id="compliance-log-list" class="text-sm text-gray-500 max-h-80 overflow-y-auto custom-scrollbar">Loading…</div>
             <div id="compliance-log-footer" class="hidden mt-3 flex items-center justify-between">
                 <span id="compliance-log-count" class="text-xs text-gray-400"></span>
                 <button id="compliance-log-more" class="hidden text-xs font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">Show more</button>
             </div>
        </div>

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">AI Provider Allow-List</h4>
             <p class="text-xs text-gray-500 mb-4">Restrict which LLM providers may receive your organization's content — across chat, audits, and background tasks. Enforcement fails closed: blocked providers are never silently substituted. Changes are recorded in the evidence log above.</p>
             <div class="space-y-4">
                 <label class="flex items-center gap-2 text-sm">
                     <input type="checkbox" id="chk-provider-restrict" ${org.settings?.provider_allowlist ? 'checked' : ''}>
                     <span class="font-bold text-gray-700 dark:text-gray-300">Restrict providers</span>
                     <span class="text-xs text-gray-400">(unchecked = all providers allowed)</span>
                 </label>
                 <div id="provider-checklist" class="grid md:grid-cols-2 gap-2 ${org.settings?.provider_allowlist ? '' : 'hidden'}">
                     <div class="text-sm text-gray-400">Loading providers…</div>
                 </div>
                 <p class="text-xs text-gray-400">BAA = provider offers a HIPAA Business Associate Agreement on an enterprise tier. EU = an EU/EEA-resident hosting option exists. ZDR = prompts are not retained by default; ZDR* = zero data retention is available on an enterprise/request basis (hover a badge for the provider's exact posture, verified July 2026). Voice synthesis via edge-tts is governed separately.</p>
                 <div class="flex justify-end">
                     <button id="btn-save-providers" class="px-5 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">Save Provider Settings</button>
                 </div>
             </div>
        </div>

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">Data Retention &amp; Legal Hold</h4>
             <p class="text-xs text-gray-500 mb-4">Records older than the retention period are destroyed by the daily purge and evidenced above (SEC 17a-4 / Reg S-P). A legal hold suspends all destruction.</p>
             <div class="space-y-4">
                 <div class="grid md:grid-cols-2 gap-4">
                     <label class="block">
                         <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Retention period</span>
                         <select id="sel-retention-years" class="mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                             <option value="" ${!org.settings?.retention_years ? 'selected' : ''}>Keep forever (no purge)</option>
                             ${[3, 5, 6, 7].map(y => `<option value="${y}" ${org.settings?.retention_years === y ? 'selected' : ''}>${y} years</option>`).join('')}
                         </select>
                     </label>
                     <div class="block">
                         <span class="text-sm font-bold text-gray-700 dark:text-gray-300">Legal hold</span>
                         <label class="mt-2 flex items-center gap-2 text-sm">
                             <input type="checkbox" id="chk-legal-hold" ${org.settings?.legal_hold?.active ? 'checked' : ''}>
                             Suspend all data destruction
                         </label>
                         <input id="inp-hold-reason" placeholder="Reason (required to place a hold)"
                             value="${(org.settings?.legal_hold?.active && org.settings?.legal_hold?.reason) ? String(org.settings.legal_hold.reason).replace(/"/g, '&quot;') : ''}"
                             class="mt-2 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm ${org.settings?.legal_hold?.active ? '' : 'hidden'}">
                     </div>
                 </div>
                 <div class="flex justify-end">
                     <button id="btn-save-retention" class="px-5 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold shadow hover:shadow-md transition-all">Save Retention Settings</button>
                 </div>
             </div>
        </div>

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">Offline &amp; Device Caching</h4>
             <p class="text-xs text-gray-500 mb-4">When disabled (the default), members' browsers and devices keep no local copies of org conversations — no offline cache, no queued messages, no app-shell caching. Members' clients purge existing local data on their next sign-in. Changes are recorded in the evidence log.</p>
             <div class="flex items-center justify-between gap-4">
                 <label class="flex items-center gap-2 text-sm">
                     <input type="checkbox" id="chk-offline-enabled" ${org.settings?.offline_enabled ? 'checked' : ''}>
                     <span class="font-bold text-gray-700 dark:text-gray-300">Allow offline mode on member devices</span>
                 </label>
                 <button id="btn-save-offline" class="px-5 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-sm font-bold shadow hover:shadow-md transition-all whitespace-nowrap">Save Offline Settings</button>
             </div>
        </div>

        <div class="settings-card">
             <h4 class="text-lg font-semibold mb-1">Examiner Export (Records Production)</h4>
             <p class="text-xs text-gray-500 mb-4">Decrypted message records plus audit-trail integrity metadata for a date range. Every export is logged to the evidence log as chain of custody.</p>
             <div class="flex flex-wrap items-center gap-2">
                 <input type="date" id="exp-from" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                 <span class="text-sm text-gray-500">to</span>
                 <input type="date" id="exp-to" class="rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm">
                 <button id="btn-export-records" class="px-4 py-2 border border-gray-300 dark:border-neutral-600 rounded-lg text-sm">Export JSON</button>
             </div>
        </div>
    `;

    // --- Provider allow-list wiring ---
    const chkRestrict = cards.querySelector('#chk-provider-restrict');
    const checklist = cards.querySelector('#provider-checklist');
    chkRestrict.addEventListener('change', () => checklist.classList.toggle('hidden', !chkRestrict.checked));
    loadProviderChecklist(org.id);
    cards.querySelector('#btn-save-providers').addEventListener('click', async () => {
        let allowlist = null;
        if (chkRestrict.checked) {
            allowlist = [...checklist.querySelectorAll('input[type=checkbox]:checked')].map(c => c.value);
            if (!allowlist.length) {
                ui.showToast('Select at least one provider, or uncheck "Restrict providers"', 'error');
                return;
            }
        }
        try {
            await api.updateOrgProviders(org.id, allowlist);
            ui.showToast('Provider settings saved', 'success');
            loadComplianceLog(org.id);
        } catch (e) {
            ui.showToast(e.message || 'Save failed', 'error');
        }
    });

    // --- Retention & legal hold wiring ---
    const chkHold = cards.querySelector('#chk-legal-hold');
    const inpReason = cards.querySelector('#inp-hold-reason');
    chkHold.addEventListener('change', () => inpReason.classList.toggle('hidden', !chkHold.checked));
    cards.querySelector('#btn-save-retention').addEventListener('click', async () => {
        const yearsRaw = cards.querySelector('#sel-retention-years').value;
        const payload = {
            retention_years: yearsRaw ? parseInt(yearsRaw) : null,
            legal_hold: { active: chkHold.checked, reason: inpReason.value.trim() },
        };
        try {
            await api.updateRetention(org.id, payload);
            ui.showToast('Retention settings saved', 'success');
            loadComplianceLog(org.id);
        } catch (e) {
            ui.showToast(e.message || 'Save failed', 'error');
        }
    });

    // --- Offline kill-switch wiring ---
    cards.querySelector('#btn-save-offline').addEventListener('click', async () => {
        try {
            await api.updateOfflineConfig(org.id, cards.querySelector('#chk-offline-enabled').checked);
            ui.showToast('Offline settings saved — members pick this up on their next sign-in', 'success');
            loadComplianceLog(org.id);
        } catch (e) {
            ui.showToast(e.message || 'Save failed', 'error');
        }
    });

    // --- Examiner export wiring ---
    cards.querySelector('#btn-export-records').addEventListener('click', () => {
        const from = cards.querySelector('#exp-from').value;
        const to = cards.querySelector('#exp-to').value;
        if (!from || !to) { ui.showToast('Pick a from and to date', 'error'); return; }
        window.open(api.recordsExportUrl(org.id, from, to), '_blank');
        setTimeout(() => loadComplianceLog(org.id), 1500);
    });

    loadComplianceLog(org.id);
    renderIncidentsSection(incidents, org);
}

// The API returns newest-first and hard-caps at 100. Start with 20; "Show
// more" raises the window to the cap. Kept module-level so refreshes after
// retention saves / exports don't collapse an expanded view.
const LOG_CAP = 100;
let logLimit = 20;

async function loadComplianceLog(orgId) {
    const el = document.getElementById('compliance-log-list');
    if (!el) return;
    const footer = document.getElementById('compliance-log-footer');
    const count = document.getElementById('compliance-log-count');
    const more = document.getElementById('compliance-log-more');
    try {
        const res = await api.getComplianceLog(orgId, logLimit);
        const events = res.events || [];
        if (!events.length) {
            el.innerHTML = '<span class="text-gray-400">No compliance events yet.</span>';
            if (footer) footer.classList.add('hidden');
            return;
        }
        if (footer && count && more) {
            footer.classList.remove('hidden');
            const truncated = events.length === logLimit;
            if (truncated && logLimit < LOG_CAP) {
                count.textContent = `Showing the latest ${events.length} events`;
                more.classList.remove('hidden');
                more.onclick = () => { logLimit = LOG_CAP; loadComplianceLog(orgId); };
            } else if (truncated) {
                count.textContent = `Showing the latest ${events.length} events — the full history is included in examiner exports`;
                more.classList.add('hidden');
            } else {
                count.textContent = `${events.length} recorded event${events.length === 1 ? '' : 's'}`;
                more.classList.add('hidden');
            }
        }
        el.innerHTML = events.map(e => {
            const when = e.created_at ? new Date(e.created_at).toLocaleString() : '';
            const summary = e.event_type === 'purge_completed' && e.detail?.counts
                ? ` — ${e.detail.counts.conversations ?? 0} conversations, ${e.detail.counts.chat_history ?? 0} messages destroyed`
                : e.event_type === 'examiner_export' && e.detail?.counts
                    ? ` — ${e.detail.counts.messages} messages produced`
                    : '';
            return `<div class="py-1.5 border-b border-gray-100 dark:border-neutral-800 last:border-0">
                <span class="font-mono text-xs text-gray-400">${when}</span>
                <span class="ml-2 font-medium">${e.event_type.replace(/_/g, ' ')}</span>
                <span class="text-gray-500">${summary}</span>
                <span class="ml-2 text-xs text-gray-400">${e.actor || ''}</span>
            </div>`;
        }).join('');
    } catch (e) {
        el.innerHTML = `<span class="text-sm text-red-500">Failed to load evidence log: ${e.message || e}</span>`;
    }
}

async function loadProviderChecklist(orgId) {
    const el = document.getElementById('provider-checklist');
    if (!el) return;
    try {
        const res = await api.getOrgProviders(orgId);
        const badge = (on, label, title = '') => on
            ? `<span class="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400" ${title ? `title="${title.replace(/"/g, '&quot;')}"` : ''}>${label}</span>`
            : '';
        // ZDR: green = no retention by default; amber = zero-data-retention
        // available on an enterprise/request basis (not automatic).
        const zdrBadge = (p) => {
            if (!p.zdr) return '';
            const cls = p.zdr === 'default'
                ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400'
                : 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400';
            return `<span class="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded ${cls}" title="${(p.zdr_note || '').replace(/"/g, '&quot;')}">ZDR${p.zdr === 'available' ? '*' : ''}</span>`;
        };
        el.innerHTML = (res.providers || []).map(p => `
            <label class="flex items-center gap-2 text-sm rounded-lg border border-gray-200 dark:border-neutral-700 px-3 py-2">
                <input type="checkbox" value="${p.key}" ${p.allowed ? 'checked' : ''}>
                <span class="font-medium">${p.label}</span>
                ${badge(p.baa_capable, 'BAA')}${badge(p.eu_hostable, 'EU')}${zdrBadge(p)}
            </label>`).join('');
    } catch (e) {
        el.innerHTML = `<span class="text-sm text-red-500">Failed to load providers: ${e.message || e}</span>`;
    }
}
