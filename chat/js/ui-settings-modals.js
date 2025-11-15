// ui-settings-modals.js

import * as ui from './ui.js'; 
import { getAvatarForProfile } from './ui-auth-sidebar.js'; 

// External libraries (must be available globally or imported)
// NOTE: marked, hljs, DOMPurify are assumed to be available globally from the original file's context.

// --- SETTINGS RENDERING (CONTROL PANEL) ---

/**
 * Sets up event listeners for the Control Panel navigation tabs.
 */
export function setupControlPanelTabs() {
    ui._ensureElements();
    const tabs = [ui.elements.cpNavProfile, ui.elements.cpNavModels, ui.elements.cpNavDashboard, ui.elements.cpNavAppSettings];
    const panels = [ui.elements.cpTabProfile, ui.elements.cpTabModels, ui.elements.cpTabDashboard, ui.elements.cpTabAppSettings];
    
    tabs.forEach((tab, index) => {
        if (!tab) return;
        tab.addEventListener('click', () => {
            tabs.forEach(t => t?.classList.remove('active'));
            tab.classList.add('active');
            
            panels.forEach(p => p?.classList.add('hidden'));
            if (panels[index]) {
                panels[index].classList.remove('hidden');
            }

            if (tab === ui.elements.cpNavDashboard) {
                renderSettingsDashboardTab();
            }
        });
    });
    
    if (tabs[0]) {
      tabs[0].click();
    }
}

/**
 * Renders the Profile selection tab in the Control Panel.
 */
export function renderSettingsProfileTab(profiles, activeProfileKey, onProfileChange) {
  ui._ensureElements();
    const container = ui.elements.cpTabProfile;
    if (!container) return;
    
    const viewDetailsHandler = (key) => {
        const profile = profiles.find(p => p.key === key);
        if (profile) {
            renderProfileDetailsModal(profile); 
            ui.showModal('profile'); 
        }
    };
    
    // ... (HTML rendering for profile selection) ...
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose a Persona</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Select a profile to define the AI's values, worldview, and rules. The chat will reload to apply the change.</p>
        <div class="space-y-4" role="radiogroup">
            ${profiles.map(profile => {
                const avatarUrl = getAvatarForProfile(profile.name);
                const description = profile.description_short || profile.description || '';
                return `
                <div class="p-4 border ${profile.key === activeProfileKey ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg transition-colors">
                    <label class="flex items-center justify-between cursor-pointer">
                        <div class="flex items-center gap-3">
                            <img src="${avatarUrl}" alt="${profile.name} Avatar" class="w-8 h-8 rounded-lg">
                            <span class="font-semibold text-base text-neutral-800 dark:text-neutral-200">${profile.name}</span>
                        </div>
                        <input type="radio" name="ethical-profile" value="${profile.key}" class="form-radio text-green-600 focus:ring-green-500" ${profile.key === activeProfileKey ? 'checked' : ''}>
                    </label>
                    <p class="text-sm text-neutral-600 dark:text-neutral-300 mt-2">${description}</p>
                    <div class="mt-3">
                        <button data-key="${profile.key}" class="view-profile-details-btn text-sm font-medium text-green-600 dark:text-green-500 hover:underline">
                            View Details
                        </button>
                    </div>
                </div>
            `}).join('')}
        </div>
    `;

    // ... (Event listeners for radio buttons and details buttons) ...
    container.querySelectorAll('input[name="ethical-profile"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            onProfileChange(e.target.value);
            container.querySelectorAll('.p-4.border').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('.p-4.border').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('.p-4.border').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });
    
    container.querySelectorAll('.view-profile-details-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            viewDetailsHandler(btn.dataset.key);
        });
    });
}

/**
 * Renders the AI Model selection tab in the Control Panel.
 */
export function renderSettingsModelsTab(availableModels, user, onModelsSave) {
    ui._ensureElements();
    const container = ui.elements.cpTabModels;
    if (!container) return;
    
    const createSelect = (id, label, selectedValue) => `
        <div>
            <label for="${id}" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">${label}</label>
            <select id="${id}" class="settings-modal-select">
                ${availableModels.map(model => `
                    <option value="${model}" ${model === selectedValue ? 'selected' : ''}>${model}</option>
                `).join('')}
            </select>
        </div>
    `;

    // ... (HTML rendering for model selection) ...
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose AI Models</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Assign a specific AI model to each of the three faculties. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'Intellect (Generation)', user.intellect_model)}
            ${createSelect('model-select-will', 'Will (Gatekeeping)', user.will_model)}
            ${createSelect('model-select-conscience', 'Conscience (Auditing)', user.conscience_model)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    document.getElementById('save-models-btn').addEventListener('click', () => {
        const newModels = {
            intellect_model: document.getElementById('model-select-intellect').value,
            will_model: document.getElementById('model-select-will').value,
            conscience_model: document.getElementById('model-select-conscience').value,
        };
        onModelsSave(newModels);
    });
}

/**
 * Renders the embedded dashboard iframe in the Control Panel.
 */
export function renderSettingsDashboardTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabDashboard;
    if (!container) return;

    if (container.querySelector('iframe')) return;

    container.innerHTML = ''; 

    const headerDiv = document.createElement('div');
    headerDiv.className = "p-6 shrink-0";
    headerDiv.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Trace & Analyze</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-0 text-sm">Analyze ethical alignment and trace decisions across all conversations.</p>
    `;
    
    const iframeContainer = document.createElement('div');
    iframeContainer.className = "w-full h-[1024px] overflow-hidden";

    const iframe = document.createElement('iframe');
    iframe.src = "https://dashboard.selfalignmentframework.com/?embed=true";
    iframe.className = "w-full h-full rounded-lg"; 
    iframe.title = "SAFi Dashboard";
    // FIX: Added 'allow-downloads' to enable file downloads from the iframe source.
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-downloads";
    
    iframeContainer.appendChild(iframe);

    container.appendChild(headerDiv);
    container.appendChild(iframeContainer);
}

/**
 * Renders the App Settings tab (Theme, Logout, Delete Account).
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

    // ... (HTML rendering for app settings) ...
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">App Settings</h3>
        
        <div class_="space-y-4">
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

    // ... (Event listeners) ...
    container.querySelectorAll('input[name="theme-select"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const newTheme = e.target.value;
            onThemeChange(newTheme);
            
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

// --- CONSCIENCE MODAL RENDERING ---

/**
 * Sets up the content for the Conscience (Ethical Reasoning) modal.
 */
export function setupConscienceModalContent(payload) {
    ui._ensureElements();
    const container = ui.elements.conscienceDetails;
    if (!container) return;
    container.innerHTML = ''; 

    container.insertAdjacentHTML('beforeend', renderIntro(payload));
    container.insertAdjacentHTML('beforeend', renderScoreAndTrend(payload));
    container.insertAdjacentHTML('beforeend', renderLedger(payload.ledger));
    
    container.querySelectorAll('.expand-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const reason = btn.parentElement.querySelector('.reason-text');
            const isTruncated = reason.classList.contains('truncated');
            reason.classList.toggle('truncated');
            btn.textContent = isTruncated ? 'Show Less' : 'Show More';
        });
    });

    const copyBtn = document.getElementById('copy-audit-btn');
    if (copyBtn) {
        const newCopyBtn = copyBtn.cloneNode(true);
        copyBtn.parentNode.replaceChild(newCopyBtn, copyBtn);
        newCopyBtn.addEventListener('click', () => copyAuditToClipboard(payload));
    }
}

function renderIntro(payload) {
    const profileName = payload.profile ? `the <strong>${payload.profile}</strong>` : 'the current';
    return `<p class="text-base text-neutral-600 dark:text-neutral-300 mb-6">This response was shaped by ${profileName} ethical profile. Here’s a breakdown of the reasoning:</p>`;
}

function renderScoreAndTrend(payload) {
    if (payload.spirit_score === null || payload.spirit_score === undefined) return '';

    const score = Math.max(0, Math.min(10, payload.spirit_score));
    const circumference = 50 * 2 * Math.PI;
    const offset = circumference - (score / 10) * circumference;

    const getScoreColor = (s) => {
        if (s >= 8) return 'text-green-500';
        if (s >= 5) return 'text-yellow-500';
        return 'text-red-500';
    };
    
    const colorClass = getScoreColor(score);

    const radialGauge = `
        <div class="relative flex flex-col items-center justify-center">
            <svg class="w-32 h-32 transform -rotate-90">
                <circle class="text-neutral-200 dark:text-neutral-700" stroke-width="8" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
                <circle class="${colorClass.replace('text-', 'stroke-')}" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
            </svg>
            <div class="absolute flex flex-col items-center">
                 <span class="text-3xl font-bold ${colorClass}">${score.toFixed(1)}</span>
                 <span class="text-xs text-neutral-500 dark:text-neutral-400">/ 10</span>
            </div>
        </div>
        <h4 class="font-semibold mt-2 text-center">Alignment Score</h4>
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center max-w-[180px]">Reflects alignment with the active value set.</p>
    `;

    const scores = (payload.spirit_scores_history || []).filter(s => s !== null && s !== undefined).slice(-10);
    let sparkline = '<div class="flex-1 flex items-center justify-center text-sm text-neutral-400">Not enough data for trend.</div>';

    if (scores.length > 1) {
        const width = 200, height = 60, padding = 5;
        const maxScore = 10, minScore = 0;
        const range = maxScore - minScore;
        const points = scores.map((s, i) => {
            const x = (i / (scores.length - 1)) * (width - 2 * padding) + padding;
            const y = height - padding - ((s - minScore) / range) * (height - 2 * padding);
            return `${x},${y}`;
        }).join(' ');

        const lastPoint = points.split(' ').pop().split(',');
        sparkline = `
            <div class="flex-1 pl-4">
                <h4 class="font-semibold mb-2 text-center">Alignment Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <polyline fill="none" class="stroke-green-500" stroke-width="2" points="${points}" />
                    <circle fill="${getScoreColor(scores[scores.length-1]).replace('text-','fill-')}" class="stroke-white dark:stroke-neutral-800" r="3" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center">Recent score history</p>
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 sm:grid-cols-2 gap-6 items-center bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4 mb-6">${radialGauge}${sparkline}</div>`;
}

function renderLedger(ledger) {
    if (!ledger || ledger.length === 0) {
        return '<div class="text-sm text-center text-neutral-500 py-4">No specific values were engaged for this response.</div>';
    }

    const groups = {
        upholds: ledger.filter(r => r.score > 0),
        conflicts: ledger.filter(r => r.score < 0),
        neutral: ledger.filter(r => r.score === 0),
    };

    for (const key in groups) {
        groups[key].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    }

    const groupConfig = {
        upholds: { title: 'Upholds', icon: 'M5 13l4 4L19 7', color: 'green' },
        conflicts: { title: 'Conflicts', icon: 'M6 18L18 6M6 6l12 12', color: 'red' },
        neutral: { title: 'Neutral', icon: 'M18 12H6', color: 'neutral' },
    };

    let html = '';
    for (const key of ['upholds', 'conflicts', 'neutral']) {
        if (groups[key].length > 0) {
            const config = groupConfig[key];
            html += `
                <div class="flex items-center gap-3 my-4">
                    <span class="p-1.5 bg-${config.color}-100 dark:bg-${config.color}-900/40 rounded-full">
                        <svg class="w-5 h-5 text-${config.color}-600 dark:text-${config.color}-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${config.icon}"></path></svg>
                    </span>
                    <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${config.title} (${groups[key].length})</h4>
                    <div class="flex-1 h-px bg-neutral-200 dark:bg-neutral-700"></div>
                </div>
                <div class="space-y-3">
                    ${groups[key].map(renderLedgerItem).join('')}
                </div>
            `;
        }
    }
    return html;
}

function renderLedgerItem(item) {
    const reasonHtml = DOMPurify.sanitize(String(item.reason || ''));
    const maxLength = 120;
    const isLong = reasonHtml.length > maxLength;
    
    const confidenceDisplayHtml = item.confidence ? `
        <div class="flex items-center gap-2 w-full sm:w-auto sm:min-w-[160px]">
            <span class="text-xs font-medium text-neutral-500 dark:text-neutral-400 hidden sm:inline">Confidence</span>
            <div class="h-1.5 flex-1 rounded-full bg-neutral-200 dark:bg-neutral-700">
                <div class="h-full rounded-full bg-green-500" style="width: ${item.confidence * 100}%"></div>
            </div>
            <span class="text-xs font-semibold text-neutral-600 dark:text-neutral-300 w-9 text-right">${Math.round(item.confidence * 100)}%</span>
        </div>
    ` : '';

    return `
        <div class="bg-white dark:bg-neutral-800/60 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700/80">
            <div class="flex items-start sm:items-center justify-between gap-4 mb-2 flex-col sm:flex-row">
                <div class="font-semibold text-neutral-800 dark:text-neutral-200">${item.value}</div>
                ${confidenceDisplayHtml}
            </div>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-600 dark:text-neutral-400">
                <div class="reason-text ${isLong ? 'truncated' : ''}">${reasonHtml}</div>
                ${isLong ? '<button class="expand-btn">Show More</button>' : ''}
            </div>
        </div>
    `;
}

function copyAuditToClipboard(payload) {
    let text = `SAFi Ethical Reasoning Audit\n`;
    text += `Profile: ${payload.profile || 'N/A'}\n`;
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

// --- START: PROFILE DETAILS MODAL ---

/**
 * Helper to create a formatted section for the profile details modal.
 */
function createModalSection(title, content) {
    if (!content) return '';
    
    let contentHtml = '';
    
    if (Array.isArray(content)) {
        if (content.length === 0) return '';
        contentHtml = '<ul class="space-y-1">' + content.map(item => `<li class="flex gap-2"><span class="opacity-60">»</span><span class="flex-1">${item}</span></li>`).join('') + '</ul>';
    } else {
        contentHtml = DOMPurify.sanitize(marked.parse(String(content ?? '')));
    }

    return `
        <div class="mb-6">
            <h3 class="text-lg font-semibold text-neutral-800 dark:text-neutral-200 mb-3">${title}</h3>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-700 dark:text-neutral-300">
                ${contentHtml}
            </div>
        </div>
    `;
}

/**
 * Creates the HTML for the "Values" section, including rubrics.
 */
function renderValuesSection(values) {
    if (!values || values.length === 0) return '';

    const valuesHtml = values.map(v => {
        let rubricHtml = '';
        if (v.rubric) {
            
            const scoringGuideHtml = (v.rubric.scoring_guide || []).map(g => {
                let scoreClasses = '';
                let scoreText = String(g.score); 

                if (g.score > 0) {
                    scoreClasses = 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
                    scoreText = `+${g.score.toFixed(1)}`; 
                } else if (g.score === 0) {
                    scoreClasses = 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-300';
                    scoreText = g.score.toFixed(1); 
                } else { 
                    scoreClasses = 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
                    scoreText = g.score.toFixed(1); 
                }
                
                const scoreChipHtml = `<span class="inline-block text-xs font-mono font-bold px-1.5 py-0.5 rounded ${scoreClasses}">${scoreText}</span>`;
                
                return `<li class="mb-1.5 flex items-start gap-2">
                            <div class="flex-shrink-0 w-12 text-center mt-0.5">${scoreChipHtml}</div>
                            <div class="flex-1">${g.descriptor}</div>
                        </li>`;
            }).join('');
            
            rubricHtml = `
                <div class="mt-3 pl-4 border-l-2 border-neutral-200 dark:border-neutral-700">
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300">Rubric Description:</h6>
                    <p class="italic text-sm">${v.rubric.description || 'N/A'}</p>
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300 mt-3">Scoring Guide:</h6>
                    <ul class="list-none pl-0 mt-2">${scoringGuideHtml}</ul>
                </div>
            `;
        }
        
        return `
            <div classa="mb-3">
                <h5 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${v.value}</h5>
                <p class="mb-1 text-sm">${v.definition || 'No definition provided.'}</p>
                ${rubricHtml}
            </div>
        `;
    }).join('<hr class="my-4 border-neutral-200 dark:border-neutral-700">');

    return `
        <div class="mb-6">
            <h3 class="text-lg font-semibold text-neutral-800 dark:text-neutral-200 mb-3">Values</h3>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-700 dark:text-neutral-300">
                ${valuesHtml}
            </div>
        </div>
    `;
}

/**
 * Populates the Profile Details modal with the given profile data.
 */
export function renderProfileDetailsModal(profile) {
    ui._ensureElements();
    const container = ui.elements.profileModalContent;
    if (!container) {
        console.error("Profile modal content area not found.");
        return;
    }

    const titleEl = document.getElementById('profile-modal-title');
    if (titleEl) titleEl.textContent = profile.name || 'Profile Details';

    container.innerHTML = '';
    
    container.insertAdjacentHTML('beforeend', createModalSection('Description', profile.description));
    container.insertAdjacentHTML('beforeend', createModalSection('Worldview', profile.worldview));
    container.insertAdjacentHTML('beforeend', createModalSection('Style', profile.style));
    container.insertAdjacentHTML('beforeend', renderValuesSection(profile.values));
    container.insertAdjacentHTML('beforeend', createModalSection('Rules (Non-Negotiable)', profile.will_rules));

    container.scrollTop = 0;
}