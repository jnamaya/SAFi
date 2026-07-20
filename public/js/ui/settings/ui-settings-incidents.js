// Security Incidents section of the Compliance tab (admin-only). Multi-regime
// incident registry: each incident is tagged with the notification regimes it
// is reportable under (SEC Reg S-P, EU AI Act Art. 73, HIPAA breach rule) and
// every applicable clock is computed server-side and shown live. List view
// with clock badges, create/edit form with per-regime inputs, detail view
// with event timeline and JSON/CSV export. SAFi records and tracks; the firm
// sends actual notices via its own channels and logs the *_notified event,
// which stamps that clock's stop timestamp.
// Rendered by ui-settings-compliance.js into #compliance-incidents.
import * as ui from '../ui.js';
import * as api from '../../core/api.js';

let orgId = null;
let orgRegimeDefaults = ['reg_sp'];

const STATUS_OPTIONS = ['open', 'assessing', 'notifying', 'closed'];
const SEVERITY_OPTIONS = ['low', 'medium', 'high', 'critical'];

const REGIME_LABELS = { reg_sp: 'SEC Reg S-P', eu_ai_act: 'EU AI Act', hipaa: 'HIPAA' };
const EU_CLASS_OPTIONS = ['general', 'death_or_serious_harm', 'widespread'];
const HIPAA_ROLE_OPTIONS = ['covered_entity', 'business_associate'];

// Short badge prefixes per clock key (full labels come from the server).
const CLOCK_SHORT = {
    customer_notice: 'Reg S-P', eu_authority: 'EU Art. 73',
    hipaa_individuals: 'HIPAA ind.', hipaa_hhs: 'HIPAA HHS',
    hipaa_media: 'HIPAA media', hipaa_ce: 'HIPAA→CE',
};

const BASE_EVENT_TYPES = ['note', 'assessment', 'containment'];
const REGIME_EVENT_TYPES = {
    reg_sp: ['notification_sent', 'ag_delay'],
    eu_ai_act: ['authority_notified'],
    hipaa: ['individuals_notified', 'hhs_notified', 'media_notified', 'ce_notified'],
};

function eventTypesFor(regimes) {
    return BASE_EVENT_TYPES.concat((regimes || []).flatMap(r => REGIME_EVENT_TYPES[r] || []));
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

// datetime-local expects "YYYY-MM-DDTHH:MM" in local time
function toInputValue(v) {
    if (!v) return '';
    const d = new Date(v);
    if (isNaN(d)) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function clockBadge(clock) {
    if (!clock) return '';
    const base = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold';
    const short = CLOCK_SHORT[clock.key] || clock.regime || '';
    const prefix = short ? `${short}: ` : '';
    switch (clock.state) {
        case 'excepted':
            return `<span class="${base} bg-gray-200 text-gray-700 dark:bg-neutral-700 dark:text-gray-300">${prefix}excepted (harm assessment)</span>`;
        case 'notified':
            return `<span class="${base} bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">${prefix}notified${clock.days_taken !== null ? ` in ${clock.days_taken}d` : ''}</span>`;
        case 'overdue':
            return `<span class="${base} bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">${prefix}OVERDUE ${Math.abs(clock.days_remaining)}d</span>`;
        default: {
            // Short statutory windows (EU 2/10/15d) go amber sooner than 30/60d ones.
            const amberAt = clock.window_days && clock.window_days <= 15 ? 2 : 7;
            const amber = clock.days_remaining !== null && clock.days_remaining <= amberAt;
            const cls = amber ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'
                              : 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
            const label = clock.days_remaining === null ? 'clock running' : `due in ${clock.days_remaining}d`;
            return `<span class="${base} ${cls}">${prefix}${label}</span>`;
        }
    }
}

function clockBadges(incident) {
    return (incident.clocks || (incident.clock ? [incident.clock] : []))
        .map(clockBadge).join(' ');
}

function vendorBadge(clock) {
    if (!clock || clock.vendor_notice_late === null || clock.vendor_notice_late === undefined) return '';
    if (clock.vendor_notice_late) {
        return `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200" title="Vendor took ${clock.vendor_notice_hours}h to notify (72h required)">Vendor notice late (${clock.vendor_notice_hours}h)</span>`;
    }
    return `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">Vendor notice ${clock.vendor_notice_hours}h</span>`;
}

export async function renderIncidentsSection(container, org) {
    if (!container) return;
    container.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    try {
        if (!org) {
            container.innerHTML = `<p class="text-sm text-gray-500">You need an organization (and the admin role) to manage incidents.</p>`;
            return;
        }
        orgId = org.id;
        await renderList(container);
    } catch (e) {
        console.error('Incidents section error:', e);
        container.innerHTML = `<p class="text-sm text-red-500">Failed to load incidents.</p>`;
    }
}

async function renderList(container) {
    const [res, regimeCfg] = await Promise.all([
        api.listIncidents(orgId),
        api.getIncidentRegimes(orgId).catch(() => null),
    ]);
    if (regimeCfg?.regimes) orgRegimeDefaults = regimeCfg.regimes;
    const incidents = res.incidents || [];
    const rows = incidents.map(i => `
        <tr class="border-b border-gray-100 dark:border-neutral-800 hover:bg-gray-50 dark:hover:bg-neutral-800 cursor-pointer" data-incident="${i.id}">
            <td class="px-4 py-3 text-sm font-medium">${esc(i.title)}</td>
            <td class="px-4 py-3 text-sm capitalize">${esc(i.status)}</td>
            <td class="px-4 py-3 text-sm capitalize">${esc(i.severity)}</td>
            <td class="px-4 py-3 text-sm">${(i.regimes || []).map(r => esc(REGIME_LABELS[r] || r)).join(', ')}</td>
            <td class="px-4 py-3 text-sm">${fmtDate(i.firm_aware_at)}</td>
            <td class="px-4 py-3"><div class="flex flex-wrap gap-1">${clockBadges(i)} ${vendorBadge(i.clock)}</div></td>
        </tr>`).join('');

    const defaultsBoxes = Object.entries(REGIME_LABELS).map(([k, label]) => `
        <label class="flex items-center gap-1.5 text-sm">
            <input type="checkbox" name="regime-default" value="${k}" ${orgRegimeDefaults.includes(k) ? 'checked' : ''}> ${label}
        </label>`).join('');

    container.innerHTML = `
        <div class="flex items-center justify-between mb-4">
            <div>
                <h2 class="text-xl font-semibold">Security Incidents</h2>
                <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Multi-regime incident registry. Every notification clock for an incident's tagged regimes runs from when the firm became aware.</p>
            </div>
            <button id="incident-new-btn" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg">New Incident</button>
        </div>
        <div id="regime-defaults" class="flex flex-wrap items-center gap-4 mb-4 px-4 py-3 rounded-lg border border-gray-200 dark:border-neutral-700 bg-gray-50 dark:bg-neutral-800">
            <span class="text-sm font-medium text-gray-700 dark:text-gray-300">Default regimes for new incidents:</span>
            ${defaultsBoxes}
            <span class="text-xs text-gray-400">Changes are evidence-logged. Individual incidents can override.</span>
        </div>
        ${incidents.length === 0
            ? `<p class="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">No incidents recorded.</p>`
            : `<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-neutral-700">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 dark:bg-neutral-800 text-xs uppercase text-gray-500 dark:text-gray-400">
                        <tr><th class="px-4 py-3">Title</th><th class="px-4 py-3">Status</th><th class="px-4 py-3">Severity</th><th class="px-4 py-3">Regimes</th><th class="px-4 py-3">Firm aware</th><th class="px-4 py-3">Notification clocks</th></tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
               </div>`}`;

    container.querySelector('#incident-new-btn')?.addEventListener('click', () => renderForm(container, null));
    container.querySelectorAll('[data-incident]').forEach(tr =>
        tr.addEventListener('click', () => renderDetail(container, tr.getAttribute('data-incident'))));

    const defaultsBox = container.querySelector('#regime-defaults');
    defaultsBox.addEventListener('change', async () => {
        const picked = [...defaultsBox.querySelectorAll('input[name="regime-default"]:checked')].map(cb => cb.value);
        if (picked.length === 0) {
            ui.showToast('At least one regime is required', 'error');
            await renderList(container);
            return;
        }
        try {
            const saved = await api.setIncidentRegimes(orgId, picked);
            orgRegimeDefaults = saved.regimes || picked;
            ui.showToast('Default regimes saved', 'success');
        } catch (err) {
            ui.showToast(err.message || 'Failed to save regimes', 'error');
            await renderList(container);
        }
    });
}

function formField(label, inner, help = '') {
    return `<label class="block"><span class="text-sm font-medium text-gray-700 dark:text-gray-300">${label}</span>
        ${help ? `<span class="block text-xs text-gray-400 mb-1">${help}</span>` : ''}${inner}</label>`;
}

const INPUT_CLS = 'mt-1 w-full rounded-lg border border-gray-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 px-3 py-2 text-sm';

function renderForm(container, incident) {
    const i = incident || {};
    const tagged = incident ? (i.regimes || ['reg_sp']) : orgRegimeDefaults;
    const sel = (opts, cur) => opts.map(o => `<option value="${o}" ${o === cur ? 'selected' : ''}>${o.replace(/_/g, ' ')}</option>`).join('');
    const regimeBoxes = Object.entries(REGIME_LABELS).map(([k, label]) => `
        <label class="flex items-center gap-1.5 text-sm">
            <input type="checkbox" name="regimes" value="${k}" data-regime-box ${tagged.includes(k) ? 'checked' : ''}> ${label}
        </label>`).join('');
    container.innerHTML = `
        <button id="incident-back" class="text-sm text-blue-600 hover:underline mb-4">&larr; Back to incidents</button>
        <h2 class="text-xl font-semibold mb-4">${incident ? "Edit Incident" : "New Incident"}</h2>
        <form id="incident-form" class="max-w-2xl space-y-4">
            ${formField('Title *', `<input name="title" required maxlength="255" class="${INPUT_CLS}" value="${esc(i.title || '')}">`)}
            ${formField('Description', `<textarea name="description" rows="3" class="${INPUT_CLS}">${esc(i.description || '')}</textarea>`)}
            <div class="grid grid-cols-2 gap-4">
                ${formField('Status', `<select name="status" class="${INPUT_CLS}">${sel(STATUS_OPTIONS, i.status || 'open')}</select>`)}
                ${formField('Severity', `<select name="severity" class="${INPUT_CLS}">${sel(SEVERITY_OPTIONS, i.severity || 'medium')}</select>`)}
            </div>
            ${formField('Reportable under *', `<div class="flex flex-wrap gap-4 mt-1">${regimeBoxes}</div>`,
                        'Tagging a regime runs its notification clocks; untag if the incident is determined non-reportable under it (the change is recorded in the event trail)')}
            <div id="eu-fields" class="${tagged.includes('eu_ai_act') ? '' : 'hidden'} space-y-4 border-l-2 border-gray-200 dark:border-neutral-700 pl-4">
                ${formField('EU incident class', `<select name="eu_incident_class" class="${INPUT_CLS}">${sel(EU_CLASS_OPTIONS, i.eu_incident_class || 'general')}</select>`,
                            'Art. 73 authority-report deadline: general 15d · death or serious harm 10d · widespread 2d')}
            </div>
            <div id="hipaa-fields" class="${tagged.includes('hipaa') ? '' : 'hidden'} space-y-4 border-l-2 border-gray-200 dark:border-neutral-700 pl-4">
                <div class="grid grid-cols-2 gap-4">
                    ${formField('HIPAA role', `<select name="hipaa_role" class="${INPUT_CLS}">${sel(HIPAA_ROLE_OPTIONS, i.hipaa_role || 'covered_entity')}</select>`,
                                'Business associates owe the covered entity notice within 60d instead')}
                    ${formField('Individuals affected', `<input type="number" min="0" name="affected_count" class="${INPUT_CLS}" value="${i.affected_count ?? ''}">`,
                                '≥500 adds media + contemporaneous HHS notice; <500 goes in the HHS annual log')}
                </div>
            </div>
            ${formField('Firm became aware *', `<input type="datetime-local" name="firm_aware_at" required class="${INPUT_CLS}" value="${toInputValue(i.firm_aware_at)}">`,
                        'Awareness / discovery date — starts the notification clocks of every tagged regime')}
            <div class="grid grid-cols-2 gap-4">
                ${formField('Occurred (start)', `<input type="datetime-local" name="occurred_at" class="${INPUT_CLS}" value="${toInputValue(i.occurred_at)}">`)}
                ${formField('Occurred (range end)', `<input type="datetime-local" name="occurred_range_end" class="${INPUT_CLS}" value="${toInputValue(i.occurred_range_end)}">`)}
            </div>
            ${formField('Source', `<select name="source" id="incident-source" class="${INPUT_CLS}">
                <option value="internal" ${i.source !== 'vendor' ? 'selected' : ''}>internal</option>
                <option value="vendor" ${i.source === 'vendor' ? 'selected' : ''}>vendor (service provider)</option></select>`)}
            <div id="vendor-fields" class="${i.source === 'vendor' ? '' : 'hidden'} space-y-4 border-l-2 border-gray-200 dark:border-neutral-700 pl-4">
                ${formField('Vendor name *', `<input name="vendor_name" class="${INPUT_CLS}" value="${esc(i.vendor_name || '')}">`)}
                <div class="grid grid-cols-2 gap-4">
                    ${formField('Vendor became aware', `<input type="datetime-local" name="vendor_aware_at" class="${INPUT_CLS}" value="${toInputValue(i.vendor_aware_at)}">`)}
                    ${formField('Vendor notified firm', `<input type="datetime-local" name="vendor_notified_firm_at" class="${INPUT_CLS}" value="${toInputValue(i.vendor_notified_firm_at)}">`, 'Rule requires ≤ 72 hours after vendor awareness')}
                </div>
            </div>
            ${formField('Data types involved', `<input name="data_types" class="${INPUT_CLS}" value="${esc((i.data_types || []).join ? (i.data_types || []).join(', ') : '')}" placeholder="e.g. email, chat content, oauth tokens">`, 'Comma-separated; feeds the customer-notice content')}
            ${formField('Affected scope', `<textarea name="affected_scope" rows="2" class="${INPUT_CLS}" placeholder="e.g. all users whose conversations were stored between X and Y">${esc(i.affected_scope || '')}</textarea>`)}
            ${formField('Assessment notes (nature & scope)', `<textarea name="assessment_notes" rows="2" class="${INPUT_CLS}">${esc(i.assessment_notes || '')}</textarea>`)}
            ${formField('Containment notes', `<textarea name="containment_notes" rows="2" class="${INPUT_CLS}">${esc(i.containment_notes || '')}</textarea>`)}
            ${formField('Harm assessment', `<textarea name="harm_assessment" rows="2" class="${INPUT_CLS}">${esc(i.harm_assessment || '')}</textarea>`)}
            ${formField('Harm determination', `<select name="harm_determination" class="${INPUT_CLS}">
                <option value="" ${!i.harm_determination ? 'selected' : ''}>— undetermined —</option>
                <option value="notification_required" ${i.harm_determination === 'notification_required' ? 'selected' : ''}>notification required</option>
                <option value="no_substantial_harm" ${i.harm_determination === 'no_substantial_harm' ? 'selected' : ''}>no substantial harm (documented exception)</option></select>`,
                'Server-stamps who made the determination and when')}
            <div class="border-t border-gray-200 dark:border-neutral-700 pt-4 space-y-4">
                <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="ag_delay" ${i.ag_delay ? 'checked' : ''}> Attorney-General delay in effect</label>
                <div class="grid grid-cols-2 gap-4">
                    ${formField('AG delay reference', `<input name="ag_delay_reference" class="${INPUT_CLS}" value="${esc(i.ag_delay_reference || '')}">`)}
                    ${formField('AG delay until', `<input type="datetime-local" name="ag_delay_until" class="${INPUT_CLS}" value="${toInputValue(i.ag_delay_until)}">`)}
                </div>
            </div>
            <div class="flex gap-3 pt-2">
                <button type="submit" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg">${incident ? 'Save changes' : 'Create incident'}</button>
                <button type="button" id="incident-cancel" class="px-4 py-2 text-sm text-gray-600 dark:text-gray-300">Cancel</button>
            </div>
        </form>`;

    container.querySelector('#incident-source').addEventListener('change', e =>
        container.querySelector('#vendor-fields').classList.toggle('hidden', e.target.value !== 'vendor'));
    const regimeOn = k => !!container.querySelector(`input[name="regimes"][value="${k}"]`)?.checked;
    container.querySelectorAll('[data-regime-box]').forEach(cb => cb.addEventListener('change', () => {
        container.querySelector('#eu-fields').classList.toggle('hidden', !regimeOn('eu_ai_act'));
        container.querySelector('#hipaa-fields').classList.toggle('hidden', !regimeOn('hipaa'));
    }));
    const goBack = () => incident ? renderDetail(container, incident.id) : renderList(container);
    container.querySelector('#incident-back').addEventListener('click', goBack);
    container.querySelector('#incident-cancel').addEventListener('click', goBack);

    container.querySelector('#incident-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const data = {};
        for (const [k, v] of fd.entries()) data[k] = v === '' ? null : v;
        data.ag_delay = fd.get('ag_delay') === 'on';
        data.data_types = (fd.get('data_types') || '').split(',').map(s => s.trim()).filter(Boolean);
        data.regimes = fd.getAll('regimes');
        if (data.regimes.length === 0) {
            ui.showToast('Select at least one regime', 'error');
            return;
        }
        if (!data.regimes.includes('eu_ai_act')) data.eu_incident_class = null;
        if (!data.regimes.includes('hipaa')) {
            data.hipaa_role = null;
            data.affected_count = null;
        } else if (data.affected_count != null) {
            const n = parseInt(data.affected_count, 10);
            data.affected_count = Number.isNaN(n) ? null : n;
        }
        for (const k of ['firm_aware_at', 'occurred_at', 'occurred_range_end', 'vendor_aware_at', 'vendor_notified_firm_at', 'ag_delay_until']) {
            if (data[k]) data[k] = new Date(data[k]).toISOString();
        }
        try {
            if (incident) {
                await api.updateIncident(orgId, incident.id, data);
                ui.showToast('Incident updated', 'success');
                await renderDetail(container, incident.id);
            } else {
                const created = await api.createIncident(orgId, data);
                ui.showToast('Incident recorded', 'success');
                await renderDetail(container, created.id);
            }
        } catch (err) {
            ui.showToast(err.message || 'Save failed', 'error');
        }
    });
}

async function renderDetail(container, incidentId) {
    container.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;
    const res = await api.getIncident(orgId, incidentId);
    const i = res.incident;
    const events = res.events || [];
    const clock = i.clock;

    const fieldRows = [
        ['Status', `${esc(i.status)}`], ['Severity', esc(i.severity)],
        ['Regimes', (i.regimes || []).map(r => esc(REGIME_LABELS[r] || r)).join(', ')],
        ['Source', i.source === 'vendor' ? `vendor — ${esc(i.vendor_name)}` : 'internal'],
        ['Firm became aware', fmtDate(i.firm_aware_at)],
        ['Occurred', i.occurred_range_end ? `${fmtDate(i.occurred_at)} → ${fmtDate(i.occurred_range_end)}` : fmtDate(i.occurred_at)],
        ['Data types', esc((i.data_types || []).join(', ') || '—')],
        ['Affected scope', esc(i.affected_scope || '—')],
        ['Assessment', esc(i.assessment_notes || '—')],
        ['Containment', esc(i.containment_notes || '—')],
        ['Harm assessment', esc(i.harm_assessment || '—')],
        ['Harm determination', i.harm_determination
            ? `${esc(i.harm_determination)} <span class="text-xs text-gray-400">(${esc(i.harm_determined_by || '')}, ${fmtDate(i.harm_determined_at)})</span>` : '—'],
    ];
    if ((i.regimes || []).includes('reg_sp')) {
        fieldRows.push(['Customers notified', fmtDate(i.customers_notified_at)]);
    }
    if ((i.regimes || []).includes('eu_ai_act')) {
        fieldRows.push(['EU incident class', esc((i.eu_incident_class || 'general').replace(/_/g, ' '))]);
    }
    if ((i.regimes || []).includes('hipaa')) {
        fieldRows.push(['HIPAA role', esc((i.hipaa_role || 'covered_entity').replace(/_/g, ' '))]);
        fieldRows.push(['Individuals affected', i.affected_count ?? '—']);
    }
    if (i.source === 'vendor') {
        fieldRows.splice(5, 0, ['Vendor aware / notified firm', `${fmtDate(i.vendor_aware_at)} → ${fmtDate(i.vendor_notified_firm_at)}`]);
    }
    if (i.ag_delay) fieldRows.push(['AG delay', `until ${fmtDate(i.ag_delay_until)} — ${esc(i.ag_delay_reference || '')}`]);

    const timeline = events.map(e => `
        <li class="border-l-2 border-gray-200 dark:border-neutral-700 pl-4 pb-4">
            <div class="text-xs text-gray-400">${fmtDate(e.event_at)} · ${esc(e.actor_email || e.actor_id || 'system')}</div>
            <div class="text-sm font-medium capitalize">${esc(e.event_type.replace(/_/g, ' '))}</div>
            ${e.detail ? `<div class="text-sm text-gray-600 dark:text-gray-300">${esc(e.detail)}</div>` : ''}
            ${e.changes ? `<pre class="text-xs bg-gray-50 dark:bg-neutral-800 rounded p-2 mt-1 overflow-x-auto">${esc(JSON.stringify(e.changes, null, 1))}</pre>` : ''}
        </li>`).join('');

    container.innerHTML = `
        <button id="incident-back" class="text-sm text-blue-600 hover:underline mb-4">&larr; Back to incidents</button>
        <div class="flex items-start justify-between mb-2">
            <h1 class="text-2xl font-bold">${esc(i.title)}</h1>
            <div class="flex gap-2">
                <button id="incident-edit" class="px-3 py-1.5 text-sm border border-gray-300 dark:border-neutral-600 rounded-lg">Edit</button>
                <a href="${api.incidentExportUrl(orgId, i.id, 'json')}" class="px-3 py-1.5 text-sm border border-gray-300 dark:border-neutral-600 rounded-lg">Export JSON</a>
                <a href="${api.incidentExportUrl(orgId, i.id, 'csv')}" class="px-3 py-1.5 text-sm border border-gray-300 dark:border-neutral-600 rounded-lg">Export CSV</a>
            </div>
        </div>
        <div class="mb-4 space-y-1.5">
            ${(i.clocks || []).map(c => `
                <div class="flex flex-wrap gap-2 items-center">${clockBadge(c)}
                    <span class="text-xs text-gray-500 dark:text-gray-400">${esc(c.label || '')}</span>
                    ${c.state === 'notified' && c.notified_at ? `<span class="text-xs text-gray-400">notified ${fmtDate(c.notified_at)}</span>`
                      : c.due_at ? `<span class="text-xs text-gray-400">due ${fmtDate(c.due_at)}</span>` : ''}
                </div>`).join('')}
            ${vendorBadge(clock)}
        </div>
        ${i.description ? `<p class="text-sm text-gray-600 dark:text-gray-300 mb-4 max-w-2xl">${esc(i.description)}</p>` : ''}
        <div class="grid md:grid-cols-2 gap-6 max-w-5xl">
            <div class="rounded-lg border border-gray-200 dark:border-neutral-700 divide-y divide-gray-100 dark:divide-neutral-800">
                ${fieldRows.map(([k, v]) => `<div class="px-4 py-2.5 grid grid-cols-3 gap-2"><span class="text-xs uppercase text-gray-400 pt-0.5">${k}</span><span class="col-span-2 text-sm">${v}</span></div>`).join('')}
            </div>
            <div>
                <h2 class="text-lg font-semibold mb-3">Event timeline</h2>
                <ul>${timeline || '<li class="text-sm text-gray-400">No events.</li>'}</ul>
                <form id="incident-event-form" class="mt-4 space-y-2 border-t border-gray-200 dark:border-neutral-700 pt-4">
                    <div class="flex gap-2">
                        <select name="event_type" class="${INPUT_CLS} mt-0 w-48">
                            ${eventTypesFor(i.regimes).map(t => `<option value="${t}">${t.replace(/_/g, ' ')}</option>`).join('')}
                        </select>
                        <input name="detail" required placeholder="What happened (e.g. notices mailed to 120 customers)" class="${INPUT_CLS} mt-0 flex-1">
                    </div>
                    <p class="text-xs text-gray-400">The "… notified" event types record that the firm sent that notice through its own channels — the first one stamps the date that stops the matching clock.</p>
                    <button type="submit" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg">Log event</button>
                </form>
            </div>
        </div>`;

    container.querySelector('#incident-back').addEventListener('click', () => renderList(container));
    container.querySelector('#incident-edit').addEventListener('click', () => renderForm(container, i));
    container.querySelector('#incident-event-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
            await api.logIncidentEvent(orgId, i.id, { event_type: fd.get('event_type'), detail: fd.get('detail') });
            ui.showToast('Event logged', 'success');
            await renderDetail(container, i.id);
        } catch (err) {
            ui.showToast(err.message || 'Failed to log event', 'error');
        }
    });
}
