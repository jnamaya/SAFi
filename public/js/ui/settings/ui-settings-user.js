import * as ui from '../ui.js';
import * as api from '../../core/api.js';

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
            <button id="save-my-profile-btn" class="px-5 py-2 rounded-lg font-semibold bg-black text-white hover:bg-gray-800 text-sm transition-colors shadow-sm">
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
            if (nextInput) nextInput.focus();
        }, 0);
    }
}
