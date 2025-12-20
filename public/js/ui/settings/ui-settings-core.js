import * as ui from '../ui.js';
import { renderSettingsDashboardTab } from './ui-settings-dashboard.js'; // Extracted separately or kept inline? Plan didn't specifying dashboard but it's small.
// Wait, plan didn't have dashboard. I should verify if I extract it or keep it.
// The plan listed 8 modules. Dashboard wasn't one of them explicitly, but it's part of the tabs.
// Looking at the code, renderSettingsDashboardTab is independent. I will add it to `ui-settings-core.js` or a new `ui-settings-dashboard.js`.
// Let's check `ui-settings-core.js` responsibility. It handles tabs.
// I'll make a decision to put Dashboard in `ui-settings-dashboard.js` to be clean, or just keep it in core if it's tiny.
// It creates an iframe. It's distinct. I'll create `ui-settings-dashboard.js`.

// Re-evaluating core imports based on what I will create.
// Core needs to import the render functions to call them in the switch/click handler.

import { renderSettingsOrganizationTab, setOrgCurrentUser } from './ui-settings-org.js';
import { renderSettingsProfileTab } from './ui-settings-agents.js';
import { renderSettingsModelsTab } from './ui-settings-models.js';
import { renderSettingsMyProfileTab } from './ui-settings-user.js';
import { renderSettingsGovernanceTab } from './ui-settings-governance.js';
import { renderSettingsAppTab } from './ui-settings-app.js';
// I'll add dashboard here to be safe and create the file later.
// Note: Imports might fail until files exist, but that's fine as long as I create them all before running.

let currentUser = null;

// NEW: Global state container for settings context
const settingsState = {
    profiles: [],
    activeProfileKey: null,
    availableModels: [],
    onProfileChange: null,
    currentTheme: 'system',
    onThemeChange: null,
    onLogout: null,
    onDeleteAccount: null,
    // Model handlers
    onSaveModels: null
};

export function updateCurrentUser(u) {
    currentUser = u;
    // Propagate to org module which needs it for member table
    setOrgCurrentUser(u);
}

/**
 * Updates the global settings state with data/callbacks from app.js.
 * This is required because ui-settings-core handles the navigation but app.js owns the data.
 */
export function updateSettingsState(newState) {
    Object.assign(settingsState, newState);
    // Also update local user reference if passed (redundant slightly but safe)
    if (newState.currentUser) {
        updateCurrentUser(newState.currentUser);
    }
}

/**
 * Sets up event listeners for the Control Panel navigation tabs.
 * This function is called once on application load.
 */
/**
 * Sets up event listeners for the Control Panel navigation tabs (Sidebar).
 * This function is called once on application load.
 */
export function setupControlPanelTabs() {
    ui._ensureElements();
    setupDelegatedModalListeners();
    ensureProfileModalExists();

    // Mobile Menu Toggle Logic
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    const mobileMenuBackdrop = document.getElementById('mobile-menu-backdrop');
    const mobileMenuClose = document.getElementById('close-mobile-menu');

    function toggleMobileMenu() {
        if (!mobileMenu || !mobileMenuBackdrop) return;
        if (mobileMenu.classList.contains('-translate-x-full')) {
            mobileMenu.classList.remove('-translate-x-full');
            mobileMenuBackdrop.classList.remove('hidden');
        } else {
            mobileMenu.classList.add('-translate-x-full');
            mobileMenuBackdrop.classList.add('hidden');
        }
    }

    if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', toggleMobileMenu);
    if (mobileMenuClose) mobileMenuClose.addEventListener('click', toggleMobileMenu);
    if (mobileMenuBackdrop) mobileMenuBackdrop.addEventListener('click', toggleMobileMenu);

    // Sidebar Navigation Logic
    const sidebarButtons = document.querySelectorAll('.sidebar-item');

    sidebarButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            if (!tabId) return;

            // 1. Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));

            // 1.5 Force Close Inline Wizard if open
            const wizardView = document.getElementById('agent-wizard-view');
            if (wizardView) {
                wizardView.classList.add('hidden');
                wizardView.classList.remove('flex');
            }
            const pwView = document.getElementById('policy-wizard-view');
            if (pwView) {
                pwView.classList.add('hidden');
                pwView.classList.remove('flex');
            }

            // 2. Show selected tab content
            const selectedContent = document.getElementById('tab-' + tabId);
            if (selectedContent) selectedContent.classList.remove('hidden');

            // 3. Update Sidebar Active State
            sidebarButtons.forEach(el => el.classList.remove('active'));
            btn.classList.add('active');

            // 4. Update Mobile Menu Active State
            // (If we had separate mobile buttons, which we might inject dynamically or have static duplicates)

            // 5. Trigger Lazy Loading
            // 5. Trigger Lazy Loading
            if (tabId === 'dashboard') {
                import('./ui-settings-dashboard.js').then(m => m.renderSettingsDashboardTab());
            } else if (tabId === 'governance') {
                renderSettingsGovernanceTab();
            } else if (tabId === 'organization') {
                renderSettingsOrganizationTab();
            } else if (tabId === 'profile') {
                renderSettingsMyProfileTab();
            } else if (tabId === 'agents') {
                // Pass args from state
                renderSettingsProfileTab(
                    settingsState.profiles,
                    settingsState.activeProfileKey,
                    settingsState.onProfileChange,
                    currentUser,
                    settingsState.availableModels
                );
            } else if (tabId === 'models') {
                // Pass args from state
                renderSettingsModelsTab(
                    settingsState.availableModels,
                    currentUser,
                    settingsState.onSaveModels
                );
            } else if (tabId === 'settings') {
                // Pass args from state
                renderSettingsAppTab(
                    settingsState.currentTheme,
                    settingsState.onThemeChange,
                    settingsState.onLogout,
                    settingsState.onDeleteAccount
                );
            }
        });
    });
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
        conscienceContainer.addEventListener('click', function (event) {
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
export function ensureProfileModalExists() {
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
