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

    const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    // Raw agent keys (e.g. "the_fiduciary") can reach us for historical turns
    // from non-active agents; make them readable.
    const profileName = payload.profile ? String(payload.profile).replace(/_/g, ' ') : null;
    const policyName = payload.policy_name || null;

    // Scored values come from the governing policy (two-tier model), so name
    // the policy when we know it; agent wording is the standalone fallback.
    const evaluatedAgainst = policyName
        ? `the standards of <strong class="text-gray-700 dark:text-gray-300">${esc(policyName)}</strong>, the policy governing ${profileName ? `<strong class="text-gray-700 dark:text-gray-300">${esc(profileName)}</strong>` : 'this agent'}`
        : `${profileName ? `<strong class="text-gray-700 dark:text-gray-300">${esc(profileName)}</strong>'s` : "this agent's"} values and standards`;

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
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
            This report shows how this response was evaluated against ${evaluatedAgainst}.
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
    // A missing score means the audit hasn't completed (or failed) — show N/A,
    // never a default value that reads as a real result.
    const hasScore = payload.spirit_score !== null && payload.spirit_score !== undefined;
    const score = hasScore ? Math.max(0, Math.min(10, payload.spirit_score)) : 0;
    const circumference = 50 * 2 * Math.PI; // 314
    const offset = hasScore ? circumference - (score / 10) * circumference : circumference;

    // Thresholds match the Audit Hub dashboard gauge (safi_dashboard.py)
    const getScoreColor = (s) => {
        if (s > 7) return 'text-green-500';
        if (s > 4) return 'text-yellow-500';
        return 'text-red-500';
    };

    const getGradId = (s) => {
        if (s > 7) return 'gauge-grad-green';
        if (s > 4) return 'gauge-grad-yellow';
        return 'gauge-grad-red';
    };

    const gradId = getGradId(score);
    const colorClass = hasScore ? getScoreColor(score) : 'text-gray-400 dark:text-gray-500';

    const radialGauge = `
        <div class="flex flex-col items-center justify-center">
            <div class="relative w-32 h-32">
                <svg class="w-full h-full transform -rotate-90" viewBox="0 0 120 120">
                    <defs>
                        <linearGradient id="gauge-grad-green" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#10b981" />
                            <stop offset="100%" stop-color="#34d399" />
                        </linearGradient>
                        <linearGradient id="gauge-grad-yellow" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#f59e0b" />
                            <stop offset="100%" stop-color="#fbbf24" />
                        </linearGradient>
                        <linearGradient id="gauge-grad-red" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#ef4444" />
                            <stop offset="100%" stop-color="#f87171" />
                        </linearGradient>
                        <filter id="gauge-glow" x="-20%" y="-20%" width="140%" height="140%">
                            <feGaussianBlur stdDeviation="2.5" result="blur" />
                            <feComposite in="SourceGraphic" in2="blur" operator="over" />
                        </filter>
                    </defs>
                    <circle class="text-gray-200 dark:text-neutral-800" stroke-width="8" stroke="currentColor" fill="transparent" r="50" cx="60" cy="60" />
                    ${hasScore ? `
                    <!-- Subtle backing glow circle -->
                    <circle stroke="url(#${gradId})" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" fill="transparent" r="50" cx="60" cy="60" class="opacity-20 blur-[2px]" />
                    <!-- Primary indicator circle with glow filter -->
                    <circle stroke="url(#${gradId})" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" fill="transparent" r="50" cx="60" cy="60" filter="url(#gauge-glow)" />
                    ` : ''}
                </svg>
                <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center">
                    <span class="text-4xl font-bold ${colorClass}">${hasScore ? score.toFixed(1) : 'N/A'}</span>
                    <span class="text-xs text-gray-500 dark:text-gray-400">${hasScore ? '/ 10' : 'audit pending'}</span>
                </div>
            </div>
            <h4 class="font-semibold mt-3 text-center text-gray-800 dark:text-gray-200 text-sm">Alignment Score</h4>
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
        
        // Construct closed path for dynamic background gradient fill under trendline
        const fillPoints = `${points} ${width - padding},${height - padding} ${padding},${height - padding}`;

        sparkline = `
            <div class="flex-1">
                <h4 class="font-semibold mb-2 text-center md:text-left text-gray-800 dark:text-gray-200 text-sm">Alignment Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <defs>
                        <linearGradient id="sparkline-grad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#10b981" stop-opacity="0.2" />
                            <stop offset="100%" stop-color="#10b981" stop-opacity="0.0" />
                        </linearGradient>
                    </defs>
                    <!-- Dotted lines at 10, 5, 0 -->
                    <line x1="0" y1="${padding}" x2="${width}" y2="${padding}" class="stroke-neutral-300/40 dark:stroke-neutral-700/40" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" class="stroke-neutral-300/40 dark:stroke-neutral-700/40" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height - padding}" x2="${width}" y2="${height - padding}" class="stroke-neutral-300/40 dark:stroke-neutral-700/40" stroke-width="1" stroke-dasharray="2 2" />
                    
                    <!-- Trend Area Fill -->
                    <polygon points="${fillPoints}" fill="url(#sparkline-grad)" />

                    <!-- Data Line -->
                    <polyline fill="none" class="stroke-emerald-500 dark:stroke-emerald-400" stroke-width="2" points="${points}" />
                    
                    <!-- Last point circle -->
                    <circle fill="currentColor" class="${getScoreColor(scores[scores.length - 1])} stroke-white dark:stroke-gray-900" stroke-width="2" r="4" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 text-center md:text-left">Recent score history (${scores.length} turns)</p>
                
                ${payload.user_role === 'member' ? '' : `
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-2 text-center md:text-left">
                    <a href="#" id="view-full-dashboard-link" class="font-medium text-emerald-600 dark:text-emerald-400 hover:underline">
                        View Full Audit Report &rarr;
                    </a>
                </p>
                `}
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-6 items-center conscience-trend-grid rounded-lg p-5 mb-6">${radialGauge}${sparkline}</div>`;
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

    // Responsive Layout Styles
    const layoutClasses = "flex-1 flex flex-col sm:flex-row items-center justify-center gap-1 sm:gap-2 py-3 sm:py-4 px-1 sm:px-3 text-center border-b-2 font-medium text-xs sm:text-sm focus:outline-none transition-colors duration-200";

    const badgeColorClass = {
        green: 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300',
        red: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
        gray: 'bg-gray-100 text-gray-800 dark:bg-neutral-800 dark:text-gray-300',
    }[config.color];

    return `
        <button data-tab-target="#tab-${key}" 
                class="conscience-tab-btn tab-btn status-${config.color} ${isActive ? 'active' : ''} ${layoutClasses}" 
                aria-current="${isActive ? 'page' : 'false'}">
            
            <!-- Icon: slightly larger on mobile for touch targets -->
            <svg class="w-5 h-5 sm:w-5 sm:h-5 text-${config.color}-500 mb-0.5 sm:mb-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${config.icon}"></path>
            </svg>
            
            <!-- Text & Badge Wrapper -->
            <div class="flex items-center gap-1.5">
                <span>${title}</span>
                <span class="${badgeColorClass} px-1.5 py-0.5 rounded-full text-[10px] sm:text-xs font-medium">
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

    const statusCardClass = {
        upholds: 'audit-card-uphold',
        conflicts: 'audit-card-conflict',
        neutral: 'audit-card-neutral',
    }[key];

    const confidenceDisplayHtml = item.confidence ? `
        <div class="flex items-center gap-2 w-full md:w-auto md:min-w-[160px]">
            <span class="text-xs font-medium text-gray-500 dark:text-gray-400">Confidence</span>
            <div class="confidence-meter-track flex-1">
                <div class="confidence-meter-fill" style="width: ${item.confidence * 100}%"></div>
            </div>
            <span class="text-xs font-semibold text-gray-600 dark:text-gray-300 w-9 text-right">${Math.round(item.confidence * 100)}%</span>
        </div>
    ` : '';

    return `
        <div class="p-4 rounded-lg ${statusCardClass}">
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

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab-target');

            // Update button styles
            tabButtons.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-current', 'false');
            });

            btn.classList.add('active');
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
            if (wrapper) wrapper.classList.remove('md:ml-64');

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
    if (payload.policy_name) text += `Governing Policy: ${payload.policy_name}\n`;
    text += `Alignment Score: ${payload.spirit_score !== null && payload.spirit_score !== undefined ? payload.spirit_score.toFixed(1) + '/10' : 'N/A'}\n`;
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
