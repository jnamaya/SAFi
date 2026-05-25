import * as ui from '../ui.js';
import * as api from '../../core/api.js';

// Store the profile data in memory
let userProfileData = {};
let isProfileFetched = false;

// All chip-based sections (order = display order in the 2-col grid)
const CHIP_SECTIONS = [
    {
        key: 'profession',
        title: 'My Profession',
        subtitle: 'What do you do?',
    },
    {
        key: 'location',
        title: 'My Location',
        subtitle: 'Where are you based?',
    },
    {
        key: 'stated_values',
        title: 'My Values',
        subtitle: 'What defines your ethics?',
    },
    {
        key: 'interests',
        title: 'My Interests',
        subtitle: 'Topics you enjoy?',
    },
    {
        key: 'stated_goals',
        title: 'My Goals',
        subtitle: 'What are you aiming for?',
    },
    {
        key: 'key_facts',
        title: 'Key Facts',
        subtitle: 'Other context about your life',
    },
];

// Quick-add suggestions per section
const SUGGESTIONS = {
    profession: [
        'Software Engineer', 'Teacher', 'Entrepreneur', 'Designer',
        'Product Manager', 'Student', 'Healthcare Worker', 'Researcher',
        'Lawyer', 'Marketer',
    ],
    location: [
        'New York', 'San Francisco', 'Remote', 'Europe',
        'Latin America', 'Asia', 'Austin TX', 'London', 'Miami',
    ],
    stated_values: [
        'Honesty', 'Creativity', 'Family First', 'Sustainability',
        'Freedom', 'Logic', 'Empathy', 'Hard Work', 'Tradition',
    ],
    interests: [
        'Technology', 'Hiking', 'History', 'Cooking',
        'Philosophy', 'Sci-Fi', 'Finance', 'Art', 'Coding',
    ],
    stated_goals: [
        'Learn a language', 'Build a business', 'Improve fitness',
        'Read more books', 'Save money', 'Travel more',
    ],
    key_facts: [
        'Married', 'Single', 'Have kids', 'Own a dog',
        'Live in the city', 'Digital Nomad', 'Work from home',
    ],
};

// Sections counted toward completeness (about_me counts as one)
const COMPLETENESS_KEYS = ['about_me', ...CHIP_SECTIONS.map(s => s.key)];

/**
 * Renders the "My Profile" tab.
 * Fetches data from the API on first open; subsequent opens use cached data.
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
        const raw = await api.fetchUserProfileMemory();
        isProfileFetched = true;

        userProfileData = raw || {};

        // Migrate legacy key: family_status → key_facts
        if (!userProfileData.key_facts && userProfileData.family_status) {
            userProfileData.key_facts = userProfileData.family_status;
            delete userProfileData.family_status;
        }

        // Ensure all chip arrays exist
        CHIP_SECTIONS.forEach(({ key }) => {
            userProfileData[key] = Array.isArray(userProfileData[key]) ? userProfileData[key] : [];
        });

        // Ensure about_me is a string
        if (typeof userProfileData.about_me !== 'string') {
            userProfileData.about_me = '';
        }

        _buildProfileUI(container);

    } catch (error) {
        container.innerHTML = `<p class="text-red-500">Error loading profile: ${error.message}</p>`;
    }
}

// ---------------------------------------------------------------------------
// Completeness
// ---------------------------------------------------------------------------

function _computeCompleteness() {
    let filled = 0;
    for (const key of COMPLETENESS_KEYS) {
        const val = userProfileData[key];
        if (key === 'about_me') {
            if (typeof val === 'string' && val.trim().length > 0) filled++;
        } else {
            if (Array.isArray(val) && val.length > 0) filled++;
        }
    }
    return { filled, total: COMPLETENESS_KEYS.length };
}

function _buildCompletenessBar() {
    const { filled, total } = _computeCompleteness();
    const pct = Math.round((filled / total) * 100);

    let colorClass = 'bg-red-400';
    let label = 'Just getting started';
    if (pct >= 80) { colorClass = 'bg-green-500'; label = 'Great profile!'; }
    else if (pct >= 50) { colorClass = 'bg-yellow-400'; label = 'Looking good'; }
    else if (pct >= 25) { colorClass = 'bg-orange-400'; label = 'Keep going'; }

    return `
        <div class="mb-6 p-4 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-900">
            <div class="flex items-center justify-between mb-2">
                <span class="text-sm font-medium text-neutral-700 dark:text-neutral-300">Profile completeness</span>
                <span class="text-sm font-semibold text-neutral-500 dark:text-neutral-400">${filled} / ${total} sections · ${label}</span>
            </div>
            <div class="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                <div class="${colorClass} h-2 rounded-full transition-all duration-500" style="width: ${pct}%"></div>
            </div>
            <p class="text-xs text-neutral-400 dark:text-neutral-500 mt-2">
                The more you fill in, the more SAFi personalizes every response to you.
            </p>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Main UI builder
// ---------------------------------------------------------------------------

function _buildProfileUI(container) {
    const gridSections   = CHIP_SECTIONS.filter(s => !s.fullWidth);
    const inlineSections = CHIP_SECTIONS.filter(s =>  s.fullWidth);

    container.innerHTML = `
        <div class="mb-5">
            <h3 class="text-xl font-semibold">My Profile</h3>
            <p class="text-neutral-500 dark:text-neutral-400 text-sm mt-1">
                Tell SAFi about yourself. Everything here shapes how it responds to you.
            </p>
        </div>

        ${_buildCompletenessBar()}

        <!-- About Me — full width free text -->
        ${_buildAboutMeSection()}

        <!-- Full-width chip sections (e.g. Communication Style) -->
        ${inlineSections.map(s => `
            <div class="mb-6">${_buildProfileSection(s.key, s.title, s.subtitle)}</div>
        `).join('')}

        <!-- 2-column chip sections -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            ${gridSections.map(s => _buildProfileSection(s.key, s.title, s.subtitle)).join('')}
        </div>

        <div class="mt-8 flex justify-end pt-4 border-t border-neutral-200 dark:border-neutral-700">
            <button id="save-my-profile-btn"
                class="px-5 py-2 rounded-lg font-semibold bg-black text-white hover:bg-gray-800 text-sm transition-colors shadow-sm">
                Save Changes
            </button>
        </div>
    `;

    _attachProfileEventListeners(container);
}

// ---------------------------------------------------------------------------
// About Me textarea section
// ---------------------------------------------------------------------------

function _buildAboutMeSection() {
    const val = userProfileData.about_me || '';
    return `
        <div class="profile-section-container shadow-sm mb-6">
            <div class="flex items-center gap-2 mb-3 border-b border-gray-100 dark:border-gray-700 pb-2">
                <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">About Me</h4>
                <span class="text-xs text-neutral-400 font-normal ml-auto">In your own words</span>
            </div>
            <textarea
                id="profile-about-me"
                rows="3"
                maxlength="500"
                placeholder="e.g. I'm a product manager at a fintech startup in Miami. I like concise, practical answers and I'm always working on a side project."
                class="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-sm text-neutral-800 dark:text-neutral-200 resize-none focus:outline-none focus:ring-2 focus:ring-green-500 placeholder-neutral-400"
            >${DOMPurify.sanitize(val)}</textarea>
            <div class="text-right text-xs text-neutral-400 mt-1">
                <span id="about-me-char-count">${val.length}</span> / 500
            </div>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Chip section builder
// ---------------------------------------------------------------------------

function _buildProfileSection(key, title, subtitle) {
    const items = userProfileData[key] || [];

    const availableSuggestions = (SUGGESTIONS[key] || [])
        .filter(s => !items.map(i => i.toLowerCase()).includes(s.toLowerCase()))
        .sort(() => 0.5 - Math.random())
        .slice(0, 4);

    const chipsHtml = items.length > 0
        ? items.map((item, index) => `
            <div class="profile-chip">
                <span>${DOMPurify.sanitize(item)}</span>
                <button class="chip-delete-btn" data-key="${key}" data-index="${index}" title="Remove">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
          `).join('')
        : `<div class="empty-section-state">Nothing here yet — add one or pick a suggestion.</div>`;

    const suggestionsHtml = availableSuggestions.length > 0
        ? `
            <div class="suggestions-area">
                <div class="suggestion-label">Quick Add:</div>
                <div>
                    ${availableSuggestions.map(s =>
                        `<button class="suggestion-pill" data-key="${key}" data-val="${s}">+ ${s}</button>`
                    ).join('')}
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
                           placeholder="Type and press Enter…">
                    <button data-key="${key}"
                        class="add-profile-item-btn shrink-0 px-3 py-2 rounded-lg font-medium bg-neutral-800 text-white hover:bg-black dark:bg-neutral-700 dark:hover:bg-neutral-600 text-sm transition-colors">
                        Add
                    </button>
                </div>
                ${suggestionsHtml}
            </div>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

function _attachProfileEventListeners(container) {
    // 1. "Add" button
    container.querySelectorAll('.add-profile-item-btn').forEach(btn => {
        btn.addEventListener('click', () => _handleAddItem(btn.dataset.key, container));
    });

    // 2. Enter key in chip inputs
    container.querySelectorAll('input[id^="profile-input-"]').forEach(input => {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                _handleAddItem(input.id.replace('profile-input-', ''), container);
            }
        });
    });

    // 3. Delete chip
    container.querySelectorAll('.chip-container').forEach(list => {
        list.addEventListener('click', (e) => {
            const deleteBtn = e.target.closest('.chip-delete-btn');
            if (!deleteBtn) return;
            const { key, index } = deleteBtn.dataset;
            if (userProfileData[key]) {
                userProfileData[key].splice(parseInt(index), 1);
                _buildProfileUI(container);
            }
        });
    });

    // 4. Suggestion pill
    container.querySelectorAll('.suggestion-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const { key, val } = pill.dataset;
            if (!userProfileData[key]) userProfileData[key] = [];
            userProfileData[key].push(val);
            _buildProfileUI(container);
        });
    });

    // 5. About Me character counter
    const aboutMeTextarea = document.getElementById('profile-about-me');
    const charCount = document.getElementById('about-me-char-count');
    if (aboutMeTextarea && charCount) {
        aboutMeTextarea.addEventListener('input', () => {
            charCount.textContent = aboutMeTextarea.value.length;
        });
    }

    // 6. Save
    const saveBtn = document.getElementById('save-my-profile-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            // Capture About Me textarea value before saving
            const aboutMeEl = document.getElementById('profile-about-me');
            if (aboutMeEl) userProfileData.about_me = aboutMeEl.value.trim();

            const originalText = saveBtn.textContent;
            saveBtn.textContent = 'Saving…';
            saveBtn.disabled = true;

            try {
                // Clean chip arrays (remove empty strings)
                for (const key in userProfileData) {
                    if (Array.isArray(userProfileData[key])) {
                        userProfileData[key] = userProfileData[key]
                            .filter(item => item && String(item).trim() !== '');
                    }
                }

                await api.updateUserProfileMemory(userProfileData);
                ui.showToast('Profile saved!', 'success');

                // Re-render to update the completeness bar
                _buildProfileUI(container);
            } catch (error) {
                ui.showToast(`Error saving: ${error.message}`, 'error');
            } finally {
                saveBtn.textContent = originalText;
                saveBtn.disabled = false;
            }
        });
    }
}

// ---------------------------------------------------------------------------
// Add item helper
// ---------------------------------------------------------------------------

function _handleAddItem(key, container) {
    const input = document.getElementById(`profile-input-${key}`);
    if (!input) return;

    const value = input.value.trim();
    if (!value) return;

    if (!userProfileData[key]) userProfileData[key] = [];
    userProfileData[key].push(value);

    input.value = '';
    _buildProfileUI(container);

    // Refocus the same input after re-render for rapid entry
    setTimeout(() => {
        document.getElementById(`profile-input-${key}`)?.focus();
    }, 0);
}
