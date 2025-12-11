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

export function updateCurrentUser(u) {
    currentUser = u;
    // Propagate to org module which needs it for member table
    setOrgCurrentUser(u);
}

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
        ui.elements.cpNavOrganization, // Organization (Admin only)
        ui.elements.cpNavProfile,
        ui.elements.cpNavModels,
        ui.elements.cpNavMyProfile,
        ui.elements.cpNavDashboard,
        ui.elements.cpNavAppSettings,
        ui.elements.cpNavGovernance
    ];
    const panels = [
        ui.elements.cpTabOrganization,
        ui.elements.cpTabProfile,
        ui.elements.cpTabModels,
        ui.elements.cpTabMyProfile,
        ui.elements.cpTabDashboard,
        ui.elements.cpTabAppSettings,
        ui.elements.cpTabGovernance
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
                // Inline implementation or imported? 
                // I'll define renderSettingsDashboardTab at the bottom of this file if it's small, 
                // OR import it.
                // Let's import it to be consistent. 
                import('./ui-settings-dashboard.js').then(m => m.renderSettingsDashboardTab());
            }
            if (tab === ui.elements.cpNavGovernance) {
                renderSettingsGovernanceTab();
            }
            if (tab === ui.elements.cpNavOrganization) {
                renderSettingsOrganizationTab();
            }
            // Lazy-load user profile
            if (tab === ui.elements.cpNavMyProfile) {
                renderSettingsMyProfileTab();
            }
        });
    });

    // Activate the first tab by default
    // CHANGE: Don't auto-click here. Logic moved to renderControlPanel to respect RBAC.
    // if (tabs[0]) {
    //    tabs[0].click();
    // }
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
