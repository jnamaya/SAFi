import * as ui from '../ui.js';
import * as api from '../../core/api.js';
import { getAvatarForProfile } from '../ui-auth-sidebar.js'; // Need to check path adjustment? Yes, one level deeper.
import { openAgentWizard } from '../ui-agent-wizard.js';
import { ensureProfileModalExists } from './ui-settings-core.js'; // Circular dependency risk? Core depends on this for render? No, core imports render. This imports generic helper.

/**
 * Renders the Profile selection tab in the Control Panel.
 * @param {Array} profiles - List of available profile objects
 * @param {string} activeProfileKey - The key of the currently active profile
 * @param {Function} onProfileChange - Callback function when a profile is selected
 * @param {Object} currentUser - The current user object
 * @param {Array} availableModels - List of available AI models (for wizard)
 */
export function renderSettingsProfileTab(profiles, activeProfileKey, onProfileChange, currentUser, availableModels = []) {
    ui._ensureElements();
    const container = ui.elements.cpTabProfile;
    if (!container) return;

    // Handler to open the profile details modal
    const viewDetailsHandler = (key) => {
        // Double check modal exists before trying to render
        ensureProfileModalExists();

        // FIX: Use String() conversion to ensure we match "1" with 1 if types differ
        const profile = profiles.find(p => String(p.key) === String(key));
        if (profile) {
            renderProfileDetailsModal(profile);
            ui.showModal('profile');
        } else {
            console.error('Profile not found for key:', key);
        }
    };

    // Generate the HTML for the profile list
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Agents</h3>
        <p class="text-sm text-gray-400 mt-1 mb-6">Select an agent from the list below to start chatting. Switching agents will start a new conversation.</p>
        
        <!-- NEW: "Create New Agent" Button (Admins/Editors Only) -->
        ${(currentUser && ['admin', 'editor'].includes(currentUser.role)) ? `
        <div class="mb-6">
            <button id="btn-create-agent" class="w-full flex items-center justify-center gap-2 p-4 border-2 border-dashed border-gray-300 dark:border-neutral-700 rounded-xl hover:border-green-500 hover:bg-green-50 dark:hover:bg-green-900/20 transition-all group">
                <div class="p-2 bg-gray-100 dark:bg-neutral-800 rounded-full group-hover:bg-green-100 dark:group-hover:bg-green-800 transition-colors">
                    <svg class="w-6 h-6 text-gray-500 dark:text-gray-400 group-hover:text-green-600 dark:group-hover:text-green-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                    </svg>
                </div>
                <div class="text-left">
                    <h4 class="font-semibold text-gray-700 dark:text-gray-200 group-hover:text-green-700 dark:group-hover:text-green-300">Create an Agent</h4>
                    <p class="text-xs text-gray-500 dark:text-gray-400 group-hover:text-green-600/70">Create a unique agent with its unique values & rules</p>
                </div>
            </button>
        </div>
        ` : ''}
        
        <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-6">
            ${profiles.map(profile => {
        const avatarUrl = getAvatarForProfile(profile.name);
        const description = profile.description_short || profile.description || '';
        const isActive = profile.key === activeProfileKey;

        // Card Styling
        // Active: Green border, slight green tint
        const activeClasses = `border-green-500 bg-green-50/50 dark:bg-green-900/10 ring-2 ring-green-500 ring-offset-2 dark:ring-offset-neutral-900`;
        const inactiveClasses = `border-gray-200 dark:border-neutral-800 bg-white dark:bg-neutral-800 hover:border-green-300 dark:hover:border-green-700 hover:shadow-md`;

        return `
                <div class="group relative flex flex-col rounded-2xl border transition-all duration-200 ${isActive ? activeClasses : inactiveClasses}">
                    
                    <!-- Selection Logic (Hidden Radio) -->
                    <label class="absolute inset-0 z-0 cursor-pointer">
                        <input type="radio" name="ethical-profile" value="${profile.key}" class="sr-only" ${isActive ? 'checked' : ''}>
                    </label>

                    <!-- Active Indicator Badge -->
                    ${isActive ? `
                    <div class="absolute top-3 right-3 z-10 bg-green-500 text-white p-1 rounded-full shadow-sm">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    ` : ''}

                    <div class="p-6 flex flex-col items-center text-center flex-1 z-1 pointer-events-none">
                        <img src="${avatarUrl}" alt="${profile.name}" class="w-20 h-20 rounded-2xl shadow-sm object-cover mb-4 bg-gray-100 dark:bg-neutral-700">
                        <h3 class="font-bold text-lg text-gray-900 dark:text-white mb-2 line-clamp-1">${profile.name}</h3>
                        <p class="text-sm text-gray-500 dark:text-gray-400 line-clamp-3 leading-relaxed">${description}</p>
                    </div>

                    <!-- Actions Footer -->
                    <div class="mt-auto pt-4 pb-4 px-6 border-t border-gray-100 dark:border-neutral-700/50 flex justify-center gap-2 z-10 relative">
                        <button type="button" data-key="${profile.key}" class="view-profile-details-btn px-3 py-1.5 text-xs font-semibold text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-neutral-700/50 hover:bg-gray-200 dark:hover:bg-neutral-700 rounded-lg transition-colors">
                            Details
                        </button>
                        ${(profile.is_custom && currentUser && (currentUser.role === 'admin' || currentUser.id === profile.created_by)) ? `
                        <button type="button" data-key="${profile.key}" class="edit-agent-btn px-3 py-1.5 text-xs font-semibold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/30 rounded-lg transition-colors">
                            Edit
                        </button>
                        <button type="button" data-key="${profile.key}" class="delete-agent-btn px-3 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors">
                            Delete
                        </button>
                        ` : ''}
                    </div>
                </div>
            `}).join('')}
        </div>
    `;

    // Attach event listeners for radio buttons
    // Note: We listen on the container for capture or change events bubbling up
    container.querySelectorAll('input[name="ethical-profile"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const newProfileKey = e.target.value;
            onProfileChange(newProfileKey);
        });
    });

    // Attach event listeners for "View Details" buttons
    container.querySelectorAll('.view-profile-details-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            viewDetailsHandler(btn.dataset.key);
        };
    });

    // --- NEW: Attach listeners for "Edit Agent" buttons ---
    container.querySelectorAll('.edit-agent-btn').forEach(btn => {
        btn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const key = btn.dataset.key;

            // Show loading state on button
            const originalText = btn.innerHTML;
            btn.innerHTML = 'Loading...';
            btn.disabled = true;

            try {
                const res = await api.getAgent(key);
                if (res && res.ok && res.agent) {
                    openAgentWizard(res.agent, availableModels); // Updated to pass models
                } else {
                    ui.showToast("Failed to load agent details", "error");
                }
            } catch (err) {
                ui.showToast(`Error: ${err.message}`, "error");
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        };
    });

    // --- NEW: Attach listeners for "Delete Agent" buttons ---
    container.querySelectorAll('.delete-agent-btn').forEach(btn => {
        btn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const key = btn.dataset.key;

            if (confirm("Are you sure you want to permanently delete this agent?")) {
                const originalText = btn.innerHTML;
                btn.innerHTML = `<span class="thinking-spinner w-3 h-3 inline-block"></span>`;
                btn.disabled = true;

                try {
                    await api.deleteAgent(key);
                    ui.showToast("Agent deleted.", "success");
                    setTimeout(() => window.location.reload(), 1000);
                } catch (err) {
                    ui.showToast(`Error: ${err.message}`, "error");
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }
            }
        };
    });

    // --- NEW: Attach Event Listener for "Create New Agent" ---
    const createBtn = document.getElementById('btn-create-agent');
    if (createBtn) {
        createBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openAgentWizard(null, availableModels); // Updated to pass models
        });
    }
}

// --- PROFILE DETAILS MODAL HELPERS ---

/**
 * Helper to create a formatted HTML section for the profile details modal.
 * @param {string} title - The section title
 * @param {string | Array} content - The content (markdown string or list of strings)
 */
function createModalSection(title, content) {
    if (!content) return '';

    let contentHtml = '';

    if (Array.isArray(content)) {
        if (content.length === 0) return '';
        contentHtml = '<ul class="space-y-1">' + content.map(item => `<li class="flex gap-2"><span class="opacity-60">»</span><span class="flex-1">${item}</span></li>`).join('') + '</ul>';
    } else {
        // Use marked to parse markdown content
        // Assuming marked and DOMPurify are global as per original file comments
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
 * @param {Array} values - The list of value objects
 */
function renderValuesSection(values) {
    if (!values || values.length === 0) return '';

    const valuesHtml = values.map(v => {
        let rubricHtml = '';
        if (v.rubric) {

            // Handle both Object (standard) and Limit (custom) rubric formats
            let scoringGuide = [];
            let description = 'N/A';

            if (Array.isArray(v.rubric)) {
                // Custom Agent Format: rubric is the list, description is on the value
                scoringGuide = v.rubric;
                description = v.description || 'N/A';
            } else {
                // Standard Format: rubric is object
                scoringGuide = v.rubric.scoring_guide || [];
                description = v.rubric.description || 'N/A';
            }

            const scoringGuideHtml = scoringGuide.map(g => {
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

                // Handle both 'descriptor' (built-in) and 'criteria' (custom wizard) keys
                const text = g.descriptor || g.criteria || '';

                return `<li class="mb-1.5 flex items-start gap-2">
                            <div class="flex-shrink-0 w-12 text-center mt-0.5">${scoreChipHtml}</div>
                            <div class="flex-1">${text}</div>
                        </li>`;
            }).join('');

            rubricHtml = `
                <div class="mt-3 pl-4 border-l-2 border-neutral-200 dark:border-neutral-700">
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300">Rubric Description:</h6>
                    <p class="italic text-sm">${description}</p>
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300 mt-3">Scoring Guide:</h6>
                    <ul class="list-none pl-0 mt-2">${scoringGuideHtml}</ul>
                </div>
            `;
        }

        // Use v.value (ID) or fallback to v.name if value is missing (custom agent quirks)
        // Also use v.description as definition fallback for custom agents
        const valName = v.value || v.name || 'Unknown Value';
        const valDef = v.definition || v.description || 'No definition provided.';

        return `
            <div classa="mb-3">
                <h5 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${valName}</h5>
                <p class="mb-1 text-sm">${valDef}</p>
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
 * @param {object} profile - The full profile object
 */
export function renderProfileDetailsModal(profile) {
    ui._ensureElements();

    // FIX: Ensure modal exists in DOM before grabbing reference
    ensureProfileModalExists();

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

}
