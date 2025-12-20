import * as ui from '../ui.js';

/**
 * Renders the embedded dashboard iframe in the Control Panel.
 */
import * as api from '../../core/api.js';

/**
 * Renders the embedded dashboard iframe in the Control Panel.
 * Now Secured: Fetches an ephemeral access token first.
 */
export async function renderSettingsDashboardTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabDashboard;
    if (!container) return;

    // Don't re-render if iframe already exists
    if (container.querySelector('iframe')) return;

    container.innerHTML = `
        <div class="flex items-center justify-center w-full h-full text-neutral-500">
            <div class="flex flex-col items-center gap-2">
                <div class="loader ease-linear rounded-full border-4 border-t-4 border-gray-200 h-8 w-8"></div>
                <span>Securing connection to dashboard...</span>
            </div>
        </div>
    `;

    try {
        const result = await api.getDashboardToken();
        if (!result.token) {
            throw new Error(result.error || 'Access denied');
        }

        container.innerHTML = ''; // Clear loading state

        const headerDiv = document.createElement('div');
        headerDiv.className = "p-6 shrink-0";
        headerDiv.innerHTML = `
            <h3 class="text-xl font-semibold mb-4">Trace & Analyze</h3>
            <p class="text-neutral-500 dark:text-neutral-400 mb-0 text-sm">Analyze ethical alignment and trace decisions across all conversations.</p>
        `;

        const iframeContainer = document.createElement('div');
        iframeContainer.className = "w-full flex-1 relative min-h-0";

        const iframe = document.createElement('iframe');
        iframe.src = `https://dash.selfalignmentframework.com/?embed=true&token=${encodeURIComponent(result.token)}`;
        iframe.className = "absolute inset-0 w-full h-full rounded-lg border-0";
        iframe.title = "SAFi Dashboard";
        iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-downloads";

        iframeContainer.appendChild(iframe);

        container.appendChild(headerDiv);
        container.appendChild(iframeContainer);

    } catch (error) {
        console.error('Dashboard Access Error:', error);
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center w-full h-full text-center p-8">
                <div class="bg-red-50 dark:bg-red-900/20 p-4 rounded-xl mb-4 text-red-600 dark:text-red-400">
                    <svg class="w-12 h-12 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                    </svg>
                    <h3 class="font-bold text-lg">Access Denied</h3>
                    <p class="text-sm mt-1">${error.message || 'You do not have permission to view this dashboard.'}</p>
                </div>
                <button onclick="document.getElementById('desktop-back-to-chat').click()" class="px-4 py-2 bg-neutral-200 dark:bg-neutral-800 rounded-lg font-medium hover:bg-neutral-300 dark:hover:bg-neutral-700 transition-colors">
                    Back to Chat
                </button>
            </div>
        `;
    }
}
