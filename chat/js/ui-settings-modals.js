// ui-settings-modals.js

import * as ui from './ui.js'; 
import { getAvatarForProfile } from './ui-auth-sidebar.js'; 
import * as api from './api.js';

// External libraries (must be available globally or imported)
// NOTE: marked, hljs, DOMPurify are assumed to be available globally from the original file's context.

// --- SETTINGS RENDERING (CONTROL PANEL) ---

/**
 * Sets up event listeners for the Control Panel navigation tabs.
 * This function is called once on application load.
 */
export function setupControlPanelTabs() {
    ui._ensureElements();
    
    // --- FIX: SET UP MODAL DELEGATED LISTENERS ---
    // We call this function *once* when the app initializes.
    // This attaches a single, persistent listener to the modal container
    // to prevent the "frozen links" bug.
    setupDelegatedModalListeners();
    // --- END FIX ---

    // --- FIX: Ensure the Profile Modal exists in the DOM ---
    ensureProfileModalExists();

    const tabs = [
        ui.elements.cpNavProfile, 
        ui.elements.cpNavModels, 
        ui.elements.cpNavMyProfile, // My Profile Tab
        ui.elements.cpNavDashboard, 
        ui.elements.cpNavAppSettings
    ];
    const panels = [
        ui.elements.cpTabProfile, 
        ui.elements.cpTabModels, 
        ui.elements.cpTabMyProfile, // My Profile Panel
        ui.elements.cpTabDashboard, 
        ui.elements.cpTabAppSettings
    ];
    
    tabs.forEach((tab, index) => {
        if (!tab) return;
        tab.addEventListener('click', () => {
            // Handle tab highlighting
            tabs.forEach(t => t?.classList.remove('active'));
            tab.classList.add('active');
            
            // Handle panel visibility
            panels.forEach(p => p?.classList.add('hidden'));
            if (panels[index]) {
                panels[index].classList.remove('hidden');
            }

            // Lazy-load dashboard
            if (tab === ui.elements.cpNavDashboard) {
                renderSettingsDashboardTab();
            }
            // Lazy-load user profile
            if (tab === ui.elements.cpNavMyProfile) {
                renderSettingsMyProfileTab(); 
            }
        });
    });
    
    // Activate the first tab by default
    if (tabs[0]) {
      tabs[0].click();
    }
}

// --- FIX: NEW FUNCTION FOR ONE-TIME LISTENERS ---
/**
 * Attaches persistent, delegated event listeners to modal containers.
 * This runs ONLY ONCE on app load to prevent duplicate listeners.
 */
function setupDelegatedModalListeners() {
    // --- "Show More" logic for Conscience Modal ---
    const conscienceContainer = ui.elements.conscienceDetails;
    if (conscienceContainer) {
        conscienceContainer.addEventListener('click', function(event) {
            // This single listener handles all "Show More" clicks inside
            // the conscience modal, even on dynamic content.
            if (event.target.classList.contains('expand-btn')) {
                const reasonText = event.target.previousElementSibling;
                if (reasonText && reasonText.classList.contains('reason-text')) {
                    const isTruncated = reasonText.classList.contains('truncated');
                    reasonText.classList.toggle('truncated');
                    event.target.textContent = isTruncated ? 'Show Less' : 'Show More';
                }
            }
        });
    }
}

/**
 * INJECTS the Profile Details Modal HTML if it is missing.
 * This prevents the "Profile modal content area not found" error.
 */
function ensureProfileModalExists() {
    if (document.getElementById('profile-details-modal')) return;

    console.log('Injecting missing Profile Details Modal...');

    const modalHtml = `
    <div id="profile-details-modal" class="fixed inset-0 z-50 hidden" aria-labelledby="modal-title" role="dialog" aria-modal="true">
        <!-- Backdrop -->
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-black/80 transition-opacity" aria-hidden="true"></div>
        
        <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
            <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
                <div class="relative transform overflow-hidden rounded-lg bg-white dark:bg-neutral-900 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-2xl border border-neutral-200 dark:border-neutral-800">
                    
                    <!-- Header -->
                    <div class="flex items-center justify-between px-4 py-3 border-b border-neutral-200 dark:border-neutral-800">
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white" id="profile-modal-title">Profile Details</h3>
                        <button type="button" id="close-profile-modal" class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300 p-1 rounded-md hover:bg-gray-100 dark:hover:bg-neutral-800 transition-colors">
                            <span class="sr-only">Close</span>
                            <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>

                    <!-- Content -->
                    <div id="profile-details-content" class="px-6 py-4 max-h-[70vh] overflow-y-auto custom-scrollbar bg-white dark:bg-neutral-900">
                        <!-- Dynamic Content -->
                    </div>

                    <!-- Footer -->
                    <div class="bg-gray-50 dark:bg-neutral-950 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6 border-t border-neutral-200 dark:border-neutral-800">
                        <button type="button" id="done-profile-modal" class="inline-flex w-full justify-center rounded-md bg-green-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 sm:ml-3 sm:w-auto transition-colors">Done</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // CRITICAL: Manually update the UI elements reference
    // This fixes the "Cannot read properties of null (reading 'classList')" error in ui.js
    ui.elements.profileModal = document.getElementById('profile-details-modal');
    ui.elements.profileModalContent = document.getElementById('profile-details-content');
    
    // Re-attach close listeners since this is a new element
    const closeBtn = document.getElementById('close-profile-modal');
    const doneBtn = document.getElementById('done-profile-modal');

    if (closeBtn) closeBtn.addEventListener('click', ui.closeModal);
    if (doneBtn) doneBtn.addEventListener('click', ui.closeModal);
}
// --- END FIX ---


/**
 * Renders the Profile selection tab in the Control Panel.
 * @param {Array} profiles - List of available profile objects
 * @param {string} activeProfileKey - The key of the currently active profile
 * @param {Function} onProfileChange - Callback function when a profile is selected
 */
export function renderSettingsProfileTab(profiles, activeProfileKey, onProfileChange) {
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
        <h3 class="text-xl font-semibold mb-4">Choose a Persona</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Select a profile to define the AI's values, worldview, and rules. The chat will reload to apply the change.</p>
        <div class="space-y-4" role="radiogroup">
            ${profiles.map(profile => {
                const avatarUrl = getAvatarForProfile(profile.name);
                const description = profile.description_short || profile.description || '';
                return `
                <div class="p-4 border ${profile.key === activeProfileKey ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg transition-colors relative group">
                    <label class="flex items-center justify-between cursor-pointer relative z-0">
                        <div class="flex items-center gap-3">
                            <img src="${avatarUrl}" alt="${profile.name} Avatar" class="w-8 h-8 rounded-lg">
                            <span class="font-semibold text-base text-neutral-800 dark:text-neutral-200">${profile.name}</span>
                        </div>
                        <input type="radio" name="ethical-profile" value="${profile.key}" class="form-radio text-green-600 focus:ring-green-500" ${profile.key === activeProfileKey ? 'checked' : ''}>
                    </label>
                    <p class="text-sm text-neutral-600 dark:text-neutral-300 mt-2 relative z-0">${description}</p>
                    
                    <!-- FIX: Added relative positioning and z-index to ensure button sits on top -->
                    <div class="mt-3 relative z-10">
                        <button type="button" data-key="${profile.key}" class="view-profile-details-btn text-sm font-medium text-green-600 dark:text-green-500 hover:underline focus:outline-none px-1 py-0.5 rounded hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors">
                            View Details
                        </button>
                    </div>
                </div>
            `}).join('')}
        </div>
    `;

    // Attach event listeners for radio buttons
    container.querySelectorAll('input[name="ethical-profile"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            onProfileChange(e.target.value);
            // Update styles to show selection
            container.querySelectorAll('.p-4.border').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('.p-4.border').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('.p-4.border').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });
    
    // Attach event listeners for "View Details" buttons
    // FIX: Used explicit 'onclick' to ensure we override any bubbling issues and guarantee execution
    container.querySelectorAll('.view-profile-details-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault(); 
            e.stopPropagation(); 
            viewDetailsHandler(btn.dataset.key);
        };
    });
}

/**
 * Renders the AI Model selection tab in the Control Panel.
 * @param {Array} availableModels - List of model name strings OR objects {id, label, categories}
 * @param {object} user - The current user object (to get selections)
 * @param {Function} onModelsSave - Callback function when save is clicked
 */
export function renderSettingsModelsTab(availableModels, user, onModelsSave) {
    ui._ensureElements();
    const container = ui.elements.cpTabModels;
    if (!container) return;
    
    // Filter the available models based on categories
    // We handle backward compatibility: if no 'categories' field exists, include it in both lists.
    const intellectModels = availableModels.filter(m => {
        if (typeof m === 'string') return true; // Legacy support
        return !m.categories || m.categories.includes('intellect');
    });

    const supportModels = availableModels.filter(m => {
        if (typeof m === 'string') return true; // Legacy support
        return !m.categories || m.categories.includes('support');
    });
    
    // Helper function to create a single <select> dropdown with a custom list of options
    const createSelect = (id, label, selectedValue, modelsList) => `
        <div>
            <label for="${id}" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">${label}</label>
            <select id="${id}" class="settings-modal-select">
                ${modelsList.map(model => {
                    // Handle both old format (string) and new format (object)
                    const modelId = model.id || model;
                    const modelLabel = model.label || model;

                    return `
                    <option value="${modelId}" ${modelId === selectedValue ? 'selected' : ''}>
                        ${modelLabel}
                    </option>
                    `;
                }).join('')}
            </select>
        </div>
    `;

    // Generate the HTML for the model selectors
    // We pass different filtered lists to each selector
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose AI Models</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Assign a specific AI model to each of the three faculties. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'Intellect (Generation)', user.intellect_model, intellectModels)}
            ${createSelect('model-select-will', 'Will (Gatekeeping)', user.will_model, supportModels)}
            ${createSelect('model-select-conscience', 'Conscience (Auditing)', user.conscience_model, supportModels)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    // Attach event listener for the save button
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
    iframe.src = "https://dash.selfalignmentframework.com/?embed=true";
    // UPDATED: Use absolute positioning to fill the flex container completely
    iframe.className = "absolute inset-0 w-full h-full rounded-lg border-0"; 
    iframe.title = "SAFi Dashboard";
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms allow-downloads";
    
    iframeContainer.appendChild(iframe);

    container.appendChild(headerDiv);
    container.appendChild(iframeContainer);
}

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

// --- START: "MY PROFILE" TAB (ENHANCED UX) ---

// Store the profile data in memory
let userProfileData = {};
let isProfileFetched = false;

// Static suggestions to help users who don't know what to type
const SUGGESTIONS = {
    stated_values: ['Honesty', 'Creativity', 'Family First', 'Sustainability', 'Freedom', 'Logic', 'Empathy', 'Hard Work', 'Tradition'],
    interests: ['Technology', 'Hiking', 'History', 'Cooking', 'Philosophy', 'Sci-Fi', 'Finance', 'Art', 'Coding'],
    stated_goals: ['Learn a language', 'Build a business', 'Improve fitness', 'Read more books', 'Save money', 'Travel to Japan'],
    family_status: ['Married', 'Single', 'Have 2 kids', 'Own a dog', 'Live in the city', 'Digital Nomad']
};

/**
 * Renders the "My Profile" tab (What SAFi Knows About Me).
 * Fetches data from the API on first click.
 */
export async function renderSettingsMyProfileTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabMyProfile;
    if (!container || isProfileFetched) return;

    container.innerHTML = `
        <div class="flex items-center justify-center h-32">
            <div class="thinking-spinner"></div>
        </div>
    `;

    try {
        userProfileData = await api.fetchUserProfileMemory();
        isProfileFetched = true;
        
        if (!userProfileData) userProfileData = {};

        // Ensure arrays
        ['stated_values', 'interests', 'family_status', 'stated_goals'].forEach(k => {
            userProfileData[k] = Array.isArray(userProfileData[k]) ? userProfileData[k] : [];
        });

        _buildProfileUI(container);
        
    } catch (error) {
        container.innerHTML = `<p class="text-red-500">Error loading profile: ${error.message}</p>`;
    }
}

/**
 * Helper to build the actual UI after data is fetched.
 * @param {HTMLElement} container - The panel to render into.
 */
function _buildProfileUI(container) {
    container.innerHTML = `
        <div class="mb-6">
            <div>
                <h3 class="text-xl font-semibold">My Profile</h3>
                <p class="text-neutral-500 dark:text-neutral-400 text-sm mt-1">
                    Teach the AI about you. It uses this context to personalize every response.
                </p>
            </div>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            ${_buildProfileSection('stated_values', 'My Values', 'What defines your ethics?', 'shield')}
            ${_buildProfileSection('interests', 'My Interests', 'Topics you enjoy?', 'heart')}
            ${_buildProfileSection('stated_goals', 'My Goals', 'What are you aiming for?', 'flag')}
            ${_buildProfileSection('family_status', 'Key Facts', 'Context about your life?', 'info')}
        </div>

        <div class="mt-8 flex justify-end pt-4 border-t border-neutral-200 dark:border-neutral-700">
            <button id="save-my-profile-btn" class="px-5 py-2 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors shadow-sm">
                Save Changes
            </button>
        </div>
    `;
    
    _attachProfileEventListeners(container);
}

/**
 * Helper to build one editable section with chips and suggestions.
 */
function _buildProfileSection(key, title, subtitle, iconType) {
    const items = userProfileData[key] || [];
    
    // Get 3 random suggestions that the user DOESN'T already have
    const availableSuggestions = (SUGGESTIONS[key] || [])
        .filter(s => !items.map(i => i.toLowerCase()).includes(s.toLowerCase()))
        .sort(() => 0.5 - Math.random())
        .slice(0, 4);

    const chipsHtml = items.length > 0 
        ? items.map((item, index) => `
            <div class="profile-chip">
                <span>${DOMPurify.sanitize(item)}</span>
                <button class="chip-delete-btn" data-key="${key}" data-index="${index}" title="Remove">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
            </div>
          `).join('')
        : `<div class="empty-section-state">Nothing here yet. Add a value or pick a suggestion!</div>`;

    const suggestionsHtml = availableSuggestions.length > 0 
        ? `
            <div class="suggestions-area">
                <div class="suggestion-label">Quick Add:</div>
                <div>
                    ${availableSuggestions.map(s => `<button class="suggestion-pill" data-key="${key}" data-val="${s}">+ ${s}</button>`).join('')}
                </div>
            </div>
          ` 
        : '';

    return `
        <div class="profile-section-container shadow-sm">
            <div class="flex items-center gap-2 mb-3 border-b border-gray-100 dark:border-gray-700 pb-2">
                <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${title}</h4>
                <span class="text-xs text-neutral-400 font-normal ml-auto">${subtitle}</span>
            </div>
            
            <div class="chip-container" id="chip-list-${key}">
                ${chipsHtml}
            </div>

            <div class="relative mt-2">
                <div class="flex gap-2">
                    <input type="text" id="profile-input-${key}" 
                           class="settings-modal-select flex-1 !py-2 !text-sm" 
                           placeholder="Type and press Enter...">
                    <button data-key="${key}" class="add-profile-item-btn shrink-0 px-3 py-2 rounded-lg font-medium bg-neutral-800 text-white hover:bg-black dark:bg-neutral-700 dark:hover:bg-neutral-600 text-sm transition-colors">
                        Add
                    </button>
                </div>
                ${suggestionsHtml}
            </div>
        </div>
    `;
}

/**
 * Attach listeners for Add, Delete, Suggestions, and Save
 */
function _attachProfileEventListeners(container) {
    // 1. Handle "Add" via Button
    container.querySelectorAll('.add-profile-item-btn').forEach(btn => {
        btn.addEventListener('click', () => _handleAddItem(btn.dataset.key, container));
    });

    // 2. Handle "Add" via Enter Key
    container.querySelectorAll('input[id^="profile-input-"]').forEach(input => {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const key = input.id.replace('profile-input-', '');
                _handleAddItem(key, container);
            }
        });
    });

    // 3. Handle "Delete" (Event delegation on container)
    container.querySelectorAll('.chip-container').forEach(list => {
        list.addEventListener('click', (e) => {
            const deleteBtn = e.target.closest('.chip-delete-btn');
            if (deleteBtn) {
                const key = deleteBtn.dataset.key;
                const index = parseInt(deleteBtn.dataset.index);
                
                // Remove item
                if (userProfileData[key]) {
                    userProfileData[key].splice(index, 1);
                    _buildProfileUI(container); // Re-render to update indices
                }
            }
        });
    });

    // 4. Handle "Suggestion Click"
    container.querySelectorAll('.suggestion-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const key = pill.dataset.key;
            const val = pill.dataset.val;
            
            if (!userProfileData[key]) userProfileData[key] = [];
            userProfileData[key].push(val);
            _buildProfileUI(container);
        });
    });
    
    // 5. Handle "Save"
    const saveBtn = document.getElementById('save-my-profile-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            const originalText = saveBtn.textContent;
            saveBtn.textContent = 'Saving...';
            saveBtn.disabled = true;
            
            try {
                // Clean data (remove empty strings)
                for (const key in userProfileData) {
                    if (Array.isArray(userProfileData[key])) {
                        userProfileData[key] = userProfileData[key].filter(item => item && String(item).trim() !== '');
                    }
                }
                
                await api.updateUserProfileMemory(userProfileData);
                ui.showToast('Profile updated successfully', 'success');
            } catch (error) {
                ui.showToast(`Error saving: ${error.message}`, 'error');
            } finally {
                saveBtn.textContent = originalText;
                saveBtn.disabled = false;
            }
        });
    }
}

function _handleAddItem(key, container) {
    const input = document.getElementById(`profile-input-${key}`);
    if (!input) return;
    
    const value = input.value.trim();
    if (value) {
        if (!userProfileData[key]) userProfileData[key] = [];
        userProfileData[key].push(value);
        
        // Clear input and focus back for rapid entry
        input.value = '';
        _buildProfileUI(container);
        
        // Refocus the input we just used
        setTimeout(() => {
            const nextInput = document.getElementById(`profile-input-${key}`);
            if(nextInput) nextInput.focus();
        }, 0);
    }
}

// --- END: NEW "MY PROFILE" TAB ---


// --- CONSCIENCE MODAL RENDERING (NEW DESIGN) ---

/**
 * Main function to build and inject the Conscience ("Ethical Reasoning") modal content.
 * @param {object} payload - The audit payload from the message
 */
export function setupConscienceModalContent(payload) {
    ui._ensureElements();
    const container = ui.elements.conscienceDetails;
    if (!container) return;
    container.innerHTML = ''; // Clear previous content

    const profileName = payload.profile ? `<strong>${payload.profile}</strong>` : 'the current';
    
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
            This response was shaped by the ${profileName} ethical profile. Here’s a breakdown of the reasoning:
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
            <h4 class="font-semibold mt-3 text-center text-gray-800 dark:text-gray-200">Alignment Score</h4>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 text-center max-w-[180px]">Reflects alignment with the active value set.</p>
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
                <h4 class="font-semibold mb-2 text-center md:text-left text-gray-800 dark:text-gray-200">Alignment Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <!-- Dotted lines at 10, 5, 0 -->
                    <line x1="0" y1="${padding}" x2="${width}" y2="${padding}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    <line x1="0" y1="${height - padding}" x2="${width}" y2="${height - padding}" class="stroke-gray-300 dark:stroke-gray-600" stroke-width="1" stroke-dasharray="2 2" />
                    
                    <!-- Data Line -->
                    <polyline fill="none" class="stroke-green-500" stroke-width="2" points="${points}" />
                    
                    <!-- Last point circle -->
                    <circle fill="currentColor" class="${getScoreColor(scores[scores.length-1])} stroke-white dark:stroke-gray-900" stroke-width="2" r="4" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1 text-center md:text-left">Recent score history (${scores.length} turns)</p>
                
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-2 text-center md:text-left">
                    <a href="#" id="view-full-dashboard-link" class="font-medium text-green-600 dark:text-green-500 hover:underline">
                        View Full Dashboard &rarr;
                    </a>
                </p>
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-6 items-center bg-gray-50 dark:bg-gray-900/50 rounded-lg p-5 mb-6 border border-gray-200 dark:border-gray-700">${radialGauge}${sparkline}</div>`;
}

/**
 * Renders a single tab button.
 * Mobile Optimization: Stacks icon above text and uses full width (flex-1).
 * Desktop: Keeps original side-by-side layout.
 * @param {string} key - 'upholds', 'conflicts', 'neutral'
 * @param {string} title - The button text
 * @param {number} count - The number for the badge
 * @param {boolean} isActive - Whether this tab is active
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
    // flex-1: makes them equal width
    // flex-col sm:flex-row: stacked on mobile, inline on desktop
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
 * @param {string} key 
 * @param {Array} items - The ledger items
 * @param {boolean} isActive - Whether this panel is visible
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
 * @param {object} item - A single ledger item
 * @param {string} key - 'upholds', 'conflicts', 'neutral'
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
                <div class="font-semibold text-gray-800 dark:text-gray-100">${item.value}</div>
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
 * This function is called *every time* the modal content is rendered.
 * @param {HTMLElement} container - The conscience modal content container.
 * @param {object} payload - The audit payload.
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
    // This is now handled by the persistent, delegated listener in
    // setupDelegatedModalListeners() to prevent the "frozen link" bug.

    // --- Copy button logic ---
    // We must re-attach this to the button inside the modal shell (which is in ui.js)
    // This finds the button in the *document* (outside the content container)
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
            ui.elements.chatView.classList.add('hidden');
            // 3. Show the control panel
            ui.elements.controlPanelView.classList.remove('hidden');
            // 4. Programmatically click the dashboard tab
            if (ui.elements.cpNavDashboard) {
                ui.elements.cpNavDashboard.click();
            }
        });
    }
}

/**
 * Copies a plain-text summary of the audit to the clipboard.
 * @param {object} payload - The audit payload
 */
function copyAuditToClipboard(payload) {
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
// --- END: CONSCIENCE MODAL RENDERING ---

// --- START: PROFILE DETAILS MODAL ---

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

    // Scroll to top of modal content
    container.scrollTop = 0;
}