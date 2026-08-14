/**
 * Tool Servers: what the operator installed, and what it offers (backlog 48d).
 *
 * This screen installs nothing. An earlier version let an admin browse the
 * official registry and install a hosted server here; it was removed, because
 * installation belongs on the host, where the person doing it already holds the
 * rights that installing implies.
 *
 * The job left for this screen is the one the pipeline actually needs: show that
 * a server exists and is talking, list the tools it advertises, and be
 * unambiguous that none of it is doing anything yet. A tool becomes usable only
 * when a policy enables it and an agent is assigned it, so the copy says so
 * rather than leaving an admin to wonder whether an install "took".
 */
import * as api from '../../core/api.js';

let state = { servers: [], toolCount: 0, error: '' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

export async function renderSettingsToolsTab() {
    const container = document.getElementById('tab-tools');
    if (!container) return;
    container.innerHTML = shell();
    await refresh();
}

function shell() {
    return `
    <div class="max-w-4xl mx-auto p-6 space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Tool Servers</h1>
        <p class="text-sm text-gray-500 mt-1 max-w-3xl">
          Tool servers your operator has installed on this deployment, and what each tool is
          enabled by. A tool does nothing until a policy enables it and an agent is assigned it.
        </p>
      </div>

      <div class="rounded-xl border border-gray-200 dark:border-neutral-800 bg-gray-50 dark:bg-neutral-900/50 p-4">
        <h2 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">How a tool reaches an agent</h2>
        <ol class="text-sm text-gray-600 dark:text-gray-400 space-y-1 list-decimal list-inside">
          <li>An operator installs the server on the host.</li>
          <li>SAFi connects to it and asks what tools it has. That is this page.</li>
          <li>A policy editor enables specific tools and blocks the rest.</li>
          <li>An agent is assigned the tools its policy allows.</li>
          <li>Every call is checked against that list before it runs.</li>
        </ol>
      </div>

      <div id="tools-list" class="space-y-4"></div>
    </div>`;
}

async function refresh() {
    try {
        const data = await api.listMcpServers();
        if (data && data.ok === false) throw new Error(data.error || 'Could not load tool servers.');
        state.servers = (data && data.servers) || [];
        state.toolCount = (data && data.tool_count) || 0;
        state.error = '';
    } catch (err) {
        state.servers = [];
        state.error = err.message || 'Could not load tool servers.';
    }
    paint();
}

/**
 * One tool, with its real status.
 *
 * "Enabled" here means a policy lists it, which is the ceiling the Will
 * enforces; "assigned" means an agent carries it. Both are shown because they
 * answer different questions, and because a tool enabled by a policy that no
 * agent uses is a common and perfectly reasonable state that should not read as
 * either on or off.
 */
function toolRow(t) {
    const enabled = t.policies && t.policies.length;
    const assigned = t.agents && t.agents.length;
    return `
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono text-xs text-gray-700 dark:text-gray-300">${esc(t.name)}</span>
            ${enabled
              ? '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">enabled</span>'
              : '<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600 dark:bg-neutral-800 dark:text-gray-400">inactive</span>'}
          </div>
          <p class="text-xs text-gray-500 mt-0.5">${esc(t.description)}</p>
          ${enabled ? `<p class="text-xs text-gray-500 mt-1">Policy: ${t.policies.map(esc).join(', ')}</p>` : ''}
          ${assigned
            ? `<p class="text-xs text-gray-500">Agents: ${t.agents.map(esc).join(', ')}</p>`
            : (enabled ? '<p class="text-xs text-gray-400">No agent is assigned it yet.</p>' : '')}
        </div>
      </div>`;
}

function paint() {
    const el = document.getElementById('tools-list');
    if (!el) return;

    if (state.error) {
        el.innerHTML = `<p class="text-sm text-red-600 dark:text-red-400 py-4">${esc(state.error)}</p>`;
        return;
    }
    if (!state.servers.length) {
        el.innerHTML = `
          <div class="rounded-xl border border-dashed border-gray-300 dark:border-neutral-700 p-6 text-center">
            <p class="text-sm text-gray-500">No tool servers are installed on this deployment.</p>
            <p class="text-xs text-gray-400 mt-2">
              An operator adds one with <span class="font-mono">scripts/safi_mcp.py add</span> on the host.
            </p>
          </div>`;
        return;
    }

    el.innerHTML = state.servers.map(s => `
      <div class="rounded-xl border border-gray-200 dark:border-neutral-800 p-4 bg-white dark:bg-neutral-900">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-semibold text-gray-900 dark:text-white">${esc(s.label)}</span>
              <span class="font-mono text-xs text-gray-500">${esc(s.key)}</span>
              ${s.connected
                ? '<span class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">connected</span>'
                : '<span class="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">not connected</span>'}
            </div>
            ${s.error ? `<p class="text-xs text-red-600 dark:text-red-400 mt-2">${esc(s.error)}</p>` : ''}
          </div>
          <span class="text-xs text-gray-400 shrink-0">${s.tools.length} tool${s.tools.length === 1 ? '' : 's'}</span>
        </div>

        ${s.tools.length ? `
          <div class="mt-3 border-t border-gray-100 dark:border-neutral-800 pt-3 space-y-3">
            ${s.tools.map(toolRow).join('')}
          </div>
          ${s.enabled_count === 0 ? `
            <p class="text-xs text-gray-400 mt-3">
              None of these are enabled yet. Turn on the ones you want in a policy's
              Tools &amp; Guardrails step.
            </p>` : ''}` : ''}
      </div>`).join('');
}
