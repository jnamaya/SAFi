/**
 * js/ui/ui-data-sources.js
 * Renders the Tools section of the composer's + panel: the accounts a member
 * can connect so their agents' tools run as them. Two kinds can live here
 * under one set of rules: delegated OAuth connectors (a catalogue that has
 * been empty since the last one retired on 2026-08-15) and OAuth-protected
 * MCP tool servers, which is everything members connect today. The section
 * was called "Data Sources" until 2026-08-15; ids and function names keep
 * the old spelling so nothing cached or externally referenced breaks.
 */

import * as api from '../core/api.js';
import { updateDataSourcesLabel } from './ui-composer-menu.js';

const DROPDOWN_ID = 'data-sources-dropdown';

// The same brand marks the Tools Catalog uses, so the two surfaces agree on
// what a service looks like. Recognition is presentation only, matched on the
// row's key and label; anything unrecognized gets the generic tool icon.
const BRAND_ICONS = {
    google: `<svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.4c-.3 1.6-1.2 2.9-2.5 3.8v3h4c2.4-2.2 3.6-5.4 3.6-9z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-4-3c-1.1.7-2.5 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.3v3.1C3.3 21.4 7.3 24 12 24z"/><path fill="#FBBC05" d="M5.4 14.4c-.2-.7-.4-1.5-.4-2.4s.1-1.7.4-2.4V6.5H1.3C.5 8.2 0 10 0 12s.5 3.8 1.3 5.5l4.1-3.1z"/><path fill="#EA4335" d="M12 4.7c1.8 0 3.3.6 4.6 1.8L20.1 3C18 1.1 15.2 0 12 0 7.3 0 3.3 2.6 1.3 6.5l4.1 3.1C6.3 6.8 8.9 4.7 12 4.7z"/></svg>`,
    microsoft: `<svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24"><path fill="#f35325" d="M1 1h10v10H1z"/><path fill="#81bc06" d="M13 1h10v10H13z"/><path fill="#05a6f0" d="M1 13h10v10H1z"/><path fill="#ffba08" d="M13 13h10v10H13z"/></svg>`,
    github: `<svg class="w-5 h-5 shrink-0 text-neutral-900 dark:text-white" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>`
};

const GENERIC_ICON = `<svg class="w-5 h-5 shrink-0 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
    d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
</svg>`;

function iconFor(key, label) {
    const hay = `${key || ''} ${label || ''}`.toLowerCase();
    if (hay.includes('github')) return BRAND_ICONS.github;
    if (hay.includes('google') || hay.includes('workspace')) return BRAND_ICONS.google;
    if (hay.includes('microsoft') || hay.includes('graph') || hay.includes('365')) return BRAND_ICONS.microsoft;
    return GENERIC_ICON;
}

export function initDataSources() {
    checkDataSources();
}

/**
 * Fetches status and updates the menu items.
 */
export async function checkDataSources() {
    try {
        const response = await api.fetchAuthStatus();
        const connected = (response && response.connected) || [];
        renderMenu(connected, (response && response.connectors) || [],
                   (response && response.mcp_servers) || []);
        const mcpConnected = ((response && response.mcp_servers) || [])
            .filter(s => s.connected).length;
        updateDataSourcesLabel(connected.length + mcpConnected);
    } catch (e) {
        console.warn('Failed to fetch data source status', e);
        // Offer nothing rather than the whole catalogue: this menu used to
        // render a hardcoded list regardless of the response, so a failed
        // status call still advertised every connector.
        renderMenu([], []);
    }
}

function renderMenu(connectedList, connectors, mcpServers) {
    const dropdown = document.getElementById(DROPDOWN_ID);
    if (!dropdown) return;

    dropdown.innerHTML = '';

    // Driven by /auth/status, not by a hardcoded catalogue. The endpoint
    // already returns each connector with `allowed` (org policy permits
    // linking it) and `usable` (some agent this member can reach is authorized
    // to call its tools). The old list ignored both and offered all three, so
    // an org that allows only GitHub still advertised OneDrive/SharePoint —
    // and clicking it failed, because the login route enforces the allow-list
    // even when the menu does not.
    //
    // Both flags gate visibility, not just `allowed`. A source is offered only
    // when the org permits it AND some agent this member can reach is
    // authorized to call its tools — connecting is the means to an agent's
    // end, so a source no agent needs is not an option, it is an invitation
    // to grant a token nothing will ever read. (The first version of this
    // filter checked `allowed` alone, so an unrestricted org still advertised
    // every connector — and worse, left the login link live on them.)
    //
    // A connector the member has ALREADY linked stays on the list even when it
    // is no longer allowed or usable: an admin can revoke after the fact, and
    // the member still needs to see a live token in order to disconnect it.
    // Hiding a granted token is worse than showing a blocked one.
    const visible = (connectors || []).filter(
        c => (c.allowed !== false && c.usable !== false) || connectedList.includes(c.key)
    );
    const visibleMcp = (mcpServers || []).filter(
        s => (s.allowed !== false && s.usable !== false) || s.connected
    );

    // The empty state considers BOTH lists. The first version checked only the
    // delegated connectors and returned early, so a member whose agents used
    // exclusively MCP tool servers was told nothing needed setting up while a
    // connected GitHub sat unrendered below the return.
    if (!visible.length && !visibleMcp.length) {
        dropdown.innerHTML = `
            <p class="px-3 py-2 text-xs text-neutral-500">
                None of your agents use connected tools, so there is
                nothing to set up here.
            </p>`;
        return;
    }

    visible.forEach(source => {
        const isConnected = connectedList.includes(source.key);
        const blocked = source.allowed === false;
        const unused = source.usable === false && !blocked;
        // Only a source that clears BOTH flags and is not yet linked carries a
        // live login link. Unusable rows only exist here when already
        // connected (the filter above), and their job is disconnect
        // visibility, not inviting a grant.
        const connectable = !isConnected && !blocked && !unused;

        const item = document.createElement('a');
        item.href = connectable ? `/api/auth/${source.key}/login` : '#';
        item.className = `
            flex items-center gap-3 px-3 py-2 rounded-lg transition-colors group
            ${connectable
                ? 'hover:bg-green-50 dark:hover:bg-green-900/20'
                : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 cursor-default'
            }
        `;

        let status, statusClass;
        if (isConnected && blocked) {
            status = '\u25cf Connected \u2014 no longer permitted';
            statusClass = 'text-amber-600 dark:text-amber-400';
        } else if (isConnected && unused) {
            // A live token for a source no agent reads \u2014 visible only for
            // the disconnect, and named so the member knows removing it costs
            // nothing.
            status = '\u25cf Connected \u2014 no agent here uses it';
            statusClass = 'text-neutral-400';
        } else if (isConnected) {
            status = '\u25cf Connected';
            statusClass = 'text-green-600 dark:text-green-400';
        } else {
            // The visibility filter admits no unconnected source that is
            // blocked or unusable, so the only remaining state is connectable.
            status = 'Click to connect';
            statusClass = 'text-neutral-500 group-hover:text-green-600 dark:group-hover:text-green-400';
        }

        item.innerHTML = `
            ${iconFor(source.key, source.label)}
            <div class="flex flex-col">
                <span class="text-sm font-medium text-neutral-900 dark:text-neutral-100">${source.label || source.key}</span>
                <span class="text-xs ${statusClass}">${status}</span>
            </div>
        `;

        if (!connectable) {
            item.addEventListener('click', (e) => e.preventDefault());
        }

        dropdown.appendChild(item);
    });

    // OAuth-protected tool servers, same rules as the connectors above: offered
    // only when the org admits it AND some agent this member can reach is
    // granted its tools (the backend computes both; the login route enforces
    // them again). A connected server stays visible regardless, because a
    // member must always be able to see and revoke a live grant.
    if (visibleMcp.length) {
        if (visible.length) {
            const divider = document.createElement('div');
            divider.className = 'my-1 border-t border-neutral-200 dark:border-neutral-800';
            dropdown.appendChild(divider);
        }

        visibleMcp.forEach(server => {
            const connectable = !server.connected && server.allowed !== false
                                && server.usable !== false;
            const item = document.createElement('a');
            item.href = connectable ? server.login : '#';
            item.className = `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors group ${connectable
                ? 'hover:bg-green-50 dark:hover:bg-green-900/20'
                : 'hover:bg-neutral-100 dark:hover:bg-neutral-800 cursor-default'}`;

            let status, statusClass;
            if (server.connected) {
                status = '● Connected · click to disconnect';
                statusClass = 'text-green-600 dark:text-green-400';
            } else {
                status = 'Click to sign in';
                statusClass = 'text-neutral-500 group-hover:text-green-600 dark:group-hover:text-green-400';
            }

            item.innerHTML = `
                ${iconFor(server.key, server.label)}
                <div class="flex flex-col">
                    <span class="text-sm font-medium text-neutral-900 dark:text-neutral-100">${server.label || server.key}</span>
                    <span class="text-xs ${statusClass}">${status}</span>
                </div>`;

            if (server.connected) {
                item.addEventListener('click', async (e) => {
                    e.preventDefault();
                    if (!confirm(`Disconnect ${server.label || server.key}? Your agents lose access to it until you sign in again.`)) return;
                    try {
                        await api.disconnectMcpAuth(server.key);
                        checkDataSources();
                    } catch (err) { /* leave the row; a failed revoke must stay visible */ }
                });
            } else if (!connectable) {
                item.addEventListener('click', (e) => e.preventDefault());
            }
            dropdown.appendChild(item);
        });
    }
}

