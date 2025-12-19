import * as api from './api.js';
import * as ui from '../ui/ui.js';
import * as uiAuthSidebar from '../ui/ui-auth-sidebar.js';
import * as uiMessages from '../ui/ui-messages.js';
import * as uiSettingsModals from '../ui/ui-settings-modals.js';
import { initDataSources } from '../ui/ui-data-sources.js';
import * as chat from './chat.js';
import { setupControlPanelTabs, updateSettingsState } from '../ui/settings/ui-settings-core.js';

import offlineManager from '../services/offline-manager.js';

// --- CAPACITOR GLOBAL STATE & PLUGINS ---
const Cap = typeof window !== 'undefined' ? window.Capacitor : undefined;
const isNative = !!(Cap && typeof Cap.isNativePlatform === 'function' && Cap.isNativePlatform());
const Plugins = Cap?.Plugins || {};
const GoogleAuth = Plugins?.GoogleAuth;
const SplashScreen = Plugins?.SplashScreen;
const Haptics = Plugins?.Haptics;
const StatusBar = Plugins?.StatusBar;
const Network = Plugins?.Network;
// ADDED: Import App Plugin
const App = Plugins?.App;

const WEB_CLIENT_ID = '391499357887-ggqkfpcqptcr93raffcv5mhgufmlu92v.apps.googleusercontent.com';

// --- GLOBAL STATE ---
let user = null;
let activeProfileData = {};
let availableProfiles = [];
let availableModels = [];
// FLAG: Ensure listeners are only attached once
let listenersAttached = false;

// =================================================================
// --- NATIVE HELPERS (MOVED TO TOP TO FIX REFERENCE ERROR) ---
// =================================================================

/** Sets the native status bar style and App Window color */
function setSystemBarsTheme(isDark) {
  if (!isNative || !StatusBar) return;

  const barColor = isDark ? '#000000' : '#ffffff';

  try {
    StatusBar.setStyle({ style: isDark ? 'DARK' : 'LIGHT' });
    StatusBar.setBackgroundColor({ color: barColor });
  } catch (e) {
    console.error('Failed to set status bar style:', e);
  }
}

/** Triggers a light haptic impact */
function hapticImpactLight() {
  if (isNative && Haptics) {
    try { Haptics.impact({ style: 'LIGHT' }); } catch (e) {
      // console.warn('Haptic impact failed', e);
    }
  }
}

/** Triggers a short vibration, typically for errors */
function hapticError() {
  if (isNative && Haptics) {
    try { Haptics.vibrate(); } catch (e) {
      // console.warn('Haptic vibrate failed', e);
    }
  }
}

/** Initialize GoogleAuth only on native. */
async function initializeNativeAuth() {
  if (!isNative || !GoogleAuth) {
    // console.warn('GoogleAuth plugin not found or not native.');
    return;
  }
  try {
    await GoogleAuth.initialize({
      scopes: ['profile', 'email'],
      serverClientId: WEB_CLIENT_ID,
      forceCodeForRefreshToken: true
    });
    console.log('[GA] initialize OK');
  } catch (e) {
    console.error('[GA] initialize failed:', e);
  }
}

/** Native Google Sign-In flow, then backend exchange. */
async function handleNativeLogin() {
  if (!GoogleAuth) {
    ui.showToast('Google Sign-In not available on this device.', 'error');
    return;
  }
  try {
    const googleUser = await GoogleAuth.signIn();
    const authCode = googleUser?.serverAuthCode;

    if (!authCode) {
      ui.showToast('Authentication failed. No server auth code.', 'error');
      hapticError();
      return;
    }

    await api.mobileLogin(authCode);

    hapticImpactLight();
    ui.showToast('Login successful!', 'success');
    setTimeout(() => window.location.reload(), 400);
  } catch (err) {
    const msg = ('' + (err?.message || err)).toUpperCase();
    if (msg.includes('12501') || msg.includes('USER_CANCELED') || msg.includes('CANCELLED')) {
      // User cancelled the sign-in, this is not an error
      return;
    }
    console.error('[GA] signIn failed:', err);
    ui.showToast(err?.message || 'Google sign-in failed.', 'error');
    hapticError();
  }
}

/** Show/hide the offline banner and update UI for native status */
function updateOfflineUI(isOnline) {
  const banner = document.getElementById('offline-banner');
  if (banner) {
    banner.classList.toggle('hidden', isOnline);
  }
}

// --- THEME ---

/** Applies the selected theme and saves it to localStorage. */
function applyTheme(theme) {
  const isSystemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  let shouldBeDark = false;

  if (theme === 'system') {
    localStorage.removeItem('theme');
    shouldBeDark = isSystemDark;
  } else if (theme === 'dark') {
    localStorage.theme = 'dark';
    shouldBeDark = true;
  } else {
    localStorage.theme = 'light';
    shouldBeDark = false;
  }

  if (shouldBeDark) {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
  // Update native status bar to match the theme
  setSystemBarsTheme(shouldBeDark);


  // Re-render app settings tab if it's currently open to reflect the theme change
  if (ui.elements.controlPanelView && !ui.elements.controlPanelView.classList.contains('hidden')) {
    const currentActiveTab = document.querySelector('.modal-tab-button.active');
    if (currentActiveTab && currentActiveTab.id === 'cp-nav-app-settings') {
      uiSettingsModals.renderSettingsAppTab(
        theme,
        applyTheme,
        handleLogout,
        () => ui.showModal('delete') // Show modal instead of direct delete
      );
    }
  }
}

// --- AUTHENTICATION & DATA LOADING ---

async function checkLoginStatus() {
  try {
    await api.awaitAuthInit();
    const me = await api.getMe();
    user = (me && me.ok) ? me.user : null;

    // Render the sidebar/login view based on auth state
    uiAuthSidebar.updateUIForAuthState(user);

    if (user) {
      // FIX: Only initialize the offline manager (and flush queue) IF we are logged in.
      // This prevents the "401 Loop of Death" where pending prompts try to send while logged out.
      try {
        await offlineManager.initNetworkListener();
      } catch (e) {
        console.warn("Offline manager init warning:", e);
      }

      // User is logged in, fetch necessary data
      const [profilesResponse, modelsResponse] = await Promise.all([
        api.fetchAvailableProfiles(),
        api.fetchAvailableModels()
      ]);

      availableProfiles = profilesResponse.available || [];
      availableModels = modelsResponse.models || [];

      // --- CRITICAL UPDATE: Pass profiles to sidebar for avatar lookup ---
      uiAuthSidebar.setKnownProfiles(availableProfiles);
      // ------------------------------------------------------------------

      // Determine the active profile
      const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
      activeProfileData = availableProfiles.find(p => p.key === currentProfileKey) || availableProfiles[0] || {};

      // Update the UI with the active profile
      // Pass the FULL object so it can find the custom avatar
      uiAuthSidebar.updateActiveProfileChip(activeProfileData);

      // This function renders the content for all control panel tabs
      renderControlPanel();

      // Load the conversation list and the active chat
      await chat.loadConversations(
        activeProfileData,
        user,
        handleExamplePromptClick,
        ui.showModal,
        true // Explicitly set shouldSwitchChat=true on initial load
      );

      // Initialize Data Sources UI (Dropdown)
      initDataSources();
    }
    // Attach all global event listeners
    attachEventListeners();
  } catch (error) {
    console.error("Failed to check login status:", error);
    uiAuthSidebar.updateUIForAuthState(null); // Show login screen on error
    attachEventListeners(); // Still attach login button listener
    hapticError();
  } finally {
    // Hide the native splash screen
    setTimeout(() => {
      if (SplashScreen) {
        SplashScreen.hide();
      } else if (isNative) {
        // console.warn('SplashScreen plugin not available, cannot hide.');
      }
    }, 250);
  }
}

// --- LOGIC HANDLERS ---

async function handleLogout() {
  hapticImpactLight();
  if (isNative && GoogleAuth) {
    try { await GoogleAuth.signOut(); } catch (e) { console.warn('Google signOut error:', e); }
  }

  try {
    await api.logout();
  } catch (e) {
    console.warn('Logout API call failed (may be queued):', e);
  }

  localStorage.removeItem('theme'); // Reset theme
  await api.clearAuthToken(); // Clear local token

  window.location.reload(); // Reload the app
}

async function handleDeleteAccount() {
  try {
    const response = await api.deleteAccount();

    if (response === 'QUEUED') {
      ui.showToast('Account deletion queued.', 'info');
      ui.closeModal();
      return;
    }

    ui.showToast('Account deleted successfully.', 'success');
    hapticImpactLight();

    if (isNative && GoogleAuth) {
      try { await GoogleAuth.signOut(); } catch (e) { console.warn('Google signOut error:', e); }
    }

    await api.clearAuthToken();
    localStorage.removeItem('theme');

    setTimeout(() => window.location.reload(), 1000);
  } catch (error) {
    console.error('Failed to delete account:', error);
    ui.showToast(error.message || 'Could not delete account.', 'error');
    hapticError();
  } finally {
    ui.closeModal();
  }
}

/** Renders the content for all Control Panel tabs */
function renderControlPanel() {
  if (!user) return;

  // --- NEW: Strict RBAC Visibility Matrix ---
  console.log('[RBAC] Checking visibility for user:', user.id, 'Role:', user.role);

  // Organization: Admin & Auditor only (Auditor = View Only)
  const canSeeOrg = ['admin', 'auditor'].includes(user.role);
  // Governance: Admin, Editor, Auditor (Member = No Access)
  const canSeeGovernance = ['admin', 'editor', 'auditor'].includes(user.role);
  // Dashboard: Admin, Editor, Auditor (Member = No Access)
  // Dashboard: Admin, Editor, Auditor (Member = No Access)
  // Dashboard: Admin, Editor, Auditor (Member = No Access)
  const canSeeDashboard = ['admin', 'editor', 'auditor'].includes(user.role);

  // Models: Admin, Editor, Auditor (Member = No Access)
  const canSeeModels = ['admin', 'editor', 'auditor'].includes(user.role);

  console.log('[RBAC] Flags:', { canSeeOrg, canSeeGovernance, canSeeDashboard, canSeeModels });

  const navOrg = document.getElementById('nav-organization'); // NEW ID
  if (navOrg) {
    if (canSeeOrg) navOrg.classList.remove('hidden');
    else navOrg.classList.add('hidden');
  }

  // Hide AI Models Tab if not authorized
  const navModels = document.getElementById('nav-models');
  if (navModels) {
    if (canSeeModels) navModels.classList.remove('hidden');
    else navModels.classList.add('hidden');
  }

  const navGov = document.getElementById('nav-governance'); // NEW ID
  if (navGov) {
    if (canSeeGovernance) navGov.classList.remove('hidden');
    else navGov.classList.add('hidden');
  }

  // Dashboard tab currently hidden/removed in HTML, but keeping logic safe
  const navDash = document.getElementById('nav-dashboard'); // NEW ID
  if (navDash) {
    if (canSeeDashboard) navDash.classList.remove('hidden');
    else navDash.classList.add('hidden');
  }

  // --- NEW: Hide entire Management Group if no children are visible ---
  const navGroupManagement = document.getElementById('nav-group-management');
  if (navGroupManagement) {
    if (canSeeOrg || canSeeGovernance || canSeeDashboard) {
      navGroupManagement.classList.remove('hidden');
    } else {
      navGroupManagement.classList.add('hidden');
    }
  }
  // ----------------------------------------

  // Update UI Modals with current user context
  uiSettingsModals.updateCurrentUser(user);

  // Render Personas Tab
  // Render Personas Tab
  uiSettingsModals.renderSettingsProfileTab(
    availableProfiles,
    activeProfileData.key,
    handleProfileChange,
    user, // Pass user for ownership checks
    availableModels // Pass models for wizard
  );

  // Render AI Models Tab
  uiSettingsModals.renderSettingsModelsTab(
    availableModels,
    user,
    handleModelsSave
  );

  // --- NEW: Init Agent Selector ---
  uiAuthSidebar.initAgentSelector(
    availableProfiles,
    activeProfileData.key,
    handleProfileChange
  );

  // --- NEW: Push State to UI Settings Module ---
  // This ensures the sidebar click handlers work correctly even if data changes
  updateSettingsState({
    currentUser: user,
    profiles: availableProfiles,
    activeProfileKey: activeProfileData.key,
    availableModels: availableModels,
    onProfileChange: handleProfileChange,
    currentTheme: localStorage.theme || 'system',
    onThemeChange: applyTheme,
    onLogout: handleLogout,
    onDeleteAccount: () => ui.showModal('delete'),
    onSaveModels: handleModelsSave
  });

  // Render "My Profile" Tab. This will fetch the data.
  uiSettingsModals.renderSettingsMyProfileTab();

  // Render App Settings Tab
  uiSettingsModals.renderSettingsAppTab(
    localStorage.theme || 'system',
    applyTheme,
    handleLogout,
    () => ui.showModal('delete') // Open "are you sure" modal
  );

  // --- NEW: Select Default Open Tab (RBAC Aware) ---
  // Ensure we switch to a visible tab if the current/default one is hidden.
  // We prioritize: Agents (Profile) > Organization > Dashboard
  const orgTab = document.getElementById('nav-organization');
  const agentsTab = document.getElementById('nav-agents'); // "Agents" tab
  const modelsTab = document.getElementById('nav-models'); // "Models" tab

  // Safety fallback logic
  // If the *currently active* tab is now hidden, switch to a safe default.
  const currentActive = document.querySelector('.sidebar-item.active');
  let activeIsVisible = currentActive && !currentActive.classList.contains('hidden');

  if (!activeIsVisible) {
    if (agentsTab && !agentsTab.classList.contains('hidden')) {
      agentsTab.click();
    } else if (orgTab && !orgTab.classList.contains('hidden')) {
      orgTab.click();
    }
  }
  // --------------------------------------------------

  // --- Mobile Menu Population ---
  const mobileNavContainer = document.getElementById('mobile-nav-links');
  const desktopNav = document.getElementById('sidebar-nav');
  if (mobileNavContainer && desktopNav) {
    mobileNavContainer.innerHTML = ''; // Clear previous

    Array.from(desktopNav.children).forEach(child => {
      // Skip "Back to Chat" as header has one
      if (child.querySelector('#desktop-back-to-chat')) return;

      // Only clone visible elements (respect RBAC)
      // desktopNav children are divs wrapping uls. Check if the buttons inside are hidden?
      // The RBAC logic hides the BUTTONS inside the list items usually? 
      // WAIT, RBAC logic above removes 'hidden' from: navOrg, navGov, navDash.
      // Those are BUTTONS.
      // The structure is Div -> UL -> LI -> Button.
      // If the button is hidden, we clone it hidden.
      // If we want to skip cloning hidden items?
      // Let's just clone. If button is hidden, it will be hidden on mobile too.
      // BUT IDs must be stripped to avoid conflict.

      const clone = child.cloneNode(true);
      clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));

      mobileNavContainer.appendChild(clone);
    });

    // Re-attach listeners to the CLONED buttons
    mobileNavContainer.querySelectorAll('button[data-tab]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.dataset.tab;
        const originalBtn = document.getElementById(`nav-${tab}`);
        if (originalBtn) originalBtn.click();

        // Close mobile menu
        document.getElementById('mobile-menu')?.classList.add('-translate-x-full');
        document.getElementById('mobile-menu-backdrop')?.classList.add('hidden');
      });
    });
  }
}

async function handleProfileChange(newProfileKey) {
  hapticImpactLight();
  try {
    const response = await api.updateUserProfile(newProfileKey);

    if (response === 'QUEUED') {
      ui.showToast('Profile change queued.', 'info');
      // Optimistically update UI
      activeProfileData = availableProfiles.find(p => p.key === newProfileKey) || activeProfileData;
      uiAuthSidebar.updateActiveProfileChip(activeProfileData); // Pass object for avatar support
      return;
    }

    const selectedProfile = availableProfiles.find(p => p.key === newProfileKey);
    ui.showToast(`Agent switched to ${selectedProfile.name}. Reloading...`, 'success');

    // Set a flag to force a new chat window after the reload
    sessionStorage.setItem('forceNewChat', 'true');

    setTimeout(() => window.location.reload(), 1000); // Reload to apply changes
  } catch (error) {
    console.error('Failed to switch profile:', error);
    ui.showToast('Could not switch agent.', 'error');
    hapticError();
  }
}

async function handleModelsSave(newModels) {
  hapticImpactLight();
  try {
    const response = await api.updateUserModels(newModels);

    if (response === 'QUEUED') {
      ui.showToast('Model changes queued.', 'info');
      // Optimistically update UI
      user.intellect_model = newModels.intellect_model;
      user.will_model = newModels.will_model;
      user.conscience_model = newModels.conscience_model;
      ui.closeModal(); // Close the control panel
      return;
    }

    ui.showToast('Model preferences saved. Reloading...', 'success');
    setTimeout(() => window.location.reload(), 1000); // Reload to apply changes
  } catch (error) {
    console.error('Failed to save models:', error);
    ui.showToast('Could not save model preferences.', 'error');
    hapticError();
  }
}

/** Handles click on an example prompt in the empty chat view */
function handleExamplePromptClick(promptText) {
  ui.elements.messageInput.value = promptText;
  chat.autoSize(); // Resize textarea
  ui.elements.sendButton.disabled = false;
  chat.sendMessage(activeProfileData, user);
}

// --- EVENT LISTENERS ---

/** Attaches all non-dynamic event listeners */
function attachEventListeners() {
  if (listenersAttached) return; // Prevent duplicates

  // --- Auth Handlers (Explicit & Robust) ---

  // 1. Google Login
  if (ui.elements.loginButton) {
    if (isNative && GoogleAuth) {
      ui.elements.loginButton.addEventListener('click', handleNativeLogin);
    } else {
      ui.elements.loginButton.addEventListener('click', () => { window.location.href = '/api/login'; });
    }
  }

  // 2. Microsoft Login (FIXED: Added Listener)
  const microsoftBtn = document.getElementById('login-microsoft-button');
  if (microsoftBtn) {
    microsoftBtn.addEventListener('click', () => {
      window.location.href = '/api/login/microsoft';
    });
  }

  // --- Chat Composer ---
  if (ui.elements.sendButton) {
    ui.elements.sendButton.addEventListener('click', () => { hapticImpactLight(); chat.sendMessage(activeProfileData, user); });
    ui.elements.messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        hapticImpactLight();
        chat.sendMessage(activeProfileData, user);
      }
    });
    ui.elements.messageInput.addEventListener('input', chat.autoSize);
  }

  // --- Sidebar & Navigation ---
  const newChatButton = document.getElementById('new-chat-button');
  if (newChatButton) {
    newChatButton.addEventListener('click', () => {
      hapticImpactLight();
      chat.startNewConversation(false, activeProfileData, user, handleExamplePromptClick);
      if (window.innerWidth < 768) ui.closeSidebar();
    });
  }

  const menuToggle = document.getElementById('menu-toggle');
  if (menuToggle) menuToggle.addEventListener('click', ui.openSidebar);
  const closeSidebarButton = document.getElementById('close-sidebar-button');
  if (closeSidebarButton) closeSidebarButton.addEventListener('click', ui.closeSidebar);
  const sidebarOverlay = document.getElementById('sidebar-overlay');
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', ui.closeSidebar);

  // --- Control Panel ---
  const controlPanelButton = document.getElementById('control-panel-btn');
  if (controlPanelButton) {
    controlPanelButton.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      // HIDE Sidebar entirely
      ui.closeSidebar(); // Close mobile menu if open
      const sidebar = document.getElementById('sidebar');
      if (sidebar) {
        sidebar.classList.add('hidden'); // Ensure hidden class is present
        sidebar.classList.remove('md:flex'); // Disable desktop flex display
      }

      // Remove margin from main wrapper to reclaim space
      const wrapper = document.getElementById('main-layout-wrapper');
      if (wrapper) wrapper.classList.remove('md:ml-72');
    });
  }

  // --- Control Panel Logout Button ---
  const navLogoutBtn = document.getElementById('nav-logout');
  if (navLogoutBtn) {
    navLogoutBtn.addEventListener('click', handleLogout);
  }

  // --- Control Panel Mobile Menu (Delegated for robustness) ---
  // Using delegation to ensure it works even if elements aren't immediately found/bound
  document.addEventListener('click', (e) => {
    // Open Menu
    const openBtn = e.target.closest('#mobile-menu-btn');
    if (openBtn) {
      const menu = document.getElementById('mobile-menu');
      const backdrop = document.getElementById('mobile-menu-backdrop');
      if (menu && backdrop) {
        menu.classList.remove('-translate-x-full');
        backdrop.classList.remove('hidden');
        setTimeout(() => backdrop.classList.remove('opacity-0'), 10);
      }
    }

    // Close Menu (Close Btn or Backdrop click)
    const closeBtn = e.target.closest('#close-mobile-menu');
    const isBackdrop = e.target.id === 'mobile-menu-backdrop';

    if (closeBtn || isBackdrop) {
      const menu = document.getElementById('mobile-menu');
      const backdrop = document.getElementById('mobile-menu-backdrop');
      if (menu && backdrop) {
        menu.classList.add('-translate-x-full');
        backdrop.classList.add('opacity-0');
        setTimeout(() => backdrop.classList.add('hidden'), 300);
      }
    }
  });

  // Back Button Logic (New ID: desktop-back-to-chat)
  // Also keep support for old btn just in case, though we removed it from HTML
  const backButtons = [
    document.getElementById('desktop-back-to-chat'),
    document.getElementById('control-panel-back-btn'),
    document.getElementById('mobile-back-to-chat')
  ];

  backButtons.forEach(btn => {
    if (!btn) return;
    btn.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.controlPanelView.classList.add('hidden');
      ui.elements.chatView.classList.remove('hidden');

      // SHOW Sidebar Logic (Restore Desktop)
      const sidebar = document.getElementById('sidebar');
      if (sidebar) {
        sidebar.classList.add('md:flex'); // Restore desktop display
        // Note: We leave 'hidden' class alone as it's the default state for mobile (toggled by ui.js)
        // But if we forced it added above, we might not need to remove it if md:flex overrides it.
        // Yet to be safe for mobile consistency:
        // sidebar.classList.add('hidden'); // Ensure it starts hidden on mobile until toggled
      }

      // Restore margin to main wrapper
      const wrapper = document.getElementById('main-layout-wrapper');
      if (wrapper) wrapper.classList.add('md:ml-72');
    });
  });

  // --- Profile Chips (shortcut to Control Panel) ---
  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      // HIDE Sidebar entirely
      ui.closeSidebar();
      const sidebar = document.getElementById('sidebar');
      if (sidebar) {
        sidebar.classList.add('hidden');
        sidebar.classList.remove('md:flex');
      }

      // Remove margin from main wrapper
      const wrapper = document.getElementById('main-layout-wrapper');
      if (wrapper) wrapper.classList.remove('md:ml-72');

      if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click(); // Go to profile tab
    });
  }
  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      // HIDE Sidebar entirely
      ui.closeSidebar();
      const sidebar = document.getElementById('sidebar');
      if (sidebar) {
        sidebar.classList.add('hidden');
        sidebar.classList.remove('md:flex');
      }

      // Remove margin from main wrapper
      const wrapper = document.getElementById('main-layout-wrapper');
      if (wrapper) wrapper.classList.remove('md:ml-72');

      if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click(); // Go to profile tab
    });
  }

  // --- Modal Buttons ---
  document.getElementById('close-conscience-modal')?.addEventListener('click', ui.closeModal);
  document.getElementById('got-it-conscience-modal')?.addEventListener('click', ui.closeModal);
  document.getElementById('cancel-delete-btn')?.addEventListener('click', ui.closeModal);
  document.getElementById('modal-backdrop')?.addEventListener('click', ui.closeModal);
  document.getElementById('confirm-delete-btn')?.addEventListener('click', handleDeleteAccount);

  document.getElementById('close-profile-modal')?.addEventListener('click', ui.closeModal);
  document.getElementById('done-profile-modal')?.addEventListener('click', ui.closeModal);

  ui.elements.cancelRenameBtn?.addEventListener('click', ui.closeModal);
  ui.elements.confirmRenameBtn?.addEventListener('click', () => { hapticImpactLight(); chat.handleConfirmRename(activeProfileData, user); });
  ui.elements.renameInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      hapticImpactLight();
      chat.handleConfirmRename(activeProfileData, user);
    }
  });

  ui.elements.cancelDeleteConvoBtn?.addEventListener('click', ui.closeModal);
  ui.elements.confirmDeleteConvoBtn?.addEventListener('click', () => { hapticImpactLight(); chat.handleConfirmDelete(activeProfileData, user); });

  // --- Global Click Listeners ---
  document.addEventListener('click', (event) => {
    // Close convo menu if clicking outside
    const convoMenuButton = event.target.closest('.convo-menu-button');
    if (!convoMenuButton) {
      ui.closeAllConvoMenus();
    }
  });

  // --- System Listeners ---
  uiSettingsModals.setupControlPanelTabs();

  try {
    // Listen for system theme changes
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', () => {
      if (localStorage.theme === 'system' || !localStorage.theme) {
        applyTheme('system');
      }
    });

    // Listen for network online/offline status
    if (isNative && Network) {
      Network.addListener('networkStatusChange', (status) => {
        updateOfflineUI(status.connected);
      });
      // Update initial state
      Network.getStatus().then(status => updateOfflineUI(status.connected));
    }

    // --- NEW: Refresh conversations when app resumes from background ---
    if (isNative && App) {
      App.addListener('appStateChange', ({ isActive }) => {
        if (isActive && user) {
          // Only reload if the app is active and the user is logged in
          console.log('App resumed, reloading conversations...');
          // This call should switch and scroll to the bottom of the active chat
          chat.loadConversations(activeProfileData, user, handleExamplePromptClick, ui.showModal, true);
        }
      });
    }

    // --- Control Panel Logout Button ---
    const cpNavLogout = document.getElementById('cp-nav-logout');
    if (cpNavLogout) {
      cpNavLogout.addEventListener('click', handleLogout);
    }

  } catch (e) {
    console.error('Failed to add theme/network/app listener:', e);
  }

  listenersAttached = true;
}

// --- BOOTSTRAP ---

document.addEventListener('DOMContentLoaded', async () => {
  // 1. Apply initial theme and set system bars
  applyTheme(localStorage.theme || 'system');

  // FIX: Removed offlineManager init from here to prevent 401 loops.
  // It is now called inside checkLoginStatus on success.

  // 3. Initialize native auth for Google Sign-In
  await initializeNativeAuth();

  // 4. Run main logic
  await checkLoginStatus();
});