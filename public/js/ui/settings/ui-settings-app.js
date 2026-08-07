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
                            Add this key to your authenticator app, then confirm with the 6-digit code it shows.
                        </p>
                        <div class="mb-2 p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 font-mono text-xs break-all select-all">${res.secret}</div>
                        <a href="${res.otpauth_uri}" class="block text-xs text-green-600 hover:underline mb-3">Open in authenticator app</a>
                        <div class="flex items-center gap-2">
                            <input id="mfa-confirm-code" type="text" inputmode="numeric" maxlength="6" placeholder="123456"
                                class="w-28 px-2 py-1.5 rounded border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm text-center tracking-widest">
                            <button id="mfa-confirm-btn" class="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-xs font-medium transition-colors">Confirm</button>
                        </div>`;
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

const PROVIDERS = [
    { id: 'google', name: 'Google Drive', icon: '<path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.84.81-.53z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/><path d="M12 12h9c0-.63-.09-1.29-.27-1.92H12v1.92z" fill="#4285F4"/>' },
    { id: 'microsoft', name: 'Microsoft OneDrive / SharePoint', icon: '<path fill="#f35325" d="M1 1h10v10H1z" /><path fill="#81bc06" d="M12 1h10v10H12z" /><path fill="#05a6f0" d="M1 12h10v10H1z" /><path fill="#ffba08" d="M12 12h10v10H12z" />' },
    { id: 'github', name: 'GitHub', icon: '<path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" fill="currentColor"/>' },
];

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

    list.innerHTML = PROVIDERS.map(p => `
        <div class="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-700 rounded-lg bg-white dark:bg-neutral-800" data-provider="${p.id}">
            <div class="flex items-center gap-3 min-w-0">
                <svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24">${p.icon}</svg>
                <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200 truncate">${p.name}</span>
            </div>
            <div class="status-action shrink-0">${_connectBtn(p.id)}</div>
        </div>`).join('');

    // Delegated, and attached before the fetch. The previous version defined the
    // handler as window.disconnectAccount *inside* the try block and referenced
    // it from an inline onclick, so a failed getAuthStatus left Disconnect
    // buttons wired to a function that did not exist.
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
            row.querySelector('.status-action').innerHTML = _connectBtn(id);
        } catch (err) {
            console.error('Disconnect failed', err);
            alert('Failed to disconnect. Please try again.');
            btn.textContent = original;
            btn.disabled = false;
        }
    });

    try {
        const res = await api.getAuthStatus();
        const connected = (res && res.connected) ? res.connected : [];
        PROVIDERS.forEach(p => {
            const isConnected = connected.includes(p.id) || connected.some(c => c.provider === p.id);
            const slot = list.querySelector(`div[data-provider="${p.id}"] .status-action`);
            if (slot) slot.innerHTML = isConnected ? _connectedBtn() : _connectBtn(p.id);
        });
    } catch (e) {
        // Server unreachable: the rows stay on "Connect", which is the safe
        // reading — it fails to an action rather than to a false "Connected".
        console.warn('Failed to load connection status', e);
    }
}
