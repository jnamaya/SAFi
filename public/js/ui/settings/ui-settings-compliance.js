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
             <div id="compliance-log-list" class="text-sm text-gray-500">Loading…</div>
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
                 <p class="text-xs text-gray-400">BAA = provider offers a HIPAA Business Associate Agreement on an enterprise tier. EU = an EU/EEA-resident hosting option exists. Voice synthesis via edge-tts is governed separately.</p>
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

async function loadComplianceLog(orgId) {
    const el = document.getElementById('compliance-log-list');
    if (!el) return;
    try {
        const res = await api.getComplianceLog(orgId);
        const events = res.events || [];
        if (!events.length) {
            el.innerHTML = '<span class="text-gray-400">No compliance events yet.</span>';
            return;
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
        const badge = (on, label) => on
            ? `<span class="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400">${label}</span>`
            : '';
        el.innerHTML = (res.providers || []).map(p => `
            <label class="flex items-center gap-2 text-sm rounded-lg border border-gray-200 dark:border-neutral-700 px-3 py-2">
                <input type="checkbox" value="${p.key}" ${p.allowed ? 'checked' : ''}>
                <span class="font-medium">${p.label}</span>
                ${badge(p.baa_capable, 'BAA')}${badge(p.eu_hostable, 'EU')}
            </label>`).join('');
    } catch (e) {
        el.innerHTML = `<span class="text-sm text-red-500">Failed to load providers: ${e.message || e}</span>`;
    }
}
