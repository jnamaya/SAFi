/**
 * Tools Catalog: what the operator installed, and what it offers (backlog 48d).
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
    wireAuthControls();
}

function shell() {
    return `
    <div class="max-w-4xl mx-auto p-6 space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Tools Catalog</h1>
        <p class="text-sm text-gray-500 mt-1 max-w-3xl">
          These are tools your administrator has installed on this deployment, and what each one
          is enabled by. A tool does nothing until a policy enables it and an agent is assigned it.
        </p>
      </div>

      <div class="rounded-xl border border-gray-200 dark:border-neutral-800 bg-gray-50 dark:bg-neutral-900/50 p-4">
        <h2 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">How tools get into this catalog</h2>
        <ol class="text-sm text-gray-600 dark:text-gray-400 space-y-1.5 list-decimal list-outside pl-5">
          <li>An administrator installs the MCP server from the terminal or command prompt.</li>
          <li>SAFi connects to that server, asks what tools it has, and catalogs them here.</li>
          <li>An admin or editor enables specific tools in the policy wizard, under
              <strong>Tools &amp; Guardrails</strong>. Those tools then become available to every
              agent that uses that policy.</li>
          <li>Every call an agent makes is checked against that allow list before it runs.</li>
        </ol>
      </div>

      <div id="tools-list" class="space-y-4"></div>
    </div>`;
}

async function refresh() {
    try {
        const data = await api.listMcpServers();
        if (data && data.ok === false) throw new Error(data.error || 'Could not load the tools catalog.');
        state.servers = (data && data.servers) || [];
        state.toolCount = (data && data.tool_count) || 0;
        state.error = '';
    } catch (err) {
        state.servers = [];
        state.error = err.message || 'Could not load the tools catalog.';
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

/**
 * OAuth servers are connected per PERSON, not per process: "connected" on their
 * card means "you are", and the button connects or disconnects your own
 * account. The token it stores is audience-bound to this one server — it is
 * not a Google (or other upstream) credential and works nowhere else.
 */
function statusBadge(s) {
    if (s.auth === 'oauth') {
        return s.user_connected
            ? '<span class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">you are connected</span>'
            : '<span class="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">sign-in required</span>';
    }
    return s.connected
        ? '<span class="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">connected</span>'
        : '<span class="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">not connected</span>';
}

function authControls(s) {
    if (s.auth !== 'oauth') return '';
    if (s.user_connected) {
        return `<button data-mcp-disconnect="${esc(s.key)}"
                  class="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-neutral-700 text-xs">Disconnect</button>`;
    }
    return `<a href="/api/mcp/auth/${encodeURIComponent(s.key)}/login"
              class="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium">Sign in</a>`;
}

function wireAuthControls() {
    const el = document.getElementById('tools-list');
    if (!el || el.dataset.authWired) return;
    el.dataset.authWired = '1';
    el.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-mcp-disconnect]');
        if (!btn) return;
        btn.disabled = true;
        try {
            await api.disconnectMcpAuth(btn.dataset.mcpDisconnect);
            await refresh();
        } catch (err) {
            btn.disabled = false;
        }
    });
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
            <p class="text-sm text-gray-500">No tools have been installed on this deployment yet.</p>
            <p class="text-xs text-gray-400 mt-2">
              An administrator adds an MCP server from the host with
              <span class="font-mono">scripts/safi_mcp.py add</span>.
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
              ${statusBadge(s)}
            </div>
            ${s.error ? `<p class="text-xs text-red-600 dark:text-red-400 mt-2">${esc(s.error)}</p>` : ''}
            ${s.auth === 'oauth' && !s.tools.length ? '<p class="text-xs text-gray-500 mt-2">Tools appear after the first sign-in: this server shows its catalog to a signed-in user, not to the deployment.</p>' : ''}
          </div>
          <div class="flex items-center gap-3 shrink-0">
            ${authControls(s)}
            <span class="text-xs text-gray-400">${s.tools.length} tool${s.tools.length === 1 ? '' : 's'}</span>
          </div>
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
