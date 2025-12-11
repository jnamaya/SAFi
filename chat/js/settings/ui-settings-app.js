import * as ui from '../ui.js';

/**
 * Renders the App Settings tab (Theme, Logout, Delete Account).
 * @param {string} currentTheme - The current theme ('light', 'dark', 'system')
 * @param {Function} onThemeChange - Callback for theme selection
 * @param {Function} onLogout - Callback for logout button
 * @param {Function} onDelete - Callback for delete button
 */
export function renderSettingsAppTab(currentTheme, onThemeChange, onLogout, onDelete) {
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
        <h3 class="text-xl font-semibold mb-4">App Settings</h3>
        
        <div class="space-y-4">
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-2">Theme</h4>
            <div class="space-y-2" role="radiogroup">
                ${themes.map(theme => `
                    <label class="flex items-center gap-3 p-3 border ${theme.key === currentTheme ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-green-500 dark:hover:border-green-400 transition-colors">
                        <input type="radio" name="theme-select" value="${theme.key}" class="form-radio text-green-600 focus:ring-green-500" ${theme.key === currentTheme ? 'checked' : ''}>
                        <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200">${theme.name}</span>
                    </label>
                `).join('')}
            </div>
            
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mt-8 mb-2">Account</h4>
            <div class="space-y-3">
                <button id="cp-logout-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-lg border border-neutral-300 dark:border-neutral-700 transition-colors">
                    Sign Out
                </button>
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

    document.getElementById('cp-logout-btn').addEventListener('click', onLogout);
    document.getElementById('cp-delete-account-btn').addEventListener('click', onDelete);
}
