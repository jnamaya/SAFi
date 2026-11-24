import * as uiSettingsModals from './ui-settings-modals.js';

export let elements = {};
let currentLoadingInterval = null;
let activeToast = null;
let openDropdown = null;

export let isSidebarOpen = false;

export function _initElements() {
  elements = {
    loginView: document.getElementById('login-view'),
    chatView: document.getElementById('chat-view'),
    controlPanelView: document.getElementById('control-panel-view'),
    controlPanelBackButton: document.getElementById('control-panel-back-btn'),

    cpNavProfile: document.getElementById('nav-agents'),
    cpNavDashboard: document.getElementById('nav-dashboard'),
    cpNavAppSettings: document.getElementById('nav-settings'),
    cpNavMyProfile: document.getElementById('nav-profile'),
    cpNavGovernance: document.getElementById('nav-governance'),
    cpNavOrganization: document.getElementById('nav-organization'),

    cpTabProfile: document.getElementById('tab-agents'),
    cpTabDashboard: document.getElementById('tab-dashboard'),
    cpTabAppSettings: document.getElementById('tab-settings'),
    cpTabMyProfile: document.getElementById('tab-profile'),
    cpTabGovernance: document.getElementById('tab-governance'),
    cpTabOrganization: document.getElementById('tab-organization'),
    cpTabCompliance: document.getElementById('tab-compliance'),

    loginButton: document.getElementById('login-button'),
    sidebarContainer: document.getElementById('sidebar-container'),
    chatWindow: document.getElementById('chat-window'),
    messageInput: document.getElementById('message-input'),
    sendButton: document.getElementById('send-button'),
    toastContainer: document.getElementById('toast-container'),
    modalBackdrop: document.getElementById('modal-backdrop'),
    conscienceModal: document.getElementById('conscience-modal'),
    deleteAccountModal: document.getElementById('delete-account-modal'),
    composerFooter: document.getElementById('composer-footer'),
    conscienceDetails: document.getElementById('conscience-details'),
    closeConscienceModalBtn: document.getElementById('close-conscience-modal'),

    agentSelectorDropdown: document.getElementById('agent-selector-dropdown'),

    renameModal: document.getElementById('rename-modal'),
    renameInput: document.getElementById('rename-input'),
    confirmRenameBtn: document.getElementById('confirm-rename-btn'),
    cancelRenameBtn: document.getElementById('cancel-rename-btn'),

    deleteConvoModal: document.getElementById('delete-convo-modal'),
    confirmDeleteConvoBtn: document.getElementById('confirm-delete-convo-btn'),
    deleteConvoModal: document.getElementById('delete-convo-modal'),
    confirmDeleteConvoBtn: document.getElementById('confirm-delete-convo-btn'),
    cancelDeleteConvoBtn: document.getElementById('cancel-delete-convo-btn'),

    clearAllConvosModal: document.getElementById('clear-all-convos-modal'),
    confirmClearAllConvosBtn: document.getElementById('confirm-clear-all-convos-btn'),
    cancelClearAllConvosBtn: document.getElementById('cancel-clear-all-convos-btn'),

    projectNameModal: document.getElementById('project-name-modal'),
    projectNameModalTitle: document.getElementById('project-name-modal-title'),
    projectNameInput: document.getElementById('project-name-input'),
    confirmProjectNameBtn: document.getElementById('confirm-project-name-btn'),
    cancelProjectNameBtn: document.getElementById('cancel-project-name-btn'),

    deleteProjectModal: document.getElementById('delete-project-modal'),
    deleteProjectName: document.getElementById('delete-project-name'),
    confirmDeleteProjectBtn: document.getElementById('confirm-delete-project-btn'),
    cancelDeleteProjectBtn: document.getElementById('cancel-delete-project-btn'),

    demoLimitModal: document.getElementById('demo-limit-modal'),
    closeDemoLimitBtn: document.getElementById('close-demo-limit-btn'),

    activeProfileChip: document.getElementById('active-profile-chip'),
    activeProfileChipMobile: document.getElementById('active-profile-chip-mobile'),

    profileModal: document.getElementById('profile-details-modal'),
    profileModalContent: document.getElementById('profile-details-content'),

    sidebarElement: null,
    sidebarOverlay: null,
    menuToggleButton: document.getElementById('menu-toggle'),
  };
}

export function _ensureElements() {
  if (!elements.loginView) {
    _initElements();
  }
}


export function setOpenDropdown(menuElement) {
  _ensureElements();
  closeAllConvoMenus();
  openDropdown = menuElement;
  document.body.appendChild(openDropdown);
}

export function closeAllConvoMenus() {
  if (openDropdown) {
    openDropdown.remove();
    openDropdown = null;
  }
}

let hideSidebarTimeout = null;

function updateSidebarState(open) {
  _ensureElements();
  elements.sidebarElement = document.getElementById('sidebar');
  elements.sidebarOverlay = document.getElementById('sidebar-overlay');

  if (!elements.sidebarElement || !elements.sidebarOverlay) return;

  if (hideSidebarTimeout) {
    clearTimeout(hideSidebarTimeout);
    hideSidebarTimeout = null;
  }

  elements.sidebarElement.style.transform = '';

  if (open) {
    elements.sidebarElement.classList.remove('hidden');
    elements.sidebarElement.classList.add('flex');
    elements.sidebarOverlay.classList.remove('hidden');

    requestAnimationFrame(() => {
      elements.sidebarElement.classList.remove('-translate-x-full');
      elements.sidebarOverlay.classList.remove('opacity-0');
    });

    isSidebarOpen = true;

  } else {
    elements.sidebarElement.classList.add('-translate-x-full');
    elements.sidebarOverlay.classList.add('opacity-0');

    setTimeout(() => {
      if (!isSidebarOpen) elements.sidebarOverlay.classList.add('hidden');
    }, 300);

    isSidebarOpen = false;

    hideSidebarTimeout = setTimeout(() => {
      if (!isSidebarOpen) {
        elements.sidebarElement.classList.add('hidden');
        elements.sidebarElement.classList.remove('flex');
      }
    }, 350);
  }
}

export function openSidebar() {
  updateSidebarState(true);
}

export function closeSidebar() {
  updateSidebarState(false);
}

export function toggleDesktopSidebar() {
  const collapsed = document.documentElement.classList.toggle('sidebar-collapsed');
  try {
    localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
  } catch (e) {
  }
}


export function clearLoadingInterval() {
  if (currentLoadingInterval) {
    clearInterval(currentLoadingInterval);
    currentLoadingInterval = null;
  }
}

export function setLoadingInterval(interval) {
  currentLoadingInterval = interval;
}

export function scrollToBottom() {
  _ensureElements();
  const chatWindow = elements.chatWindow;

  if (chatWindow) {
    requestAnimationFrame(() => {
      const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
      chatWindow.scrollTo({
        top: chatWindow.scrollHeight,
        behavior: behavior
      });
      setTimeout(() => {
        chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'auto' });
      }, 150);
    });
  }
}


const isNative = false;
const Toast = null;

export async function showToast(message, type = 'info', duration = 3000) {
  if (type === 'info') return;

  _ensureElements();

  try {
    if (isNative && Toast && typeof Toast.show === 'function') {
      let capDuration = duration <= 2000 ? 'short' : 'long';
      await Toast.show({ text: message, duration: capDuration });
      return;
    }
  } catch (e) {
    console.warn('Native Toast failed:', e);
  }

  if (activeToast) activeToast.remove();
  const toast = document.createElement('div');
  const colors = { info: 'bg-green-500', success: 'bg-green-600', error: 'bg-red-600', warning: 'bg-amber-500' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]} cursor-default`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);
  activeToast = toast;

  setTimeout(() => toast.classList.add('show'), 10);

  setTimeout(() => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', function handler() {
      toast.removeEventListener('transitionend', handler);
      toast.remove();
    });
    if (activeToast === toast) activeToast = null;
  }, duration);
}


export function showModal(kind, data) {
  _ensureElements();
  if (kind === 'conscience') {
    uiSettingsModals.setupConscienceModalContent(data);
    elements.conscienceModal.classList.remove('hidden');
  } else if (kind === 'delete') {
    elements.deleteAccountModal.classList.remove('hidden');
  }
  else if (kind === 'rename') {
    if (elements.renameInput) {
      elements.renameInput.value = data.oldTitle;
    }
    elements.renameModal.classList.remove('hidden');
    if (elements.renameInput) {
      elements.renameInput.focus();
      elements.renameInput.select();
    }
  } else if (kind === 'delete-convo') {
    elements.deleteConvoModal.classList.remove('hidden');
  } else if (kind === 'clear-all-convos') {
    elements.clearAllConvosModal.classList.remove('hidden');
  } else if (kind === 'project-name') {
    elements.projectNameModal.classList.remove('hidden');
    if (elements.projectNameInput) {
      elements.projectNameInput.focus();
      elements.projectNameInput.select();
    }
  } else if (kind === 'delete-project') {
    elements.deleteProjectModal.classList.remove('hidden');
  }
  else if (kind === 'profile') {
    elements.profileModal.classList.remove('hidden');
  }
  else if (kind === 'demo_limit') {
    elements.demoLimitModal.classList.remove('hidden');
    elements.closeDemoLimitBtn.onclick = closeModal;
  }

  elements.modalBackdrop.classList.remove('hidden');
}

export function closeModal() {
  _ensureElements();
  elements.modalBackdrop.classList.add('hidden');
  elements.conscienceModal.classList.add('hidden');
  elements.deleteAccountModal.classList.add('hidden');
  elements.renameModal.classList.add('hidden');
  elements.deleteConvoModal.classList.add('hidden');
  if (elements.clearAllConvosModal) elements.clearAllConvosModal.classList.add('hidden');
  if (elements.projectNameModal) elements.projectNameModal.classList.add('hidden');
  if (elements.deleteProjectModal) elements.deleteProjectModal.classList.add('hidden');
  if (elements.demoLimitModal) elements.demoLimitModal.classList.add('hidden');

  if (elements.profileModal) {
    elements.profileModal.classList.add('hidden');
  }
}

_ensureElements();