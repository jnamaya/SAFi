import * as ui from '../ui.js';
import { renderSettingsDashboardTab } from './ui-settings-dashboard.js';
import { renderSettingsOrganizationTab, renderSettingsIdentityTab, setOrgCurrentUser } from './ui-settings-org.js';
import { renderSettingsProfileTab } from './ui-settings-agents.js';
import { renderSettingsMyProfileTab, setProfileIdentity } from './ui-settings-user.js';
import { renderSettingsGovernanceTab } from './ui-settings-governance.js';
import { renderSettingsAppTab } from './ui-settings-app.js';
import { renderSettingsHelpTab } from './ui-settings-help.js';
import { renderSettingsComplianceTab } from './ui-settings-compliance.js';
import { renderSettingsReviewTab, setReviewCurrentUser } from './ui-settings-review.js';
import { renderSettingsKnowledgeTab, setKnowledgeCurrentUser,
         stopPolling as stopKnowledgePolling } from './ui-settings-knowledge.js';

let currentUser = null;

const settingsState = {
    profiles: [],
    activeProfileKey: null,
    availableModels: [],
    onProfileChange: null,
    currentTheme: 'system',
    onThemeChange: null,
    onLogout: null,
    onDeleteAccount: null
};

export function updateCurrentUser(u) {
    currentUser = u;
    setOrgCurrentUser(u);
    setReviewCurrentUser(u);
    setKnowledgeCurrentUser(u);
    setProfileIdentity(u);
}

export function updateSettingsState(newState) {
    Object.assign(settingsState, newState);
    if (newState.currentUser) {
        updateCurrentUser(newState.currentUser);
    }
}

export function setupControlPanelTabs() {
    ui._ensureElements();
    setupDelegatedModalListeners();
    ensureProfileModalExists();


    const sidebarButtons = document.querySelectorAll('.sidebar-item');

    sidebarButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            if (!tabId) return;

            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));

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

            const selectedContent = document.getElementById('tab-' + tabId);
            if (selectedContent) selectedContent.classList.remove('hidden');

            sidebarButtons.forEach(el => el.classList.remove('active'));
            btn.classList.add('active');


            if (tabId === 'dashboard') {
                import('./ui-settings-dashboard.js').then(m => m.renderSettingsDashboardTab());
            } else if (tabId === 'governance') {
                renderSettingsGovernanceTab();
            } else if (tabId === 'organization') {
                renderSettingsOrganizationTab();
            } else if (tabId === 'identity') {
                renderSettingsIdentityTab();
            } else if (tabId === 'compliance') {
                renderSettingsComplianceTab();
            } else if (tabId === 'review') {
                renderSettingsReviewTab();
            } else if (tabId === 'profile') {
                renderSettingsMyProfileTab();
            } else if (tabId === 'schedules') {
                import('./ui-settings-schedules.js').then(m =>
                    m.renderSettingsSchedulesTab(settingsState.profiles));
            } else if (tabId === 'agents') {
                renderSettingsProfileTab(
                    settingsState.profiles,
                    settingsState.activeProfileKey,
                    settingsState.onProfileChange,
                    currentUser
                );
            } else if (tabId === 'settings') {
                renderSettingsAppTab(
                    settingsState.currentTheme,
                    settingsState.onThemeChange,
                    settingsState.onDeleteAccount
                );
            } else if (tabId === 'tools') {
                import('./ui-settings-tools.js').then(m => m.renderSettingsToolsTab());
            } else if (tabId === 'usage') {
                import('./ui-settings-usage.js').then(m => m.renderSettingsUsageTab());
            } else if (tabId === 'knowledge') {
                renderSettingsKnowledgeTab();
            } else if (tabId === 'help') {
                renderSettingsHelpTab();
            } else if (tabId === 'inbox') {
                import('../ui-attention.js').then(m => m.renderSettingsInboxTab());
            }

            if (tabId !== 'knowledge') stopKnowledgePolling();
        });
    });
}


function setupDelegatedModalListeners() {
    const conscienceContainer = ui.elements.conscienceDetails;
    if (conscienceContainer) {
        conscienceContainer.addEventListener('click', function (event) {
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

    document.addEventListener('click', (event) => {
        const el = event.target.closest?.('.chain-hash');
        if (!el) return;
        const hash = el.dataset.hash;
        if (!hash || !navigator.clipboard) return;
        navigator.clipboard.writeText(hash).then(() => {
            const shown = el.textContent;
            el.classList.add('copied');
            el.textContent = 'copied ✓';
            setTimeout(() => {
                el.classList.remove('copied');
                el.textContent = shown;
            }, 1200);
        }, () => {   });
    });
}

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

    ui.elements.profileModal = document.getElementById('profile-details-modal');
    ui.elements.profileModalContent = document.getElementById('profile-details-content');

    const closeBtn = document.getElementById('close-profile-modal');
    const doneBtn = document.getElementById('done-profile-modal');

    if (closeBtn) closeBtn.addEventListener('click', ui.closeModal);
    if (doneBtn) doneBtn.addEventListener('click', ui.closeModal);
}
