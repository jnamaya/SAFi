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
 *
 * Layout: one compact card per server (thumbnail, name, connection, counts),
 * two or three abreast. The full tool list, which can run long, lives behind
 * the card's "View tools" button in a modal, so ten servers stay one screen.
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
    wireEvents(container);
}

function shell() {
    return `
    <div class="max-w-5xl mx-auto p-6 space-y-8">
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

      <div id="tools-list"></div>

      <div id="tools-modal" class="hidden fixed inset-0 z-50">
        <div class="absolute inset-0 bg-black/40" data-modal-close></div>
        <div class="relative mx-auto mt-16 mb-10 w-[calc(100%-2rem)] max-w-2xl max-h-[75vh] flex flex-col rounded-xl bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-800 shadow-xl">
          <div class="flex items-center justify-between gap-3 px-5 py-4 border-b border-gray-100 dark:border-neutral-800">
            <div class="min-w-0">
              <h3 id="tools-modal-title" class="font-semibold text-gray-900 dark:text-white truncate"></h3>
              <p id="tools-modal-subtitle" class="text-xs text-gray-500"></p>
            </div>
            <button data-modal-close aria-label="Close"
              class="shrink-0 w-8 h-8 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-neutral-800">&#10005;</button>
          </div>
          <div id="tools-modal-body" class="px-5 py-4 space-y-3 overflow-y-auto"></div>
        </div>
      </div>
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

/* ── thumbnails ──────────────────────────────────────────────────────────────
   No server ships an image, so the thumbnail is a brand mark for vendors we
   can recognize from the key/label, and a monogram tile for everything else.
   Recognition is presentation only; nothing behavioural keys off it. */

const BRAND_ICONS = {
    google: `<svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.4c-.3 1.6-1.2 2.9-2.5 3.8v3h4c2.4-2.2 3.6-5.4 3.6-9z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-4-3c-1.1.7-2.5 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.3v3.1C3.3 21.4 7.3 24 12 24z"/><path fill="#FBBC05" d="M5.4 14.4c-.2-.7-.4-1.5-.4-2.4s.1-1.7.4-2.4V6.5H1.3C.5 8.2 0 10 0 12s.5 3.8 1.3 5.5l4.1-3.1z"/><path fill="#EA4335" d="M12 4.7c1.8 0 3.3.6 4.6 1.8L20.1 3C18 1.1 15.2 0 12 0 7.3 0 3.3 2.6 1.3 6.5l4.1 3.1C6.3 6.8 8.9 4.7 12 4.7z"/></svg>`,
    microsoft: `<svg class="w-5 h-5" viewBox="0 0 24 24"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M13 1h10v10H13z"/><path fill="#05a6f0" d="M1 13h10v10H1z"/><path fill="#ffba08" d="M13 13h10v10H13z"/></svg>`,
    github: `<svg class="w-5 h-5 text-gray-900 dark:text-white" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>`,
};

const MONO_TILES = [
    'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
    'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
    'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
];

function thumbnail(s) {
    const hay = `${s.key} ${s.label}`.toLowerCase();
    let mark = null;
    if (hay.includes('github')) mark = BRAND_ICONS.github;
    else if (hay.includes('google') || hay.includes('workspace')) mark = BRAND_ICONS.google;
    else if (hay.includes('microsoft') || hay.includes('graph') || hay.includes('365')) mark = BRAND_ICONS.microsoft;
    if (mark) {
        return `<div class="w-9 h-9 shrink-0 rounded-lg border border-gray-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 flex items-center justify-center">${mark}</div>`;
    }
    let hash = 0;
    for (const ch of String(s.key)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    const tile = MONO_TILES[hash % MONO_TILES.length];
    const letter = esc((s.label || s.key || '?').trim().charAt(0).toUpperCase());
    return `<div class="w-9 h-9 shrink-0 rounded-lg ${tile} flex items-center justify-center text-sm font-bold">${letter}</div>`;
}

/**
 * One tool, with its real status — rendered inside the modal.
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

function card(s) {
    const enabled = s.enabled_count || 0;
    const counts = s.tools.length
        ? `${s.tools.length} tool${s.tools.length === 1 ? '' : 's'} &middot; ${enabled} enabled`
        : (s.auth === 'oauth' ? 'Tools appear after the first sign-in.' : 'No tools discovered.');
    return `
      <div class="rounded-xl border border-gray-200 dark:border-neutral-800 p-4 bg-white dark:bg-neutral-900 flex flex-col gap-3">
        <div class="flex items-start gap-3">
          ${thumbnail(s)}
          <div class="min-w-0">
            <p class="font-semibold text-sm text-gray-900 dark:text-white truncate" title="${esc(s.label)}">${esc(s.label)}</p>
            <p class="font-mono text-[11px] text-gray-500 truncate">${esc(s.key)}</p>
          </div>
        </div>
        <div>${statusBadge(s)}</div>
        <p class="text-xs text-gray-500">${counts}</p>
        ${s.error ? `<p class="text-xs text-red-600 dark:text-red-400 truncate" title="${esc(s.error)}">${esc(s.error)}</p>` : ''}
        <div class="mt-auto pt-1 flex items-center gap-2">
          ${s.tools.length ? `
            <button data-mcp-tools="${esc(s.key)}"
              class="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-neutral-700 text-xs font-medium hover:bg-gray-50 dark:hover:bg-neutral-800">
              View tools
            </button>` : ''}
          ${authControls(s)}
        </div>
      </div>`;
}

function openToolsModal(key) {
    const s = state.servers.find(v => v.key === key);
    const modal = document.getElementById('tools-modal');
    if (!s || !modal) return;
    document.getElementById('tools-modal-title').textContent = s.label;
    const enabled = s.enabled_count || 0;
    document.getElementById('tools-modal-subtitle').textContent =
        `${s.key} · ${s.tools.length} tool${s.tools.length === 1 ? '' : 's'}, ${enabled} enabled by a policy`;
    document.getElementById('tools-modal-body').innerHTML =
        s.tools.map(toolRow).join('')
        + (enabled === 0 ? `
            <p class="text-xs text-gray-400 pt-2 border-t border-gray-100 dark:border-neutral-800">
              None of these are enabled yet. Turn on the ones you want in a policy's
              Tools &amp; Guardrails step.
            </p>` : '');
    modal.classList.remove('hidden');
}

function closeToolsModal() {
    document.getElementById('tools-modal')?.classList.add('hidden');
}

function wireEvents(container) {
    if (container.dataset.toolsWired) return;
    container.dataset.toolsWired = '1';
    container.addEventListener('click', async (e) => {
        if (e.target.closest('[data-modal-close]')) return closeToolsModal();
        const view = e.target.closest('[data-mcp-tools]');
        if (view) return openToolsModal(view.dataset.mcpTools);
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
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeToolsModal();
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

    el.innerHTML = `
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        ${state.servers.map(card).join('')}
      </div>`;
}
