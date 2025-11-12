import * as api from './api.js';
import * as ui from './ui.js';
import * as uiRender from './ui-render.js';
import * as chat from './chat.js';
import * as utils from './utils.js';

// --- GLOBAL STATE ---
let user = null; // Store user object
let activeProfileData = {}; // Stores the full profile details
let availableProfiles = []; // Stores the list of *full profile objects*
let availableModels = []; 

// --- INITIALIZATION ---

/**
 * Checks login status, loads initial data, and sets up UI.
 */
async function checkLoginStatus() {
    try {
        const me = await api.getMe();
        user = (me && me.ok) ? me.user : null;
        
        // Use uiRender for the complex UI update (sidebar template)
        uiRender.updateUIForAuthState(
            user, 
            handleLogout, 
            () => ui.showModal('delete'),
            applyTheme 
        );
        
        if (user) {
            const [profilesResponse, modelsResponse] = await Promise.all([
                api.fetchAvailableProfiles(),
                api.fetchAvailableModels()
            ]);
            
            availableProfiles = profilesResponse.available || [];
            availableModels = modelsResponse.models || [];
            
            const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
            
            activeProfileData = availableProfiles.find(p => p.key === currentProfileKey) || availableProfiles[0] || {};
            
            // --- MODIFICATION: Update profile chip as soon as data is loaded ---
            uiRender.updateActiveProfileChip(activeProfileData.name || 'Default');
            // --- END MODIFICATION ---

            // Pass necessary data and handlers to the rendering functions
            renderControlPanel();
            
            await chat.loadConversations(
                activeProfileData, 
                user, 
                handleExamplePromptClick,
                ui.showModal // Pass modal function down
            );
        }
        attachEventListeners();
    } catch (error) {
        console.error("Failed to check login status:", error);
        uiRender.updateUIForAuthState(null, handleLogout, () => ui.showModal('delete'), applyTheme);
        attachEventListeners();
    }
}

// --- SETTINGS AND PROFILE HANDLERS ---

function renderControlPanel() {
    if (!user) return;
    
    uiRender.renderSettingsProfileTab(
        availableProfiles, 
        activeProfileData.key, 
        handleProfileChange
    );
    
    uiRender.renderSettingsModelsTab(
        availableModels, 
        user, 
        handleModelsSave
    );

    uiRender.renderSettingsAppTab(
        localStorage.theme || 'system',
        applyTheme,
        handleLogout,
        () => ui.showModal('delete')
    );
}

async function handleProfileChange(newProfileKey) {
    try {
        await api.updateUserProfile(newProfileKey);
        const selectedProfile = availableProfiles.find(p => p.key === newProfileKey);
        ui.showToast(`Profile switched to ${selectedProfile.name}. Reloading...`, 'success');
        setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
        console.error('Failed to switch profile:', error);
        ui.showToast('Could not switch profile.', 'error');
    }
}

async function handleModelsSave(newModels) {
    try {
        await api.updateUserModels(newModels);
        ui.showToast('Model preferences saved. Reloading...', 'success');
        setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
         console.error('Failed to save models:', error);
        ui.showToast('Could not save model preferences.', 'error');
    }
}

/**
 * Applies the selected theme and saves it to localStorage.
 * @param {'light' | 'dark' | 'system'} theme 
 */
function applyTheme(theme) {
    if (theme === 'system') {
        localStorage.removeItem('theme');
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
    } else if (theme === 'dark') {
        localStorage.theme = 'dark';
        document.documentElement.classList.add('dark');
    } else {
        localStorage.theme = 'light';
        document.documentElement.classList.remove('dark');
    }

    // Re-render the app settings tab to update radio buttons if Control Panel is open
    if (ui.elements.controlPanelView && !ui.elements.controlPanelView.classList.contains('hidden')) {
        const currentActiveTab = document.querySelector('.modal-tab-button.active');
        if (currentActiveTab && currentActiveTab.id === 'cp-nav-app-settings') {
            uiRender.renderSettingsAppTab(
                theme,
                applyTheme,
                handleLogout,
                () => ui.showModal('delete')
            );
        }
    }
}

/**
 * Handler for example prompt buttons in the empty state.
 * @param {string} promptText 
 */
function handleExamplePromptClick(promptText) {
    // 1. Set the input value
    ui.elements.messageInput.value = promptText;
    
    // 2. Ensure input is sized correctly and enabled
    chat.autoSize();
    ui.elements.sendButton.disabled = false;
    
    // 3. Immediately trigger the message send logic, which handles conversation creation
    // The sendMessage logic is fully self-contained (creating the convo if currentConversationId is null)
    chat.sendMessage(activeProfileData, user);
}

// --- AUTHENTICATION HANDLERS ---

async function handleLogout() {
    await fetch(api.urls.LOGOUT, { method: 'POST', credentials: 'include' });
    window.location.reload();
}

async function handleDeleteAccount() {
    try {
        await api.deleteAccount();
        ui.showToast('Account deleted successfully.', 'success');
        setTimeout(() => window.location.reload(), 1500);
    } catch (error) {
        ui.showToast(error.message, 'error');
    } finally {
        ui.closeModal();
    }
}

// --- EVENT LISTENERS ---

function attachEventListeners() {
    // Auth & Login
    if (ui.elements.loginButton) {
        ui.elements.loginButton.addEventListener('click', () => { window.location.href = api.urls.LOGIN; });
    }

    // Chat Composer
    if (ui.elements.sendButton) {
        ui.elements.sendButton.addEventListener('click', () => chat.sendMessage(activeProfileData, user));
        ui.elements.messageInput.addEventListener('keydown', (e) => { 
            if (e.key === 'Enter' && !e.shiftKey) { 
                e.preventDefault(); 
                chat.sendMessage(activeProfileData, user); 
            } 
        });
        ui.elements.messageInput.addEventListener('input', chat.autoSize);
    }

    // Sidebar & Navigation
    const newChatButton = document.getElementById('new-chat-button');
    if (newChatButton) {
        newChatButton.addEventListener('click', () => { 
            // FIX: Pass activeProfileData and user to startNewConversation
            chat.startNewConversation(false, activeProfileData, user, handleExamplePromptClick); 
            if (window.innerWidth < 768) ui.closeSidebar(); 
        });
    }

    const menuToggle = document.getElementById('menu-toggle');
    if (menuToggle) menuToggle.addEventListener('click', ui.openSidebar);
    const closeSidebarButton = document.getElementById('close-sidebar-button');
    if(closeSidebarButton) closeSidebarButton.addEventListener('click', ui.closeSidebar);
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    if(sidebarOverlay) sidebarOverlay.addEventListener('click', ui.closeSidebar);

    // Control Panel
    const controlPanelButton = document.getElementById('control-panel-btn');
    if (controlPanelButton) {
        controlPanelButton.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            if (window.innerWidth < 768) ui.closeSidebar();
        });
    }
    if (ui.elements.controlPanelBackButton) {
        ui.elements.controlPanelBackButton.addEventListener('click', () => {
            ui.elements.controlPanelView.classList.add('hidden');
            ui.elements.chatView.classList.remove('hidden');
        });
    }

    // Active Profile Chip click to open CP/Profile tab
    if (ui.elements.activeProfileChip) {
        ui.elements.activeProfileChip.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
        });
    }
    if (ui.elements.activeProfileChipMobile) {
        ui.elements.activeProfileChipMobile.addEventListener('click', () => {
            ui.elements.chatView.classList.add('hidden');
            ui.elements.controlPanelView.classList.remove('hidden');
            if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
        });
    }

    // Modals
    document.getElementById('close-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('got-it-conscience-modal')?.addEventListener('click', ui.closeModal);
    document.getElementById('cancel-delete-btn')?.addEventListener('click', ui.closeModal);
    document.getElementById('modal-backdrop')?.addEventListener('click', ui.closeModal);
    document.getElementById('confirm-delete-btn')?.addEventListener('click', handleDeleteAccount);

    // Rename Modal listeners call chat module handlers
    ui.elements.cancelRenameBtn?.addEventListener('click', ui.closeModal);
    ui.elements.confirmRenameBtn?.addEventListener('click', () => chat.handleConfirmRename(activeProfileData, user));
    ui.elements.renameInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            chat.handleConfirmRename(activeGProfileData, user);
        }
    });

    // Delete Convo Modal listeners call chat module handlers
    ui.elements.cancelDeleteConvoBtn?.addEventListener('click', ui.closeModal);
    ui.elements.confirmDeleteConvoBtn?.addEventListener('click', () => chat.handleConfirmDelete(activeProfileData, user));
    
    // Global click listener to close menus
    document.addEventListener('click', (event) => {
        const convoMenuButton = event.target.closest('.convo-menu-button');
        if (!convoMenuButton) {
            ui.closeAllConvoMenus();
        }
    });

    // Control Panel Tabs Setup (Logic stays here as it ties to modal/view state)
    uiRender.setupControlPanelTabs();
}

document.addEventListener('DOMContentLoaded', checkLoginStatus);