import * as ui from '../ui.js';

/**
 * Main function to build and inject the Conscience ("Ethical Reasoning") modal content.
 * @param {object} payload - The audit payload from the message
 */
export function setupConscienceModalContent(payload) {
    ui._ensureElements();
    const container = ui.elements.conscienceDetails;
    if (!container) return;
    container.innerHTML = ''; // Clear previous content

    const profileName = payload.profile ? `<strong>${payload.profile}</strong>` : 'current';

    // 1. Group ledger items
    const ledger = payload.ledger || [];
    const groups = {
        upholds: ledger.filter(r => r.score > 0),
        conflicts: ledger.filter(r => r.score < 0),
        neutral: ledger.filter(r => r.score === 0),
    };
    ['upholds', 'conflicts', 'neutral'].forEach(key => {
        groups[key].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    });

    // 2. Build the new HTML structure
    // ADDED w-full to nav to ensure tabs span full width
    container.innerHTML = `
        <p class="text-base text-gray-600 dark:text-gray-300 mb-6">
            Audit Report: Verification that this response complies with both the ${profileName} ethical profile and organizational safety rules & values.
        </p>
        
        ${renderScoreAndTrend(payload)}
        
        <div>
            <!-- Tab Buttons -->
            <div class="border-b border-gray-200 dark:border-gray-700">
                <nav class="flex -mb-px w-full" aria-label="Tabs" id="conscience-tabs">
                    ${renderTabButton('upholds', 'Upholds', groups.upholds.length, true)}
                    ${renderTabButton('conflicts', 'Conflicts', groups.conflicts.length, false)}
                    ${renderTabButton('neutral', 'Neutral', groups.neutral.length, false)}
                </nav>
            </div>

            <!-- Tab Panels -->
            <div class="py-5">
                ${renderTabPanel('upholds', groups.upholds, true)}
                ${renderTabPanel('conflicts', groups.conflicts, false)}
                ${renderTabPanel('neutral', groups.neutral, false)}
            </div>
        </div>
    `;

    // 3. Attach all event listeners for the new content
    attachModalEventListeners(container, payload);
}

/**
 * Renders the "Score & Trend" dashboard card.
 * @param {object} payload 
 */
function renderScoreAndTrend(payload) {
    // --- Radial Gauge ---
    const score = (payload.spirit_score !== null && payload.spirit_score !== undefined) ? Math.max(0, Math.min(10, payload.spirit_score)) : 10.0;
    const circumference = 50 * 2 * Math.PI; // 314
    const offset = circumference - (score / 10) * circumference;

    const getScoreColor = (s) => {
        if (s >= 8) return 'text-green-500';
        if (s >= 5) return 'text-yellow-500';
        return 'text-red-500';
    };
    const colorClass = getScoreColor(score);

    const radialGauge = `
        <div class="flex flex-col items-center justify-center">
            <div class="relative w-32 h-32">
                <svg class="w-full h-full transform -rotate-90" viewBox="0 0 120 120">
                    <circle class="text-gray-200 dark:text-gray-700" stroke-width="10" stroke="currentColor" fill="transparent" r="50" cx="60" cy="60" />
                    <circle class="${colorClass}" stroke-width="10" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" stroke="currentColor" fill="transparent" r="50" cx="60" cy="60" />
                </svg>
                <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center">
                    <span class="text-4xl font-bold ${colorClass}">${score.toFixed(1)}</span>
                    <span class="text-xs text-gray-500 dark:text-gray-400">/ 10</span>
                </div>
            </div>
            <h4 class="font-semibold mt-3 text-center text-gray-800 dark:text-gray-200">Consistency Score</h4>

        </div>
    `;

    // --- Sparkline ---
    const scores = (payload.spirit_scores_history || [])
        .filter(s => s !== null && s !== undefined) // Filter out null/undefined
        .slice(-10); // Get last 10

    let sparkline = '<div class="flex-1 flex items-center justify-center text-sm text-gray-400">Not enough data for trend.</div>';

    if (scores.length > 1) {
        const width = 200, height = 60, padding = 5;
        const maxScore = 10, minScore = 0;
        const range = maxScore - minScore;
        // Map scores to X,Y coordinates
        const points = scores.map((s, i) => {
            const x = (i / (scores.length - 1)) * (width - 2 * padding) + padding;
            const y = height - padding - ((s - minScore) / range) * (height - 2 * padding);
            return `${x},${y}`;
        }).join(' ');

        const lastPoint = points.split(' ').pop().split(',');
        sparkline = `
            <div class="flex-1">
                <h4 class="font-semibold mb-2 text-center md:text-left text-gray-800 dark:text-gray-200">Consistency Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <!-- Dotted lines at 10, 5, 0 -->
                    <line x1="0" y1="${padding}" x2="${width}" y2="${padding}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height - padding}" x2="${width}" y2="${height - padding}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    
                    <!-- Data Line -->
                    <polyline fill="none" class="stroke-green-500" stroke-width="2" points="${points}" />
                    
                    <!-- Last point circle -->
                    <circle fill="currentColor" class="${getScoreColor(scores[scores.length - 1])} stroke-white dark:stroke-gray-900" stroke-width="2" r="4" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 text-center md:text-left">Recent score history (${scores.length} turns)</p>
                
                ${payload.user_role === 'member' ? '' : `
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-2 text-center md:text-left">
                    <a href="#" id="view-full-dashboard-link" class="font-medium text-green-600 dark:text-green-500 hover:underline">
                        View Full Audit Report &rarr;
                    </a>
                </p>
                `}
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-6 items-center bg-gray-50 dark:bg-gray-900/50 rounded-lg p-5 mb-6 border border-gray-200 dark:border-gray-700">${radialGauge}${sparkline}</div>`;
}

/**
 * Renders a single tab button.
 */
function renderTabButton(key, title, count, isActive) {
    const groupConfig = {
        upholds: { icon: 'M5 13l4 4L19 7', color: 'green' },
        conflicts: { icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z', color: 'red' },
        neutral: { icon: 'M18 12H6', color: 'gray' },
    };
    const config = groupConfig[key];

    // State Styles (these are toggled by the event listener)
    const activeClasses = `border-${config.color}-500 text-${config.color}-600 dark:border-${config.color}-500 dark:text-${config.color}-500`;
    const inactiveClasses = 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300 dark:hover:border-gray-600';

    // Responsive Layout Styles
    const layoutClasses = "flex-1 flex flex-col sm:flex-row items-center justify-center gap-1 sm:gap-2 py-3 sm:py-4 px-1 sm:px-3 text-center border-b-2 font-medium text-xs sm:text-sm focus:outline-none transition-colors duration-200";

    return `
        <button data-tab-target="#tab-${key}" 
                class="tab-btn ${isActive ? activeClasses : inactiveClasses} ${layoutClasses}" 
                aria-current="${isActive ? 'page' : 'false'}">
            
            <!-- Icon: slightly larger on mobile for touch targets -->
            <svg class="w-5 h-5 sm:w-5 sm:h-5 text-${config.color}-500 mb-0.5 sm:mb-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${config.icon}"></path>
            </svg>
            
            <!-- Text & Badge Wrapper -->
            <div class="flex items-center gap-1.5">
                <span>${title}</span>
                <span class="bg-${config.color}-100 text-${config.color}-800 dark:bg-${config.color}-900 dark:text-${config.color}-300 px-1.5 py-0.5 rounded-full text-[10px] sm:text-xs font-medium">
                    ${count}
                </span>
            </div>
        </button>
    `;
}

/**
 * Renders a single tab panel with its ledger items.
 */
function renderTabPanel(key, items, isActive) {
    let content = '';
    if (items.length > 0) {
        content = items.map(item => renderLedgerItem(item, key)).join('');
    } else {
        content = `<p class="text-sm text-center text-gray-500 dark:text-gray-400">No items in this category.</p>`;
    }

    return `
        <div id="tab-${key}" class="tab-panel space-y-4 ${isActive ? '' : 'hidden'}">
            ${content}
        </div>
    `;
}

/**
 * Renders a single ledger item.
 */
function renderLedgerItem(item, key) {
    const reasonHtml = DOMPurify.sanitize(String(item.reason || ''));
    const maxLength = 120;
    const isLong = reasonHtml.length > maxLength;

    const borderColor = {
        upholds: 'border-green-200 dark:border-green-700/80',
        conflicts: 'border-red-300 dark:border-red-700/80',
        neutral: 'border-gray-200 dark:border-gray-700/80',
    }[key];

    const confidenceDisplayHtml = item.confidence ? `
        <div class="flex items-center gap-2 w-full md:w-auto md:min-w-[160px]">
            <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Confidence</span>
            <div class="h-1.5 flex-1 rounded-full bg-gray-200 dark:bg-gray-600">
                <div class="h-full rounded-full bg-green-500" style="width: ${item.confidence * 100}%"></div>
            </div>
            <span class="text-xs font-semibold text-gray-600 dark:text-gray-300 w-9 text-right">${Math.round(item.confidence * 100)}%</span>
        </div>
    ` : '';

    return `
        <div class="bg-white dark:bg-gray-800/60 p-4 rounded-lg border ${borderColor}">
            <div class="flex flex-col md:flex-row justify-between md:items-center gap-2 mb-2">
                <div class="font-semibold text-gray-800 dark:text-gray-100">${item.value || item.name || item.Value || 'Unknown Value'}</div>
                ${confidenceDisplayHtml}
            </div>
            <div class="prose prose-sm text-gray-600 dark:text-gray-400 max-w-none">
                <div class="reason-text ${isLong ? 'truncated' : ''}">${reasonHtml}</div>
                ${isLong ? '<button class="expand-btn">Show More</button>' : ''}
            </div>
        </div>
    `;
}

/**
 * Attaches event listeners for tabs, copy button, and dashboard link.
 */
function attachModalEventListeners(container, payload) {
    // --- Tab switching logic ---
    const tabButtons = container.querySelectorAll('.tab-btn');
    const tabPanels = container.querySelectorAll('.tab-panel');

    const groupConfig = {
        upholds: { color: 'green' },
        conflicts: { color: 'red' },
        neutral: { color: 'gray' },
    };

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab-target');

            // Update button styles
            tabButtons.forEach(b => {
                const key = b.getAttribute('data-tab-target').replace('#tab-', '');
                const config = groupConfig[key];
                b.classList.remove(`border-${config.color}-500`, `text-${config.color}-600`, `dark:border-${config.color}-500`, `dark:text-${config.color}-500`);
                b.classList.add('border-transparent', 'text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'dark:text-gray-400', 'dark:hover:text-gray-300', 'dark:hover:border-gray-600');
                b.setAttribute('aria-current', 'false');
            });

            const activeKey = targetId.replace('#tab-', '');
            const activeConfig = groupConfig[activeKey];
            btn.classList.add(`border-${activeConfig.color}-500`, `text-${activeConfig.color}-600`, `dark:border-${activeConfig.color}-500`, `dark:text-${activeConfig.color}-500`);
            btn.classList.remove('border-transparent', 'text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'dark:text-gray-400', 'dark:hover:text-gray-300', 'dark:hover:border-gray-600');
            btn.setAttribute('aria-current', 'page');

            // Show/hide panels
            tabPanels.forEach(panel => {
                if ('#' + panel.id === targetId) {
                    panel.classList.remove('hidden');
                } else {
                    panel.classList.add('hidden');
                }
            });
        });
    });

    // --- "Show More" logic ---
    // This is now handled by the persistent, delegated listener in ui-settings-core.js

    // --- Copy button logic ---
    // We must re-attach this to the button inside the modal shell (which is in ui.js)
    const copyBtn = document.getElementById('copy-audit-btn');
    if (copyBtn) {
        // Clone to remove old listeners and prevent memory leaks
        const newCopyBtn = copyBtn.cloneNode(true);
        copyBtn.parentNode.replaceChild(newCopyBtn, copyBtn);
        // Add the fresh listener with the new payload
        newCopyBtn.addEventListener('click', () => copyAuditToClipboard(payload));
    }

    // --- Dashboard Link logic ---
    const dashboardLink = container.querySelector('#view-full-dashboard-link');
    if (dashboardLink) {
        dashboardLink.addEventListener('click', (e) => {
            e.preventDefault();
            // 1. Close this modal
            ui.closeModal();
            // 2. Hide the chat view
            ui.elements.chatView.style.display = 'none';
            ui.elements.chatView.classList.add('hidden');

            // 3. Show the control panel
            ui.elements.controlPanelView.classList.remove('hidden');

            // 4. HIDE Sidebar entirely & Fix Layout (Match app.js Control Panel logic)
            ui.closeSidebar();
            const sidebar = document.getElementById('sidebar');
            if (sidebar) {
                sidebar.classList.add('hidden');
                sidebar.classList.remove('md:flex');
            }
            const wrapper = document.getElementById('main-layout-wrapper');
            if (wrapper) wrapper.classList.remove('md:ml-72');

            // 5. Programmatically click the dashboard tab
            if (ui.elements.cpNavDashboard) {
                ui.elements.cpNavDashboard.click();
            }
        });
    }
}

/**
 * Copies a plain-text summary of the audit to the clipboard.
 */
function copyAuditToClipboard(payload) {
    // Implementation same as original
    let text = `SAFi Ethical Reasoning Audit\n`;
    text += `Profile: ${payload.profile || 'N_A'}\n`;
    text += `Alignment Score: ${payload.spirit_score !== null ? payload.spirit_score.toFixed(1) + '/10' : 'N/A'}\n`;
    text += `------------------------------------\n\n`;

    if (payload.ledger && payload.ledger.length > 0) {
        const upholds = payload.ledger.filter(r => r.score > 0);
        const conflicts = payload.ledger.filter(r => r.score < 0);
        const neutral = payload.ledger.filter(r => r.score === 0);

        if (upholds.length > 0) {
            text += 'UPHOLDS:\n';
            upholds.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (conflicts.length > 0) {
            text += 'CONFLICTS:\n';
            conflicts.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (neutral.length > 0) {
            text += 'NEUTRAL:\n';
            neutral.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
        }
    } else {
        text += 'No specific values were engaged for this response.';
    }

    navigator.clipboard.writeText(text).then(() => {
        ui.showToast('Audit copied to clipboard', 'success');
    }, () => {
        ui.showToast('Failed to copy audit', 'error');
    });
}
