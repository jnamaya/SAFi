/**
 * Scheduled Updates (backlog 54): personal agent digests on a timer.
 *
 * v1 rules the UI states plainly: delivery goes to the user's own account
 * email only; the runner executes each due schedule as a FULL governed turn
 * (the digest also appears as a conversation), and the email carries the
 * approved output. Schedules are a local time + weekday set in the user's
 * timezone, captured from the browser at creation.
 */
import * as api from '../../core/api.js';
import * as ui from '../ui.js';
import { escapeHtml } from '../../core/utils.js';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

let _profiles = [];
let _editing = null;   // the schedule being edited, or null for create mode

export async function renderSettingsSchedulesTab(profiles) {
    if (Array.isArray(profiles) && profiles.length) _profiles = profiles;
    const container = document.getElementById('tab-schedules');
    if (!container) return;
    container.innerHTML = `<div class="flex items-center justify-center h-32"><div class="thinking-spinner"></div></div>`;

    let data = { email_configured: false, schedules: [] };
    try {
        data = await api.fetchSchedules();
        // Editing something that no longer exists (deleted elsewhere) resets
        // the form to create mode rather than saving into a 404.
        if (_editing && !(data.schedules || []).some(s => s.id === _editing.id)) _editing = null;
    } catch (e) {
        container.innerHTML = `<p class="text-red-500 p-6">Could not load schedules: ${escapeHtml(e.message || '')}</p>`;
        return;
    }
    _paint(container, data);
}

function _paint(container, data) {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const rows = (data.schedules || []).map(_scheduleRow).join('');

    container.innerHTML = `
        <div class="settings-page-header">
            <h1>Scheduled Updates</h1>
            <p>Have an agent send you an update on a schedule. Each run is a fully
            governed turn — it appears in your conversations and in the audit
            record — and the approved response is emailed to your account address.</p>
        </div>

        ${data.email_configured ? '' : `
        <div class="mb-6 p-4 rounded-lg border border-amber-200 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-900/10 text-sm text-amber-800 dark:text-amber-300">
            Email is not configured on this deployment (SMTP settings in .env).
            Schedules will still run and appear in your conversations, but no
            email will be sent until an operator configures SMTP.
        </div>`}

        <div class="profile-section-container shadow-sm mb-6" id="sched-form">
            <div class="flex items-center gap-2 mb-3 border-b border-gray-100 dark:border-gray-700 pb-2">
                <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${_editing ? 'Edit schedule' : 'New schedule'}</h4>
                <span class="text-xs text-neutral-400 font-normal ml-auto">Times are in ${escapeHtml(_editing ? (_editing.timezone || tz) : tz)}</span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <label class="text-xs font-bold text-gray-500 uppercase">Agent</label>
                    <select id="sched-agent" class="w-full mt-1 p-2.5 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm">
                        ${_profiles.map(p => {
                            const k = p.key || p.id || '';
                            const sel = _editing && _editing.agent_key === k ? ' selected' : '';
                            return `<option value="${escapeHtml(k)}"${sel}>${escapeHtml(p.name || k)}</option>`;
                        }).join('')}
                    </select>
                    <label class="text-xs font-bold text-gray-500 uppercase mt-3 block">Time</label>
                    <input id="sched-time" type="time" value="${escapeHtml(_editing ? (_editing.time_of_day || '06:00') : '06:00')}"
                        class="mt-1 p-2.5 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm">
                    <label class="text-xs font-bold text-gray-500 uppercase mt-3 block">Days</label>
                    <div id="sched-days" class="flex flex-wrap gap-2 mt-1">
                        ${DAY_LABELS.map((d, i) => {
                            const on = _editing
                                ? String(_editing.days || '').split(',').includes(String(i))
                                : i < 5;
                            return `
                            <label class="flex items-center gap-1.5 text-sm px-2.5 py-1 rounded-lg border border-gray-200 dark:border-neutral-700 cursor-pointer select-none">
                                <input type="checkbox" value="${i}" ${on ? 'checked' : ''} class="accent-green-600">${d}
                            </label>`;
                        }).join('')}
                    </div>
                </div>
                <div class="flex flex-col">
                    <label class="text-xs font-bold text-gray-500 uppercase">What should the agent do?</label>
                    <textarea id="sched-prompt" class="flex-1 mt-1 p-3 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm resize-y min-h-28"
                        placeholder="e.g. Summarize today's market headlines and any earnings reports relevant to my portfolio watchlist.">${escapeHtml(_editing ? (_editing.prompt || '') : '')}</textarea>
                    <div class="mt-3 self-end flex items-center gap-3">
                        ${_editing ? `<button id="sched-cancel" class="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-neutral-800">Cancel</button>` : ''}
                        <button id="sched-create" class="px-5 py-2 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm shadow-sm">
                            ${_editing ? 'Save changes' : 'Create schedule'}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="space-y-2">${rows || '<p class="text-sm text-gray-400 px-1">No schedules yet.</p>'}</div>
    `;

    container.querySelector('#sched-create')?.addEventListener('click', async () => {
        const days = [...container.querySelectorAll('#sched-days input:checked')].map(c => parseInt(c.value, 10));
        const payload = {
            agent_key: container.querySelector('#sched-agent').value,
            prompt: container.querySelector('#sched-prompt').value.trim(),
            time_of_day: container.querySelector('#sched-time').value,
            days,
        };
        try {
            if (_editing) {
                // Deliberately no timezone in the update payload: editing a
                // schedule from another timezone must not silently shift when
                // it fires. The stored timezone stays until recreated.
                await api.updateSchedule(_editing.id, payload);
                _editing = null;
                ui.showToast('Schedule updated.', 'success');
            } else {
                await api.createSchedule({ ...payload, timezone: tz });
                ui.showToast('Schedule created.', 'success');
            }
            renderSettingsSchedulesTab();
        } catch (e) {
            ui.showToast(_err(e) || 'Could not save the schedule.', 'error');
        }
    });

    container.querySelector('#sched-cancel')?.addEventListener('click', () => {
        _editing = null;
        renderSettingsSchedulesTab();
    });

    container.querySelectorAll('[data-sched-edit]').forEach(btn => {
        btn.addEventListener('click', () => {
            _editing = (data.schedules || []).find(s => s.id === btn.dataset.schedEdit) || null;
            _paint(container, data);
            container.querySelector('#sched-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });

    container.querySelectorAll('[data-sched-toggle]').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                await api.updateSchedule(btn.dataset.schedToggle, { enabled: btn.dataset.enabled !== '1' });
                renderSettingsSchedulesTab();
            } catch (e) { ui.showToast('Could not update the schedule.', 'error'); }
        });
    });
    container.querySelectorAll('[data-sched-delete]').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this schedule?')) return;
            try {
                await api.deleteSchedule(btn.dataset.schedDelete);
                ui.showToast('Schedule deleted.', 'success');
                renderSettingsSchedulesTab();
            } catch (e) { ui.showToast('Could not delete the schedule.', 'error'); }
        });
    });
}

function _scheduleRow(s) {
    const days = String(s.days || '').split(',').filter(Boolean)
        .map(d => DAY_LABELS[parseInt(d, 10)] || '').join(', ');
    const agent = String(s.agent_key || '').replace(/_/g, ' ');
    const on = !!Number(s.enabled);
    return `
        <div class="flex items-start justify-between gap-4 p-4 rounded-lg border border-gray-200 dark:border-neutral-700 ${on ? '' : 'opacity-60'}">
            <div class="min-w-0">
                <div class="text-sm font-semibold text-gray-800 dark:text-gray-200">${escapeHtml(agent)}
                    <span class="font-normal text-gray-400 ml-2">${escapeHtml(s.time_of_day || '')} · ${escapeHtml(days)} · ${escapeHtml(s.timezone || '')}</span>
                </div>
                <div class="text-sm text-gray-500 mt-1 truncate">${escapeHtml(s.prompt || '')}</div>
                ${s.last_status ? `<div class="text-xs text-gray-400 mt-1">Last run: ${escapeHtml(s.last_run_date || '')} — ${escapeHtml(s.last_status)}</div>` : ''}
            </div>
            <div class="shrink-0 flex items-center gap-3">
                <button data-sched-edit="${escapeHtml(s.id)}" class="text-xs font-medium text-green-700 dark:text-green-400 hover:underline">Edit</button>
                <button data-sched-toggle="${escapeHtml(s.id)}" data-enabled="${on ? 1 : 0}"
                    class="text-xs font-medium ${on ? 'text-gray-500 hover:text-gray-700' : 'text-green-600 hover:underline'}">${on ? 'Pause' : 'Resume'}</button>
                <button data-sched-delete="${escapeHtml(s.id)}" class="text-xs text-red-600 dark:text-red-400 hover:underline">Delete</button>
            </div>
        </div>`;
}

function _err(e) {
    try { const p = JSON.parse(e.message); return p.error; } catch (_) { return e.message; }
}
