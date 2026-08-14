/**
 * Tool Servers: browse the MCP registry and install a server (backlog 48).
 *
 * The copy in here does real work, so it is worth stating why it is worded the
 * way it is. Two things a person must not misread:
 *
 *   1. A registry listing verifies who published a server, not that its code is
 *      safe. Presenting the catalogue without saying so turns provenance into
 *      an implied endorsement.
 *   2. Installing grants nothing. The server still has to be allowed, granted
 *      by a policy, enabled on an agent, and every call still passes the Will.
 *      That is what makes a one-click install safe, so the screen says it.
 */
import * as api from '../../core/api.js';
import * as ui from '../ui.js';

let state = { servers: [], results: [], mode: 'remote', soleReviewer: false, searching: false, error: '' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

const STATUS_BADGE = {
    pending: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    active: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
    rejected: 'bg-gray-100 text-gray-600 dark:bg-neutral-800 dark:text-gray-400',
    disabled: 'bg-gray-100 text-gray-600 dark:bg-neutral-800 dark:text-gray-400',
};

export async function renderSettingsToolsTab() {
    const container = document.getElementById('tab-tools');
    if (!container) return;
    container.innerHTML = shell();
    await refresh();
    wire();
}

function shell() {
    return `
    <div class="max-w-5xl mx-auto p-6 space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Tool Servers</h1>
        <p class="text-sm text-gray-500 mt-1 max-w-3xl">
          Add tools your agents can use, from the official MCP registry. A server you install
          here becomes available to grant, it is not granted to anything yet: an agent can only
          use it once a policy allows it and you enable it on that agent.
        </p>
      </div>

      <div class="rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/20 p-4">
        <p class="text-sm text-amber-900 dark:text-amber-200">
          <strong>What a registry listing means.</strong> The registry checks that the publisher
          really owns the name they published under. It does not review the code, scan it, or
          vouch for it. Install servers from publishers you would trust with the data your
          agents will send them.
        </p>
      </div>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Installed</h2>
        <div id="tools-installed" class="space-y-3"></div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Find a server</h2>
        <div class="flex gap-2">
          <input id="tools-search" type="search" placeholder="Search the MCP registry"
            class="flex-1 px-4 py-2.5 rounded-lg border border-gray-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-green-500">
          <button id="tools-search-btn"
            class="px-4 py-2.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium">Search</button>
        </div>
        <div id="tools-results" class="space-y-3"></div>
      </section>
    </div>`;
}

async function refresh() {
    try {
        const data = await api.listMcpServers();
        state.servers = data.servers || [];
        state.mode = data.install_mode || 'remote';
        state.soleReviewer = !!data.sole_reviewer;
    } catch (e) {
        state.servers = [];
    }
    paintInstalled();
}

function paintInstalled() {
    const el = document.getElementById('tools-installed');
    if (!el) return;
    if (!state.servers.length) {
        el.innerHTML = `<p class="text-sm text-gray-500 py-4">No tool servers installed yet.</p>`;
        return;
    }
    el.innerHTML = state.servers.map(s => {
        const badge = STATUS_BADGE[s.status] || STATUS_BADGE.disabled;
        // A pending server the current admin installed cannot be approved by
        // them unless they are the org's only reviewer. Saying which of those
        // two situations they are in is the difference between a useful screen
        // and a disabled button with no explanation.
        const needsOther = s.status === 'pending' && s.self_installed && !state.soleReviewer;
        const canReview = s.status === 'pending' && (!s.self_installed || state.soleReviewer);
        return `
        <div class="rounded-xl border border-gray-200 dark:border-neutral-800 p-4 bg-white dark:bg-neutral-900">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-gray-900 dark:text-white">${esc(s.title || s.connector_key)}</span>
                <span class="text-xs px-2 py-0.5 rounded-full ${badge}">${esc(s.status)}</span>
                ${s.connected ? '<span class="text-xs text-green-600 dark:text-green-400">connected</span>' : ''}
                ${s.connection_error ? `<span class="text-xs text-red-600 dark:text-red-400">${esc(s.connection_error)}</span>` : ''}
              </div>
              <p class="text-xs text-gray-500 mt-1 font-mono">${esc(s.registry_name)} ${esc(s.registry_version || '')}</p>
              <p class="text-xs text-gray-500 mt-1 break-all">${esc(s.url)}</p>
              ${s.tools && s.tools.length ? `<p class="text-xs text-gray-500 mt-2">Tools: ${s.tools.map(esc).join(', ')}</p>` : ''}
              ${s.status === 'active' ? `<p class="text-xs text-gray-500 mt-2">Grant it to an agent as the <span class="font-mono">${esc(s.connector_key)}</span> tool.</p>` : ''}
              ${needsOther ? '<p class="text-xs text-amber-700 dark:text-amber-400 mt-2">Waiting for another admin to review. You installed it, so you cannot approve it yourself.</p>' : ''}
              ${s.status === 'active' && !s.independent_review ? '<p class="text-xs text-gray-500 mt-2">Approved by its installer as the only eligible reviewer, recorded as a non-independent review.</p>' : ''}
            </div>
            <div class="flex flex-col gap-2 shrink-0">
              ${canReview ? `
                <button data-review="approve" data-id="${esc(s.id)}"
                  class="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium">Approve</button>
                <button data-review="reject" data-id="${esc(s.id)}"
                  class="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-neutral-700 text-xs">Reject</button>` : ''}
              <button data-remove="${esc(s.id)}"
                class="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-neutral-700 text-xs text-red-600">Remove</button>
            </div>
          </div>
        </div>`;
    }).join('');
}

function paintResults() {
    const el = document.getElementById('tools-results');
    if (!el) return;
    if (state.searching) {
        el.innerHTML = `<p class="text-sm text-gray-500 py-4">Searching…</p>`;
        return;
    }
    if (state.error) {
        el.innerHTML = `<p class="text-sm text-red-600 dark:text-red-400 py-4">${esc(state.error)}</p>`;
        return;
    }
    if (!state.results.length) {
        el.innerHTML = `<p class="text-sm text-gray-500 py-4">No servers matched that search.</p>`;
        return;
    }
    el.innerHTML = state.results.map(r => `
      <div class="rounded-xl border border-gray-200 dark:border-neutral-800 p-4 bg-white dark:bg-neutral-900">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-semibold text-gray-900 dark:text-white">${esc(r.title)}</span>
              <span class="text-xs text-gray-500">${esc(r.version)}</span>
            </div>
            <p class="text-xs text-gray-500 mt-1 font-mono">${esc(r.name)}</p>
            <p class="text-sm text-gray-600 dark:text-gray-400 mt-2">${esc(r.description)}</p>
            ${r.installable ? '' : `<p class="text-xs text-amber-700 dark:text-amber-400 mt-2">${esc(r.not_installable_reason)}</p>`}
          </div>
          <div class="shrink-0">
            ${r.installable
              ? `<button data-install="${esc(r.name)}"
                   class="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium">Install</button>`
              : `<span class="text-xs text-gray-400">Not installable here</span>`}
          </div>
        </div>
      </div>`).join('');
}

function wire() {
    const box = document.getElementById('tab-tools');
    if (!box || box.dataset.wired) return;
    box.dataset.wired = '1';

    box.addEventListener('click', async (e) => {
        const search = e.target.closest('#tools-search-btn');
        const install = e.target.closest('[data-install]');
        const review = e.target.closest('[data-review]');
        const remove = e.target.closest('[data-remove]');

        if (search) return doSearch();

        if (install) {
            install.disabled = true;
            try {
                await api.installMcpServer(install.dataset.install);
                ui.showToast('Installed. It needs an admin review before agents can use it.', 'success');
                await refresh();
            } catch (err) {
                ui.showToast(err.message || 'Install failed.', 'error');
            } finally {
                install.disabled = false;
            }
            return;
        }

        if (review) {
            try {
                const res = await api.reviewMcpServer(review.dataset.id, review.dataset.review);
                (res.warnings || []).forEach(w => ui.showToast(w, 'error'));
                if (!res.warnings || !res.warnings.length) {
                    ui.showToast(`Server ${review.dataset.review}d.`, 'success');
                }
                await refresh();
            } catch (err) {
                ui.showToast(err.message || 'Review failed.', 'error');
            }
            return;
        }

        if (remove) {
            if (!confirm('Remove this tool server? Agents granted it will lose those tools.')) return;
            try {
                await api.removeMcpServer(remove.dataset.remove);
                await refresh();
            } catch (err) {
                ui.showToast(err.message || 'Remove failed.', 'error');
            }
        }
    });

    box.addEventListener('keydown', (e) => {
        if (e.target.id === 'tools-search' && e.key === 'Enter') doSearch();
    });
}

async function doSearch() {
    const input = document.getElementById('tools-search');
    state.searching = true;
    state.error = '';
    paintResults();
    try {
        const data = await api.searchMcpRegistry(input?.value || '');
        // A failed call must not render as "no matches". httpGet resolves with
        // the body on a non-2xx rather than throwing, so an unreachable
        // registry or a schema change upstream would otherwise look exactly
        // like a search that found nothing, which is how the nested-payload
        // parsing bug stayed invisible.
        if (data && data.ok === false) throw new Error(data.error || 'The registry could not be reached.');
        state.results = (data && data.servers) || [];
    } catch (err) {
        state.results = [];
        state.error = err.message || 'The registry could not be reached.';
        ui.showToast(state.error, 'error');
    } finally {
        state.searching = false;
        paintResults();
    }
}
