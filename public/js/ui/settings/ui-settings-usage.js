import * as api from '../../core/api.js';
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

function usageTable(title, note, headers, rows) {
    return `
        <div class="settings-card">
            <h4 class="text-lg font-semibold">${title}</h4>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5 mb-4">${note}</p>
            ${rows.length === 0
                ? '<p class="text-sm text-gray-400">No usage in this period.</p>'
                : `<div class="overflow-x-auto"><table class="w-full text-sm">
                    <thead><tr class="text-left text-xs uppercase text-gray-400 border-b border-gray-200 dark:border-neutral-800">
                        ${headers.map(h => `<th class="py-2 pr-4">${h}</th>`).join('')}
                    </tr></thead>
                    <tbody>${rows.map(cells => `
                        <tr class="border-b border-gray-100 dark:border-neutral-800/60">
                            ${cells.map(c => `<td class="py-2 pr-4">${c}</td>`).join('')}
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
                <div>
                    <p class="text-sm text-gray-500 dark:text-gray-400">Last ${usage.days} days</p>
                    <p class="text-2xl font-bold text-neutral-900 dark:text-white mt-1">
                        ${fmtUsd(totCost)}${unpriced ? ' <span class="text-sm font-normal text-gray-400">(+ unpriced models)</span>' : ''}
                    </p>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
                        ${fmtTokens(totIn)} tokens in, ${fmtTokens(totOut)} tokens out, across ${totCalls} model calls.
                    </p>
                </div>
                <div class="flex items-center gap-2">
                    <label for="usage-days" class="text-sm text-gray-500">Period</label>
                    <select id="usage-days" class="p-2 rounded border border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 text-sm">
                        <option value="7" ${usage.days === 7 ? 'selected' : ''}>7 days</option>
                        <option value="30" ${usage.days === 30 ? 'selected' : ''}>30 days</option>
                        <option value="90" ${usage.days === 90 ? 'selected' : ''}>90 days</option>
                    </select>
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
                r.calls,
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
                fmtUsd(estCost(r.tokens_in, r.tokens_out, priceFor(r.model, prices))),
            ])
        )}

        ${usageTable(
            'By faculty',
            'What governance itself costs: every governed turn pays for a Conscience audit on top of the Intellect draft.',
            ['Faculty route', 'Calls', 'Tokens in', 'Tokens out'],
            usage.by_route.map(r => [
                escapeHtml(routeLabels[r.route] || r.route),
                r.calls,
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
                r.calls,
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
                r.calls,
                fmtTokens(r.tokens_in),
                fmtTokens(r.tokens_out),
            ])
        )}
    `;

    const daySelect = document.getElementById('usage-days');
    if (daySelect) {
        daySelect.addEventListener('change', () => {
            renderSettingsUsageTab(parseInt(daySelect.value, 10));
        });
    }
}
