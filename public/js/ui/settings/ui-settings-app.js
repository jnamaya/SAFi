import * as ui from '../ui.js';
import * as api from '../../core/api.js';

/**
 * Renders the App Settings tab.
 *
 * Card order is fixed by the template — Appearance, Connected Accounts,
 * Security, Account — and the two async sections fill a placeholder that is
 * already in the right place. The previous version located its insertion point
 * by searching for an <h4> whose textContent was "Account", which had two
 * consequences: Connected Accounts ended up *inside* the Account card (that h4's
 * parent is the .settings-card itself, not a wrapper), and the final order
 * depended on which fetch resolved first.
 *
 * Sign-out lives in the sidebar (Log Out) — not duplicated here.
 *
 * @param {string} currentTheme - 'light' | 'dark' | 'system'
 * @param {Function} onThemeChange - Callback for theme selection
 * @param {Function} onDelete - Callback for the delete-account button
 */
export function renderSettingsAppTab(currentTheme, onThemeChange, onDelete) {
    ui._ensureElements();
    const container = ui.elements.cpTabAppSettings;
    if (!container) return;

    container.innerHTML = `
        <div class="settings-page-header">
            <h1>App Settings</h1>
            <p>Appearance, security, connected data sources, and your account.</p>
        </div>

        <div class="settings-card">
            <h4 class="text-lg font-semibold mb-1">Appearance</h4>
            <p class="text-xs text-gray-500 mb-4">
                <strong>System</strong> follows whatever your device is set to, and changes with it.
            </p>
            ${_themeControl(currentTheme)}
        </div>

        <div class="settings-card" id="app-connected-card">
            <h4 class="text-lg font-semibold mb-1">Connected Accounts</h4>
            <p class="text-xs text-gray-500 mb-4">
                Link a data source so an agent can read from it on your behalf. Each
                tool call is still authorized against the agent's policy before it runs.
            </p>
            <div id="connected-list" class="space-y-3"></div>
        </div>

        <!-- Filled by _renderSecurityCard, and only shown for local accounts:
             SSO users manage MFA at their identity provider. -->
        <div class="settings-card hidden" id="app-security-card"></div>

        <div class="settings-card">
            <h4 class="text-lg font-semibold mb-1">Account</h4>
            <p class="text-xs text-gray-500 mb-4">
                Deleting your account removes your conversations and profile. It cannot be undone.
            </p>
            <button id="cp-delete-account-btn"
                class="px-4 py-2 text-sm font-medium rounded-lg text-red-600 dark:text-red-500 border border-red-300 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors">
                Delete Account…
            </button>
        </div>
    `;

    _wireThemeControl(container, onThemeChange);
    container.querySelector('#cp-delete-account-btn').addEventListener('click', onDelete);

    _renderConnectedAccounts(container);
    _renderSecurityCard(container);
}


/* ── Appearance ──────────────────────────────────────────────────────────── */

const THEMES = [
    { key: 'light',  name: 'Light',  icon: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>' },
    { key: 'dark',   name: 'Dark',   icon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>' },
    { key: 'system', name: 'System', icon: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>' },
];

// Written out in full rather than composed, so Tailwind's scanner sees both
// variants as complete literals — a class name built by concatenation is not
// emitted into main.css.
const SEG_BASE = 'relative flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium cursor-pointer select-none transition-colors';
const SEG_ON = 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-white shadow-sm';
const SEG_OFF = 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-800 dark:hover:text-neutral-200';

function _themeControl(currentTheme) {
    return `
        <div role="radiogroup" aria-label="Theme"
             class="grid grid-cols-3 gap-1 p-1 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-800 focus-within:ring-2 focus-within:ring-green-500">
            ${THEMES.map(t => `
                <label data-theme-seg class="${SEG_BASE} ${t.key === currentTheme ? SEG_ON : SEG_OFF}">
                    <input type="radio" name="theme-select" value="${t.key}" class="sr-only"
                        ${t.key === currentTheme ? 'checked' : ''}>
                    <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${t.icon}</svg>
                    <span>${t.name}</span>
                </label>
            `).join('')}
        </div>`;
}

function _wireThemeControl(container, onThemeChange) {
    const segments = container.querySelectorAll('[data-theme-seg]');
    // Real radio inputs rather than buttons with role="radio": arrow-key
    // navigation within the group then comes from the browser for free.
    container.querySelectorAll('input[name="theme-select"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            onThemeChange(e.target.value);
            segments.forEach(seg => {
                const on = seg.contains(e.target);
                seg.className = `${SEG_BASE} ${on ? SEG_ON : SEG_OFF}`;
            });
        });
    });
}


/* ── Security ────────────────────────────────────────────────────────────── */

async function _renderSecurityCard(container) {
    const card = container.querySelector('#app-security-card');
    if (!card) return;

    let mfa;
    try {
        mfa = await api.getMyMfa();
    } catch {
        return; // endpoint unavailable (e.g. demo user) — leave the card hidden
    }
    if (!mfa || !mfa.ok || !mfa.local_account) return; // SSO accounts: MFA lives at the IdP

    const render = (state) => {
        card.classList.remove('hidden');
        card.innerHTML = `
            <h4 class="text-lg font-semibold mb-1">Two-Factor Authentication</h4>
            <p class="text-xs text-gray-500 mb-4">
                A 6-digit code from an authenticator app is required at sign-in.
                ${state.org_requires_mfa ? '<span class="font-semibold">Your organization requires this.</span>' : ''}
            </p>
            <div id="mfa-card-body"></div>
            <p id="mfa-card-error" class="hidden text-red-500 text-xs mt-2"></p>`;
        const body = card.querySelector('#mfa-card-body');
        const errEl = card.querySelector('#mfa-card-error');
        const showErr = (m) => { errEl.textContent = m; errEl.classList.remove('hidden'); };

        if (state.totp_enabled) {
            body.innerHTML = `
                <div class="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-700 rounded-lg">
                    <span class="text-xs font-bold text-green-600 bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded">Enabled</span>
                    <div class="flex items-center gap-2">
                        <input id="mfa-disable-code" type="text" inputmode="numeric" maxlength="6" placeholder="Code"
                            class="w-24 px-2 py-1.5 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-xs text-center">
                        <button id="mfa-disable-btn" class="text-xs text-red-600 hover:text-red-800 underline font-medium">Disable</button>
                    </div>
                </div>`;
            body.querySelector('#mfa-disable-btn').addEventListener('click', async () => {
                errEl.classList.add('hidden');
                const code = body.querySelector('#mfa-disable-code').value.trim();
                if (code.length !== 6) { showErr('Enter a current 6-digit code to disable.'); return; }
                try {
                    await api.disableTotp(code);
                    render({ ...state, totp_enabled: false });
                } catch (e) { showErr(e.message || 'Invalid code.'); }
            });
        } else {
            body.innerHTML = `
                <button id="mfa-enable-btn" class="px-4 py-2 rounded-lg bg-neutral-800 dark:bg-neutral-700 text-white text-xs font-medium hover:bg-black dark:hover:bg-neutral-600 transition-colors">
                    Set up authenticator app
                </button>`;
            body.querySelector('#mfa-enable-btn').addEventListener('click', async () => {
                errEl.classList.add('hidden');
                try {
                    const res = await api.setupTotp();
                    body.innerHTML = `
                        <p class="text-xs text-neutral-500 dark:text-neutral-400 mb-2">
                            Scan this with Google Authenticator, Microsoft Authenticator, or
                            any TOTP app, then confirm with the 6-digit code it shows.
                        </p>
                        <div id="mfa-qr" class="mb-2 inline-block rounded-lg overflow-hidden"></div>
                        <details class="mb-3">
                            <summary class="text-xs text-neutral-500 dark:text-neutral-400 cursor-pointer">Can't scan? Enter the key manually</summary>
                            <div class="mt-2 p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 font-mono text-xs break-all select-all">${res.secret}</div>
                            <a href="${res.otpauth_uri}" class="block text-xs text-green-600 hover:underline mt-1">Open in authenticator app on this device</a>
                        </details>
                        <div class="flex items-center gap-2">
                            <input id="mfa-confirm-code" type="text" inputmode="numeric" maxlength="6" placeholder="123456"
                                class="w-28 px-2 py-1.5 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm text-center tracking-widest">
                            <button id="mfa-confirm-btn" class="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium transition-colors">Confirm</button>
                        </div>`;
                    // qrcode global from js/lib/qrcode.js (vendored, MIT). typeNumber 0
                    // auto-sizes to the data length; 'M' matches common authenticator-app
                    // QR conventions. Rendered as self-contained SVG (own white background
                    // baked in), so it stays legible regardless of the app's theme.
                    try {
                        const qr = qrcode(0, 'M');
                        qr.addData(res.otpauth_uri);
                        qr.make();
                        body.querySelector('#mfa-qr').innerHTML = qr.createSvgTag(4);
                    } catch { /* manual-entry details above still work without it */ }
                    body.querySelector('#mfa-confirm-btn').addEventListener('click', async () => {
                        errEl.classList.add('hidden');
                        const code = body.querySelector('#mfa-confirm-code').value.trim();
                        if (code.length !== 6) { showErr('Enter the 6-digit code.'); return; }
                        try {
                            await api.verifyTotp(code);
                            render({ ...state, totp_enabled: true });
                        } catch (e) { showErr(e.message || 'Invalid code.'); }
                    });
                    body.querySelector('#mfa-confirm-code').focus();
                } catch (e) { showErr(e.message || 'Could not start enrollment.'); }
            });
        }
    };
    render(mfa);
}


/* ── Connected accounts ──────────────────────────────────────────────────── */

// Empty since 2026-08-15: the delegated connectors this catalogue offered
// (Google Drive, OneDrive/SharePoint, GitHub) all retired in favour of MCP
// OAuth servers, which members connect from the Tools Catalog or the
// composer's + panel. The renderer below hides the whole card when there is
// nothing to offer, so an empty list keeps the tab clean without deleting
// the machinery a future delegated account would reuse.
const PROVIDERS = [];

const _connectBtn = (id) =>
    `<a href="/api/auth/${id}/login" class="text-xs bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 px-3 py-1.5 rounded font-medium transition-colors">Connect</a>`;

const _connectedBtn = () => `
    <div class="flex items-center gap-2">
        <span class="text-xs font-bold text-green-600 bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded">Connected</span>
        <button data-disconnect class="text-xs text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 underline font-medium">Disconnect</button>
    </div>`;

async function _renderConnectedAccounts(container) {
    const list = container.querySelector('#connected-list');
    if (!list) return;

    // One call gives what this member has linked, what their org permits, and
    // whether any agent they can reach would actually use it. Nothing renders
    // until it returns: drawing the full catalogue first and removing rows
    // afterwards flashes Connect buttons for sources they cannot use.
    let connected = [];
    let offerable = null;   // null = server said nothing; fall back to the catalogue
    try {
        const res = await api.getAuthStatus();
        connected = (res && res.connected) ? res.connected : [];
        if (res && Array.isArray(res.connectors)) {
            // Both flags must hold. `allowed` is the org's policy; `usable`
            // means some agent is authorized to call a tool from this source.
            // Offering an allowed-but-unusable source buys the member an OAuth
            // grant that nothing reads.
            offerable = new Set(res.connectors.filter(c => c.allowed && c.usable).map(c => c.key));
        }
    } catch (e) {
        // Server unreachable: fall through and render the catalogue on
        // "Connect". The route guard is the actual control, so a stale list
        // here cannot create a connection the org has blocked.
        console.warn('Failed to load connection status', e);
    }

    // A source can be linked but no longer offerable — an admin blocked it, or
    // the tool came out of the policy, after the fact. Keep those visible so
    // the member can still disconnect: hiding a live token is the one thing
    // worse than showing it.
    const isConnected = (id) => connected.includes(id) || connected.some(c => c.provider === id);
    const visible = PROVIDERS.filter(p => offerable === null || offerable.has(p.id) || isConnected(p.id));

    if (!visible.length) {
        // Hiding the whole card rather than explaining an empty one: for most
        // orgs no agent uses a data source at all, and three greyed-out rows
        // with a disclaimer is noise on a tab everyone opens for the theme.
        const card = container.querySelector('#app-connected-card');
        if (card) card.classList.add('hidden');
        return;
    }

    list.innerHTML = visible.map(p => `
        <div class="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-700 rounded-lg bg-white dark:bg-neutral-800" data-provider="${p.id}">
            <div class="flex items-center gap-3 min-w-0">
                <svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24">${p.icon}</svg>
                <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200 truncate">${p.name}</span>
            </div>
            <div class="status-action shrink-0">
                ${isConnected(p.id) ? _connectedBtn() : _connectBtn(p.id)}
            </div>
        </div>
        ${offerable && !offerable.has(p.id) ? `
            <p class="-mt-2 mb-1 px-3 text-xs text-gray-500">
                No agent you can use reads from this any more. Disconnecting is safe.
            </p>` : ''}`).join('');

    // Delegated rather than per-button: the row contents are replaced after a
    // disconnect, and a listener bound to the button would go with them.
    list.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-disconnect]');
        if (!btn) return;
        const row = btn.closest('[data-provider]');
        const id = row?.dataset.provider;
        if (!id || !confirm(`Disconnect ${id}?`)) return;

        const original = btn.textContent;
        btn.textContent = '…';
        btn.disabled = true;
        try {
            await api.disconnectProvider(id);
            if (offerable !== null && !offerable.has(id)) {
                // Only visible because it was still linked. Now that it is not,
                // offering Connect would point at something the route blocks or
                // no agent would use.
                row.nextElementSibling?.matches('p') && row.nextElementSibling.remove();
                row.remove();
                if (!list.querySelector('[data-provider]')) {
                    container.querySelector('#app-connected-card')?.classList.add('hidden');
                }
            } else {
                row.querySelector('.status-action').innerHTML = _connectBtn(id);
            }
        } catch (err) {
            console.error('Disconnect failed', err);
            alert('Failed to disconnect. Please try again.');
            btn.textContent = original;
            btn.disabled = false;
        }
    });
}
