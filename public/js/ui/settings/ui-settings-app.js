import * as ui from '../ui.js';
import * as api from '../../core/api.js';

/**
 * Renders the App Settings tab (Theme, Connected Accounts, Delete Account).
 * Sign-out lives in the sidebar (Log Out) — not duplicated here.
 * @param {string} currentTheme - The current theme ('light', 'dark', 'system')
 * @param {Function} onThemeChange - Callback for theme selection
 * @param {Function} onDelete - Callback for delete button
 */
export function renderSettingsAppTab(currentTheme, onThemeChange, onDelete) {
    ui._ensureElements();
    const container = ui.elements.cpTabAppSettings;
    if (!container) return;

    const themes = [
        { key: 'light', name: 'Light' },
        { key: 'dark', name: 'Dark' },
        { key: 'system', name: 'System Default' }
    ];

    // Generate HTML for the settings
    container.innerHTML = `
        <div class="settings-page-header">
            <h1>App Settings</h1>
            <p>Manage your appearance, account, and connected data sources.</p>
        </div>

        <div class="settings-card">
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-3">Theme</h4>
            <div class="space-y-2" role="radiogroup">
                ${themes.map(theme => `
                    <label class="flex items-center gap-3 p-3 border ${theme.key === currentTheme ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-green-500 dark:hover:border-green-400 transition-colors">
                        <input type="radio" name="theme-select" value="${theme.key}" class="form-radio text-green-600 focus:ring-green-500" ${theme.key === currentTheme ? 'checked' : ''}>
                        <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200">${theme.name}</span>
                    </label>
                `).join('')}
            </div>
        </div>

        <div class="settings-card">
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-3">Account</h4>
            <div class="space-y-3">
                <button id="cp-delete-account-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-red-600 dark:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg border border-red-300 dark:border-red-700 transition-colors">
                    Delete Account...
                </button>
            </div>
        </div>
    `;

    // Attach event listeners
    container.querySelectorAll('input[name="theme-select"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const newTheme = e.target.value;
            onThemeChange(newTheme);

            // Update styles
            container.querySelectorAll('label').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('label').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('label').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });

    document.getElementById('cp-delete-account-btn').addEventListener('click', onDelete);

    // Fetch and render connected accounts
    _renderConnectedAccounts(container);

    // Two-factor authentication (local accounts)
    _renderSecurityCard(container);
}

async function _renderSecurityCard(container) {
    let mfa;
    try {
        mfa = await api.getMyMfa();
    } catch {
        return; // endpoint unavailable (e.g. demo user) — skip the card
    }
    if (!mfa || !mfa.ok || !mfa.local_account) return; // SSO accounts: MFA lives at the IdP

    const card = document.createElement('div');
    card.className = 'settings-card';
    const accountHeader = Array.from(container.querySelectorAll('h4')).find(h => h.textContent === 'Account');
    if (accountHeader && accountHeader.parentNode) {
        accountHeader.parentNode.parentNode.insertBefore(card, accountHeader.parentNode);
    } else {
        container.appendChild(card);
    }

    const render = (state) => {
        card.innerHTML = `
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-1">Two-Factor Authentication</h4>
            <p class="text-xs text-neutral-500 dark:text-neutral-400 mb-3">
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

async function _renderConnectedAccounts(container) {
    const list = document.createElement('div');
    list.id = "connected-accounts-section";
    list.className = "settings-card";

    // Default Providers List
    const providers = [
        { id: 'google', name: 'Google Drive', icon: '<path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.84.81-.53z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/><path d="M12 12h9c0-.63-.09-1.29-.27-1.92H12v1.92z" fill="#4285F4"/>' },
        { id: 'microsoft', name: 'Microsoft OneDrive / SharePoint', icon: '<path fill="#f35325" d="M1 1h10v10H1z" /><path fill="#81bc06" d="M12 1h10v10H12z" /><path fill="#05a6f0" d="M1 12h10v10H1z" /><path fill="#ffba08" d="M12 12h10v10H12z" />' },
        { id: 'github', name: 'GitHub', icon: '<path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" fill="currentColor"/>' }
    ];

    list.innerHTML = `
        <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-2">Connected Accounts</h4>
        <div id="connected-list" class="space-y-3">
             <!-- Render defaults immediately -->
             ${providers.map(p => `
                <div class="flex items-center justify-between p-3 border border-neutral-200 dark:border-neutral-700 rounded-lg bg-white dark:bg-neutral-800" data-provider="${p.id}">
                    <div class="flex items-center gap-3">
                        <svg class="w-5 h-5" viewBox="0 0 24 24">${p.icon}</svg>
                        <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200">${p.name}</span>
                    </div>
                    <div class="status-action">
                        <a href="/api/auth/${p.id}/login" class="text-xs bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 px-3 py-1.5 rounded font-medium transition-colors">Connect</a>
                    </div>
                </div>
             `).join('')}
        </div>
    `;

    // Insert into DOM immediately
    // Find the "Account" header to insert before
    const accountHeader = Array.from(container.querySelectorAll('h4')).find(h => h.textContent === 'Account');

    if (accountHeader && accountHeader.parentNode) {
        // Insert into the wrapper div (accountHeader.parentNode), not the main container
        accountHeader.parentNode.insertBefore(list, accountHeader);
    } else {
        // Fallback: append to the main container's inner wrapper if found, or container itself
        const wrapper = container.querySelector('.space-y-4');
        if (wrapper) {
            wrapper.appendChild(list);
        } else {
            container.appendChild(list);
        }
    }

    // Then try to fetch status to update UI
    try {
        const res = await api.getAuthStatus();
        console.log("DEBUG: Auth Status Response:", res);
        const connected = (res && res.connected) ? res.connected : [];

        // Update UI based on status
        providers.forEach(p => {
            // Backend returns list of strings ['google', 'microsoft'] OR objects
            const isConnected = connected.includes(p.id) || connected.some(c => c.provider === p.id);
            const row = list.querySelector(`div[data-provider="${p.id}"] .status-action`);

            if (isConnected) {
                if (row) {
                    row.innerHTML = `
                        <div class="flex items-center gap-2">
                             <span class="text-xs font-bold text-green-600 bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded">Connected</span>
                             <button class="text-xs text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 underline font-medium" onclick="disconnectAccount('${p.id}', this)">Disconnect</button>
                        </div>
                    `;
                }
            } else {
                // Reset to Connect button if disconnected
                if (row) {
                    row.innerHTML = `<a href="/api/auth/${p.id}/login" class="text-xs bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 px-3 py-1.5 rounded font-medium transition-colors">Connect</a>`;
                }
            }
        });

        // Add handler for disconnect buttons
        window.disconnectAccount = async (providerId, btn) => {
            if (!confirm(`Are you sure you want to disconnect ${providerId}?`)) return;

            btn.innerHTML = '...';
            btn.disabled = true;

            try {
                await api.disconnectProvider(providerId);
                // Re-fetch status to update UI
                const newRes = await api.getAuthStatus();
                const newConnected = (newRes && newRes.connected) ? newRes.connected : [];

                // Re-run the update loop logic (simplified here by recursion or direct DOM update)
                // For simplicity, we just reload the tab render or manipulate DOM directly
                // Let's just find the row and reset it to "Connect" state
                const row = list.querySelector(`div[data-provider="${providerId}"] .status-action`);
                if (row) {
                    row.innerHTML = `<a href="/api/auth/${providerId}/login" class="text-xs bg-neutral-100 dark:bg-neutral-700 hover:bg-neutral-200 dark:hover:bg-neutral-600 px-3 py-1.5 rounded font-medium transition-colors">Connect</a>`;
                }
            } catch (e) {
                console.error("Disconnect failed", e);
                alert("Failed to disconnect. Please try again.");
                btn.innerHTML = 'Disconnect';
                btn.disabled = false;
            }
        };

    } catch (e) {
        console.warn("Failed to load connection status (Server down?)", e);
        // We leave the "Connect" buttons as is.
    }
}
