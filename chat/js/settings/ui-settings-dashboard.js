import * as ui from '../ui.js';

/**
 * Renders the embedded dashboard iframe in the Control Panel.
 */
export function renderSettingsDashboardTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabDashboard;
    if (!container) return;

    // Don't re-render if iframe already exists
    if (container.querySelector('iframe')) return;

    container.innerHTML = ''; // Clear any placeholders

    const headerDiv = document.createElement('div');
    headerDiv.className = "p-6 shrink-0";
    headerDiv.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Trace & Analyze</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-0 text-sm">Analyze ethical alignment and trace decisions across all conversations.</p>
    `;

    const iframeContainer = document.createElement('div');
    // UPDATED: Changed from fixed h-[1024px] to flexible height
    // flex-1: fills remaining vertical space
    // min-h-0: allows the flex child to shrink below its content size (crucial for scrolling)
    // relative: establishes context for absolute positioning of the iframe
    iframeContainer.className = "w-full flex-1 relative min-h-0";

    const iframe = document.createElement('iframe');
    iframe.src = "https://dashboard.selfalignmentframework.com/?embed=true";
    // UPDATED: Use absolute positioning to fill the flex container completely
    iframe.className = "absolute inset-0 w-full h-full rounded-lg border-0";
    iframe.title = "SAFi Dashboard";
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-downloads";

    iframeContainer.appendChild(iframe);

    container.appendChild(headerDiv);
    container.appendChild(iframeContainer);
}
