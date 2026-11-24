import * as api from './api.js';
import * as ui from '../ui/ui.js';
import * as uiAuthSidebar from '../ui/ui-auth-sidebar.js';
import * as uiMessages from '../ui/ui-messages.js';
import * as uiSettingsModals from '../ui/ui-settings-modals.js';
import { initDataSources } from '../ui/ui-data-sources.js';
import { initModelSelector, getActiveModelLabel, getActiveModel } from '../ui/ui-model-selector.js';
import { initComposerMenu, updateAgentLabel, updateModelLabel, updateAiDisclosure } from '../ui/ui-composer-menu.js';
import { initVoiceInput } from '../ui/ui-voice-input.js';
import { getAvatarForProfile } from '../ui/ui-auth-sidebar.js';
import * as chat from './chat.js';
import * as uiSaved from '../ui/ui-saved.js';
import { setupControlPanelTabs, updateSettingsState } from '../ui/settings/ui-settings-core.js';

import offlineManager from '../services/offline-manager.js';
import * as cache from './cache.js';

const isNative = false;
const GoogleAuth = null;
const SplashScreen = null;
const Haptics = null;
const StatusBar = null;
const Network = null;
const App = null;
const Browser = null;

const WEB_CLIENT_ID = '391499357887-ggqkfpcqptcr93raffcv5mhgufmlu92v.apps.googleusercontent.com';

let user = null;
let activeProfileData = {};
let availableProfiles = [];
let availableModels = [];
let listenersAttached = false;


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

function hapticImpactLight() {
  if (isNative && Haptics) {
    try { Haptics.impact({ style: 'LIGHT' }); } catch (e) {
    }
  }
}

function hapticError() {
  if (isNative && Haptics) {
    try { Haptics.vibrate(); } catch (e) {
    }
  }
}

async function initializeNativeAuth() {
  if (!isNative || !GoogleAuth) {
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

async function handleNativeLogin() {
  if (!GoogleAuth) {
    ui.showToast('Google Sign-In not available on this device.', 'error');
    return;
  }
  try {
    const googleUser = await GoogleAuth.signIn();
    
    const authCode = googleUser?.authentication?.idToken || googleUser?.serverAuthCode;

    if (!authCode) {
      ui.showToast('Authentication failed. No auth token received.', 'error');
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
      return;
    }
    console.error('[GA] signIn failed:', err);
    ui.showToast(err?.message || 'Google sign-in failed.', 'error');
    hapticError();
  }
}

async function handleNativeMicrosoftLogin() {
  if (!Browser) {
    ui.showToast('Browser plugin not available.', 'error');
    return;
  }
  try {
    const redirectUri = encodeURIComponent('com.safi.app://auth');
    await Browser.open({
      url: `https://safi.selfalignmentframework.com/api/login/microsoft?redirect_uri=${redirectUri}`,
      windowName: '_self'
    });
  } catch (err) {
    console.error('[MS] Browser open failed:', err);
    ui.showToast('Could not open Microsoft login.', 'error');
  }
}

function updateOfflineUI(isOnline) {
  const banner = document.getElementById('offline-banner');
  if (banner) {
    banner.classList.toggle('hidden', isOnline);
  }
}


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
  setSystemBarsTheme(shouldBeDark);


  if (ui.elements.controlPanelView && !ui.elements.controlPanelView.classList.contains('hidden')) {
    const currentActiveTab = document.querySelector('.modal-tab-button.active');
    if (currentActiveTab && currentActiveTab.id === 'cp-nav-app-settings') {
      uiSettingsModals.renderSettingsAppTab(
        theme,
        applyTheme,
        () => ui.showModal('delete')
      );
    }
  }
}


function showMfaEnrollmentGate() {
  const gate = document.createElement('div');
  gate.id = 'mfa-enrollment-gate';
  gate.className = 'fixed inset-0 z-[100] flex items-center justify-center bg-white dark:bg-black p-4';
  gate.innerHTML = `
    <div class="w-full max-w-md bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-2xl shadow-xl p-6">
      <h2 class="text-lg font-bold text-neutral-900 dark:text-white mb-1">Two-factor authentication required</h2>
      <p class="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
        Your organization requires an authenticator app on this account before you can continue.
      </p>
      <div id="mfa-gate-step1">
        <button id="mfa-gate-generate" class="w-full px-4 py-2.5 rounded-lg bg-green-600 hover:bg-green-700 text-white font-semibold text-sm transition">
          Set up authenticator
        </button>
      </div>
      <div id="mfa-gate-step2" class="hidden">
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mb-2">
          Scan this with Google Authenticator, Microsoft Authenticator, or any
          TOTP app, then enter the 6-digit code it shows.
        </p>
        <div id="mfa-gate-qr" class="mb-3 inline-block rounded-lg overflow-hidden"></div>
        <details class="mb-3">
          <summary class="text-xs text-neutral-500 dark:text-neutral-400 cursor-pointer">Can't scan? Enter the key manually</summary>
          <div class="mt-2 mb-1 p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 font-mono text-sm break-all select-all" id="mfa-gate-secret"></div>
          <a id="mfa-gate-otpauth" href="#" class="block text-xs text-green-600 hover:underline">Open in authenticator app on this device</a>
        </details>
        <input id="mfa-gate-code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="123456"
          class="w-full px-4 py-2.5 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-sm tracking-widest text-center dark:text-white mb-2" />
        <button id="mfa-gate-verify" class="w-full px-4 py-2.5 rounded-lg bg-green-600 hover:bg-green-700 text-white font-semibold text-sm transition">
          Verify and continue
        </button>
      </div>
      <p id="mfa-gate-error" class="hidden text-red-500 text-xs text-center mt-2"></p>
      <button id="mfa-gate-logout" class="w-full mt-4 text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 underline">
        Sign out instead
      </button>
    </div>`;
  document.body.appendChild(gate);

  const errEl = gate.querySelector('#mfa-gate-error');
  const showErr = (msg) => { errEl.textContent = msg; errEl.classList.remove('hidden'); };

  gate.querySelector('#mfa-gate-generate').addEventListener('click', async () => {
    errEl.classList.add('hidden');
    try {
      const res = await api.setupTotp();
      gate.querySelector('#mfa-gate-secret').textContent = res.secret;
      gate.querySelector('#mfa-gate-otpauth').href = res.otpauth_uri;
      try {
        const qr = qrcode(0, 'M');
        qr.addData(res.otpauth_uri);
        qr.make();
        gate.querySelector('#mfa-gate-qr').innerHTML = qr.createSvgTag(4);
      } catch {   }
      gate.querySelector('#mfa-gate-step1').classList.add('hidden');
      gate.querySelector('#mfa-gate-step2').classList.remove('hidden');
      gate.querySelector('#mfa-gate-code').focus();
    } catch (e) {
      showErr(e.message || 'Could not start enrollment.');
    }
  });

  gate.querySelector('#mfa-gate-verify').addEventListener('click', async () => {
    errEl.classList.add('hidden');
    const code = gate.querySelector('#mfa-gate-code').value.trim();
    if (code.length !== 6) { showErr('Enter the 6-digit code.'); return; }
    try {
      await api.verifyTotp(code);
      window.location.reload();
    } catch (e) {
      showErr(e.message || 'Invalid code.');
    }
  });

  gate.querySelector('#mfa-gate-logout').addEventListener('click', async () => {
    try { await api.logout(); } finally { window.location.reload(); }
  });
}

async function checkLoginStatus() {
  try {
    await api.awaitAuthInit();
    let me = await api.getMe();

    if ((!me || !me.ok) && isNative && GoogleAuth) {
      try {
        const refreshed = await GoogleAuth.refresh();
        const newToken = refreshed?.authentication?.idToken || refreshed?.idToken;
        if (newToken) {
          console.log('[AUTH] Silent token refresh succeeded.');
          await api.mobileLogin(newToken);
          me = await api.getMe();
        }
      } catch (refreshErr) {
        console.log('[AUTH] Silent refresh failed, showing login screen.', refreshErr);
      }
    }

    user = (me && me.ok) ? me.user : null;

    if (user && user.mfa_setup_required) {
      showMfaEnrollmentGate();
      return;
    }

    uiAuthSidebar.updateUIForAuthState(user);

    if (user) {
      try {
        const offlineOk = user.offline_enabled !== false;
        await offlineManager.setOfflineAllowed(offlineOk);
        await cache.setPersistenceAllowed(offlineOk);
      } catch (e) {
        console.warn("Offline policy apply warning:", e);
      }

      try {
        await offlineManager.initNetworkListener();
      } catch (e) {
        console.warn("Offline manager init warning:", e);
      }

      const [profilesResponse, modelsResponse] = await Promise.all([
        api.fetchAvailableProfiles(),
        api.fetchAvailableModels()
      ]);

      availableProfiles = profilesResponse.available || [];
      availableModels = modelsResponse.models || [];

      uiAuthSidebar.setKnownProfiles(availableProfiles);

      const currentProfileKey = user.active_profile || (availableProfiles[0] ? availableProfiles[0].key : null);
      activeProfileData = availableProfiles.find(p => p.key === currentProfileKey) || availableProfiles[0] || null;

      const composerWrapper = document.querySelector('.composer-bg-wrapper');
      if (!activeProfileData || !activeProfileData.key) {
        activeProfileData = null;
        if (composerWrapper) {
          composerWrapper.classList.add('hidden');
        }
        if (ui.elements.messageInput) {
          ui.elements.messageInput.disabled = true;
          ui.elements.messageInput.placeholder = 'No agents currently available';
        }
        if (ui.elements.sendButton) {
          ui.elements.sendButton.disabled = true;
        }
      } else {
        if (composerWrapper) {
          composerWrapper.classList.remove('hidden');
        }
        if (ui.elements.messageInput) {
          ui.elements.messageInput.disabled = false;
        }
        if (user.active_profile !== activeProfileData.key) {
          user.active_profile = activeProfileData.key;
          api.updateUserProfile(activeProfileData.key).catch(() => {});
        }
      }

      uiAuthSidebar.updateActiveProfileChip(activeProfileData);

      renderControlPanel();

      initModelSelector(availableModels, user.intellect_model, (modelId) => {
        handleQuickModelSwitch(modelId);
        updateModelLabel(getActiveModelLabel());
      }, modelsResponse.public_demo_ui === true);
      const activeModel = getActiveModel();
      if (activeModel && user.intellect_model !== activeModel.id) {
        user.intellect_model = activeModel.id;
      }

      await chat.loadConversations(
        activeProfileData,
        user,
        handleExamplePromptClick,
        ui.showModal,
        true
      );

      initDataSources();

      chat.initFileUpload();

      initComposerMenu({ onAttachFile: () => chat.triggerFilePicker() });

      initVoiceInput();

      updateModelLabel(getActiveModelLabel());

      await applyDeepLink();
    }
    attachEventListeners();
  } catch (error) {
    console.error("Failed to check login status:", error);
    uiAuthSidebar.updateUIForAuthState(null);
    attachEventListeners();
    hapticError();
  } finally {
    setTimeout(() => {
      if (SplashScreen) {
        SplashScreen.hide();
      } else if (isNative) {
      }
    }, 250);
  }
}


async function handleLogout() {
  console.log('[LOGOUT] Handle logout triggered.');
  hapticImpactLight();
  if (isNative && GoogleAuth) {
    try { await GoogleAuth.signOut(); } catch (e) { console.warn('Google signOut error:', e); }
  }

  try {
    await api.logout();
  } catch (e) {
    console.warn('Logout API call failed (may be queued):', e);
  }

  localStorage.removeItem('theme');
  await api.clearAuthToken();

  console.log('[LOGOUT] Local state cleared. Reloading...');

  setTimeout(() => window.location.reload(), 100);
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

function renderControlPanel() {
  if (!user) return;

  console.log('[RBAC] Checking visibility for user:', user.id, 'Role:', user.role);

  const canSeeOrg = ['admin', 'auditor'].includes(user.role);
  const canSeeGovernance = ['admin', 'editor', 'auditor'].includes(user.role);
  const canSeeDashboard = ['admin', 'editor', 'auditor'].includes(user.role);

  const canSeeIncidents = user.role === 'admin';

  const canSeeReview = ['admin', 'auditor'].includes(user.role);

  console.log('[RBAC] Flags:', { canSeeOrg, canSeeGovernance, canSeeDashboard, canSeeIncidents, canSeeReview });

  uiSettingsModals.setConscienceDashboardAccess(canSeeDashboard);

  const navOrg = document.getElementById('nav-organization');
  if (navOrg) {
    if (canSeeOrg) navOrg.classList.remove('hidden');
    else navOrg.classList.add('hidden');
  }

  const navIdentity = document.getElementById('nav-identity');
  if (navIdentity) {
    if (canSeeOrg) navIdentity.classList.remove('hidden');
    else navIdentity.classList.add('hidden');
  }


  const navGov = document.getElementById('nav-governance');
  if (navGov) {
    if (canSeeGovernance) navGov.classList.remove('hidden');
    else navGov.classList.add('hidden');
  }

  const navDash = document.getElementById('nav-dashboard');
  if (navDash) {
    if (canSeeDashboard) navDash.classList.remove('hidden');
    else navDash.classList.add('hidden');
  }

  const navCompliance = document.getElementById('nav-compliance');
  if (navCompliance) {
    if (canSeeIncidents) navCompliance.classList.remove('hidden');
    else navCompliance.classList.add('hidden');
  }

  const navReview = document.getElementById('nav-review');
  if (navReview) {
    if (canSeeReview) navReview.classList.remove('hidden');
    else navReview.classList.add('hidden');
  }

  const canSeeKnowledge = ['admin', 'editor', 'auditor'].includes(user.role);

  const navKnowledge = document.getElementById('nav-knowledge');
  if (navKnowledge) {
    if (canSeeKnowledge) navKnowledge.classList.remove('hidden');
    else navKnowledge.classList.add('hidden');
  }

  const navTools = document.getElementById('nav-tools');
  if (navTools) {
    if (user.role === 'admin') navTools.classList.remove('hidden');
    else navTools.classList.add('hidden');
  }

  const navUsage = document.getElementById('nav-usage');
  if (navUsage) {
    if (user.role === 'admin') navUsage.classList.remove('hidden');
    else navUsage.classList.add('hidden');
  }

  const navGroupManagement = document.getElementById('nav-group-management');
  if (navGroupManagement) {
    if (canSeeOrg || canSeeGovernance || canSeeDashboard || canSeeReview || canSeeKnowledge) {
      navGroupManagement.classList.remove('hidden');
    } else {
      navGroupManagement.classList.add('hidden');
    }
  }

  uiSettingsModals.updateCurrentUser(user);

  uiSettingsModals.renderSettingsProfileTab(
    availableProfiles,
    activeProfileData?.key || null,
    handleProfileChange,
    user
  );

  uiAuthSidebar.initAgentSelector(
    availableProfiles,
    activeProfileData?.key || null,
    handleProfileChange
  );
  if (activeProfileData) {
    updateAgentLabel(activeProfileData.name, activeProfileData.avatar || getAvatarForProfile(activeProfileData.name));
    updateAiDisclosure(activeProfileData, handleViewGoverningPolicy);
  } else {
    updateAgentLabel('None');
  }

  updateSettingsState({
    currentUser: user,
    profiles: availableProfiles,
    activeProfileKey: activeProfileData?.key || null,
    availableModels: availableModels,
    onProfileChange: handleProfileChange,
    currentTheme: localStorage.theme || 'system',
    onThemeChange: applyTheme,
    onLogout: handleLogout,
    onDeleteAccount: () => ui.showModal('delete')
  });

  uiSettingsModals.renderSettingsMyProfileTab();

  uiSettingsModals.renderSettingsAppTab(
    localStorage.theme || 'system',
    applyTheme,
    () => ui.showModal('delete')
  );

  const orgTab = document.getElementById('nav-organization');
  const agentsTab = document.getElementById('nav-agents');

  const currentActive = document.querySelector('.sidebar-item.active');
  let activeIsVisible = currentActive && !currentActive.classList.contains('hidden');

  if (!activeIsVisible) {
    if (agentsTab && !agentsTab.classList.contains('hidden')) {
      agentsTab.click();
    } else if (orgTab && !orgTab.classList.contains('hidden')) {
      orgTab.click();
    }
  }

  const mobileNavContainer = document.getElementById('mobile-nav-links');
  const desktopNav = document.getElementById('sidebar-nav');
  if (mobileNavContainer && desktopNav) {
    mobileNavContainer.innerHTML = '';

    Array.from(desktopNav.children).forEach(child => {
      if (child.querySelector('#desktop-back-to-chat')) return;

      const clone = child.cloneNode(true);
      clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));

      mobileNavContainer.appendChild(clone);
    });

    mobileNavContainer.querySelectorAll('button[data-tab]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.dataset.tab;
        const originalBtn = document.getElementById(`nav-${tab}`);
        if (originalBtn) originalBtn.click();

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
      activeProfileData = availableProfiles.find(p => p.key === newProfileKey) || activeProfileData;
      uiAuthSidebar.updateActiveProfileChip(activeProfileData);
      updateAiDisclosure(activeProfileData, handleViewGoverningPolicy);
      return;
    }

    const selectedProfile = availableProfiles.find(p => p.key === newProfileKey);
    updateAgentLabel(selectedProfile?.name, selectedProfile?.avatar || getAvatarForProfile(selectedProfile?.name));
    ui.showToast(`Agent switched to ${selectedProfile.name}. Reloading...`, 'success');

    sessionStorage.setItem('forceNewChat', 'true');

    setTimeout(() => window.location.reload(), 1000);
  } catch (error) {
    console.error('Failed to switch profile:', error);
    ui.showToast('Could not switch agent.', 'error');
    hapticError();
  }
}

async function handleViewGoverningPolicy(profile) {
  try {
    const res = await api.getPolicy(profile.policy_id);
    const policy = res?.policy;
    if (!policy) throw new Error('Policy not found');

    const cfg = policy.policy_config || {};
    const descParts = [`**Policy ID:** ${policy.id}`];
    if (policy.version) descParts.push(`**Version:** ${policy.version}`);
    if (cfg.business_unit) descParts.push(`**Business Unit:** ${cfg.business_unit}`);
    if (cfg.scope_statement) descParts.push(`**Scope:** ${cfg.scope_statement}`);
    if (profile.has_charter) {
      descParts.push(`This policy operates under the ${profile.org_name ? `**${profile.org_name}** ` : ''}organization charter.`);
    }

    uiSettingsModals.renderProfileDetailsModal({
      name: policy.name,
      description: descParts.join('\n\n'),
      worldview: policy.worldview,
      values: policy.values_weights,
      will_rules: policy.will_rules
    }, { isPolicy: true });
    ui.showModal('profile');
  } catch (error) {
    console.error('Failed to load policy details:', error);
    ui.showToast('Could not load policy details.', 'error');
  }
}

async function handleQuickModelSwitch(modelId) {
  try {
    await api.updateUserModels({ intellect_model: modelId });
    user.intellect_model = modelId;
    const model = availableModels.find(m => m.id === modelId);
    ui.showToast(`Switched to ${model?.label || modelId}`, 'success');
  } catch(e) {
    console.error('Model switch failed:', e);
    ui.showToast('Could not switch model.', 'error');
  }
}

async function applyDeepLink() {
  let params;
  try {
    params = new URLSearchParams(window.location.search);
  } catch (_) {
    return;
  }
  const q = params.get('q');
  const agentKey = params.get('agent');
  if (!q && !agentKey) return;

  if (agentKey
      && agentKey !== activeProfileData?.key
      && availableProfiles.some(p => p.key === agentKey)) {
    await handleProfileChange(agentKey);
    return;
  }

  if (q) {
    ui.elements.messageInput.value = q;
    chat.autoSize();
    ui.elements.sendButton.disabled = false;
    ui.elements.messageInput.focus();
  }
  window.history.replaceState({}, '', window.location.pathname);
}

function handleExamplePromptClick(promptText) {
  ui.elements.messageInput.value = promptText;
  chat.autoSize();
  ui.elements.sendButton.disabled = false;
  chat.sendMessage(activeProfileData, user);
}


function attachEventListeners() {
  if (listenersAttached) return;

  if (ui.elements.loginButton) {
    if (isNative && GoogleAuth) {
      ui.elements.loginButton.addEventListener('click', handleNativeLogin);
    } else {
      ui.elements.loginButton.addEventListener('click', () => { window.location.href = '/api/login'; });
    }
  }

  const microsoftBtn = document.getElementById('login-microsoft-button');
  if (microsoftBtn) {
    if (isNative) {
      microsoftBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        await handleNativeMicrosoftLogin();
      });
    } else {
      microsoftBtn.addEventListener('click', () => {
        window.location.href = '/api/login/microsoft';
      });
    }
  }

  const demoBtn = document.getElementById('login-demo-button');
  if (demoBtn && isNative) {
    demoBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await fetch('https://safi.selfalignmentframework.com/api/login/demo?client=native', {
          credentials: 'include'
        });
        window.location.href = '/';
      } catch (err) {
        console.error('[Demo] Guest login failed:', err);
        ui.showToast('Could not start guest session.', 'error');
      }
    });
  }

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
    chat.autoSize();
  }

  const newChatButton = document.getElementById('new-chat-button');
  if (newChatButton) {
    newChatButton.addEventListener('click', () => {
      hapticImpactLight();
      chat.startNewConversation(false, activeProfileData, user, handleExamplePromptClick);
      if (window.innerWidth < 768) ui.closeSidebar();
    });
  }

  document.addEventListener('click', (e) => {
    if (e.target.closest('#clear-all-convos-button')) {
      hapticImpactLight();
      ui.showModal('clear-all-convos');
    }
  });

  document.addEventListener('safi:save-content', (e) => {
    const { messageId, anchor } = e.detail || {};
    if (!messageId) return;
    uiSaved.showSavePicker(anchor, chat.getProjects(), async (projectId) => {
      try {
        await api.saveContent(messageId, projectId);
        ui.showToast('Saved', 'success');
      } catch {
        ui.showToast('Could not save.', 'error');
      }
    });
  });

  document.addEventListener('click', (e) => {
    if (e.target.closest('#saved-content-button')) {
      hapticImpactLight();
      if (window.innerWidth < 768) ui.closeSidebar();
      uiSaved.openSavedModal({
        projects: chat.getProjects(),
        onJumpToConversation: (convoId) =>
          chat.switchConversation(convoId, activeProfileData, user, ui.showModal, true),
      });
    }
  });

  ui.elements.cancelClearAllConvosBtn?.addEventListener('click', ui.closeModal);
  ui.elements.confirmClearAllConvosBtn?.addEventListener('click', () => {
    hapticImpactLight();
    chat.handleConfirmClearAll(activeProfileData, user);
  });

  const menuToggle = document.getElementById('menu-toggle');
  if (menuToggle) menuToggle.addEventListener('click', ui.openSidebar);
  const closeSidebarButton = document.getElementById('close-sidebar-button');
  if (closeSidebarButton) closeSidebarButton.addEventListener('click', ui.closeSidebar);
  const sidebarOverlay = document.getElementById('sidebar-overlay');
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', ui.closeSidebar);

  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-sidebar-toggle]')) {
      hapticImpactLight();
      ui.toggleDesktopSidebar();
    }
  });

  const chatWindow = document.getElementById('chat-window');
  const scrollToBottomBtn = document.getElementById('scroll-to-bottom-btn');
  if (chatWindow && scrollToBottomBtn) {
    let rafPending = false;
    const refreshScrollButton = () => {
      const distanceFromBottom =
        chatWindow.scrollHeight - chatWindow.scrollTop - chatWindow.clientHeight;
      scrollToBottomBtn.classList.toggle('s2b-hidden', distanceFromBottom < 160);
    };
    const scheduleRefresh = () => {
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => { rafPending = false; refreshScrollButton(); });
    };
    chatWindow.addEventListener('scroll', scheduleRefresh, { passive: true });
    new MutationObserver(scheduleRefresh).observe(chatWindow, { childList: true, subtree: true });
    scrollToBottomBtn.addEventListener('click', () => {
      hapticImpactLight();
      ui.scrollToBottom();
    });
  }

  const controlPanelButton = document.getElementById('control-panel-btn');
  if (controlPanelButton) {
    controlPanelButton.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      ui.closeSidebar();
    });
  }


  document.addEventListener('click', (e) => {
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
      ui.elements.chatView.style.display = '';
      ui.elements.chatView.classList.remove('hidden');

    });
  });

  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      ui.closeSidebar();

      if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
    });
  }
  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.addEventListener('click', () => {
      hapticImpactLight();
      ui.elements.chatView.classList.add('hidden');
      ui.elements.controlPanelView.classList.remove('hidden');

      ui.closeSidebar();

      if (ui.elements.cpNavProfile) ui.elements.cpNavProfile.click();
    });
  }

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

  document.getElementById('demo-limit-signin-btn')?.addEventListener('click', handleLogout);

  document.addEventListener('click', (event) => {
    const convoMenuButton = event.target.closest('.convo-menu-button');
    if (!convoMenuButton) {
      ui.closeAllConvoMenus();
    }

    const logoutBtn = event.target.closest('[data-tab="logout"]');
    if (logoutBtn) {
      event.preventDefault();
      handleLogout();
    }
  });

  uiSettingsModals.setupControlPanelTabs();

  try {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', () => {
      if (localStorage.theme === 'system' || !localStorage.theme) {
        applyTheme('system');
      }
    });

    if (isNative && Network) {
      Network.addListener('networkStatusChange', (status) => {
        updateOfflineUI(status.connected);
      });
      Network.getStatus().then(status => updateOfflineUI(status.connected));
    }

    if (isNative && App) {
      let _lastActiveTime = Date.now();
      App.addListener('appStateChange', ({ isActive }) => {
        if (isActive && user) {
          const awayMs = Date.now() - _lastActiveTime;
          if (awayMs > 5 * 60 * 1000) {
            chat.refreshConvoListOnly(activeProfileData, user, ui.showModal);
          }
        } else {
          _lastActiveTime = Date.now();
        }
      });

      App.addListener('appUrlOpen', async ({ url }) => {
        if (!url || !url.startsWith('com.safi.app://auth')) return;
        try { await Browser?.close(); } catch (_) {}
        const params = new URL(url);
        const token = params.searchParams.get('token');
        if (token) {
          await api.setAuthToken(token);
          hapticImpactLight();
          ui.showToast('Login successful!', 'success');
          setTimeout(() => window.location.reload(), 400);
        } else {
          ui.showToast('Microsoft login failed. No token received.', 'error');
          hapticError();
        }
      });
    }

    const cpNavLogout = document.getElementById('cp-nav-logout');
    if (cpNavLogout) {
      cpNavLogout.addEventListener('click', handleLogout);
    }

  } catch (e) {
    console.error('Failed to add theme/network/app listener:', e);
  }

  listenersAttached = true;
}


document.addEventListener('DOMContentLoaded', async () => {
  applyTheme(localStorage.theme || 'system');


  await initializeNativeAuth();

  await checkLoginStatus();
});
