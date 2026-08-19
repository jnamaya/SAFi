import * as api from '../../core/api.js';
import * as ui from '../ui.js';
import { escapeHtml } from '../../core/utils.js';

/**
 * Usage & Cost tab (backlog 61). Admin-only.
 *
 * Shows the org's LLM token consumption aggregated by day, agent, faculty
 * route, and model. Raw token counts come from the llm_usage table; dollar
 * figures are computed HERE from the price map the API serves, so they are
 * estimates that track current prices rather than stored history.
 */

// Longest-substring match against the price map. Returns [in, out] USD per
// 1M tokens, or null when no price is configured for the model.
function priceFor(model, prices) {
    let best = null;
    let bestLen = -1;
    const m = (model || '').toLowerCase();
    for (const key of Object.keys(prices || {})) {
        if (m.includes(key.toLowerCase()) && key.length > bestLen) {
            best = prices[key];
            bestLen = key.length;
        }
    }
    return best;
}

function estCost(tokensIn, tokensOut, price) {
    if (!price) return null;
    return (tokensIn / 1e6) * price[0] + (tokensOut / 1e6) * price[1];
}

function fmtTokens(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
    return String(n);
}

function fmtUsd(v) {
    if (v === null) return '<span class="text-gray-400" title="No price configured for this model">n/a</span>';
    if (v > 0 && v < 0.01) return '&lt;$0.01';
    return '$' + v.toFixed(2);
}

// Columns from `numericFrom` onward are treated as numbers: right-aligned and
// tabular so digits line up down the column and are easy to compare. Column 0
// is always the row label. Anything between (e.g. a Provider name) stays a
// plain left-aligned text column.
function usageTable(title, note, headers, rows, numericFrom = 1) {
    const isNum = (i) => i >= numericFrom;
    return `
        <div class="settings-card">
            <h4 class="text-lg font-semibold">${title}</h4>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 mb-4">${note}</p>
            ${rows.length === 0
                ? '<p class="text-sm text-gray-400">No usage in this period.</p>'
                : `<div class="overflow-x-auto -mx-2"><table class="w-full text-sm">
                    <thead><tr class="text-xs uppercase tracking-wide text-gray-400 border-b border-gray-200 dark:border-neutral-800">
                        ${headers.map((h, i) => `<th class="py-2 px-3 font-medium ${isNum(i) ? 'text-right' : 'text-left'}">${h}</th>`).join('')}
                    </tr></thead>
                    <tbody>${rows.map(cells => `
                        <tr class="border-b border-gray-100 dark:border-neutral-800/60 hover:bg-gray-50 dark:hover:bg-neutral-800/40 transition-colors">
                            ${cells.map((c, i) => `<td class="py-2.5 px-3 ${i === 0
                                ? 'font-medium text-gray-900 dark:text-white'
                                : isNum(i)
                                    ? 'text-right tabular-nums text-gray-600 dark:text-gray-300'
                                    : 'text-gray-600 dark:text-gray-300'}">${c}</td>`).join('')}
                        </tr>`).join('')}
                    </tbody></table></div>`
            }
        </div>`;
}

export async function renderSettingsUsageTab(days = 30) {
    const container = document.getElementById('tab-usage');
    if (!container) return;

    container.innerHTML = `
        <div class="flex items-center justify-center h-32">
            <div class="thinking-spinner"></div>
        </div>
    `;

    let org, res;
    try {
        const orgRes = await api.getMyOrganization();
        org = orgRes ? orgRes.organization : null;
        if (!org) {
            container.innerHTML = `
                <div class="text-center p-8">
                    <h3 class="text-xl font-semibold mb-2">No Organization Found</h3>
                    <p class="text-neutral-500">Usage is tracked per organization.</p>
                </div>`;
            return;
        }
        res = await api.getOrgUsage(org.id, days);
    } catch (e) {
        container.innerHTML = `<div class="text-center p-8 text-red-500">Failed to load usage: ${escapeHtml(e.message)}</div>`;
        return;
    }

    const usage = (res && res.usage) || { by_day: [], by_model: [], by_route: [], by_agent: [] };
    const prices = (res && res.prices) || {};

    // Totals and the estimated spend come from the by-model split, the only
    // grouping where a price can be matched.
    let totIn = 0, totOut = 0, totCalls = 0, totCost = 0, unpriced = false;
    for (const r of usage.by_model) {
        totIn += r.tokens_in; totOut += r.tokens_out; totCalls += r.calls;
        const c = estCost(r.tokens_in, r.tokens_out, priceFor(r.model, prices));
        if (c === null) unpriced = true; else totCost += c;
    }

    const routeLabels = {
        intellect: 'Intellect (drafting)',
        conscience: 'Conscience (audit)',
        will: 'Will',
    };

    container.innerHTML = `
        <div class="settings-page-header">
            <h1>Usage &amp; Cost</h1>
            <p>LLM token consumption for ${escapeHtml(org.name)}, aggregated per call at the provider layer. Dollar figures are estimates from current list prices, not invoices.</p>
        </div>

        <div class="settings-card">
            <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="text-sm font-medium text-gray-500 dark:text-gray-400">Last ${usage.days} days</p>
                <div class="flex items-center gap-2">
                    <label for="usage-days" class="text-sm text-gray-500">Period</label>
                    <select id="usage-days" class="p-2 rounded-lg border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm">
                        <option value="7" ${usage.days === 7 ? 'selected' : ''}>7 days</option>
                        <option value="30" ${usage.days === 30 ? 'selected' : ''}>30 days</option>
                        <option value="90" ${usage.days === 90 ? 'selected' : ''}>90 days</option>
                    </select>
                </div>
            </div>
            <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
                <div class="rounded-xl border border-gray-100 dark:border-neutral-800 p-4">
                    <p class="text-xs uppercase tracking-wide text-gray-400">Estimated cost</p>
                    <p class="text-2xl font-bold text-green-600 dark:text-green-500 mt-1 tabular-nums">${fmtUsd(totCost)}</p>
                    ${unpriced ? '<p class="text-xs text-gray-400 mt-0.5">+ unpriced models</p>' : ''}
                </div>
                <div class="rounded-xl border border-gray-100 dark:border-neutral-800 p-4">
                    <p class="text-xs uppercase tracking-wide text-gray-400">Model calls</p>
                    <p class="text-2xl font-bold text-neutral-900 dark:text-white mt-1 tabular-nums">${totCalls.toLocaleString()}</p>
                </div>
                <div class="rounded-xl border border-gray-100 dark:border-neutral-800 p-4">
                    <p class="text-xs uppercase tracking-wide text-gray-400">Tokens in</p>
                    <p class="text-2xl font-bold text-neutral-900 dark:text-white mt-1 tabular-nums">${fmtTokens(totIn)}</p>
                </div>
                <div class="rounded-xl border border-gray-100 dark:border-neutral-800 p-4">
                    <p class="text-xs uppercase tracking-wide text-gray-400">Tokens out</p>
                    <p class="text-2xl font-bold text-neutral-900 dark:text-white mt-1 tabular-nums">${fmtTokens(totOut)}</p>
                </div>
            </div>
        </div>

        ${usageTable(
            'By model',
            'Where the money goes. Estimated from current list prices per million tokens; override with the SAFI_LLM_PRICES environment variable.',
            ['Model', 'Provider', 'Calls', 'Tokens in', 'Tokens out', 'Est. cost'],
            usage.by_model.map(r => [
                `<code class="text-xs">${escapeHtml(r.model)}</code>`,
                escapeHtml(r.provider),
                r.calls.toLocaleString(),
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
                fmtUsd(estCost(r.tokens_in, r.tokens_out, priceFor(r.model, prices))),
            ]),
            2,
        )}

        ${usageTable(
            'By faculty',
            'What governance itself costs: every governed turn pays for a Conscience audit on top of the Intellect draft.',
            ['Faculty route', 'Calls', 'Tokens in', 'Tokens out'],
            usage.by_route.map(r => [
                escapeHtml(routeLabels[r.route] || r.route),
                r.calls.toLocaleString(),
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
            ])
        )}

        ${usageTable(
            'By agent',
            'Which agents drive the consumption. "(none)" is activity outside an agent turn, such as policy wizard generation.',
            ['Agent', 'Calls', 'Tokens in', 'Tokens out'],
            usage.by_agent.map(r => [
                escapeHtml(r.agent),
                r.calls.toLocaleString(),
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
            ])
        )}

        ${usageTable(
            'By day',
            'Daily totals across all agents and models.',
            ['Day', 'Calls', 'Tokens in', 'Tokens out'],
            usage.by_day.map(r => [
                escapeHtml(r.day),
                r.calls.toLocaleString(),
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
            ])
        )}

        <div id="usage-deployment-section"></div>
        <div id="usage-model-catalog-section"></div>
        <div id="usage-provider-keys-section"></div>
    `;

    const daySelect = document.getElementById('usage-days');
    if (daySelect) {
        daySelect.addEventListener('change', () => {
            renderSettingsUsageTab(parseInt(daySelect.value, 10));
        });
    }

    renderDeploymentSection(days, prices);
    renderModelCatalogSection();
    renderProviderKeysSection(org.id);
}

// Provider API Keys (backlog 64): the org's own keys, layered over the
// deployment .env defaults. Write-only by design — the server stores the
// key encrypted and only ever returns the last 4 characters.
async function renderProviderKeysSection(orgId) {
    const host = document.getElementById('usage-provider-keys-section');
    if (!host) return;
    let res;
    try {
        res = await api.getOrgProviderKeys(orgId);
    } catch (e) {
        return;
    }
    if (!res || !res.ok) return;

    const own = new Map(res.keys.map(k => [k.provider, k]));

    host.innerHTML = `
        <div class="settings-card">
            <h4 class="text-lg font-semibold">Provider API Keys</h4>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 mb-4">
                Bring your organization's own provider keys. A stored key replaces the deployment default
                for this org's calls only (including background work), so your usage bills to your account.
                Keys are stored encrypted, are never displayed after saving, and changes apply within a minute.
            </p>
            <div class="overflow-x-auto"><table class="w-full text-sm">
                <thead><tr class="text-left text-xs uppercase text-gray-400 border-b border-gray-200 dark:border-neutral-800">
                    <th class="py-2 pr-4">Provider</th><th class="py-2 pr-4">Status</th><th class="py-2 pr-4">Key</th><th class="py-2"></th>
                </tr></thead>
                <tbody>${res.providers.map(p => {
                    const mine = own.get(p.id);
                    const status = mine
                        ? `<span class="text-green-600 dark:text-green-400 font-medium">Your org's key, ends in …${escapeHtml(mine.last4)}</span>`
                        : (p.deployment_configured
                            ? '<span class="text-gray-500">Using deployment default</span>'
                            : '<span class="text-gray-400">Not configured</span>');
                    return `
                    <tr class="border-b border-gray-100 dark:border-neutral-800/60 hover:bg-gray-50 dark:hover:bg-neutral-800/40 transition-colors">
                        <td class="py-2 pr-4 font-medium">${escapeHtml(p.label)}</td>
                        <td class="py-2 pr-4">${status}</td>
                        <td class="py-2 pr-4">
                            <input type="password" autocomplete="off" data-provider="${escapeHtml(p.id)}"
                                class="provider-key-input w-full min-w-[160px] p-1.5 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-xs"
                                placeholder="${mine ? 'Paste to replace' : 'Paste key to set'}">
                        </td>
                        <td class="py-2 text-right whitespace-nowrap">
                            <button class="provider-key-set text-xs font-semibold text-green-600 hover:text-green-700 hover:underline mr-3" data-provider="${escapeHtml(p.id)}">${mine ? 'Replace' : 'Set'}</button>
                            ${mine ? `<button class="provider-key-del text-xs text-red-500 hover:text-red-600 hover:underline" data-provider="${escapeHtml(p.id)}">Remove</button>` : ''}
                        </td>
                    </tr>`;
                }).join('')}
                </tbody></table></div>
        </div>
    `;

    host.querySelectorAll('.provider-key-set').forEach(btn => {
        btn.addEventListener('click', async () => {
            const provider = btn.dataset.provider;
            const input = host.querySelector(`.provider-key-input[data-provider="${provider}"]`);
            const key = (input?.value || '').trim();
            if (!key) return ui.showToast('Paste the key first.', 'error');
            try {
                const r = await api.setOrgProviderKey(orgId, provider, key);
                if (r && r.ok) {
                    ui.showToast(`Key stored for ${provider}. Applies within a minute.`, 'success');
                    renderProviderKeysSection(orgId);
                } else {
                    throw new Error((r && r.error) || 'Save failed');
                }
            } catch (e) {
                ui.showToast(e.message, 'error');
            }
        });
    });

    host.querySelectorAll('.provider-key-del').forEach(btn => {
        btn.addEventListener('click', async () => {
            const provider = btn.dataset.provider;
            if (!confirm(`Remove your org's ${provider} key? Calls fall back to the deployment default.`)) return;
            try {
                const r = await api.deleteOrgProviderKey(orgId, provider);
                if (r && r.ok) {
                    ui.showToast('Key removed.', 'success');
                    renderProviderKeysSection(orgId);
                } else {
                    throw new Error((r && r.error) || 'Remove failed');
                }
            } catch (e) {
                ui.showToast(e.message, 'error');
            }
        });
    });
}

// Operator-only (backlog 65): usage across every org on this deployment,
// so the operator can separate their org's spend from everyone riding the
// shared .env keys. Anyone not named in SAFI_SUPER_ADMINS gets a 403
// from the endpoint and never sees the section.
async function renderDeploymentSection(days, prices) {
    const host = document.getElementById('usage-deployment-section');
    if (!host) return;
    let res;
    try {
        res = await api.getDeploymentUsage(days);
    } catch (e) {
        return; // not an operator, or endpoint unavailable — skip silently
    }
    if (!res || !res.ok) return;

    // Roll the per-org-per-model rows up to one line per org, pricing each
    // model row before it loses its identity.
    const orgs = new Map();
    for (const r of res.usage.by_org_model) {
        const key = r.org_id || null;
        if (!orgs.has(key)) {
            orgs.set(key, {
                name: r.org_id ? (r.org_name || r.org_id) : 'Public / ungoverned',
                calls: 0, tokens_in: 0, tokens_out: 0, cost: 0, unpriced: false,
            });
        }
        const o = orgs.get(key);
        o.calls += r.calls; o.tokens_in += r.tokens_in; o.tokens_out += r.tokens_out;
        const c = estCost(r.tokens_in, r.tokens_out, priceFor(r.model, prices));
        if (c === null) o.unpriced = true; else o.cost += c;
    }
    const rows = [...orgs.values()].sort((a, b) => b.tokens_out - a.tokens_out);

    host.innerHTML = usageTable(
        'Whole deployment (operator view)',
        'Every organization on this install, plus public traffic: who spends the shared provider keys. Visible only to the super admins named in SAFI_SUPER_ADMINS.',
        ['Organization', 'Calls', 'Tokens in', 'Tokens out', 'Est. cost'],
        rows.map(o => [
            escapeHtml(o.name),
            o.calls.toLocaleString(),
            fmtTokens(o.tokens_in),
            fmtTokens(o.tokens_out),
            fmtUsd(o.unpriced ? null : o.cost),
        ])
    );
}

// Model Catalog (backlog 63): operator-added models offered in the composer
// alongside the built-ins, each with an explicit provider so dispatch never
// guesses. Admin-only endpoints; the whole tab is already admin-gated.
async function renderModelCatalogSection() {
    const host = document.getElementById('usage-model-catalog-section');
    if (!host) return;
    let res;
    try {
        res = await api.getCustomModels();
    } catch (e) {
        return;
    }
    if (!res || !res.ok) return;

    const providerOptions = res.providers.map(p =>
        `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join('');

    host.innerHTML = `
        <div class="settings-card">
            <h4 class="text-lg font-semibold">Model Catalog</h4>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 mb-4">
                Add models to the composer picker without a code change. Use the provider's exact model id.
                Only providers with a configured API key are offered; each org's provider allow-list still applies.
            </p>
            ${res.models.length === 0
                ? '<p class="text-sm text-gray-400 mb-4">No custom models yet. The built-in catalog is unaffected.</p>'
                : `<div class="overflow-x-auto mb-4"><table class="w-full text-sm">
                    <thead><tr class="text-left text-xs uppercase text-gray-400 border-b border-gray-200 dark:border-neutral-800">
                        <th class="py-2 pr-4">Model id</th><th class="py-2 pr-4">Label</th><th class="py-2 pr-4">Provider</th><th class="py-2"></th>
                    </tr></thead>
                    <tbody>${res.models.map(m => `
                        <tr class="border-b border-gray-100 dark:border-neutral-800/60 hover:bg-gray-50 dark:hover:bg-neutral-800/40 transition-colors">
                            <td class="py-2 pr-4"><code class="text-xs">${escapeHtml(m.id)}</code></td>
                            <td class="py-2 pr-4">${escapeHtml(m.label)}</td>
                            <td class="py-2 pr-4">${escapeHtml(m.provider)}</td>
                            <td class="py-2 text-right">
                                <button class="catalog-del-btn text-xs text-red-500 hover:text-red-600 hover:underline" data-id="${escapeHtml(m.id)}">Remove</button>
                            </td>
                        </tr>`).join('')}
                    </tbody></table></div>`
            }
            <div class="flex flex-wrap gap-2 items-end">
                <div class="flex-1 min-w-[180px]">
                    <label class="text-xs text-gray-500 block mb-1">Model id (exact)</label>
                    <input type="text" id="catalog-model-id" placeholder="e.g. claude-sonnet-5" class="w-full p-2 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm">
                </div>
                <div class="flex-1 min-w-[140px]">
                    <label class="text-xs text-gray-500 block mb-1">Display label</label>
                    <input type="text" id="catalog-model-label" placeholder="e.g. Claude Sonnet 5" class="w-full p-2 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm">
                </div>
                <div class="min-w-[140px]">
                    <label class="text-xs text-gray-500 block mb-1">Provider</label>
                    <select id="catalog-model-provider" class="w-full p-2 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm">${providerOptions}</select>
                </div>
                <button id="catalog-add-btn" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition-colors">Add Model</button>
            </div>
        </div>
    `;

    document.getElementById('catalog-add-btn')?.addEventListener('click', async () => {
        const id = document.getElementById('catalog-model-id').value.trim();
        const label = document.getElementById('catalog-model-label').value.trim();
        const provider = document.getElementById('catalog-model-provider').value;
        if (!id) return ui.showToast('Model id is required.', 'error');
        try {
            const r = await api.addCustomModel({ id, label, provider });
            if (r && r.ok) {
                ui.showToast('Model added. It appears in the composer within a minute.', 'success');
                renderModelCatalogSection();
            } else {
                throw new Error((r && r.error) || 'Add failed');
            }
        } catch (e) {
            ui.showToast(e.message, 'error');
        }
    });

    host.querySelectorAll('.catalog-del-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm(`Remove ${btn.dataset.id} from the catalog? Users currently set to it fall back to the default model.`)) return;
            try {
                const r = await api.deleteCustomModel(btn.dataset.id);
                if (r && r.ok) {
                    ui.showToast('Model removed.', 'success');
                    renderModelCatalogSection();
                } else {
                    throw new Error((r && r.error) || 'Remove failed');
                }
            } catch (e) {
                ui.showToast(e.message, 'error');
            }
        });
    });
}
